#!/usr/bin/env python3
"""
Experiment 5 — Bursty Workload
================================
Compares PI controller behaviour under two workload profiles:
  steady  — `yes` (constant 100% CPU demand)
  bursty  — alternating compute burst / sleep (configurable duty cycle)

The bursty profile exercises the conditional integration band: small
errors from natural burstiness should NOT accumulate integral and cause
overcorrection.

Metrics:
  • Power variance (σ) for each profile
  • Settling time comparison
  • Integral utilisation: how often does the integral term activate?
  • Stop-duration jitter under each profile

Usage:
  python3 tests/experiment_bursty.py
  python3 tests/experiment_bursty.py --budget 80 --burst-ms 150 --sleep-ms 80 --duration 30
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from experiment_utils import (
    check_driver_or_exit, ensure_output, OUTPUT_DIR, POLL_S,
    set_budget, clear_budget, reset_ctrl,
    launch_workload, terminate_workload,
    proc_read, moving_average, settling_time, save_csv, print_header,
)

DEFAULT_BUDGET    = 80
DEFAULT_BURST_MS  = 100
DEFAULT_SLEEP_MS  = 100
DEFAULT_DURATION  = 30.0
WARMUP_S          = 3.0
COOLDOWN_S        = 5.0
SMOOTH_W          = 10


# ─── Collection ──────────────────────────────────────────────

def collect(label: str, pid: int, budget_mw: int,
            duration_s: float, t0: float) -> list:
    print(f"\n─── Profile: {label} | budget={budget_mw}mW | duration={duration_s}s ───")
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
            row["time_s"] = round(t, 3)
            row["label"]  = label
            rows.append(row)
            print(
                f"t={t:6.1f}s | P={row['power_mw']:4d}mW | "
                f"quota={row['quota_pct']:3d}% | "
                f"int={row['integral']:+4d} | "
                f"err={row['error_mw']:+4d}",
                flush=True,
            )
    return rows


# ─── Analysis ────────────────────────────────────────────────

def analyse(label: str, rows: list, budget_mw: int, tol_pct: float = 5.0) -> dict:
    if not rows:
        return {}

    times   = np.array([r["time_s"]    for r in rows])
    powers  = np.array([r["power_mw"]  for r in rows], float)
    intgrl  = np.array([r["integral"]  for r in rows], float)
    stop_ms = np.array([r["stop_ms"]   for r in rows], float)
    sm      = moving_average(powers.tolist(), SMOOTH_W)

    # Normalise time within phase
    t_local = times - times[0]
    st = settling_time(t_local, sm, budget_mw, tol_pct)

    n        = len(sm)
    ss_start = max(0, n * 7 // 10)
    ss       = powers[ss_start:]
    sm_ss    = sm[ss_start:]

    # How often is integral non-zero? (integration band active)
    integ_active = np.sum(intgrl != 0) / len(intgrl) * 100

    # Stop jitter: std of stop_ms while throttled (stop_ms > 0)
    throttled_stops = stop_ms[stop_ms > 0]
    stop_jitter = float(np.std(throttled_stops)) if len(throttled_stops) > 1 else 0.0

    return dict(
        label         = label,
        budget_mw     = budget_mw,
        settle_s      = st,
        overshoot_mw  = max(0.0, float(np.max(sm[:max(1,n//3)])) - budget_mw),
        ss_mean       = float(np.mean(sm_ss)),
        ss_sigma      = float(np.std(ss)),
        ss_error      = float(abs(np.mean(sm_ss) - budget_mw)),
        power_range   = float(np.max(powers) - np.min(powers)),
        integ_active_pct = round(integ_active, 2),
        stop_jitter_ms   = round(stop_jitter, 2),
    )


# ─── Plotting ────────────────────────────────────────────────

def plot(budget_mw: int, all_rows: list, profiles: list, tol_pct: float):
    label_colors = {"steady": "#2196F3", "bursty": "#F44336"}
    tol = budget_mw * tol_pct / 100.0

    fig = plt.figure(figsize=(14, 11))
    fig.suptitle(
        f"Bursty vs Steady Workload  (budget={budget_mw}mW, ±{tol:.0f}mW band)",
        fontweight="bold",
    )
    gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.50, wspace=0.35)

    ax_pw  = fig.add_subplot(gs[0, :])   # power comparison (full width)
    ax_int = fig.add_subplot(gs[1, 0])   # integral
    ax_stp = fig.add_subplot(gs[1, 1])   # stop_ms
    ax_var = fig.add_subplot(gs[2, 0])   # variance comparison bar
    ax_set = fig.add_subplot(gs[2, 1])   # settling time bar

    for label in profiles:
        rows   = [r for r in all_rows if r["label"] == label]
        if not rows:
            continue
        times  = np.array([r["time_s"]    for r in rows])
        powers = np.array([r["power_mw"]  for r in rows], float)
        intgrl = np.array([r["integral"]  for r in rows], float)
        stops  = np.array([r["stop_ms"]   for r in rows], float)
        sm     = moving_average(powers.tolist(), SMOOTH_W)
        color  = label_colors.get(label, "gray")

        ax_pw.plot(times - times[0], sm, linewidth=2.0, color=color, label=f"{label} (smoothed)")
        ax_pw.fill_between(times - times[0], powers, alpha=0.12, color=color)
        ax_int.plot(times - times[0], intgrl, linewidth=1.3, color=color, label=label)
        ax_stp.plot(times - times[0], stops,  linewidth=1.0, color=color, label=label, alpha=0.8)

    ax_pw.axhline(budget_mw, linestyle="--", color="black", linewidth=1.3, label=f"Budget {budget_mw}mW")
    ax_pw.fill_between(
        ax_pw.get_xlim() if ax_pw.get_xlim() != (0.0, 1.0) else [0, 100],
        [budget_mw - tol] * 2, [budget_mw + tol] * 2,
        alpha=0.08, color="gray",
    )
    ax_pw.set_ylabel("Power (mW)")
    ax_pw.set_title("Power (time aligned to phase start)")
    ax_pw.legend(fontsize=8); ax_pw.grid(True, alpha=0.25); ax_pw.set_ylim(bottom=0)

    ax_int.axhline(0, linewidth=0.8, linestyle="--", color="black")
    ax_int.set_ylabel("PI Integral"); ax_int.set_xlabel("Phase time (s)")
    ax_int.set_title("Integral response — bursty profile should avoid windup")
    ax_int.legend(fontsize=8); ax_int.grid(True, alpha=0.25)

    ax_stp.set_ylabel("Stop duration (ms)"); ax_stp.set_xlabel("Phase time (s)")
    ax_stp.set_title("Stop_ms jitter under each profile")
    ax_stp.legend(fontsize=8); ax_stp.grid(True, alpha=0.25)

    # Aggregate bars
    metrics = {p: analyse(p, [r for r in all_rows if r["label"] == p], budget_mw)
               for p in profiles}
    labels  = [p for p in profiles if metrics.get(p)]

    ss_sigmas = [metrics[p]["ss_sigma"] for p in labels]
    colors    = [label_colors.get(p, "gray") for p in labels]
    ax_var.bar(labels, ss_sigmas, color=colors, width=0.4)
    ax_var.set_ylabel("SS power σ (mW)")
    ax_var.set_title("Steady-state power variability")
    ax_var.grid(True, axis="y", alpha=0.3)
    for i, v in enumerate(ss_sigmas):
        ax_var.text(i, v + 0.3, f"{v:.1f}", ha="center", fontsize=8)

    settle_vals = [metrics[p]["settle_s"] or 0 for p in labels]
    ax_set.bar(labels, settle_vals, color=colors, width=0.4)
    ax_set.set_ylabel("Settling time (s)")
    ax_set.set_title("Settling time comparison")
    ax_set.grid(True, axis="y", alpha=0.3)
    for i, v in enumerate(settle_vals):
        lbl = f"{v:.1f}s" if v > 0 else "never"
        ax_set.text(i, max(v, 0.3), lbl, ha="center", fontsize=8)

    plt.savefig(OUTPUT_DIR / f"bursty_budget{budget_mw}.png",
                dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Plot saved: {OUTPUT_DIR}/bursty_budget{budget_mw}.png")


# ─── Main ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Bursty vs steady workload experiment")
    ap.add_argument("--budget",   type=int,   default=DEFAULT_BUDGET)
    ap.add_argument("--burst-ms", type=float, default=DEFAULT_BURST_MS,
                    help="Bursty workload compute burst duration (default: 100ms)")
    ap.add_argument("--sleep-ms", type=float, default=DEFAULT_SLEEP_MS,
                    help="Bursty workload sleep duration (default: 100ms)")
    ap.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    ap.add_argument("--tol",      type=float, default=5.0)
    args = ap.parse_args()

    check_driver_or_exit()
    ensure_output()

    # Launch both workloads; we test them sequentially with the same budget
    bursty_script = Path(__file__).parent / "bursty_workload.py"
    if not bursty_script.exists():
        print(f"[error] {bursty_script} not found.", file=sys.stderr)
        sys.exit(1)

    profiles  = ["steady", "bursty"]
    workloads = {"steady": None, "bursty": None}
    all_rows  = []
    t0        = time.monotonic()

    try:
        for label in profiles:
            print(f"\nLaunching {label} workload …")
            if label == "steady":
                wl = launch_workload(["yes"])
            else:
                wl = launch_workload([
                    "python3", str(bursty_script),
                    str(args.burst_ms), str(args.sleep_ms),
                ])
            workloads[label] = wl
            pid = wl.pid
            print(f"  PID = {pid}  |  warming up {WARMUP_S}s …")
            time.sleep(WARMUP_S)

            rows = collect(label, pid, args.budget, args.duration, t0)
            all_rows.extend(rows)

            clear_budget(pid)
            terminate_workload(wl)
            workloads[label] = None

            if label != profiles[-1]:
                print(f"Cooldown {COOLDOWN_S}s …")
                time.sleep(COOLDOWN_S)
    finally:
        for wl in workloads.values():
            if wl:
                terminate_workload(wl)

    if not all_rows:
        print("No data."); return

    fields = [
        "time_s", "label", "pid", "budget_mw", "power_mw", "quota_pct",
        "stop_ms", "integral", "error_mw", "util", "freq_khz",
        "energy_uj", "viol",
    ]
    save_csv(OUTPUT_DIR / f"bursty_budget{args.budget}.csv", fields, all_rows)

    print_header("Bursty vs Steady Analysis")
    summaries = []
    for label in profiles:
        sub = [r for r in all_rows if r["label"] == label]
        m   = analyse(label, sub, args.budget, args.tol)
        if m:
            summaries.append(m)
            st_str = f"{m['settle_s']:.1f}s" if m["settle_s"] else "never"
            print(
                f"  {label:<8} settle={st_str:>7} | "
                f"ss_σ={m['ss_sigma']:.1f}mW | "
                f"int_active={m['integ_active_pct']:.0f}% | "
                f"stop_jitter={m['stop_jitter_ms']:.1f}ms"
            )

    if summaries:
        save_csv(
            OUTPUT_DIR / f"bursty_summary_budget{args.budget}.csv",
            list(summaries[0].keys()), summaries,
        )

    plot(args.budget, all_rows, profiles, args.tol)


if __name__ == "__main__":
    main()
