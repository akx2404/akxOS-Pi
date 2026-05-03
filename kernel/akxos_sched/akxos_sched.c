// SPDX-License-Identifier: GPL-2.0
/*
 * akxOS Kernel Power Budget Controller
 *
 * Core redesign: duty-cycle control via two workqueues
 * ====================================================
 *
 * Convergence (budget=60mW, baseline=216mW):
 *   Tick 0: quota=100%  → power=292mW (no throttle yet)
 *   Tick 1: quota=57.5% → power=168mW
 *   Tick 2: quota=33.9% → power= 99mW
 *   Tick 3: quota=21.1% → power= 62mW  ← settled within deadband
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/proc_fs.h>
#include <linux/uaccess.h>
#include <linux/sched.h>
#include <linux/sched/signal.h>
#include <linux/pid.h>
#include <linux/mutex.h>
#include <linux/workqueue.h>
#include <linux/ktime.h>
#include <linux/slab.h>
#include <linux/seq_file.h>
#include <linux/string.h>
#include <linux/signal.h>
#include <linux/cpufreq.h>

#include "akxos_sched.h"

static struct akxos_budget_entry budget_table[AKXOS_MAX_BUDGETS];
static DEFINE_MUTEX(budget_lock);

static struct delayed_work akxos_measure_work;  /* 500ms measurement loop */
static struct delayed_work akxos_resume_work;   /* 50ms SIGCONT poll      */
static struct proc_dir_entry *akxos_proc_entry;


/* =================================================================
 * Task helpers
 * ================================================================= */

static struct task_struct *akxos_get_task(pid_t pid)
{
    struct task_struct *task;
    rcu_read_lock();
    task = pid_task(find_vpid(pid), PIDTYPE_PID);
    if (task)
        get_task_struct(task);
    rcu_read_unlock();
    return task;
}

/* Must be called WITHOUT budget_lock held — send_sig acquires sighand lock */
static void akxos_send_signal(int pid, int sig)
{
    struct task_struct *task = akxos_get_task(pid);
    if (!task) return;
    send_sig(sig, task, 0);
    put_task_struct(task);
}

static void akxos_apply_deferred(struct akxos_deferred_signal *acts, int n)
{
    int i;
    for (i = 0; i < n; i++) {
        if (acts[i].sig_action == AKXOS_SIG_STOP)
            akxos_send_signal(acts[i].pid, SIGSTOP);
        else if (acts[i].sig_action == AKXOS_SIG_CONT)
            akxos_send_signal(acts[i].pid, SIGCONT);
    }
}


/* =================================================================
 * Hardware helpers
 * ================================================================= */

static unsigned int akxos_get_freq_khz(void)
{
    unsigned int f = cpufreq_get(0);
    return f ? f : AKXOS_FALLBACK_FREQ_KHZ;
}

static int akxos_estimate_power_mw(int util_permille, unsigned int freq_khz)
{
    u64 p = AKXOS_MODEL_CONST_FP * (u64)freq_khz * (u64)util_permille;
    return (int)(p / AKXOS_MODEL_DIVISOR);
}

static int akxos_clamp_int(int v, int lo, int hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}


/* =================================================================
 * Budget table helpers
 * ================================================================= */

static int akxos_find_slot(int pid)
{
    int i;
    for (i = 0; i < AKXOS_MAX_BUDGETS; i++)
        if (budget_table[i].active && budget_table[i].pid == pid)
            return i;
    return -1;
}

static int akxos_free_slot(void)
{
    int i;
    for (i = 0; i < AKXOS_MAX_BUDGETS; i++)
        if (!budget_table[i].active)
            return i;
    return -1;
}


/* =================================================================
 * PI controller
 *
 * Operates in milli-percent space (quota × 100) so that sub-1%
 * corrections are not lost to integer division.
 *
 * Features:
 *   Deadband ±15mW: integral frozen, Kp halved → no hunting near setpoint
 *   Zero-crossing reset: integral cleared when error changes sign →
 *     stale windup from the convergence transient does not drag the
 *     controller in the wrong direction once the process settles
 * ================================================================= */

