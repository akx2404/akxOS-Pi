#!/usr/bin/env python3
"""
Experiment 3 — Aggressive Budget / Near-Minimum Quota
=======================================================
Sets a power budget well below the workload's natural power to force
the controller against its minimum quota rail (AKXOS_CPU_QUOTA_MIN_PCT = 25%).

This directly exercises:
  • Anti-windup logic at the quota floor
  • Zero-power watchdog (AKXOS_ZERO_POWER_STREAK_LIMIT)
  • SIGCONT reliability when duty-cycle is near-maximum

Two sub-tests:
  floor  — budget so low the controller is pinned at 25% quota
  edge   — budget just above the expected floor to probe transition stability

Metrics:
  • Fraction of time at min-quota (25%)
  • Zero-power streak events (from dmesg)
  • Power oscillation amplitude at the floor
  • Integral state at saturation

Usage:
  python3 tests/experiment_low_budget.py
  python3 tests/experiment_low_budget.py --floor-budget 20 --edge-budget 40 --duration 30
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
    proc_read, moving_average, save_csv, dmesg_grep, print_header,
)

DEFAULT_FLOOR_BUDGET = 20    # mW — well below natural ~120-240 mW
DEFAULT_EDGE_BUDGET  = 45    # mW — near but above where quota would hit 25%
DEFAULT_DURATION     = 30.0  # seconds per sub-test
WARMUP_S             = 3.0
MIN_QUOTA_PCT        = 25    # must match AKXOS_CPU_QUOTA_MIN_PCT
SMOOTH_W             = 6


# ─── Collection ──────────────────────────────────────────────

def collect(label: str, pid: int, budget_mw: int,
            duration_s: float, t0: float) -> list:
    print(f"\n─── Sub-test: {label} | budget={budget_mw} mW | duration={duration_s}s ───")
    clear_budget(pid)
    reset_ctrl(pid)
    time.sleep(0.2)
    set_budget(pid, budget_mw)

    rows  = []
    start = time.monotonic()

    while (time.monotonic() - start) < duration_s:
        time.sleep(POLL_S)
        t   = time.monotonic() - t0
        row = proc_read(pid)
        if row:
            row["time_s"]  = round(t, 3)
            row["label"]   = label
            rows.append(row)
            at_floor = " [FLOOR]" if row["quota_pct"] <= MIN_QUOTA_PCT else ""
            print(
                f"t={t:6.1f}s | P={row['power_mw']:4d}mW | "
                f"quota={row['quota_pct']:3d}%{at_floor} | "
                f"stop={row['stop_ms']:3d}ms | "
                f"int={row['integral']:+4d} | "
                f"viol={row['viol']}",
                flush=True,
            )
        else:
            print(f"t={time.monotonic()-t0:6.1f}s | waiting …", flush=True)

    return rows


# ─── Analysis ────────────────────────────────────────────────

def analyse(label: str, rows: list, budget_mw: int):
    if not rows:
        print(f"  {label}: no data"); return {}

    quotas  = np.array([r["quota_pct"]  for r in rows], float)
    powers  = np.array([r["power_mw"]   for r in rows], float)
    intgrl  = np.array([r["integral"]   for r in rows], float)
    sm      = moving_average(powers.tolist(), SMOOTH_W)

    at_floor       = np.sum(quotas <= MIN_QUOTA_PCT)
    frac_floor     = at_floor / len(quotas) * 100
    ss             = sm[max(0, len(sm) * 7 // 10):]
    power_osc_amp  = float(np.max(sm) - np.min(sm))

    print(f"  {label} (budget={budget_mw}mW):")
    print(f"    Time at min-quota ({MIN_QUOTA_PCT}%): {frac_floor:.1f}%")
    print(f"    Power oscillation amplitude   : {power_osc_amp:.1f} mW")
    print(f"    SS mean power                 : {float(np.mean(ss)):.1f} mW")
    print(f"    Max integral magnitude        : {float(np.max(np.abs(intgrl))):.0f}")
    print(f"    Min quota observed            : {int(np.min(quotas))}%")

    # Scan dmesg for zero-power watchdog events
    watchdog_hits = dmesg_grep(f"zero-power watchdog")
    pid_hits = [l for l in watchdog_hits if f"PID={rows[0]['pid']}" in l]
    print(f"    Zero-power watchdog events    : {len(pid_hits)}")
    for l in pid_hits[-3:]:
        print(f"      {l.strip()}")

    return dict(
        label           = label,
        budget_mw       = budget_mw,
        frac_floor_pct  = round(frac_floor, 2),
        power_osc_mw    = round(power_osc_amp, 2),
        ss_mean_mw      = round(float(np.mean(ss)), 2),
        max_integral    = round(float(np.max(np.abs(intgrl))), 0),
        watchdog_events = len(pid_hits),
    )


# ─── Plotting ────────────────────────────────────────────────

def plot(pid: int, all_rows: list, budgets: dict):
    times   = np.array([r["time_s"]    for r in all_rows])
    powers  = np.array([r["power_mw"]  for r in all_rows], float)
    quotas  = np.array([r["quota_pct"] for r in all_rows], float)
    stop_ms = np.array([r["stop_ms"]   for r in all_rows], float)
    intgrl  = np.array([r["integral"]  for r in all_rows], float)
    labels  = [r["label"] for r in all_rows]
    sm      = moving_average(powers.tolist(), SMOOTH_W)

    label_set   = list(dict.fromkeys(labels))
    label_colors = {"floor": "#EF9A9A", "edge": "#90CAF9"}

    fig, axes = plt.subplots(4, 1, figsize=(13, 12), sharex=True)
    fig.suptitle(
        f"Aggressive Budget / Near-Minimum Quota  (PID {pid})\n"
        f"Floor budget={budgets['floor']}mW | Edge budget={budgets['edge']}mW",
        fontweight="bold",
    )

    def shade(ax):
        for lbl in label_set:
            mask = np.array([l == lbl for l in labels])
            if mask.any():
                ax.axvspan(times[mask][0], times[mask][-1],
                           alpha=0.10, color=label_colors.get(lbl, "#E0E0E0"),
                           label=lbl)
                ax.axvline(times[mask][0], linestyle=":", color="gray", linewidth=0.8)

    # Power
    ax = axes[0]
    ax.plot(times, powers, alpha=0.30, linewidth=0.7, color="steelblue")
    ax.plot(times, sm, linewidth=2.0, color="steelblue", label="Smoothed power")
    shade(ax)
    for lbl, bm in budgets.items():
        mask = np.array([l == lbl for l in labels])
        if mask.any():
            ax.hlines(bm, times[mask][0], times[mask][-1],
                      linestyle="--", linewidth=1.3, color="black", alpha=0.7)
    ax.set_ylabel("Power (mW)"); ax.grid(True, alpha=0.25); ax.set_ylim(bottom=0)
    ax.set_title("Power — note oscillation amplitude at each budget level")
    handles, lbls = ax.get_legend_handles_labels()
    ax.legend(dict(zip(lbls, handles)).values(), dict(zip(lbls, handles)).keys(),
              fontsize=8, loc="upper right")

    # Quota
    ax = axes[1]
    ax.plot(times, quotas, linewidth=1.5, color="#9C27B0")
    ax.axhline(MIN_QUOTA_PCT, linestyle="--", linewidth=1.5,
               color="red", label=f"Min quota ({MIN_QUOTA_PCT}%)")
    shade(ax)
    ax.set_ylabel("CPU Quota (%)"); ax.set_ylim(0, 110)
    ax.set_title("Quota — time pinned at floor signals anti-windup exercise")
    ax.legend(fontsize=8); ax.grid(True, alpha=0.25)

    # Stop_ms
    ax = axes[2]
    ax.plot(times, stop_ms, linewidth=1.3, color="#FF5722")
    ax.set_ylabel("Stop duration (ms)"); ax.grid(True, alpha=0.25)
    ax.set_title("Duty-cycle stop duration per measurement window")
    shade(ax)

    # Integral
    ax = axes[3]
    ax.plot(times, intgrl, linewidth=1.5, color="#F44336")
    ax.axhline(0, linewidth=0.8, linestyle="--", color="black")
    ax.axhline(80,  linewidth=1.0, linestyle=":", color="orange", label="Integral limit ±80")
    ax.axhline(-80, linewidth=1.0, linestyle=":", color="orange")
    shade(ax)
    ax.set_ylabel("PI Integral"); ax.set_xlabel("Time (s)")
    ax.set_title("Integral state — should clamp at ±80 when rail-saturated")
    ax.legend(fontsize=8); ax.grid(True, alpha=0.25)

    plt.tight_layout()
    path = OUTPUT_DIR / f"low_budget_pid{pid}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Plot saved: {path}")


# ─── Main ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Aggressive budget / quota floor experiment")
    ap.add_argument("--floor-budget", type=int, default=DEFAULT_FLOOR_BUDGET,
                    help="Very low budget (default: 20 mW)")
    ap.add_argument("--edge-budget", type=int, default=DEFAULT_EDGE_BUDGET,
                    help="Near-floor budget (default: 45 mW)")
    ap.add_argument("--duration", type=float, default=DEFAULT_DURATION,
                    help="Duration per sub-test in seconds (default: 30)")
    args = ap.parse_args()

    check_driver_or_exit()
    ensure_output()

    workload = launch_workload()
    pid = workload.pid
    print(f"Workload PID : {pid}")
    print(f"Floor budget : {args.floor_budget} mW")
    print(f"Edge budget  : {args.edge_budget} mW")
    print(f"Duration/sub : {args.duration}s")
    print(f"Warming up {WARMUP_S}s …")
    time.sleep(WARMUP_S)

    t0 = time.monotonic()
    all_rows = []

    try:
        rows = collect("floor", pid, args.floor_budget, args.duration, t0)
        all_rows.extend(rows)
        time.sleep(5.0)   # cooldown between sub-tests

        rows = collect("edge", pid, args.edge_budget, args.duration, t0)
        all_rows.extend(rows)
    finally:
        clear_budget(pid)
        terminate_workload(workload)

    if not all_rows:
        print("No data."); return

    fields = [
        "time_s", "label", "pid", "budget_mw", "power_mw", "quota_pct",
        "stop_ms", "integral", "error_mw", "util", "freq_khz",
        "energy_uj", "viol",
    ]
    save_csv(OUTPUT_DIR / f"low_budget_pid{pid}.csv", fields, all_rows)

    print_header("Aggressive Budget Analysis")
    summaries = []
    for lbl, bm in [("floor", args.floor_budget), ("edge", args.edge_budget)]:
        sub = [r for r in all_rows if r["label"] == lbl]
        s = analyse(lbl, sub, bm)
        if s:
            summaries.append(s)

    if summaries:
        save_csv(
            OUTPUT_DIR / f"low_budget_summary_pid{pid}.csv",
            list(summaries[0].keys()),
            summaries,
        )

    plot(pid, all_rows, {"floor": args.floor_budget, "edge": args.edge_budget})


if __name__ == "__main__":
    main()
