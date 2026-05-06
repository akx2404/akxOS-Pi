#!/usr/bin/env python3
"""
Experiment 8 — Controller Reset Recovery
==========================================
Deliberately saturates the PI controller (drives integral to its
clamped limit), then issues reset_ctrl and measures the time to
re-settle at a new budget.

Three phases:
  saturate  — aggressive budget well below natural power; integral
               winds up and the quota floor is hit
  reset     — brief pause; issue reset_ctrl (clears integral, quota→100%)
  recover   — set a normal budget; measure settling behaviour

Validates:
  • reset_ctrl zeroes integral and restores quota to 100%
  • No carryover from the saturated state corrupts the recovery transient
  • Recovery settling time is comparable to a cold-start settling

Usage:
  python3 tests/experiment_reset_recovery.py
  python3 tests/experiment_reset_recovery.py --sat-budget 20 --recover-budget 80
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

DEFAULT_SAT_BUDGET     = 20     # mW — far below natural power
DEFAULT_RECOVER_BUDGET = 80     # mW — normal operating budget
DEFAULT_SAT_S          = 20.0   # seconds to saturate
DEFAULT_RECOVER_S      = 30.0   # seconds to collect recovery
RESET_PAUSE_S          = 1.0    # pause between phases
WARMUP_S               = 3.0
SMOOTH_W               = 8

# Reference: cold-start settling for comparison
COLDSTART_S            = 20.0


# ─── Phase: saturation ───────────────────────────────────────

def saturate(pid: int, budget_mw: int, duration_s: float, t0: float) -> list:
    print(f"\n─── Phase: SATURATE | budget={budget_mw}mW | {duration_s}s ───")
    clear_budget(pid)
    reset_ctrl(pid)
    time.sleep(0.2)
    set_budget(pid, budget_mw)

    rows, start = [], time.monotonic()

    while (time.monotonic() - start) < duration_s:
        time.sleep(POLL_S)
        t   = time.monotonic() - t0
        row = proc_read(pid)
        if row:
            row["time_s"] = round(t, 3)
            row["phase"]  = "saturate"
            rows.append(row)
            print(
                f"t={t:6.1f}s | quota={row['quota_pct']:3d}% | "
                f"int={row['integral']:+4d} | P={row['power_mw']:4d}mW",
                flush=True,
            )
    return rows


# ─── Phase: reset ────────────────────────────────────────────

def do_reset(pid: int, sat_rows: list, t0: float) -> dict:
    print(f"\n─── Issuing reset_ctrl on PID {pid} ───")

    # Capture state just before reset
    last = sat_rows[-1] if sat_rows else {}
    int_before   = last.get("integral", None)
    quota_before = last.get("quota_pct", None)

    reset_ctrl(pid)
    time.sleep(RESET_PAUSE_S)

    # Read state immediately after reset
    row_after = proc_read(pid)

    int_after   = row_after["integral"]  if row_after else None
    quota_after = row_after["quota_pct"] if row_after else None

    print(f"  Integral : {int_before} → {int_after}")
    print(f"  Quota    : {quota_before}% → {quota_after}%")

    int_cleared = (int_after is not None and abs(int_after) < 5)
    if not int_cleared:
        print("  [WARN] Integral not fully cleared after reset_ctrl")

    quota_restored = (quota_after is not None and quota_after >= 95)
    if not quota_restored:
        print("  [WARN] Quota not restored to 100% after reset_ctrl")

    return dict(
        int_before   = int_before,
        quota_before = quota_before,
        int_after    = int_after,
        quota_after  = quota_after,
        int_cleared  = int_cleared,
        quota_restored = quota_restored,
        reset_time_s = round(time.monotonic() - t0, 3),
    )


# ─── Phase: recovery ─────────────────────────────────────────

def recover(pid: int, budget_mw: int, duration_s: float, t0: float) -> list:
    print(f"\n─── Phase: RECOVER | budget={budget_mw}mW | {duration_s}s ───")
    set_budget(pid, budget_mw)

    rows, start = [], time.monotonic()

    while (time.monotonic() - start) < duration_s:
        time.sleep(POLL_S)
        t   = time.monotonic() - t0
        row = proc_read(pid)
        if row:
            row["time_s"] = round(t, 3)
            row["phase"]  = "recover"
            rows.append(row)
            print(
                f"t={t:6.1f}s | P={row['power_mw']:4d}mW | "
                f"quota={row['quota_pct']:3d}% | "
                f"int={row['integral']:+4d} | "
                f"err={row['error_mw']:+4d}",
                flush=True,
            )
    return rows


# ─── Cold-start baseline ─────────────────────────────────────

def coldstart_baseline(pid: int, budget_mw: int, duration_s: float, t0: float) -> list:
    print(f"\n─── Phase: COLDSTART BASELINE | budget={budget_mw}mW | {duration_s}s ───")
    clear_budget(pid)
    reset_ctrl(pid)
    time.sleep(0.5)
    set_budget(pid, budget_mw)

    rows, start = [], time.monotonic()

    while (time.monotonic() - start) < duration_s:
        time.sleep(POLL_S)
        t   = time.monotonic() - t0
        row = proc_read(pid)
        if row:
            row["time_s"] = round(t, 3)
            row["phase"]  = "coldstart"
            rows.append(row)
    return rows


# ─── Analysis ────────────────────────────────────────────────

def analyse(sat_rows, recover_rows, coldstart_rows,
            reset_info, recover_budget, tol_pct=5.0):
    print_header("Reset Recovery Analysis")

    # Reset effectiveness
    print("  reset_ctrl effectiveness:")
    print(f"    Integral cleared   : {reset_info['int_cleared']}")
    print(f"    Quota restored     : {reset_info['quota_restored']}")
    print(f"    Integral before    : {reset_info['int_before']}  →  after: {reset_info['int_after']}")
    print(f"    Quota before       : {reset_info['quota_before']}%  →  after: {reset_info['quota_after']}%")

    # Recovery settling
    def phase_settle(rows, budget):
        if not rows:
            return None, None
        times  = np.array([r["time_s"]   for r in rows])
        powers = np.array([r["power_mw"] for r in rows], float)
        sm     = moving_average(powers.tolist(), SMOOTH_W)
        t_loc  = times - times[0]
        st     = settling_time(t_loc, sm, budget, tol_pct)
        ss_err = float(abs(np.mean(sm[max(0, len(sm)*7//10):]) - budget))
        return st, ss_err

    rec_st,   rec_ss_err = phase_settle(recover_rows,   recover_budget)
    cold_st,  cold_ss_err = phase_settle(coldstart_rows, recover_budget)

    fmt = lambda s: f"{s:.1f}s" if s is not None else "never"

    print(f"\n  Settling comparison (budget={recover_budget}mW, tol=±{tol_pct}%):")
    print(f"    Post-reset   : settle={fmt(rec_st)}  ss_err={rec_ss_err:.2f}mW")
    print(f"    Cold-start   : settle={fmt(cold_st)} ss_err={cold_ss_err:.2f}mW")

    if rec_st and cold_st:
        ratio = rec_st / cold_st
        flag  = "  ← SLOW RECOVERY" if ratio > 1.5 else "  ✓ comparable"
        print(f"    Ratio        : {ratio:.2f}×{flag}")

    # Integral state during saturation phase
    if sat_rows:
        intgrls = np.array([r["integral"] for r in sat_rows])
        print(f"\n  Integral during saturation: max={int(np.max(np.abs(intgrls)))}  "
              f"(limit=80 — {'HIT' if int(np.max(np.abs(intgrls))) >= 78 else 'not hit'})")


# ─── Plotting ────────────────────────────────────────────────

def plot(pid: int, sat_rows, recover_rows, coldstart_rows,
         sat_budget, recover_budget, reset_info):
    all_rows = sat_rows + recover_rows + coldstart_rows

    times   = np.array([r["time_s"]    for r in all_rows])
    powers  = np.array([r["power_mw"]  for r in all_rows], float)
    quotas  = np.array([r["quota_pct"] for r in all_rows], float)
    intgrls = np.array([r["integral"]  for r in all_rows], float)
    phases  = [r["phase"] for r in all_rows]

    sm = moving_average(powers.tolist(), SMOOTH_W)

    phase_colors = {
        "saturate": "#EF9A9A", "recover": "#A5D6A7", "coldstart": "#90CAF9"
    }

    fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True)
    fig.suptitle(
        f"Controller Reset Recovery  (PID {pid})\n"
        f"Sat budget={sat_budget}mW → reset_ctrl → recover budget={recover_budget}mW",
        fontweight="bold",
    )

    def shade(ax):
        for ph, color in phase_colors.items():
            mask = np.array([p == ph for p in phases])
            if mask.any():
                ax.axvspan(times[mask][0], times[mask][-1],
                           alpha=0.10, color=color, label=ph)
                ax.axvline(times[mask][0], linestyle=":", color="gray", linewidth=0.8)

    # Mark reset event
    reset_t = reset_info["reset_time_s"]

    # Power
    ax = axes[0]
    ax.plot(times, powers, alpha=0.25, linewidth=0.7, color="steelblue")
    ax.plot(times, sm, linewidth=2.0, color="steelblue", label="Smoothed power")
    ax.axhline(recover_budget, linestyle="--", color="green",
               linewidth=1.3, label=f"Recover budget {recover_budget}mW")
    ax.axhline(sat_budget, linestyle="--", color="red",
               linewidth=1.0, label=f"Sat budget {sat_budget}mW", alpha=0.6)
    ax.axvline(reset_t, color="purple", linewidth=2.0, linestyle="-.", label="reset_ctrl")
    shade(ax)
    ax.set_ylabel("Power (mW)"); ax.grid(True, alpha=0.25); ax.set_ylim(bottom=0)
    ax.set_title("Power across saturation → reset → recovery")
    handles, labels = ax.get_legend_handles_labels()
    seen = dict(zip(labels, handles))
    ax.legend(seen.values(), seen.keys(), fontsize=7, loc="upper right")

    # Quota
    ax = axes[1]
    ax.plot(times, quotas, linewidth=1.5, color="#9C27B0")
    ax.axvline(reset_t, color="purple", linewidth=2.0, linestyle="-.", label="reset_ctrl")
    ax.axhline(25, linestyle=":", color="red", linewidth=1.0, label="Min quota 25%")
    ax.axhline(100, linestyle=":", color="green", linewidth=1.0, label="Max quota 100%")
    shade(ax)
    ax.set_ylabel("CPU Quota (%)"); ax.set_ylim(0, 115)
    ax.set_title("Quota — should jump to 100% immediately after reset")
    ax.legend(fontsize=7); ax.grid(True, alpha=0.25)

    # Integral
    ax = axes[2]
    ax.plot(times, intgrls, linewidth=1.5, color="#F44336")
    ax.axvline(reset_t, color="purple", linewidth=2.0, linestyle="-.", label="reset_ctrl")
    ax.axhline(80,   linestyle=":", color="orange", alpha=0.7, label="±limit")
    ax.axhline(-80,  linestyle=":", color="orange", alpha=0.7)
    ax.axhline(0,    linestyle="--", color="black", linewidth=0.8)
    shade(ax)
    ax.set_ylabel("PI Integral"); ax.set_xlabel("Time (s)")
    ax.set_title("Integral — must drop to ≈0 after reset_ctrl")
    ax.legend(fontsize=7); ax.grid(True, alpha=0.25)

    plt.tight_layout()
    path = OUTPUT_DIR / f"reset_recovery_pid{pid}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Plot saved: {path}")


# ─── Main ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Controller reset recovery experiment")
    ap.add_argument("--sat-budget",     type=int,   default=DEFAULT_SAT_BUDGET)
    ap.add_argument("--recover-budget", type=int,   default=DEFAULT_RECOVER_BUDGET)
    ap.add_argument("--sat-s",          type=float, default=DEFAULT_SAT_S)
    ap.add_argument("--recover-s",      type=float, default=DEFAULT_RECOVER_S)
    ap.add_argument("--tol",            type=float, default=5.0)
    args = ap.parse_args()

    check_driver_or_exit()
    ensure_output()

    workload = launch_workload()
    pid = workload.pid
    print(f"Workload PID      : {pid}")
    print(f"Saturation budget : {args.sat_budget} mW")
    print(f"Recovery budget   : {args.recover_budget} mW")
    print(f"Warming up {WARMUP_S}s …")
    time.sleep(WARMUP_S)

    t0          = time.monotonic()
    sat_rows    = []
    recover_rows = []
    coldstart_rows = []
    reset_info  = {}

    try:
        sat_rows  = saturate(pid, args.sat_budget, args.sat_s, t0)
        reset_info = do_reset(pid, sat_rows, t0)
        recover_rows = recover(pid, args.recover_budget, args.recover_s, t0)

        # Cool down, then run cold-start for comparison
        print(f"\nCooldown 5s before cold-start baseline …")
        clear_budget(pid)
        time.sleep(5.0)
        coldstart_rows = coldstart_baseline(
            pid, args.recover_budget, COLDSTART_S, t0
        )
    finally:
        clear_budget(pid)
        terminate_workload(workload)

    all_rows = sat_rows + recover_rows + coldstart_rows
    if not all_rows:
        print("No data."); return

    fields = [
        "time_s", "phase", "pid", "budget_mw", "power_mw",
        "quota_pct", "stop_ms", "integral", "error_mw",
        "util", "freq_khz", "energy_uj", "viol",
    ]
    save_csv(OUTPUT_DIR / f"reset_recovery_pid{pid}.csv", fields, all_rows)

    analyse(sat_rows, recover_rows, coldstart_rows,
            reset_info, args.recover_budget, args.tol)

    plot(pid, sat_rows, recover_rows, coldstart_rows,
         args.sat_budget, args.recover_budget, reset_info)


if __name__ == "__main__":
    main()
