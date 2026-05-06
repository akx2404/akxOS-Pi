#!/usr/bin/env python3
"""
Experiment 6 — Long-Duration Stability
========================================
Runs a budgeted workload for an extended period and checks for:
  • Integral windup growth over time
  • Quota drift (systematic shift away from correct value)
  • Power variance increase (indicating oscillation onset)
  • Zero-power watchdog accumulation in dmesg
  • SIGSTOP/SIGCONT reliability (process never permanently stopped)

The script saves samples progressively so data is preserved even if
interrupted (Ctrl-C).

Output structure:
  • CSV: every sample with timestamp, integral, quota, power, stop_ms
  • Epoch summary CSV: per-minute aggregates
  • Plot: 4-panel time series + epoch summary

Usage:
  python3 tests/experiment_long_duration.py
  python3 tests/experiment_long_duration.py --budget 80 --duration 20
  python3 tests/experiment_long_duration.py --budget 80 --duration 60   # 1 hour
"""

import argparse
import csv
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
    proc_read, moving_average, dmesg_grep, print_header,
)

DEFAULT_BUDGET   = 80
DEFAULT_DURATION = 20.0     # minutes
SUMMARY_EVERY_S  = 60.0     # print epoch summary every N seconds
SMOOTH_W         = 20
EPOCH_W          = int(SUMMARY_EVERY_S / POLL_S)   # samples per epoch
WARMUP_S         = 3.0
FLUSH_EVERY      = 50       # flush CSV every N samples


# ─── Progressive CSV writer ───────────────────────────────────

class ProgressiveCSV:
    FIELDS = [
        "time_s", "wall_clock", "pid", "budget_mw", "power_mw", "quota_pct",
        "stop_ms", "integral", "error_mw", "util", "freq_khz",
        "energy_uj", "viol", "throttled",
    ]

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(path, "w", newline="")
        self._w = csv.DictWriter(self._f, fieldnames=self.FIELDS, extrasaction="ignore")
        self._w.writeheader()
        self._count = 0

    def write(self, row: dict):
        self._w.writerow(row)
        self._count += 1
        if self._count % FLUSH_EVERY == 0:
            self._f.flush()

    def close(self):
        self._f.flush()
        self._f.close()
        print(f"CSV saved: {self.path}  ({self._count} rows)")


# ─── Epoch aggregator ────────────────────────────────────────

class EpochStats:
    def __init__(self, budget_mw: int):
        self.budget   = budget_mw
        self.epochs   = []
        self._buf     = []

    def push(self, row: dict):
        self._buf.append(row)

    def flush_epoch(self, epoch_start_s: float):
        if not self._buf:
            return
        powers   = np.array([r["power_mw"]  for r in self._buf], float)
        quotas   = np.array([r["quota_pct"] for r in self._buf], float)
        intgrls  = np.array([r["integral"]  for r in self._buf], float)
        stops    = np.array([r["stop_ms"]   for r in self._buf], float)

        self.epochs.append(dict(
            epoch_start_s  = round(epoch_start_s, 1),
            n_samples      = len(self._buf),
            power_mean     = round(float(np.mean(powers)), 2),
            power_sigma    = round(float(np.std(powers)), 2),
            power_max      = round(float(np.max(powers)), 2),
            ss_error       = round(float(abs(np.mean(powers) - self.budget)), 2),
            quota_mean     = round(float(np.mean(quotas)), 2),
            quota_sigma    = round(float(np.std(quotas)), 2),
            integral_max   = round(float(np.max(np.abs(intgrls))), 2),
            integral_mean  = round(float(np.mean(intgrls)), 2),
            stop_sigma     = round(float(np.std(stops[stops > 0])) if (stops > 0).any() else 0.0, 2),
        ))
        self._buf = []

    def summary_csv_path(self, pid: int) -> Path:
        return OUTPUT_DIR / f"long_duration_epochs_pid{pid}.csv"


# ─── Main collection loop ─────────────────────────────────────

