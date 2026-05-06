#!/usr/bin/env python3
"""
Experiment 7 — Frequency Sensitivity / Model Accuracy
=======================================================
Validates how accurately the kernel power model tracks reality across
the Pi's DVFS frequency ladder.

Kernel model:  P_mw = (162 × freq_khz × util_permille) / 1e9

At each available frequency the experiment:
  1. Locks the CPU to that frequency via scaling_min/max_freq
  2. Runs a full-CPU workload with a permissive budget (no throttling)
  3. Reads freq_khz, util_permille, power_mw from /proc/akxos_sched
  4. Computes the analytical model prediction and the residual
  5. Also checks whether the kernel reads the set frequency correctly

Metrics:
  • MAPE  — Mean Absolute Percentage Error  (model vs kernel reading)
  • RMSE  — Root Mean Square Error
  • Frequency read error — delta between set freq and kernel-reported freq
  • Util accuracy at each frequency (should be ≈1000 under full load)

Usage:
  python3 tests/experiment_model_accuracy.py
  python3 tests/experiment_model_accuracy.py --sample-s 10 --settle-s 3
"""

import argparse
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
    proc_read, get_available_freqs_khz, set_cpu_freq_khz, reset_cpu_freq,
    model_predict_mw, save_csv, print_header,
)

# Permissive budget so the workload appears in /proc without any throttling
MEASURE_BUDGET_MW = 999
DEFAULT_SAMPLE_S  = 10.0   # seconds to collect at each frequency
DEFAULT_SETTLE_S  = 2.0    # seconds to let governor settle after freq change
WARMUP_S          = 3.0
SMOOTH_W          = 4


# ─── Per-frequency measurement ───────────────────────────────

def measure_at_freq(pid: int, freq_khz: int, sample_s: float) -> list:
    """
    Lock CPU to freq_khz, collect power samples, return list of dicts.
    """
    print(f"\n  freq={freq_khz//1000:4d} MHz | collecting {sample_s}s …", end="", flush=True)
    set_cpu_freq_khz(freq_khz)

    rows  = []
    start = time.monotonic()

    while (time.monotonic() - start) < sample_s:
        time.sleep(POLL_S)
        row = proc_read(pid)
        if row:
            row["set_freq_khz"] = freq_khz
            rows.append(row)

    if rows:
        avg_p = np.mean([r["power_mw"]  for r in rows])
        avg_u = np.mean([r["util"]      for r in rows])
        avg_f = np.mean([r["freq_khz"]  for r in rows])
        print(f"  P={avg_p:.1f}mW  util={avg_u:.0f}  "
              f"kernel_freq={avg_f/1000:.0f}MHz", flush=True)
    else:
        print("  NO DATA", flush=True)

    return rows


# ─── Analysis ────────────────────────────────────────────────

def analyse(all_freq_rows: dict) -> list:
    """
    For each frequency bucket compute accuracy metrics.
    Returns list of per-frequency summary dicts.
    """
    results = []

    for freq_khz, rows in sorted(all_freq_rows.items()):
        if not rows:
            continue

        powers   = np.array([r["power_mw"]  for r in rows], float)
        utils    = np.array([r["util"]       for r in rows], float)
        kfreqs   = np.array([r["freq_khz"]  for r in rows], float)

        avg_power   = float(np.mean(powers))
        avg_util    = float(np.mean(utils))
        avg_kfreq   = float(np.mean(kfreqs))

        # Model prediction using kernel-reported freq and util
        pred_per_sample = np.array([
            model_predict_mw(int(r["freq_khz"]), int(r["util"]))
            for r in rows
        ])
        avg_pred = float(np.mean(pred_per_sample))

        # Prediction using SET freq + expected util=1000
        pred_ideal = model_predict_mw(freq_khz, 1000)

        # Residuals
        residuals = powers - pred_per_sample
        mape      = float(np.mean(np.abs((powers - pred_per_sample) /
                                         np.maximum(powers, 1e-3))) * 100)
        rmse      = float(np.sqrt(np.mean(residuals ** 2)))

        freq_err_pct = (avg_kfreq - freq_khz) / freq_khz * 100

        results.append(dict(
            set_freq_mhz      = freq_khz // 1000,
            set_freq_khz      = freq_khz,
            kernel_freq_mhz   = round(avg_kfreq / 1000, 1),
            freq_err_pct      = round(freq_err_pct, 2),
            avg_util          = round(avg_util, 0),
            avg_power_mw      = round(avg_power, 2),
            pred_mw           = round(avg_pred, 2),
            pred_ideal_mw     = round(pred_ideal, 2),
            residual_mw       = round(avg_power - avg_pred, 2),
            mape_pct          = round(mape, 2),
            rmse_mw           = round(rmse, 2),
            n_samples         = len(rows),
        ))

    return results


