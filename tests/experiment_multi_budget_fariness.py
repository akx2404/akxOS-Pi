#!/usr/bin/env python3
"""
Experiment 9 — Multi-Budget Fairness Under Contention
=======================================================
Launches N CPU-bound workloads, assigns each a different power budget,
and verifies that all budgets are tracked independently.

Key questions:
  • Does each PID settle to its own budget setpoint?
  • Does throttling one PID cause power leakage into another's reading?
  • Is the cross-PID power correlation low (budgets are isolated)?
  • Does the driver run out of budget_table slots?

Metrics per PID:
  • Settling time, overshoot, SS mean, SS error
Cross-PID metrics:
  • Pearson correlation matrix of power signals
  • Max cross-PID correlation (should be low for isolated control)

Usage:
  python3 tests/experiment_multi_fairness.py
  python3 tests/experiment_multi_fairness.py --budgets 50 80 100 150 --duration 30
"""

import argparse
import itertools
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
    proc_read_all, moving_average, settling_time, save_csv, print_header,
)

DEFAULT_BUDGETS  = [50, 80, 100, 150]
DEFAULT_DURATION = 30.0
WARMUP_S         = 4.0
SMOOTH_W         = 10
COLORS           = ["#2196F3", "#F44336", "#4CAF50", "#FF9800",
                    "#9C27B0", "#00BCD4", "#FF5722", "#607D8B"]


# ─── Collection ──────────────────────────────────────────────

def collect(pids: list, budgets: dict, duration_s: float) -> dict:
    """
    Collect samples for all PIDs simultaneously.
    Returns {pid: list_of_rows}.
    """
    all_data = {pid: [] for pid in pids}
    start    = time.monotonic()
    t0       = start

    while (time.monotonic() - start) < duration_s:
        time.sleep(POLL_S)
        t     = time.monotonic() - t0
        rows  = proc_read_all()

        status_parts = []
        for pid in pids:
            row = rows.get(pid)
            if row:
                row["time_s"] = round(t, 3)
                all_data[pid].append(row)
                status_parts.append(
                    f"P{pids.index(pid)+1}={row['power_mw']:4d}mW(q={row['quota_pct']:3d}%)"
                )
            else:
                status_parts.append(f"P{pids.index(pid)+1}=----")

        print(f"t={t:6.1f}s | {' | '.join(status_parts)}", flush=True)

    return all_data


# ─── Analysis ────────────────────────────────────────────────