static int akxos_pi_step(struct akxos_budget_entry *entry)
{
    int error, in_deadband, in_integ_band;
    int p_mpct, i_mpct, delta_mpct, new_mpct, new_pct;

    if (entry->budget_mw <= 0)
        return AKXOS_CPU_QUOTA_MAX_PCT;

    error        = entry->budget_mw - entry->estimated_power_mw;
    in_deadband  = (error > -AKXOS_PI_DEADBAND_MW &&
                    error <  AKXOS_PI_DEADBAND_MW);
    /*
     * Conditional integration: ONLY accumulate integral when close to
     * the setpoint (|error| ≤ INTEG_THRESH and outside deadband).
     *
     * WHY: The previous zero-crossing reset (integral wiped on sign
     * change) was itself causing the 60↔120mW oscillation:
     *   1. Large negative integral during convergence → quota minimum
     *   2. Power far below budget → error sign flips → integral wiped
     *   3. P-term alone drives quota to 100% (large positive error)
     *   4. Process runs free at full power → repeat
     *
     * With conditional integration, the integral NEVER accumulates
     * during large-error convergence, so it cannot cause oscillation.
     * It only activates in the ±8mW band to eliminate steady-state
     * error that the P-term alone leaves behind.
     */
    in_integ_band = (!in_deadband &&
                     error >= -AKXOS_PI_INTEG_THRESH_MW &&
                     error <=  AKXOS_PI_INTEG_THRESH_MW);

    entry->error_mw = error;

    if (in_integ_band) {
        entry->integral_error_mw += error;
        entry->integral_error_mw = akxos_clamp_int(
            entry->integral_error_mw,
            -AKXOS_INTEGRAL_LIMIT, AKXOS_INTEGRAL_LIMIT);
    }

    /* P term — halved inside deadband to damp micro-hunting */
    p_mpct = (int)(((s64)AKXOS_KP_NUM_S * error * 10000LL) /
                   ((s64)AKXOS_KP_DEN_S * entry->budget_mw *
                    (in_deadband ? 2 : 1)));

    /* I term — zero outside integration band */
    i_mpct = in_integ_band ?
             (int)(((s64)AKXOS_KI_NUM_S * entry->integral_error_mw * 10000LL) /
                   ((s64)AKXOS_KI_DEN_S * entry->budget_mw)) : 0;

    delta_mpct = p_mpct + i_mpct;
    new_mpct   = akxos_clamp_int(
        entry->current_cpu_quota_mpct + delta_mpct,
        AKXOS_CPU_QUOTA_MIN_PCT * 100,
        AKXOS_CPU_QUOTA_MAX_PCT * 100);

    new_pct = new_mpct / 100;

    /* Anti-windup: undo integral if we're rail-limited */
    if (new_pct <= AKXOS_CPU_QUOTA_MIN_PCT && error < 0)
        entry->integral_error_mw -= error;
    if (new_pct >= AKXOS_CPU_QUOTA_MAX_PCT && error > 0)
        entry->integral_error_mw -= error;

    entry->current_cpu_quota_mpct = new_mpct;
    return new_pct;
}


/* =================================================================
 * Resume loop — 50ms poll
 *
 * Fires SIGCONT for any entry whose throttle window has expired.
 * Runs at 50ms granularity → ±50ms accuracy on stop_ms timing,
 * which is ±10% of the 500ms measurement window.  Acceptable for
 * power control where steady-state error is dominated by model
 * inaccuracy, not timing jitter.
 *
 * MUST be called outside budget_lock (sends signals).
 * ================================================================= */

static void akxos_resume_loop(struct work_struct *work)
{
    int i, n = 0;
    unsigned long long now_ns = ktime_get_ns();
    struct akxos_deferred_signal acts[AKXOS_MAX_BUDGETS];

    mutex_lock(&budget_lock);
    for (i = 0; i < AKXOS_MAX_BUDGETS; i++) {
        if (!budget_table[i].active)   continue;
        if (!budget_table[i].throttled) continue;
        if (now_ns < budget_table[i].throttle_until_ns) continue;

        budget_table[i].throttled         = 0;
        budget_table[i].throttle_until_ns = 0;
        acts[n].pid        = budget_table[i].pid;
        acts[n].sig_action = AKXOS_SIG_CONT;
        n++;
    }
    mutex_unlock(&budget_lock);

    akxos_apply_deferred(acts, n);

    schedule_delayed_work(&akxos_resume_work,
                          msecs_to_jiffies(AKXOS_RESUME_POLL_MS));
}


