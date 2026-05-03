#ifndef AKXOS_SCHED_H
#define AKXOS_SCHED_H

/* ============================================================
 * akxOS Kernel Power Budget Controller
 * ============================================================

#define AKXOS_MAX_BUDGETS        64
#define AKXOS_CONTROL_PROC       "akxos_sched"

/* Main measurement interval */
#define AKXOS_SAMPLE_INTERVAL_MS  500

/* Resume polling interval — SIGCONT is fired within ±this of the
 * target time.
 *  50ms → ±10% duty cycle → ±12mW at P_run=120mW  (oscillates)
 *  10ms → ±2%  duty cycle →  ±2mW at P_run=120mW  (stable ±4mW) */
#define AKXOS_RESUME_POLL_MS       10

/* Always leave at least this much run time per window for measurement */
#define AKXOS_MIN_RUN_MS           40

/* ---- Power model (matches Python CMOS model) ----------------------
 *  P_mw = (CONST_FP · freq_khz · util_permille) / 10^9
 *  CONST_FP = ALPHA · C_eff · V_NOM² · 10^12 = 0.15·1.2e-9·0.9025·1e12 = 162
 */
#define AKXOS_MODEL_CONST_FP     162ULL
#define AKXOS_MODEL_DIVISOR  1000000000ULL
#define AKXOS_FALLBACK_FREQ_KHZ  1500000

/* ---- PI controller (gains scaled ×1000 to prevent truncation) ----
 *  Kp = 0.10  — fast convergence, stable without integral windup
 *  Ki = 0.01  — fine steady-state correction inside ±8mW band only
 *
 *  Deadband ±4mW: Kp halved, integral frozen — matches ±4mW target
 *
 *  Conditional integration: integral updates ONLY when |error| ≤ 8mW.
 *  This is the key fix for the 60↔120mW oscillation.
 *  Previously: large negative integral built up during convergence;
 *  zero-crossing reset wiped it; P-term alone shot quota to 100%;
 *  process ran free; repeat.
 *  Now: integral stays bounded ≤80 mW·samples; it can only nudge
 *  the steady-state error by a few mW, not cause oscillation.
 */
#define AKXOS_KP_NUM_S   100
#define AKXOS_KP_DEN_S  1000
#define AKXOS_KI_NUM_S    10
#define AKXOS_KI_DEN_S  1000
#define AKXOS_PI_DEADBAND_MW       4   /* ±4mW — matches target band     */
#define AKXOS_PI_INTEG_THRESH_MW   8   /* integrate only within ±8mW     */
#define AKXOS_INTEGRAL_LIMIT      80   /* small: integral only active ±8mW */

/* Minimum quota: prevents degenerate <20ms measurement windows.
 * At 25% quota, stop_ms = 375ms max, run_ms ≥ 125ms — enough to measure. */
#define AKXOS_CPU_QUOTA_MIN_PCT    25
#define AKXOS_CPU_QUOTA_MAX_PCT   100

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
    int current_cpu_quota_mpct; /* quota × 100, e.g. 6700 = 67.00% */

    /* Duty-cycle throttle */
    int throttled;
    unsigned long long throttle_until_ns;
    unsigned long long stop_ms_last;   /* for /proc display */

    /* Telemetry only — not used in control decision */
    int violation_total;

    /* Energy accounting */
    unsigned long long energy_uj;
    unsigned long long energy_budget_uj;

    /* Live freq snapshot */
    unsigned int last_freq_khz;

    int active;
};

#define AKXOS_SIG_NONE  0
#define AKXOS_SIG_STOP  1
#define AKXOS_SIG_CONT  2

struct akxos_deferred_signal {
    int pid;
    int sig_action;
};

#endif
