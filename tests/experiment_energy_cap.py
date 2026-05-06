#!/usr/bin/env python3
"""
Experiment 4 — Energy Cap Accuracy
=====================================
Validates the kernel's energy accounting (energy_uj) and the `ecap`
warning feature.

Protocol:
  1. Measure Phase   — run with a permissive budget for MEASURE_S seconds
                        to estimate the workload's natural average power.
  2. Cap Phase       — compute a target energy cap based on the measured
                        power and a desired cap-hit time, then set `ecap`.
                        Monitor energy_uj until the cap is reached and
                        verify the dmesg warning fires at the right time.
  3. Accounting accuracy — compare energy_uj from the kernel against an
                        independent estimate (power_mw × elapsed_ms).

Metrics:
  • Actual vs predicted cap-hit time (absolute and relative error)
  • Cumulative energy accounting drift over time
  • Whether the dmesg warning fires at all

Usage:
  python3 tests/experiment_energy_cap.py
  python3 tests/experiment_energy_cap.py --cap-hit-s 20 --measure-s 8
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
    set_budget, clear_budget, reset_ctrl, set_energy_cap, reset_energy,
    launch_workload, terminate_workload,
    proc_read, moving_average, save_csv, dmesg_grep, print_header,
)

# A permissive budget that allows the workload to run at full speed
# while still appearing in /proc/akxos_sched for power readings.
MEASUREMENT_BUDGET_MW = 999
DEFAULT_MEASURE_S      = 8.0    # seconds to observe natural power
DEFAULT_CAP_HIT_S      = 25.0   # desired seconds until cap warning fires
WARMUP_S               = 3.0
SMOOTH_W               = 6
CAP_CHECK_MARGIN       = 1.5    # monitor for this many × the predicted time


# ─── Measurement phase ───────────────────────────────────────

def measure_natural_power(pid: int, duration_s: float) -> tuple:
    """
    Apply a permissive budget and sample power for duration_s seconds.
    Returns (avg_power_mw, list_of_rows).
    """
    print(f"\n─── Measurement phase ({duration_s}s, budget={MEASUREMENT_BUDGET_MW}mW) ───")
    clear_budget(pid)
    reset_ctrl(pid)
    time.sleep(0.2)
    set_budget(pid, MEASUREMENT_BUDGET_MW)
    reset_energy(pid)

    rows  = []
    start = time.monotonic()
    t0    = start

    while (time.monotonic() - start) < duration_s:
        time.sleep(POLL_S)
        t   = time.monotonic() - t0
        row = proc_read(pid)
        if row:
            row["time_s"] = round(t, 3)
            row["phase"]  = "measure"
            rows.append(row)
            print(f"t={t:5.1f}s | P={row['power_mw']:4d}mW | energy={row['energy_uj']}µJ",
                  flush=True)

    if not rows:
        return 0.0, []

    powers   = [r["power_mw"] for r in rows]
    avg_mw   = float(np.mean(powers[-max(1, len(powers)//2):]))   # use second half only
    return avg_mw, rows


# ─── Energy cap phase ────────────────────────────────────────

def run_cap_phase(pid: int, cap_uj: int, predicted_hit_s: float) -> tuple:
    """
    Reset energy counter, set ecap, monitor until cap fires or timeout.
    Returns (actual_hit_time_s | None, list_of_rows).
    """
    timeout_s = predicted_hit_s * CAP_CHECK_MARGIN + 10.0

    print(f"\n─── Cap phase ───")
    print(f"    ecap = {cap_uj} µJ  |  predicted hit ≈ {predicted_hit_s:.1f}s  "
          f"|  timeout = {timeout_s:.0f}s")

    reset_energy(pid)
    time.sleep(0.2)
    set_energy_cap(pid, cap_uj)

    rows     = []
    hit_time = None
    start    = time.monotonic()
    t0       = start

    while (time.monotonic() - start) < timeout_s:
        time.sleep(POLL_S)
        t   = time.monotonic() - t0
        row = proc_read(pid)
        if not row:
            continue
        row["time_s"] = round(t, 3)
        row["phase"]  = "cap"
        rows.append(row)

        # Detect cap reached
        cap_reached = row["energy_uj"] >= cap_uj
        flag = " ← CAP HIT" if cap_reached and hit_time is None else ""
        print(
            f"t={t:6.1f}s | P={row['power_mw']:4d}mW | "
            f"energy={row['energy_uj']:9d}µJ / {cap_uj}µJ "
            f"({100*row['energy_uj']/cap_uj:5.1f}%){flag}",
            flush=True,
        )
        if cap_reached and hit_time is None:
            hit_time = t
            break

    return hit_time, rows


# ─── Accounting accuracy ─────────────────────────────────────

def accounting_accuracy(rows: list) -> list:
    """
    Compare cumulative energy_uj (kernel) against independent estimate
    (sum of power_mw × delta_t_ms) for each sample.
    """
    if len(rows) < 2:
        return []

    accuracy_rows = []
    cum_est = 0.0

    for i in range(1, len(rows)):
        dt_ms = (rows[i]["time_s"] - rows[i-1]["time_s"]) * 1000.0
        p_mw  = rows[i-1]["power_mw"]
        cum_est += p_mw * dt_ms

        kernel_uj = rows[i]["energy_uj"]
        err_pct   = (kernel_uj - cum_est) / max(cum_est, 1) * 100

        accuracy_rows.append(dict(
            time_s     = rows[i]["time_s"],
            kernel_uj  = kernel_uj,
            estimate_uj = round(cum_est, 2),
            error_uj   = round(kernel_uj - cum_est, 2),
            error_pct  = round(err_pct, 2),
        ))
    return accuracy_rows


# ─── Plotting ────────────────────────────────────────────────

def plot(pid: int, all_rows: list, cap_uj: int,
         predicted_hit_s: float, actual_hit_s: float | None,
         acc_rows: list):

    # Split by phase
    m_rows = [r for r in all_rows if r["phase"] == "measure"]
    c_rows = [r for r in all_rows if r["phase"] == "cap"]

    fig, axes = plt.subplots(3, 1, figsize=(13, 10))
    fig.suptitle(
        f"Energy Cap Accuracy  (PID {pid})\n"
        f"ecap = {cap_uj:,} µJ | predicted hit = {predicted_hit_s:.1f}s"
        + (f" | actual = {actual_hit_s:.1f}s" if actual_hit_s else " | never hit"),
        fontweight="bold",
    )

    # Power
    ax = axes[0]
    if m_rows:
        mt = np.array([r["time_s"] for r in m_rows])
        mp = np.array([r["power_mw"] for r in m_rows], float)
        ax.fill_between(mt, mp, alpha=0.2, color="#90CAF9", label="Measure phase")
        ax.plot(mt, mp, linewidth=1.2, color="#2196F3")
    if c_rows:
        ct = np.array([r["time_s"] for r in c_rows])
        cp = np.array([r["power_mw"] for r in c_rows], float)
        ax.plot(ct, cp, linewidth=1.5, color="#F44336", label="Cap phase")
    ax.set_ylabel("Power (mW)"); ax.grid(True, alpha=0.25)
    ax.set_title("Power during measurement and cap phases"); ax.legend(fontsize=8)

    # Energy counter
    ax = axes[1]
    if c_rows:
        ct  = np.array([r["time_s"]    for r in c_rows])
        cej = np.array([r["energy_uj"] for r in c_rows], float)
        ax.plot(ct, cej / 1e3, linewidth=2.0, color="#9C27B0", label="Kernel energy_uj")
        ax.axhline(cap_uj / 1e3, linestyle="--", color="black", linewidth=1.5,
                   label=f"ecap = {cap_uj/1e3:.0f} mJ")
        ax.axvline(predicted_hit_s + (c_rows[0]["time_s"] if c_rows else 0),
                   linestyle=":", color="blue", label="Predicted hit")
        if actual_hit_s:
            ax.axvline(actual_hit_s, linestyle="-", color="red",
                       linewidth=1.5, label=f"Actual hit t={actual_hit_s:.1f}s")
    ax.set_ylabel("Energy (mJ)"); ax.grid(True, alpha=0.25)
    ax.set_title("Cumulative energy counter vs cap setpoint"); ax.legend(fontsize=8)

    # Accounting error
    ax = axes[2]
    if acc_rows:
        at = np.array([r["time_s"]   for r in acc_rows])
        ae = np.array([r["error_pct"] for r in acc_rows], float)
        ax.plot(at, ae, linewidth=1.5, color="#FF5722")
        ax.axhline(0, linewidth=0.8, linestyle="--", color="black")
        ax.fill_between(at, ae, alpha=0.2, color="#FF5722")
    ax.set_ylabel("Accounting error (%)"); ax.set_xlabel("Time (s)")
    ax.grid(True, alpha=0.25)
    ax.set_title("Kernel energy_uj vs independent estimate (power×time)")

    plt.tight_layout()
    path = OUTPUT_DIR / f"energy_cap_pid{pid}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Plot saved: {path}")


# ─── Main ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Energy cap accuracy experiment")
    ap.add_argument("--measure-s", type=float, default=DEFAULT_MEASURE_S,
                    help=f"Power measurement window (default: {DEFAULT_MEASURE_S}s)")
    ap.add_argument("--cap-hit-s", type=float, default=DEFAULT_CAP_HIT_S,
                    help=f"Desired seconds until cap fires (default: {DEFAULT_CAP_HIT_S})")
    args = ap.parse_args()

    check_driver_or_exit()
    ensure_output()

    workload = launch_workload()
    pid = workload.pid
    print(f"Workload PID : {pid}")
    print(f"Warming up {WARMUP_S}s …")
    time.sleep(WARMUP_S)

    all_rows = []

    try:
        avg_mw, m_rows = measure_natural_power(pid, args.measure_s)
        all_rows.extend(m_rows)

        if avg_mw <= 0:
            print("[error] Could not measure natural power. Is the driver loaded?")
            return

        # Compute ecap: µJ = mW × ms = mW × (s × 1000)
        cap_uj  = int(avg_mw * args.cap_hit_s * 1000)
        print(f"\n  Measured avg power : {avg_mw:.1f} mW")
        print(f"  Target cap-hit time: {args.cap_hit_s}s")
        print(f"  Computed ecap      : {cap_uj:,} µJ  ({cap_uj/1e6:.3f} J)")

        actual_hit_s, c_rows = run_cap_phase(pid, cap_uj, args.cap_hit_s)
        all_rows.extend(c_rows)

    finally:
        clear_budget(pid)
        terminate_workload(workload)

    if not all_rows:
        print("No data."); return

    # Accuracy analysis (cap phase only)
    c_rows_only = [r for r in all_rows if r["phase"] == "cap"]
    acc_rows    = accounting_accuracy(c_rows_only)

    print_header("Energy Cap Analysis")
    if actual_hit_s is not None:
        t_err    = actual_hit_s - args.cap_hit_s
        t_err_pct = t_err / args.cap_hit_s * 100
        print(f"  Predicted cap-hit time : {args.cap_hit_s:.1f}s")
        print(f"  Actual cap-hit time    : {actual_hit_s:.1f}s")
        print(f"  Timing error           : {t_err:+.1f}s  ({t_err_pct:+.1f}%)")
    else:
        print("  Cap was NOT reached within the monitoring window.")

    if acc_rows:
        errs = np.array([r["error_pct"] for r in acc_rows])
        print(f"\n  Accounting error vs power×time estimate:")
        print(f"    Mean  : {float(np.mean(errs)):+.2f}%")
        print(f"    StdDev: {float(np.std(errs)):.2f}%")
        print(f"    Max   : {float(np.max(np.abs(errs))):.2f}%")

    # Check dmesg for kernel warning
    hits = dmesg_grep(f"energy cap")
    print(f"\n  dmesg energy cap warnings: {len(hits)}")
    for l in hits[-3:]:
        print(f"    {l.strip()}")

    # Save
    all_fields = ["time_s", "phase", "pid", "budget_mw", "power_mw",
                  "quota_pct", "stop_ms", "integral", "error_mw",
                  "util", "freq_khz", "energy_uj", "viol"]
    save_csv(OUTPUT_DIR / f"energy_cap_pid{pid}.csv", all_fields, all_rows)

    if acc_rows:
        save_csv(
            OUTPUT_DIR / f"energy_cap_accounting_pid{pid}.csv",
            ["time_s", "kernel_uj", "estimate_uj", "error_uj", "error_pct"],
            acc_rows,
        )

    plot(pid, all_rows, cap_uj, args.cap_hit_s, actual_hit_s, acc_rows)


if __name__ == "__main__":
    main()