def analyse_per_pid(pid_data: dict, budgets: dict,
                    tol_pct: float = 5.0, smooth_w: int = SMOOTH_W) -> list:
    results = []
    for pid, rows in sorted(pid_data.items()):
        if not rows:
            continue
        budget   = budgets[pid]
        times    = np.array([r["time_s"]   for r in rows])
        powers   = np.array([r["power_mw"] for r in rows], float)
        sm       = moving_average(powers.tolist(), smooth_w)
        t_local  = times - times[0]
        n        = len(sm)
        st       = settling_time(t_local, sm, budget, tol_pct)
        osh      = max(0.0, float(np.max(sm[:max(1, n // 3)])) - budget)
        ss_sm    = sm[max(0, n * 7 // 10):]
        results.append(dict(
            pid         = pid,
            budget_mw   = budget,
            settle_s    = st,
            overshoot   = round(osh, 2),
            ss_mean     = round(float(np.mean(ss_sm)), 2),
            ss_error    = round(float(abs(np.mean(ss_sm) - budget)), 2),
            ss_sigma    = round(float(np.std(ss_sm)), 2),
            n_samples   = n,
        ))
    return results


def cross_correlation(pid_data: dict, smooth_w: int = SMOOTH_W) -> tuple:
    """
    Compute Pearson correlation matrix of smoothed power signals.
    Returns (pids_ordered, corr_matrix).
    """
    pids = sorted(pid_data.keys())
    # Trim to common length
    min_len = min(len(pid_data[p]) for p in pids if pid_data[p])
    if min_len < 4:
        return pids, None

    mat = []
    for pid in pids:
        rows  = pid_data[pid][:min_len]
        pwr   = [r["power_mw"] for r in rows]
        sm    = moving_average(pwr, smooth_w)
        mat.append(sm)

    mat = np.array(mat)    # shape: (n_pids, n_samples)
    corr = np.corrcoef(mat)
    return pids, corr


# ─── Plotting ────────────────────────────────────────────────

def plot(pid_data: dict, budgets: dict, per_pid_results: list,
         pids_ord: list, corr: np.ndarray, duration_s: float):
    n_pids = len(pids_ord)

    fig = plt.figure(figsize=(14, 12))
    fig.suptitle(
        f"Multi-Budget Fairness  ({n_pids} workloads)\n"
        f"Budgets: {[budgets[p] for p in sorted(budgets)]} mW",
        fontweight="bold",
    )

    gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.48, wspace=0.35)

    # Power time series (all PIDs)
    ax_pw = fig.add_subplot(gs[0, :])
    for idx, pid in enumerate(sorted(pid_data.keys())):
        rows  = pid_data[pid]
        if not rows:
            continue
        times  = np.array([r["time_s"]   for r in rows])
        powers = np.array([r["power_mw"] for r in rows], float)
        budget = budgets[pid]
        color  = COLORS[idx % len(COLORS)]
        sm     = moving_average(powers.tolist(), SMOOTH_W)
        ax_pw.plot(times, powers, alpha=0.20, linewidth=0.6, color=color)
        ax_pw.plot(times, sm, linewidth=2.0, color=color,
                   label=f"PID {pid} budget={budget}mW")
        ax_pw.axhline(budget, linestyle="--", color=color, linewidth=1.0, alpha=0.5)
    ax_pw.set_ylabel("Power (mW)"); ax_pw.set_xlabel("Time (s)")
    ax_pw.set_title("Per-PID power tracking (dashed = budget setpoint)")
    ax_pw.legend(fontsize=8, loc="upper right")
    ax_pw.grid(True, alpha=0.25); ax_pw.set_ylim(bottom=0)

    # Quota per PID
    ax_qt = fig.add_subplot(gs[1, 0])
    for idx, pid in enumerate(sorted(pid_data.keys())):
        rows = pid_data[pid]
        if not rows:
            continue
        times  = np.array([r["time_s"]   for r in rows])
        quotas = np.array([r["quota_pct"] for r in rows], float)
        ax_qt.plot(times, quotas, linewidth=1.3,
                   color=COLORS[idx % len(COLORS)],
                   label=f"PID {pid}")
    ax_qt.set_ylabel("Quota (%)"); ax_qt.set_ylim(0, 110)
    ax_qt.set_xlabel("Time (s)")
    ax_qt.set_title("Per-PID quota actions")
    ax_qt.legend(fontsize=7); ax_qt.grid(True, alpha=0.25)

    # SS error bar chart
    ax_err = fig.add_subplot(gs[1, 1])
    labels = [f"PID{r['pid']}\n{r['budget_mw']}mW" for r in per_pid_results]
    errors = [r["ss_error"] for r in per_pid_results]
    sigmas = [r["ss_sigma"] for r in per_pid_results]
    x = np.arange(len(labels))
    bars = ax_err.bar(x, errors, 0.35, color=[COLORS[i % len(COLORS)] for i in range(len(labels))],
                      label="SS error")
    ax_err.plot(x, sigmas, marker="o", color="black", linewidth=1.3, label="SS σ")
    ax_err.set_xticks(x); ax_err.set_xticklabels(labels, fontsize=8)
    ax_err.set_ylabel("mW")
    ax_err.set_title("Steady-state error & σ per PID")
    ax_err.legend(fontsize=8); ax_err.grid(True, axis="y", alpha=0.3)
    for bar, v in zip(bars, errors):
        ax_err.text(bar.get_x() + bar.get_width()/2, v + 0.3,
                    f"{v:.1f}", ha="center", fontsize=7)

    # Settling time bar
    ax_st = fig.add_subplot(gs[2, 0])
    settle_vals = [r["settle_s"] or duration_s for r in per_pid_results]
    ax_st.bar(x, settle_vals,
              color=[COLORS[i % len(COLORS)] for i in range(len(labels))],
              width=0.4)
    ax_st.set_xticks(x); ax_st.set_xticklabels(labels, fontsize=8)
    ax_st.set_ylabel("Settling time (s)")
    ax_st.set_title("Settling time per PID (→ duration means never settled)")
    ax_st.grid(True, axis="y", alpha=0.3)
    for i, v in enumerate(settle_vals):
        lbl = f"{v:.1f}s" if v < duration_s else "never"
        ax_st.text(i, v + 0.2, lbl, ha="center", fontsize=7)

    # Cross-correlation heatmap
    ax_cc = fig.add_subplot(gs[2, 1])
    if corr is not None and len(pids_ord) > 1:
        im = ax_cc.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
        plt.colorbar(im, ax=ax_cc, fraction=0.046, pad=0.04)
        tick_labels = [f"PID{p}" for p in pids_ord]
        ax_cc.set_xticks(range(len(pids_ord))); ax_cc.set_xticklabels(tick_labels, fontsize=8)
        ax_cc.set_yticks(range(len(pids_ord))); ax_cc.set_yticklabels(tick_labels, fontsize=8)
        for i, j in itertools.product(range(len(pids_ord)), range(len(pids_ord))):
            ax_cc.text(j, i, f"{corr[i,j]:.2f}", ha="center", va="center", fontsize=7)
    else:
        ax_cc.text(0.5, 0.5, "Insufficient data", ha="center", va="center",
                   transform=ax_cc.transAxes)
    ax_cc.set_title("Power cross-correlation matrix\n(off-diagonal ≈ 0 = isolated control)")

    plt.savefig(OUTPUT_DIR / f"multi_fairness_{n_pids}pids.png",
                dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Plot saved: {OUTPUT_DIR}/multi_fairness_{n_pids}pids.png")


# ─── Main ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Multi-budget fairness experiment")
    ap.add_argument("--budgets",  type=int, nargs="+", default=DEFAULT_BUDGETS,
                    help="Per-PID budgets in mW. One per workload.")
    ap.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    ap.add_argument("--tol",      type=float, default=5.0)
    args = ap.parse_args()

    check_driver_or_exit()
    ensure_output()

    n = len(args.budgets)
    print(f"Launching {n} workloads with budgets {args.budgets} mW …")

    workloads = []
    pids      = []

    try:
        for i, budget in enumerate(args.budgets):
            wl = launch_workload()
            workloads.append(wl)
            pids.append(wl.pid)
            print(f"  Workload {i+1}: PID {wl.pid} → budget {budget} mW")

        print(f"Warming up {WARMUP_S}s …")
        time.sleep(WARMUP_S)

        budgets_map = dict(zip(pids, args.budgets))
        for pid, bm in budgets_map.items():
            clear_budget(pid)
            reset_ctrl(pid)
            set_budget(pid, bm)

        print(f"\nCollecting for {args.duration}s …\n")
        pid_data = collect(pids, budgets_map, args.duration)

    finally:
        for pid in pids:
            clear_budget(pid)
        for wl in workloads:
            terminate_workload(wl)

    # Save raw data
    flat = []
    for pid, rows in pid_data.items():
        for r in rows:
            r["assigned_budget"] = budgets_map.get(pid, 0)
            flat.append(r)
    if flat:
        fields = ["time_s", "pid", "assigned_budget", "budget_mw",
                  "power_mw", "quota_pct", "stop_ms", "integral",
                  "error_mw", "util", "freq_khz", "energy_uj", "viol"]
        save_csv(OUTPUT_DIR / f"multi_fairness_{n}pids.csv", fields, flat)

    per_pid_results = analyse_per_pid(pid_data, budgets_map, args.tol)
    pids_ord, corr  = cross_correlation(pid_data)

    print_header("Multi-Budget Fairness Analysis")
    print(f"  {'PID':>6} {'Budget':>8} {'Settle':>10} {'Overshoot':>11} "
          f"{'SS Mean':>9} {'SS Err':>8} {'SS σ':>8}")
    print("  " + "─" * 68)
    for r in per_pid_results:
        st_str = f"{r['settle_s']:.1f}s" if r["settle_s"] else "never"
        print(
            f"  {r['pid']:>6} {r['budget_mw']:>8} {st_str:>10} "
            f"{r['overshoot']:>9.1f}mW {r['ss_mean']:>8.1f} "
            f"{r['ss_error']:>8.2f} {r['ss_sigma']:>8.2f}"
        )

    if corr is not None and len(pids_ord) > 1:
        print(f"\n  Cross-PID power correlations:")
        off_diag = [corr[i, j]
                    for i in range(len(pids_ord))
                    for j in range(len(pids_ord)) if i != j]
        max_corr = max(abs(v) for v in off_diag) if off_diag else 0.0
        flag = "  ← HIGH — signals may not be independent" if max_corr > 0.7 else "  ✓ low"
        print(f"    Max off-diagonal |r| = {max_corr:.3f}{flag}")

    if per_pid_results:
        save_csv(
            OUTPUT_DIR / f"multi_fairness_summary_{n}pids.csv",
            list(per_pid_results[0].keys()), per_pid_results,
        )

    plot(pid_data, budgets_map, per_pid_results, pids_ord, corr, args.duration)


if __name__ == "__main__":
    main()
