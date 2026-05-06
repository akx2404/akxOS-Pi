#!/usr/bin/env python3
"""
Experiment 1 — Step-Change Budget
==================================
Tests controller transient response when the power budget changes
mid-run (not just at startup).

Three configurable budget phases are applied sequentially to the same
workload without restarting it.  Between phases the PI state is reset
so each transition is a clean step-change.

Metrics per phase:
  • Settling time
  • Peak overshoot / undershoot
  • Steady-state mean and error
  • Integral state at the phase boundary (checks for windup carryover)

Usage:
  python3 tests/experiment_step_change.py
  python3 tests/experiment_step_change.py --budgets 120 50 80 --phase-s 25
"""

import argparse
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from experiment_utils import (
    check_driver_or_exit, ensure_output, OUTPUT_DIR, POLL_S,
    set_budget, clear_budget, reset_ctrl,
    launch_workload, terminate_workload,
    proc_read, moving_average, settling_time, save_csv, print_header,
)

# ─── Defaults ────────────────────────────────────────────────
DEFAULT_BUDGETS = [100, 60, 80]
DEFAULT_PHASE_S = 20.0
SMOOTH_WINDOW   = 10
WARMUP_S        = 3.0
PHASE_COLORS    = ["#2196F3", "#F44336", "#4CAF50", "#FF9800"]


# ─── Data collection ─────────────────────────────────────────

def collect_phase(pid: int, phase_idx: int, budget_mw: int,
                  duration_s: float, t0: float) -> list:
    clear_budget(pid)
    reset_ctrl(pid)
    time.sleep(0.2)
    set_budget(pid, budget_mw)

    rows = []
    phase_start = time.monotonic()

    while (time.monotonic() - phase_start) < duration_s:
        t = time.monotonic() - t0
        row = proc_read(pid)
        if row:
            row["time_s"]          = round(t, 3)
            row["phase"]           = phase_idx + 1
            row["phase_budget_mw"] = budget_mw
            rows.append(row)
            print(
                f"t={t:6.1f}s | P={row['power_mw']:4d} mW | "
                f"quota={row['quota_pct']:3d}% | "
                f"err={row['error_mw']:+4d} | "
                f"int={row['integral']:+4d}",
                flush=True,
            )
        time.sleep(POLL_S)

    return rows


# ─── Analysis ────────────────────────────────────────────────

