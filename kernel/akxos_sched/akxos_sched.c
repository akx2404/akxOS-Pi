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

#include "akxos_sched.h"

#define DRIVER_NAME "akxos_sched"

static struct akxos_budget_entry budget_table[AKXOS_MAX_BUDGETS];
static DEFINE_MUTEX(budget_lock);

static struct delayed_work akxos_work;
static struct proc_dir_entry *akxos_proc_entry;

/* ---------------------------------------------------------
 * PID → task_struct helper
 * --------------------------------------------------------- */

static struct task_struct *akxos_find_task_by_pid(pid_t pid)
{
    struct task_struct *task;

    rcu_read_lock();

    task = pid_task(find_vpid(pid), PIDTYPE_PID);

    if (task)
        get_task_struct(task);

    rcu_read_unlock();

    return task;
}

/* ---------------------------------------------------------
 * Signal-based CPU quota control
 *
 * SIGSTOP = pause process
 * SIGCONT = resume process
 * --------------------------------------------------------- */

static int akxos_send_signal_to_pid(int pid, int sig)
{
    struct task_struct *task;
    int ret;

    task = akxos_find_task_by_pid(pid);

    if (!task)
        return -ESRCH;

    ret = send_sig(sig, task, 0);

    put_task_struct(task);
    return ret;
}

static int akxos_pause_task(int pid)
{
    return akxos_send_signal_to_pid(pid, SIGSTOP);
}

static int akxos_resume_task(int pid)
{
    return akxos_send_signal_to_pid(pid, SIGCONT);
}

/* ---------------------------------------------------------
 * Budget table helpers
 * --------------------------------------------------------- */

static int akxos_find_budget_slot(int pid)
{
    int i;

    for (i = 0; i < AKXOS_MAX_BUDGETS; i++) {
        if (budget_table[i].active && budget_table[i].pid == pid)
            return i;
    }

    return -1;
}

static int akxos_find_free_slot(void)
{
    int i;

    for (i = 0; i < AKXOS_MAX_BUDGETS; i++) {
        if (!budget_table[i].active)
            return i;
    }

    return -1;
}

/* ---------------------------------------------------------
 * Kernel-side relative power estimation
 * --------------------------------------------------------- */

static int akxos_estimate_power_mw(int util_permille)
{
    return (util_permille * AKXOS_DEFAULT_FREQ_MHZ * AKXOS_POWER_SCALE) / 1000;
}

/* ---------------------------------------------------------
 * Clamp helper
 * --------------------------------------------------------- */

static int akxos_clamp_int(int value, int min_value, int max_value)
{
    if (value < min_value)
        return min_value;

    if (value > max_value)
        return max_value;

    return value;
}

/* ---------------------------------------------------------
 * PI CPU quota controller
 *
 * error = budget - estimated_power
 *
 * If power > budget:
 *      error negative
 *      quota decreases
 *
 * If power < budget:
 *      error positive
 *      quota increases
 *
 * integral_error stores past error, so controller remembers whether
 * the process has been over or under budget for multiple samples.
 * --------------------------------------------------------- */

static int akxos_pi_controller_step(struct akxos_budget_entry *entry)
{
    int error;
    int p_term;
    int i_term;
    int delta_quota;
    int new_quota;

    if (entry->budget_mw <= 0)
        return AKXOS_CPU_QUOTA_MAX_PCT;

    error = entry->budget_mw - entry->estimated_power_mw;

    entry->error_mw = error;

    entry->integral_error_mw += error;

    entry->integral_error_mw = akxos_clamp_int(
        entry->integral_error_mw,
        -AKXOS_INTEGRAL_LIMIT,
        AKXOS_INTEGRAL_LIMIT
    );

    /*
     * Scale terms relative to budget.
     *
     * p_term and i_term are in quota percentage points.
     */
    p_term =
        (AKXOS_KP_NUM * error * 100) /
        (AKXOS_KP_DEN * entry->budget_mw);

    i_term =
        (AKXOS_KI_NUM * entry->integral_error_mw * 100) /
        (AKXOS_KI_DEN * entry->budget_mw);

    delta_quota = p_term + i_term;

    new_quota = entry->current_cpu_quota_pct + delta_quota;

    new_quota = akxos_clamp_int(
        new_quota,
        AKXOS_CPU_QUOTA_MIN_PCT,
        AKXOS_CPU_QUOTA_MAX_PCT
    );

    /*
     * Simple anti-windup correction:
     * if quota is saturated and error keeps pushing further into saturation,
     * reduce integral pressure.
     */
    if (new_quota == AKXOS_CPU_QUOTA_MIN_PCT && error < 0)
        entry->integral_error_mw -= error;

    if (new_quota == AKXOS_CPU_QUOTA_MAX_PCT && error > 0)
        entry->integral_error_mw -= error;

    return new_quota;
}