def run(pid: int, budget_mw: int, duration_min: float) -> tuple:
    duration_s   = duration_min * 60.0
    csv_path     = OUTPUT_DIR / f"long_duration_pid{pid}.csv"
    writer       = ProgressiveCSV(csv_path)
    epoch_stats  = EpochStats(budget_mw)

    set_budget(pid, budget_mw)

    t0            = time.monotonic()
    epoch_start   = t0
    epoch_num     = 0
    zero_streak   = 0
    all_rows      = []

    print(f"\nRunning for {duration_min:.1f} min ({duration_s:.0f}s) …")
    print(f"Summary printed every {SUMMARY_EVERY_S:.0f}s. Press Ctrl-C to stop early.\n")

    try:
        while True:
            elapsed = time.monotonic() - t0
            if elapsed >= duration_s:
                break

            time.sleep(POLL_S)
            t   = time.monotonic() - t0
            row = proc_read(pid)

            if row is None:
                zero_streak += 1
                continue
            zero_streak = 0

            row["time_s"]    = round(t, 3)
            row["wall_clock"] = time.strftime("%H:%M:%S")
            writer.write(row)
            epoch_stats.push(row)
            all_rows.append(row)

            # Epoch boundary
            if (time.monotonic() - epoch_start) >= SUMMARY_EVERY_S:
                epoch_stats.flush_epoch(t - SUMMARY_EVERY_S)
                epoch_num += 1
                ep = epoch_stats.epochs[-1]
                watchdog = len(dmesg_grep("zero-power watchdog"))
                print(
                    f"[Epoch {epoch_num:3d} | t={t:6.0f}s] "
                    f"P={ep['power_mean']:5.1f}±{ep['power_sigma']:.1f}mW | "
                    f"ss_err={ep['ss_error']:.2f} | "
                    f"quota={ep['quota_mean']:.1f}±{ep['quota_sigma']:.1f}% | "
                    f"intg_max={ep['integral_max']:.0f} | "
                    f"watchdog={watchdog}",
                    flush=True,
                )
                epoch_start = time.monotonic()

    except KeyboardInterrupt:
        print("\n[interrupted — saving data]")

    writer.close()

    # Flush any partial epoch
    epoch_stats.flush_epoch(time.monotonic() - t0)

    return all_rows, epoch_stats


# ─── Analysis ────────────────────────────────────────────────

def analyse(all_rows: list, epoch_stats: EpochStats, budget_mw: int):
    if not all_rows:
        return

    powers  = np.array([r["power_mw"]  for r in all_rows], float)
    intgrls = np.array([r["integral"]  for r in all_rows], float)
    quotas  = np.array([r["quota_pct"] for r in all_rows], float)

    n    = len(powers)
    h    = n // 2
    early, late = powers[:h], powers[h:]
    eq, lq      = quotas[:h], quotas[h:]
    ei, li      = intgrls[:h], intgrls[h:]

    print_header("Long-Duration Stability Analysis")
    print(f"  Total samples : {n}  ({n*POLL_S:.0f}s)")
    print(f"\n  Power:")
    print(f"    Early half  mean={float(np.mean(early)):.2f}  σ={float(np.std(early)):.2f} mW")
    print(f"    Late half   mean={float(np.mean(late)):.2f}  σ={float(np.std(late)):.2f} mW")
    sigma_growth = float(np.std(late)) - float(np.std(early))
    flag = "  ← INSTABILITY" if sigma_growth > 5 else ""
    print(f"    σ growth    : {sigma_growth:+.2f} mW{flag}")

    print(f"\n  Quota:")
    print(f"    Early half  mean={float(np.mean(eq)):.2f}  σ={float(np.std(eq)):.2f}%")
    print(f"    Late half   mean={float(np.mean(lq)):.2f}  σ={float(np.std(lq)):.2f}%")
    quota_drift = float(np.mean(lq)) - float(np.mean(eq))
    flag = "  ← DRIFT" if abs(quota_drift) > 5 else ""
    print(f"    Drift       : {quota_drift:+.2f}%{flag}")

    print(f"\n  Integral:")
    print(f"    Early max_abs = {float(np.max(np.abs(ei))):.0f}")
    print(f"    Late  max_abs = {float(np.max(np.abs(li))):.0f}")
    intg_growth = float(np.max(np.abs(li))) - float(np.max(np.abs(ei)))
    flag = "  ← WINDUP" if intg_growth > 20 else ""
    print(f"    Growth      : {intg_growth:+.0f}{flag}")

    watchdog = dmesg_grep("zero-power watchdog")
    print(f"\n  Zero-power watchdog events : {len(watchdog)}")


# ─── Plotting ────────────────────────────────────────────────