# ─── Plotting ────────────────────────────────────────────────

def plot(pid: int, results: list):
    freqs_mhz = [r["set_freq_mhz"]  for r in results]
    avg_pwr   = [r["avg_power_mw"]  for r in results]
    pred_pwr  = [r["pred_mw"]       for r in results]
    pred_ideal= [r["pred_ideal_mw"] for r in results]
    mape      = [r["mape_pct"]      for r in results]
    freq_err  = [r["freq_err_pct"]  for r in results]
    avg_util  = [r["avg_util"]      for r in results]
    residuals = [r["residual_mw"]   for r in results]

    fig = plt.figure(figsize=(14, 10))
    fig.suptitle(
        f"Model Accuracy vs DVFS Frequency  (PID {pid})\n"
        f"Model: P = 162 × freq_khz × util / 10⁹",
        fontweight="bold",
    )
    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.35)

    # Power: actual vs predicted
    ax = fig.add_subplot(gs[0, :])
    ax.plot(freqs_mhz, avg_pwr,   marker="o", linewidth=2.0,
            color="steelblue", label="Kernel power_mw (avg)")
    ax.plot(freqs_mhz, pred_pwr,  marker="s", linewidth=1.8, linestyle="--",
            color="crimson", label="Model prediction (kernel freq+util)")
    ax.plot(freqs_mhz, pred_ideal, marker="^", linewidth=1.2, linestyle=":",
            color="orange", label="Ideal prediction (set freq, util=1000)")
    ax.fill_between(freqs_mhz,
                    [p - r for p, r in zip(avg_pwr, residuals)],
                    [p + r for p, r in zip(avg_pwr, residuals)],
                    alpha=0.10, color="steelblue", label="Residual band")
    ax.set_xlabel("CPU Frequency (MHz)"); ax.set_ylabel("Power (mW)")
    ax.set_title("Kernel estimate vs model prediction across DVFS steps")
    ax.legend(fontsize=8); ax.grid(True, alpha=0.25)

    # MAPE per frequency
    ax2 = fig.add_subplot(gs[1, 0])
    colors = ["#EF5350" if m > 10 else "#42A5F5" for m in mape]
    bars   = ax2.bar(freqs_mhz, mape, color=colors, width=50)
    ax2.axhline(5, linestyle="--", color="green", label="5% threshold")
    ax2.axhline(10, linestyle="--", color="red",   label="10% threshold")
    for bar, val in zip(bars, mape):
        ax2.text(bar.get_x() + bar.get_width()/2, val + 0.2,
                 f"{val:.1f}%", ha="center", fontsize=7)
    ax2.set_xlabel("Frequency (MHz)"); ax2.set_ylabel("MAPE (%)")
    ax2.set_title("Model error (MAPE) per frequency")
    ax2.legend(fontsize=8); ax2.grid(True, axis="y", alpha=0.3)

    # Frequency read error
    ax3 = fig.add_subplot(gs[1, 1])
    ax3.bar(freqs_mhz, freq_err, color="#AB47BC", width=50, label="Freq read error")
    ax3.plot(freqs_mhz, avg_util, marker="o", color="darkorange",
             linewidth=1.5, label="Avg util‰ (right)")
    ax3.set_xlabel("Frequency (MHz)")
    ax3.set_ylabel("Freq error (%)")
    ax3.set_title("Kernel frequency read accuracy & utilisation")
    ax3_r = ax3.twinx()
    ax3_r.plot(freqs_mhz, avg_util, marker="o", color="darkorange",
               linewidth=1.5, linestyle="-")
    ax3_r.axhline(1000, linestyle=":", color="darkorange", alpha=0.5, label="util=1000")
    ax3_r.set_ylabel("util‰")
    ax3.legend(fontsize=7, loc="upper left")
    ax3.grid(True, alpha=0.25)

    plt.savefig(OUTPUT_DIR / f"model_accuracy_pid{pid}.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Plot saved: {OUTPUT_DIR}/model_accuracy_pid{pid}.png")