/* =================================================================
 * Main measurement and control loop — 500ms period
 *
 * Each iteration:
 *   1. Measure util and power (delta_exec / delta_wall)
 *   2. Run PI → quota_pct
 *   3. If quota < 100%: apply SIGSTOP now; SIGCONT fires at
 *      T + stop_ms via akxos_resume_loop
 *   4. If quota = 100%: ensure process is running
 *
 * Because the process was stopped for stop_ms in the previous window
 * and ran for run_ms = 500 - stop_ms, delta_exec correctly reflects
 * the duty cycle: util = run_ms / 500 * 1000.
 * ================================================================= */

static void akxos_measure_loop(struct work_struct *work)
{
    int i, n = 0;
    unsigned long long now_ns = ktime_get_ns();
    struct akxos_deferred_signal acts[AKXOS_MAX_BUDGETS];

    mutex_lock(&budget_lock);

    for (i = 0; i < AKXOS_MAX_BUDGETS; i++) {
        struct task_struct *task;
        unsigned long long exec_ns, delta_exec, delta_wall;
        unsigned long long stop_ms, run_ms;
        int util, power, quota_pct;
        unsigned int freq_khz;
        int pid;

        if (!budget_table[i].active) continue;

        pid  = budget_table[i].pid;
        task = akxos_get_task(pid);
        if (!task) {
            pr_info("akxOS: PID=%d gone, removing\n", pid);
            /* Resume it in case it's stopped — can't send signal under lock */
            if (budget_table[i].throttled) {
                acts[n].pid        = pid;
                acts[n].sig_action = AKXOS_SIG_CONT;
                n++;
            }
            budget_table[i].active   = 0;
            budget_table[i].throttled = 0;
            continue;
        }

        exec_ns = task->se.sum_exec_runtime;
        put_task_struct(task);

        delta_exec = exec_ns - budget_table[i].last_exec_runtime_ns;
        delta_wall = now_ns  - budget_table[i].last_wall_time_ns;

        if (delta_wall < 1000ULL) continue; /* spurious wakeup */

        freq_khz = akxos_get_freq_khz();
        budget_table[i].last_freq_khz = freq_khz;

        /*
         * util_permille naturally reflects duty cycle:
         * if process ran for run_ms at 100% CPU:
         *   delta_exec = run_ms,  delta_wall = SAMPLE_INTERVAL_MS
         *   util = run_ms / 500 * 1000
         */
        util  = (int)((delta_exec * 1000ULL) / delta_wall);
        util  = akxos_clamp_int(util, 0, 1000);
        power = akxos_estimate_power_mw(util, freq_khz);

        budget_table[i].util_permille      = util;
        budget_table[i].estimated_power_mw = power;
        budget_table[i].last_exec_runtime_ns = exec_ns;
        budget_table[i].last_wall_time_ns    = now_ns;

        /* Energy accounting: µJ = mW × ms */
        budget_table[i].energy_uj +=
            (u64)power * (delta_wall / 1000000ULL);

        if (budget_table[i].energy_budget_uj > 0 &&
            budget_table[i].energy_uj >= budget_table[i].energy_budget_uj) {
            pr_warn("akxOS: PID=%d energy cap %llu µJ reached\n",
                    pid, budget_table[i].energy_budget_uj);
        }

        if (power > budget_table[i].budget_mw)
            budget_table[i].violation_total++;

        /* --- PI step --- */
        quota_pct = akxos_pi_step(&budget_table[i]);

        /* --- Duty-cycle throttle ---
         *
         * stop_ms = (100 - quota_pct) / 100 * SAMPLE_INTERVAL_MS
         *
         * Clamped so that run_ms >= MIN_RUN_MS, guaranteeing the
         * process always gets some CPU time for the next measurement.
         *
         * SIGSTOP is deferred (applied outside lock below).
         * SIGCONT is fired by akxos_resume_loop after stop_ms.
         */
        if (quota_pct < AKXOS_CPU_QUOTA_MAX_PCT) {
            stop_ms = (unsigned long long)(100 - quota_pct)
                      * AKXOS_SAMPLE_INTERVAL_MS / 100;

            run_ms = AKXOS_SAMPLE_INTERVAL_MS - stop_ms;
            if (run_ms < AKXOS_MIN_RUN_MS) {
                run_ms  = AKXOS_MIN_RUN_MS;
                stop_ms = AKXOS_SAMPLE_INTERVAL_MS - AKXOS_MIN_RUN_MS;
            }

            budget_table[i].throttled         = 1;
            budget_table[i].throttle_until_ns = now_ns + stop_ms * 1000000ULL;
            budget_table[i].stop_ms_last      = stop_ms;

            acts[n].pid        = pid;
            acts[n].sig_action = AKXOS_SIG_STOP;
            n++;
        } else {
            /* Quota at 100% — ensure process is running */
            if (budget_table[i].throttled) {
                budget_table[i].throttled         = 0;
                budget_table[i].throttle_until_ns = 0;
                acts[n].pid        = pid;
                acts[n].sig_action = AKXOS_SIG_CONT;
                n++;
            }
            budget_table[i].stop_ms_last = 0;
        }

        pr_info("akxOS: PID=%d util=%d pwr=%d bgt=%d err=%d intg=%d "
                "quota=%d%% stop=%llums energy=%llu freq=%u\n",
                pid, util, power,
                budget_table[i].budget_mw,
                budget_table[i].error_mw,
                budget_table[i].integral_error_mw,
                quota_pct,
                budget_table[i].stop_ms_last,
                budget_table[i].energy_uj,
                freq_khz);
    }

    mutex_unlock(&budget_lock);

    akxos_apply_deferred(acts, n);

    schedule_delayed_work(&akxos_measure_work,
                          msecs_to_jiffies(AKXOS_SAMPLE_INTERVAL_MS));
}