/* ---------------------------------------------------------
 * Apply CPU quota using pause/resume timing
 *
 * Example:
 *      sample interval = 500 ms
 *      cpu_quota = 40%
 *
 * Allowed time ≈ 200 ms
 * Throttle time ≈ 300 ms
 *
 * This implementation applies throttling after measurement.
 * --------------------------------------------------------- */

static void akxos_apply_cpu_quota(struct akxos_budget_entry *entry,
                                  unsigned long long now_ns)
{
    int cpu_quota_pct;
    int throttle_ms;
    unsigned long long throttle_ns;

    cpu_quota_pct = akxos_pi_controller_step(entry);

    entry->current_cpu_quota_pct = cpu_quota_pct;

    if (entry->estimated_power_mw > entry->budget_mw)
        entry->violation_count++;

    if (cpu_quota_pct >= AKXOS_CPU_QUOTA_MAX_PCT) {
        if (entry->throttled) {
            akxos_resume_task(entry->pid);
            entry->throttled = 0;
            entry->throttle_until_ns = 0;
        }
        return;
    }

    throttle_ms =
        (AKXOS_SAMPLE_INTERVAL_MS *
         (AKXOS_CPU_QUOTA_MAX_PCT - cpu_quota_pct)) / 100;

    if (throttle_ms <= 0)
        return;

    throttle_ns = (unsigned long long)throttle_ms * 1000000ULL;

    entry->throttled = 1;
    entry->throttle_until_ns = now_ns + throttle_ns;

    akxos_pause_task(entry->pid);
}

/* ---------------------------------------------------------
 * Set budget
 *
 * Command:
 *      echo "set <pid> <budget_mw>" > /proc/akxos_sched
 * --------------------------------------------------------- */

static int akxos_set_budget(int pid, int budget_mw)
{
    int slot;
    struct task_struct *task;
    unsigned long long now_ns;
    unsigned long long exec_ns;

    if (pid <= 0 || budget_mw <= 0)
        return -EINVAL;

    task = akxos_find_task_by_pid(pid);

    if (!task)
        return -ESRCH;

    now_ns = ktime_get_ns();
    exec_ns = task->se.sum_exec_runtime;

    put_task_struct(task);

    mutex_lock(&budget_lock);

    slot = akxos_find_budget_slot(pid);

    if (slot < 0)
        slot = akxos_find_free_slot();

    if (slot < 0) {
        mutex_unlock(&budget_lock);
        return -ENOMEM;
    }

    budget_table[slot].pid = pid;
    budget_table[slot].budget_mw = budget_mw;

    budget_table[slot].last_exec_runtime_ns = exec_ns;
    budget_table[slot].last_wall_time_ns = now_ns;

    budget_table[slot].util_permille = 0;
    budget_table[slot].estimated_power_mw = 0;

    budget_table[slot].error_mw = 0;
    budget_table[slot].integral_error_mw = 0;
    budget_table[slot].violation_count = 0;

    budget_table[slot].current_cpu_quota_pct = AKXOS_CPU_QUOTA_MAX_PCT;

    budget_table[slot].throttled = 0;
    budget_table[slot].throttle_until_ns = 0;

    budget_table[slot].active = 1;

    mutex_unlock(&budget_lock);

    akxos_resume_task(pid);

    pr_info("akxOS sched: SET cpu_quota budget PID=%d budget=%d mW\n",
            pid, budget_mw);

    return 0;
}

/* ---------------------------------------------------------
 * Clear budget
 *
 * Command:
 *      echo "clear <pid>" > /proc/akxos_sched
 * --------------------------------------------------------- */