def analyse(rows: list, budgets: list, tol_pct: float = 5.0):
    times      = np.array([r["time_s"]          for r in rows])
    powers     = np.array([r["power_mw"]         for r in rows], float)
    phases     = np.array([r["phase"]            for r in rows])
    integrals  = np.array([r["integral"]         for r in rows], float)
    budgets_ts = np.array([r["phase_budget_mw"]  for r in rows], float)
    smoothed   = moving_average(powers.tolist(), SMOOTH_WINDOW)

    print_header("Step-Change Analysis")

    summaries = []
    for ph_idx, budget in enumerate(budgets):
        mask   = phases == (ph_idx + 1)
        ph_t   = times[mask]
        ph_sm  = smoothed[mask]
        n      = len(ph_sm)

        if n == 0:
            continue

        st  = settling_time(ph_t - ph_t[0], ph_sm, budget, tol_pct)
        osh = max(0.0, float(np.max(ph_sm[:max(1, n // 3)])) - budget)
        ss  = ph_sm[max(0, n * 7 // 10):]

        summaries.append(dict(
            phase      = ph_idx + 1,
            budget_mw  = budget,
            settle_s   = st,
            overshoot  = osh,
            ss_mean    = float(np.mean(ss)),
            ss_error   = float(abs(np.mean(ss) - budget)),
            ss_sigma   = float(np.std(ss)),
        ))

        settle_str = f"{st:.1f}s" if st is not None else "never"
        print(
            f"  Phase {ph_idx+1} budget={budget:4d}mW │ "
            f"settle={settle_str:>7} │ "
            f"overshoot={osh:6.1f}mW │ "
            f"ss_mean={float(np.mean(ss)):6.1f} │ "
            f"ss_err={float(abs(np.mean(ss)-budget)):5.2f}"
        )

    # Integral carryover at each transition
    print("\n  Integral state at phase transitions:")
    for ph_idx in range(1, len(budgets)):
        mask_before = phases == ph_idx
        mask_after  = phases == (ph_idx + 1)
        if mask_before.any() and mask_after.any():
            int_b = float(integrals[mask_before][-5:].mean())
            int_a = float(integrals[mask_after][:5].mean())
            delta = int_a - int_b
            flag  = "  ← CARRYOVER" if abs(delta) > 5 else ""
            print(f"    Ph{ph_idx}→Ph{ph_idx+1}: "
                  f"{int_b:+.1f} → {int_a:+.1f} (Δ={delta:+.1f}){flag}")

    return times, powers, phases, integrals, budgets_ts, smoothed, summaries


# ─── Plotting ────────────────────────────────────────────────

def plot(pid, times, powers, phases, integrals,
         budgets_ts, smoothed, budgets, rows):
    quotas   = np.array([r["quota_pct"] for r in rows], float)
    stop_ms  = np.array([r["stop_ms"]   for r in rows], float)

    fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True)
    fig.suptitle(
        f"Step-Change Budget Experiment  (PID {pid})\n"
        f"Phases: {' → '.join(str(b)+'mW' for b in budgets)}",
        fontweight="bold",
    )

    # Phase shade helper
    def shade(ax):
        for ph_idx, budget in enumerate(budgets):
            mask = phases == (ph_idx + 1)
            if mask.any():
                ax.axvspan(times[mask][0], times[mask][-1],
                           alpha=0.07, color=PHASE_COLORS[ph_idx % len(PHASE_COLORS)])
                ax.axvline(times[mask][0], linewidth=1.0,
                           linestyle=":", color="gray", alpha=0.6)

    # ── Power ──
    ax = axes[0]
    ax.plot(times, powers, alpha=0.35, linewidth=0.8, color="steelblue", label="Raw power")
    ax.plot(times, smoothed, linewidth=2.0, color="steelblue", label=f"Smoothed (w={SMOOTH_WINDOW})")
    ax.step(times, budgets_ts, linewidth=1.5, linestyle="--",
            color="black", where="post", label="Budget setpoint")
    shade(ax)
    ax.set_ylabel("Power (mW)")
    ax.set_title("Power vs budget (phases shaded)")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(True, alpha=0.25)
    ax.set_ylim(bottom=0)

    # ── Quota + Stop_ms ──
    ax   = axes[1]
    ax2  = ax.twinx()
    ax.plot(times, quotas,  linewidth=1.5, color="#9C27B0", label="Quota (%)")
    ax2.plot(times, stop_ms, linewidth=1.2, linestyle="--",
             color="#FF5722", alpha=0.7, label="Stop duration (ms)")
    shade(ax)
    ax.set_ylabel("CPU Quota (%)");  ax.set_ylim(0, 110)
    ax2.set_ylabel("Stop duration (ms)")
    ax.set_title("Controller action")
    ax.grid(True, alpha=0.25)
    lines1, lbl1 = ax.get_legend_handles_labels()
    lines2, lbl2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, lbl1 + lbl2, fontsize=8, loc="lower right")

    # ── Integral ──
    ax = axes[2]
    ax.plot(times, integrals, linewidth=1.5, color="#F44336")
    ax.axhline(0, linewidth=0.8, linestyle="--", color="black")
    shade(ax)
    ax.set_ylabel("PI Integral (mW)")
    ax.set_xlabel("Time (s)")
    ax.set_title("Integral state — check for windup carryover at transitions")
    ax.grid(True, alpha=0.25)

    plt.tight_layout()
    path = OUTPUT_DIR / f"step_change_pid{pid}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Plot saved: {path}")


# ─── Main ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Step-change budget experiment")
    ap.add_argument("--budgets", type=int, nargs="+", default=DEFAULT_BUDGETS,
                    help="Budget sequence in mW (default: 100 60 80)")
    ap.add_argument("--phase-s", type=float, default=DEFAULT_PHASE_S,
                    help="Duration of each phase in seconds (default: 20)")
    ap.add_argument("--tol", type=float, default=5.0,
                    help="Settling tolerance %% (default: 5)")
    args = ap.parse_args()

    check_driver_or_exit()
    ensure_output()

    workload = launch_workload()
    pid = workload.pid
    print(f"Workload PID : {pid}")
    print(f"Budget phases: {args.budgets} mW, {args.phase_s}s each")
    print(f"Warming up {WARMUP_S}s …")
    time.sleep(WARMUP_S)

    all_rows = []
    t0 = time.monotonic()

    try:
        for idx, budget in enumerate(args.budgets):
            print(f"\n─── Phase {idx+1}/{len(args.budgets)}: budget = {budget} mW ───")
            rows = collect_phase(pid, idx, budget, args.phase_s, t0)
            all_rows.extend(rows)
    finally:
        clear_budget(pid)
        terminate_workload(workload)

    if not all_rows:
        print("No data collected."); return

    fields = [
        "time_s", "phase", "phase_budget_mw",
        "pid", "budget_mw", "power_mw", "quota_pct", "stop_ms",
        "integral", "error_mw", "util", "freq_khz", "energy_uj", "viol",
    ]
    save_csv(OUTPUT_DIR / f"step_change_pid{pid}.csv", fields, all_rows)

    times, powers, phases, integrals, budgets_ts, smoothed, summaries = \
        analyse(all_rows, args.budgets, args.tol)

    plot(pid, times, powers, phases, integrals,
         budgets_ts, smoothed, args.budgets, all_rows)


if __name__ == "__main__":
    main()
