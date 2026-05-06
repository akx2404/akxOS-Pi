#ifndef AKXOS_SCHED_H
#define AKXOS_SCHED_H

/* ============================================================
 * akxOS Kernel Power Budget Controlle
 * ============================================================
 * Duty-cycle SIGSTOP/SIGCONT power-budget controller with zero-power watchdog.
 *
 * /proc output expected by tests/experiment_settling.py:
 * PID Budget Freq Util Power Error Integral Quota% Stop_ms Thr Viol Energy_uJ ECap_uJ
 */

#define AKXOS_MAX_BUDGETS        64
#define AKXOS_CONTROL_PROC       "akxos_sched"

/* Main measurement interval */
#define AKXOS_SAMPLE_INTERVAL_MS 500

/* Resume polling interval */
#define AKXOS_RESUME_POLL_MS    10

/* Always leave at least this much run time per window */
#define AKXOS_MIN_RUN_MS        40

/* Power model:
 * P_mw = (CONST_FP · freq_khz · util_permille) / 10^9
 */
#define AKXOS_MODEL_CONST_FP     162ULL
#define AKXOS_MODEL_DIVISOR      1000000000ULL
#define AKXOS_FALLBACK_FREQ_KHZ  1500000

/* PI controller gains, scaled x1000 */
#define AKXOS_KP_NUM_S           100
#define AKXOS_KP_DEN_S           1000
#define AKXOS_KI_NUM_S           10
#define AKXOS_KI_DEN_S           1000
#define AKXOS_PI_DEADBAND_MW     4
#define AKXOS_PI_INTEG_THRESH_MW 8
#define AKXOS_INTEGRAL_LIMIT     80

#define AKXOS_CPU_QUOTA_MIN_PCT  15
#define AKXOS_CPU_QUOTA_MAX_PCT  100

/* Zero-power watchdog: if a live PID reports zero util/power for this
 * many measurement windows, force SIGCONT and skip PI for that sample. */
#define AKXOS_ZERO_POWER_STREAK_LIMIT 2

/* =================================================================
 * Per-process budget entry
 * ================================================================= */
struct akxos_budget_entry {

    int  pid;
    int  budget_mw;

    /* Measurement */
    unsigned long long last_exec_runtime_ns;
    unsigned long long last_wall_time_ns;
    int util_permille;
    int estimated_power_mw;

    /* PI state — no prev_error_mw (zero-crossing reset removed) */
    int error_mw;
    int integral_error_mw;
    int current_cpu_quota_mpct; /* quota ×100 */

    /* Duty-cycle throttle */
    int throttled;
    unsigned long long throttle_until_ns;
    unsigned long long stop_ms_last;

    int violation_total;

    unsigned long long energy_uj;
    unsigned long long energy_budget_uj;

    unsigned int last_freq_khz;

    /* Watchdog against missed SIGCONT / permanently stopped process */
    int zero_power_streak;

    int active;
};

#define AKXOS_SIG_NONE 0
#define AKXOS_SIG_STOP 1
#define AKXOS_SIG_CONT 2

struct akxos_deferred_signal {
    int pid;
    int sig_action;
};

#endif