static int akxos_clear_budget(int pid)
{
    int slot;

    if (pid <= 0)
        return -EINVAL;

    mutex_lock(&budget_lock);

    slot = akxos_find_budget_slot(pid);

    if (slot < 0) {
        mutex_unlock(&budget_lock);
        return -ENOENT;
    }

    budget_table[slot].active = 0;
    budget_table[slot].throttled = 0;
    budget_table[slot].throttle_until_ns = 0;
    budget_table[slot].current_cpu_quota_pct = AKXOS_CPU_QUOTA_MAX_PCT;

    mutex_unlock(&budget_lock);

    akxos_resume_task(pid);

    pr_info("akxOS sched: CLEAR cpu_quota budget PID=%d\n", pid);

    return 0;
}

/* ---------------------------------------------------------
 * Internal kernel feedback control loop
 * --------------------------------------------------------- */

static void akxos_control_loop(struct work_struct *work)
{
    int i;
    unsigned long long now_ns;

    now_ns = ktime_get_ns();

    mutex_lock(&budget_lock);

    for (i = 0; i < AKXOS_MAX_BUDGETS; i++) {
        struct task_struct *task;
        unsigned long long exec_ns;
        unsigned long long delta_exec;
        unsigned long long delta_wall;
        int util_permille;
        int estimated_power;
        int pid;

        if (!budget_table[i].active)
            continue;

        pid = budget_table[i].pid;

        /*
         * Resume task if previous CPU-quota throttle window expired.
         */
        if (budget_table[i].throttled &&
            now_ns >= budget_table[i].throttle_until_ns) {

            akxos_resume_task(pid);
            budget_table[i].throttled = 0;
            budget_table[i].throttle_until_ns = 0;
        }

        task = akxos_find_task_by_pid(pid);

        if (!task) {
            pr_info("akxOS sched: PID=%d exited, clearing budget\n", pid);
            budget_table[i].active = 0;
            continue;
        }

        exec_ns = task->se.sum_exec_runtime;

        put_task_struct(task);

        delta_exec = exec_ns - budget_table[i].last_exec_runtime_ns;
        delta_wall = now_ns - budget_table[i].last_wall_time_ns;

        if (delta_wall == 0)
            continue;

        util_permille = (int)((delta_exec * 1000ULL) / delta_wall);

        util_permille = akxos_clamp_int(util_permille, 0, 1000);

        estimated_power = akxos_estimate_power_mw(util_permille);

        budget_table[i].util_permille = util_permille;
        budget_table[i].estimated_power_mw = estimated_power;

        budget_table[i].last_exec_runtime_ns = exec_ns;
        budget_table[i].last_wall_time_ns = now_ns;

        akxos_apply_cpu_quota(&budget_table[i], now_ns);

        pr_info("akxOS cpu_quota: PID=%d util=%d/1000 power=%d mW budget=%d mW error=%d integral=%d cpu_quota=%d%% throttled=%d violations=%d\n",
                budget_table[i].pid,
                budget_table[i].util_permille,
                budget_table[i].estimated_power_mw,
                budget_table[i].budget_mw,
                budget_table[i].error_mw,
                budget_table[i].integral_error_mw,
                budget_table[i].current_cpu_quota_pct,
                budget_table[i].throttled,
                budget_table[i].violation_count);
    }

    mutex_unlock(&budget_lock);

    schedule_delayed_work(
        &akxos_work,
        msecs_to_jiffies(AKXOS_SAMPLE_INTERVAL_MS)
    );
}

/* ---------------------------------------------------------
 * /proc status output
 * --------------------------------------------------------- */

static int akxos_proc_show(struct seq_file *m, void *v)
{
    int i;

    mutex_lock(&budget_lock);

    seq_puts(m, "akxOS kernel cpu_quota controller\n");
    seq_puts(m, "PID\tBudget\tUtil\tPower\tError\tIntegral\tCPU_Quota\tThrottle\tViolations\tActive\n");

    for (i = 0; i < AKXOS_MAX_BUDGETS; i++) {
        if (!budget_table[i].active)
            continue;

        seq_printf(
            m,
            "%d\t%d\t%d\t%d\t%d\t%d\t\t%d%%\t\t%d\t\t%d\t\t%d\n",
            budget_table[i].pid,
            budget_table[i].budget_mw,
            budget_table[i].util_permille,
            budget_table[i].estimated_power_mw,
            budget_table[i].error_mw,
            budget_table[i].integral_error_mw,
            budget_table[i].current_cpu_quota_pct,
            budget_table[i].throttled,
            budget_table[i].violation_count,
            budget_table[i].active
        );
    }

    mutex_unlock(&budget_lock);

    return 0;
}