/* =================================================================
 * Set / clear budget
 * ================================================================= */

static int akxos_set_budget(int pid, int budget_mw)
{
    int slot;
    struct task_struct *task;
    unsigned long long now_ns, exec_ns;

    if (pid <= 0 || budget_mw <= 0) return -EINVAL;

    task = akxos_get_task(pid);
    if (!task) return -ESRCH;
    put_task_struct(task);

    mutex_lock(&budget_lock);

    task = akxos_get_task(pid);  /* re-resolve inside lock (TOCTOU fix) */
    if (!task) { mutex_unlock(&budget_lock); return -ESRCH; }
    now_ns  = ktime_get_ns();
    exec_ns = task->se.sum_exec_runtime;
    put_task_struct(task);

    slot = akxos_find_slot(pid);
    if (slot < 0) slot = akxos_free_slot();
    if (slot < 0) { mutex_unlock(&budget_lock); return -ENOMEM; }

    budget_table[slot].pid              = pid;
    budget_table[slot].budget_mw        = budget_mw;
    budget_table[slot].last_exec_runtime_ns = exec_ns;
    budget_table[slot].last_wall_time_ns    = now_ns;
    budget_table[slot].util_permille        = 0;
    budget_table[slot].estimated_power_mw   = 0;
    budget_table[slot].error_mw             = 0;
    budget_table[slot].integral_error_mw    = 0;
    budget_table[slot].current_cpu_quota_mpct = AKXOS_CPU_QUOTA_MAX_PCT * 100;
    budget_table[slot].throttled            = 0;
    budget_table[slot].throttle_until_ns    = 0;
    budget_table[slot].stop_ms_last         = 0;
    budget_table[slot].violation_total      = 0;
    budget_table[slot].energy_uj            = 0;
    budget_table[slot].energy_budget_uj     = 0;
    budget_table[slot].last_freq_khz        = akxos_get_freq_khz();
    budget_table[slot].active               = 1;

    mutex_unlock(&budget_lock);

    akxos_send_signal(pid, SIGCONT); /* ensure running */

    pr_info("akxOS: SET PID=%d budget=%d mW  target_duty=~%d%%\n",
            pid, budget_mw,
            (int)((u64)budget_mw * 100 /
                  (AKXOS_MODEL_CONST_FP * budget_table[slot].last_freq_khz /
                   (AKXOS_MODEL_DIVISOR / 1000))));
    return 0;
}