def plot(pid: int, budget_mw: int, all_rows: list, epoch_stats: EpochStats):
    if not all_rows:
        return

    times   = np.array([r["time_s"]    for r in all_rows])
    powers  = np.array([r["power_mw"]  for r in all_rows], float)
    quotas  = np.array([r["quota_pct"] for r in all_rows], float)
    intgrls = np.array([r["integral"]  for r in all_rows], float)
    stops   = np.array([r["stop_ms"]   for r in all_rows], float)
    sm      = moving_average(powers.tolist(), SMOOTH_W)

    fig = plt.figure(figsize=(14, 12))
    fig.suptitle(
        f"Long-Duration Stability  (PID {pid}, budget={budget_mw}mW, "
        f"{len(all_rows)*POLL_S/60:.1f}min)",
        fontweight="bold",
    )
    gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.35)

    # Power time series
    ax = fig.add_subplot(gs[0, :])
    ax.fill_between(times, powers, alpha=0.15, color="steelblue")
    ax.plot(times, sm, linewidth=1.5, color="steelblue", label=f"Smoothed (w={SMOOTH_W})")
    ax.axhline(budget_mw, linestyle="--", color="black", linewidth=1.2, label="Budget")
    ax.set_ylabel("Power (mW)"); ax.grid(True, alpha=0.25)
    ax.set_title("Power over full experiment duration")
    ax.legend(fontsize=8); ax.set_ylim(bottom=0)

    # Quota time series
    ax2 = fig.add_subplot(gs[1, 0])
    ax2.plot(times, quotas, linewidth=0.8, color="#9C27B0", alpha=0.7)
    ax2.plot(times, moving_average(quotas.tolist(), SMOOTH_W),
             linewidth=1.5, color="#9C27B0", label=f"Quota (smoothed)")
    ax2.set_ylabel("Quota (%)"); ax2.set_ylim(0, 110)
    ax2.set_xlabel("Time (s)"); ax2.grid(True, alpha=0.25)
    ax2.set_title("Quota — check for slow drift"); ax2.legend(fontsize=8)

    # Integral time series
    ax3 = fig.add_subplot(gs[1, 1])
    ax3.plot(times, intgrls, linewidth=0.8, color="#F44336", alpha=0.6)
    ax3.plot(times, moving_average(intgrls.tolist(), SMOOTH_W),
             linewidth=1.5, color="#F44336")
    ax3.axhline(80, linestyle=":", color="orange", label="±limit")
    ax3.axhline(-80, linestyle=":", color="orange")
    ax3.axhline(0, linestyle="--", color="black", linewidth=0.8)
    ax3.set_ylabel("PI Integral"); ax3.set_xlabel("Time (s)")
    ax3.grid(True, alpha=0.25); ax3.legend(fontsize=8)
    ax3.set_title("Integral — windup would show monotonic growth")

    # Epoch: power σ over time
    if epoch_stats.epochs:
        ep = epoch_stats.epochs
        ep_t  = [e["epoch_start_s"] for e in ep]
        ep_sig = [e["power_sigma"]  for e in ep]
        ep_err = [e["ss_error"]     for e in ep]
        ax4 = fig.add_subplot(gs[2, 0])
        ax4.plot(ep_t, ep_sig, marker="o", linewidth=1.5, color="steelblue", label="Power σ")
        ax4.plot(ep_t, ep_err, marker="s", linestyle="--", color="crimson", label="SS error")
        ax4.set_ylabel("mW"); ax4.set_xlabel("Time (s)")
        ax4.set_title("Per-epoch power variability & SS error")
        ax4.grid(True, alpha=0.25); ax4.legend(fontsize=8)

        ax5 = fig.add_subplot(gs[2, 1])
        ep_intg = [e["integral_max"] for e in ep]
        ax5.plot(ep_t, ep_intg, marker="^", linewidth=1.5, color="#FF5722")
        ax5.set_ylabel("Max |integral| per epoch"); ax5.set_xlabel("Time (s)")
        ax5.set_title("Integral magnitude per epoch — check for growth")
        ax5.grid(True, alpha=0.25)

    plt.savefig(OUTPUT_DIR / f"long_duration_pid{pid}.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Plot saved: {OUTPUT_DIR}/long_duration_pid{pid}.png")


# ─── Main ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Long-duration stability experiment")
    ap.add_argument("--budget",   type=int,   default=DEFAULT_BUDGET)
    ap.add_argument("--duration", type=float, default=DEFAULT_DURATION,
                    help="Duration in MINUTES (default: 20)")
    args = ap.parse_args()

    check_driver_or_exit()
    ensure_output()

    workload = launch_workload()
    pid = workload.pid
    print(f"Workload PID : {pid}")
    print(f"Budget       : {args.budget} mW")
    print(f"Duration     : {args.duration} min ({args.duration*60:.0f}s)")
    print(f"Warming up {WARMUP_S}s …")
    time.sleep(WARMUP_S)

    all_rows = epoch_stats = None
    try:
        all_rows, epoch_stats = run(pid, args.budget, args.duration)
    finally:
        clear_budget(pid)
        terminate_workload(workload)

    if not all_rows:
        print("No data."); return

    analyse(all_rows, epoch_stats, args.budget)

    if epoch_stats.epochs:
        from experiment_utils import save_csv
        save_csv(
            OUTPUT_DIR / f"long_duration_epochs_pid{pid}.csv",
            list(epoch_stats.epochs[0].keys()),
            epoch_stats.epochs,
        )

    plot(pid, args.budget, all_rows, epoch_stats)


if __name__ == "__main__":
    main()