static int akxos_proc_open(struct inode *inode, struct file *file)
{
    return single_open(file, akxos_proc_show, NULL);
}

/* ---------------------------------------------------------
 * /proc command input
 *
 * Commands:
 *
 *      echo "set <pid> <budget_mw>" > /proc/akxos_sched
 *      echo "clear <pid>" > /proc/akxos_sched
 * --------------------------------------------------------- */

static ssize_t akxos_proc_write(struct file *file,
                                const char __user *buffer,
                                size_t count,
                                loff_t *ppos)
{
    char *kbuf;
    char cmd[16];
    int pid = 0;
    int budget = 0;
    int fields;
    int ret = 0;

    if (count == 0 || count > 128)
        return -EINVAL;

    kbuf = kzalloc(count + 1, GFP_KERNEL);

    if (!kbuf)
        return -ENOMEM;

    if (copy_from_user(kbuf, buffer, count)) {
        kfree(kbuf);
        return -EFAULT;
    }

    fields = sscanf(kbuf, "%15s %d %d", cmd, &pid, &budget);

    if (fields >= 2) {
        if (strcmp(cmd, "set") == 0) {

            if (fields < 3) {
                ret = -EINVAL;
                goto out;
            }

            ret = akxos_set_budget(pid, budget);

        } else if (strcmp(cmd, "clear") == 0) {

            ret = akxos_clear_budget(pid);

        } else {
            ret = -EINVAL;
        }
    } else {
        ret = -EINVAL;
    }

out:
    kfree(kbuf);

    if (ret)
        return ret;

    return count;
}

static const struct proc_ops akxos_proc_ops = {
    .proc_open = akxos_proc_open,
    .proc_read = seq_read,
    .proc_write = akxos_proc_write,
    .proc_lseek = seq_lseek,
    .proc_release = single_release,
};

/* ---------------------------------------------------------
 * Module init / exit
 * --------------------------------------------------------- */

static int __init akxos_sched_init(void)
{
    memset(budget_table, 0, sizeof(budget_table));

    akxos_proc_entry = proc_create(
        AKXOS_CONTROL_PROC,
        0666,
        NULL,
        &akxos_proc_ops
    );

    if (!akxos_proc_entry) {
        pr_err("akxOS sched: failed to create /proc/%s\n",
               AKXOS_CONTROL_PROC);
        return -ENOMEM;
    }

    INIT_DELAYED_WORK(&akxos_work, akxos_control_loop);

    schedule_delayed_work(
        &akxos_work,
        msecs_to_jiffies(AKXOS_SAMPLE_INTERVAL_MS)
    );

    pr_info("akxOS cpu_quota controller loaded: /proc/%s\n",
            AKXOS_CONTROL_PROC);

    return 0;
}

static void __exit akxos_sched_exit(void)
{
    int i;

    cancel_delayed_work_sync(&akxos_work);

    mutex_lock(&budget_lock);

    for (i = 0; i < AKXOS_MAX_BUDGETS; i++) {
        if (budget_table[i].active) {
            akxos_resume_task(budget_table[i].pid);

            budget_table[i].active = 0;
            budget_table[i].throttled = 0;
            budget_table[i].throttle_until_ns = 0;
            budget_table[i].current_cpu_quota_pct = AKXOS_CPU_QUOTA_MAX_PCT;
        }
    }

    mutex_unlock(&budget_lock);

    if (akxos_proc_entry)
        proc_remove(akxos_proc_entry);

    pr_info("akxOS cpu_quota controller unloaded\n");
}

module_init(akxos_sched_init);
module_exit(akxos_sched_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("akxOS");
MODULE_DESCRIPTION("akxOS kernel-level PI cpu_quota power controller");
MODULE_VERSION("0.5");