static int akxos_clear_budget(int pid)
{
    int slot, was_throttled;
    if (pid <= 0) return -EINVAL;

    mutex_lock(&budget_lock);
    slot = akxos_find_slot(pid);
    if (slot < 0) { mutex_unlock(&budget_lock); return -ENOENT; }
    was_throttled                         = budget_table[slot].throttled;
    budget_table[slot].active             = 0;
    budget_table[slot].throttled          = 0;
    budget_table[slot].throttle_until_ns  = 0;
    budget_table[slot].current_cpu_quota_mpct = AKXOS_CPU_QUOTA_MAX_PCT * 100;
    mutex_unlock(&budget_lock);

    if (was_throttled) akxos_send_signal(pid, SIGCONT);

    pr_info("akxOS: CLEAR PID=%d\n", pid);
    return 0;
}

static int akxos_set_energy_cap(int pid, unsigned long long cap_uj)
{
    int slot;
    if (pid <= 0) return -EINVAL;
    mutex_lock(&budget_lock);
    slot = akxos_find_slot(pid);
    if (slot >= 0) budget_table[slot].energy_budget_uj = cap_uj;
    mutex_unlock(&budget_lock);
    return (slot >= 0) ? 0 : -ENOENT;
}


/* =================================================================
 * /proc read
 * ================================================================= */

static int akxos_proc_show(struct seq_file *m, void *v)
{
    int i;
    mutex_lock(&budget_lock);
    seq_puts(m, "akxOS power budget controller v1.2  (duty-cycle, cond-integral)\n");
    seq_printf(m, "model: P_mw = (%llu * freq_khz * util_permille) / %llu\n",
               AKXOS_MODEL_CONST_FP, AKXOS_MODEL_DIVISOR);
    seq_puts(m,
        "PID\tBudget\tFreq\tUtil\tPower\tError\tIntegral\t"
        "Quota%\tStop_ms\tThr\tViol\tEnergy_uJ\tECap_uJ\n");
    for (i = 0; i < AKXOS_MAX_BUDGETS; i++) {
        if (!budget_table[i].active) continue;
        seq_printf(m,
            "%d\t%d\t%u\t%d\t%d\t%d\t%d\t\t"
            "%d\t%llu\t%d\t%d\t%llu\t\t%llu\n",
            budget_table[i].pid,
            budget_table[i].budget_mw,
            budget_table[i].last_freq_khz,
            budget_table[i].util_permille,
            budget_table[i].estimated_power_mw,
            budget_table[i].error_mw,
            budget_table[i].integral_error_mw,
            budget_table[i].current_cpu_quota_mpct / 100,
            budget_table[i].stop_ms_last,
            budget_table[i].throttled,
            budget_table[i].violation_total,
            budget_table[i].energy_uj,
            budget_table[i].energy_budget_uj);
    }
    mutex_unlock(&budget_lock);
    return 0;
}

static int akxos_proc_open(struct inode *inode, struct file *file)
{
    return single_open(file, akxos_proc_show, NULL);
}

