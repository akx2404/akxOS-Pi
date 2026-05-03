#ifndef AKXOS_SCHED_H
#define AKXOS_SCHED_H

#define AKXOS_MAX_BUDGETS 64
#define AKXOS_CONTROL_PROC "akxos_sched"

#define AKXOS_SAMPLE_INTERVAL_MS 500

/*
 * Fixed-point relative power model:
 *
 * util_permille = 0..1000
 *
 * estimated_power_mw =
 *      util_permille * freq_mhz * scale / 1000
 */
#define AKXOS_DEFAULT_FREQ_MHZ 150
#define AKXOS_POWER_SCALE 1

/*
 * CPU quota limits.
 */
#define AKXOS_CPU_QUOTA_MIN_PCT 20
#define AKXOS_CPU_QUOTA_MAX_PCT 100

/*
 * PI controller gains.
 *
 * These are integer fixed-point gains.
 *
 * delta_quota =
 *      Kp * error + Ki * integral_error
 *
 * Kp = AKXOS_KP_NUM / AKXOS_KP_DEN
 * Ki = AKXOS_KI_NUM / AKXOS_KI_DEN
 */
#define AKXOS_KP_NUM 1
#define AKXOS_KP_DEN 10

#define AKXOS_KI_NUM 1
#define AKXOS_KI_DEN 100

/*
 * Integral windup clamp.
 */
#define AKXOS_INTEGRAL_LIMIT 5000

struct akxos_budget_entry {
    int pid;
    int budget_mw;

    unsigned long long last_exec_runtime_ns;
    unsigned long long last_wall_time_ns;

    int util_permille;
    int estimated_power_mw;

    int error_mw;
    int integral_error_mw;
    int violation_count;

    int current_cpu_quota_pct;

    int throttled;
    unsigned long long throttle_until_ns;

    int active;
};

#endif