# ─── Main ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Model accuracy / DVFS sweep experiment")
    ap.add_argument("--sample-s", type=float, default=DEFAULT_SAMPLE_S,
                    help=f"Seconds to sample at each frequency (default: {DEFAULT_SAMPLE_S})")
    ap.add_argument("--settle-s", type=float, default=DEFAULT_SETTLE_S,
                    help=f"Seconds to wait after freq change (default: {DEFAULT_SETTLE_S})")
    ap.add_argument("--freqs", type=int, nargs="*", default=None,
                    help="Explicit list of frequencies (kHz). Default: all available.")
    args = ap.parse_args()

    check_driver_or_exit()
    ensure_output()

    freqs = args.freqs or get_available_freqs_khz()
    if not freqs:
        print("[error] No frequencies available. Is cpufreq enabled?", file=sys.stderr)
        sys.exit(1)

    print(f"Frequencies to test: {[f//1000 for f in freqs]} MHz")
    print(f"Sample time / freq  : {args.sample_s}s")
    print(f"Settle time         : {args.settle_s}s")

    workload = launch_workload()
    pid = workload.pid
    print(f"Workload PID : {pid}")
    print(f"Warming up {WARMUP_S}s …")
    time.sleep(WARMUP_S)

    # Apply permissive budget so we appear in /proc
    clear_budget(pid)
    reset_ctrl(pid)
    set_budget(pid, MEASURE_BUDGET_MW)

    all_freq_rows = {}

    try:
        for freq_khz in freqs:
            time.sleep(args.settle_s)
            rows = measure_at_freq(pid, freq_khz, args.sample_s)
            all_freq_rows[freq_khz] = rows
    finally:
        clear_budget(pid)
        reset_cpu_freq()
        terminate_workload(workload)

    # Flatten all rows for CSV
    flat = []
    for rows in all_freq_rows.values():
        flat.extend(rows)

    if not flat:
        print("No data."); return

    raw_fields = ["set_freq_khz", "pid", "budget_mw", "freq_khz", "util",
                  "power_mw", "quota_pct", "stop_ms", "integral",
                  "error_mw", "energy_uj", "viol"]
    save_csv(OUTPUT_DIR / f"model_accuracy_raw_pid{pid}.csv", raw_fields, flat)

    results = analyse(all_freq_rows)

    print_header("Model Accuracy Analysis")
    print(f"{'Freq(MHz)':>10} {'KernFreq':>9} {'FreqErr%':>9} "
          f"{'Util‰':>7} {'AvgP(mW)':>10} {'Pred(mW)':>9} "
          f"{'Resid':>7} {'MAPE%':>7} {'RMSE':>7}")
    print("─" * 82)
    for r in results:
        print(
            f"{r['set_freq_mhz']:>10} "
            f"{r['kernel_freq_mhz']:>9.0f} "
            f"{r['freq_err_pct']:>+9.2f} "
            f"{r['avg_util']:>7.0f} "
            f"{r['avg_power_mw']:>10.2f} "
            f"{r['pred_mw']:>9.2f} "
            f"{r['residual_mw']:>+7.2f} "
            f"{r['mape_pct']:>7.2f} "
            f"{r['rmse_mw']:>7.2f}"
        )

    if results:
        mapes = [r["mape_pct"] for r in results]
        print(f"\n  Overall MAPE : {np.mean(mapes):.2f}%  (max={max(mapes):.2f}%)")
        rmses = [r["rmse_mw"] for r in results]
        print(f"  Overall RMSE : {np.mean(rmses):.2f} mW")

        save_csv(OUTPUT_DIR / f"model_accuracy_summary_pid{pid}.csv",
                 list(results[0].keys()), results)

    plot(pid, results)


if __name__ == "__main__":
    main()