static ssize_t akxos_proc_write(struct file *file,
                                const char __user *buffer,
                                size_t count, loff_t *ppos)
{
    char *kbuf;
    char  cmd[32];
    int   pid = 0, budget = 0, ret = 0;
    unsigned long long cap_uj = 0;

    if (!count || count > 128) return -EINVAL;
    kbuf = kzalloc(count + 1, GFP_KERNEL);
    if (!kbuf) return -ENOMEM;
    if (copy_from_user(kbuf, buffer, count)) { kfree(kbuf); return -EFAULT; }
    if (kbuf[count-1] == '\n') kbuf[count-1] = '\0';

    sscanf(kbuf, "%31s %d %d", cmd, &pid, &budget);

    if (!strcmp(cmd, "set")) {
        ret = budget > 0 ? akxos_set_budget(pid, budget) : -EINVAL;
    } else if (!strcmp(cmd, "clear")) {
        ret = akxos_clear_budget(pid);
    } else if (!strcmp(cmd, "ecap")) {
        ret = sscanf(kbuf, "%31s %d %llu", cmd, &pid, &cap_uj) == 3
              ? akxos_set_energy_cap(pid, cap_uj) : -EINVAL;
    } else if (!strcmp(cmd, "reset_energy")) {
        int slot;
        mutex_lock(&budget_lock);
        slot = akxos_find_slot(pid);
        if (slot >= 0) budget_table[slot].energy_uj = 0; else ret = -ENOENT;
        mutex_unlock(&budget_lock);
    } else if (!strcmp(cmd, "reset_ctrl")) {
        int slot;
        mutex_lock(&budget_lock);
        slot = akxos_find_slot(pid);
        if (slot >= 0) {
            budget_table[slot].integral_error_mw     = 0;
            budget_table[slot].current_cpu_quota_mpct =
                AKXOS_CPU_QUOTA_MAX_PCT * 100;
            budget_table[slot].throttled              = 0;
            budget_table[slot].throttle_until_ns      = 0;
        } else ret = -ENOENT;
        mutex_unlock(&budget_lock);
        if (!ret) akxos_send_signal(pid, SIGCONT);
    } else {
        ret = -EINVAL;
    }

    kfree(kbuf);
    return ret ? ret : (ssize_t)count;
}

static const struct proc_ops akxos_proc_ops = {
    .proc_open    = akxos_proc_open,
    .proc_read    = seq_read,
    .proc_write   = akxos_proc_write,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};


/* =================================================================
 * Module init / exit
 * ================================================================= */

static int __init akxos_sched_init(void)
{
    memset(budget_table, 0, sizeof(budget_table));

    akxos_proc_entry = proc_create(AKXOS_CONTROL_PROC, 0666, NULL,
                                   &akxos_proc_ops);
    if (!akxos_proc_entry) {
        pr_err("akxOS: failed to create /proc/%s\n", AKXOS_CONTROL_PROC);
        return -ENOMEM;
    }

    INIT_DELAYED_WORK(&akxos_measure_work, akxos_measure_loop);
    INIT_DELAYED_WORK(&akxos_resume_work,  akxos_resume_loop);

    schedule_delayed_work(&akxos_measure_work,
                          msecs_to_jiffies(AKXOS_SAMPLE_INTERVAL_MS));
    schedule_delayed_work(&akxos_resume_work,
                          msecs_to_jiffies(AKXOS_RESUME_POLL_MS));

    pr_info("akxOS: v1.2 loaded  measure=%dms  resume_poll=%dms  deadband=%dmW\n",
            AKXOS_SAMPLE_INTERVAL_MS, AKXOS_RESUME_POLL_MS, AKXOS_PI_DEADBAND_MW);
    return 0;
}

static void __exit akxos_sched_exit(void)
{
    int i;

    cancel_delayed_work_sync(&akxos_measure_work);
    cancel_delayed_work_sync(&akxos_resume_work);

    mutex_lock(&budget_lock);
    for (i = 0; i < AKXOS_MAX_BUDGETS; i++)
        budget_table[i].active = 0;
    mutex_unlock(&budget_lock);

    for (i = 0; i < AKXOS_MAX_BUDGETS; i++)
        if (budget_table[i].throttled)
            akxos_send_signal(budget_table[i].pid, SIGCONT);

    if (akxos_proc_entry) proc_remove(akxos_proc_entry);
    pr_info("akxOS: unloaded\n");
}

module_init(akxos_sched_init);
module_exit(akxos_sched_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("akxOS");
MODULE_DESCRIPTION("akxOS duty-cycle power budget controller v1.2");
MODULE_VERSION("1.2");
