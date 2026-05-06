#!/usr/bin/env python3
"""
akxOS Budget Sweep + Settling Experiment
"""

import argparse
import csv
import math
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

PROC_PATH = "/proc/akxos_sched"
POLL_S = 0.5
BUDGET_DEFAULT = 80
BUDGET_SWEEP_DEFAULT = [60, 80, 100]
TOLERANCE_PCT = 5.0
MIN_SETTLED_S = 3.0
WINDOW_SIZES = [1, 3, 5, 10, 20]
MAX_DURATION_S = 30
WARMUP_S = 3
COOLDOWN_S = 5
OUTPUT_DIR = Path("tests/results")

# Use a non-terminating CPU-bound workload for control experiments.
WORKLOAD_CMD = ["yes"]


# ─────────────────────────────────────────────────────────────
# /proc helpers
# ─────────────────────────────────────────────────────────────

def read_proc_text() -> str | None:
    try:
        return Path(PROC_PATH).read_text()
    except FileNotFoundError:
        return None


def check_driver_or_exit():
    text = read_proc_text()
    if text is None:
        print(f"[error] {PROC_PATH} not found. Load akxos_sched.ko first.", file=sys.stderr)
        sys.exit(1)

    first = text.splitlines()[0] if text.splitlines() else ""
    if "akxOS power budget controller" not in first:
        print("[error] Wrong/stale driver loaded.", file=sys.stderr)
        print(f"Current /proc header: {first}", file=sys.stderr)
        print("Expected: akxOS power budget controller", file=sys.stderr)
        sys.exit(1)


def read_proc(pid: int):
    text = read_proc_text()
    if text is None:
        return None

    for line in text.splitlines():
        parts = line.split()
        if not parts or not parts[0].isdigit():
            continue
        if int(parts[0]) != pid:
            continue

        try:
            return {
                "pid": int(parts[0]),
                "budget_mw": int(parts[1]),
                "freq_khz": int(parts[2]),
                "util": int(parts[3]),
                "power_mw": int(parts[4]),
                "error_mw": int(parts[5]),
                "integral": int(parts[6]),
                "quota_pct": int(parts[7]),
                "stop_ms": int(parts[8]),
                "throttled": int(parts[9]),
                "viol": int(parts[10]),
                "energy_uj": int(parts[11]),
            }
        except (IndexError, ValueError):
            return None

    return None


def _proc_write(cmd: str, fatal=True, quiet=False):
    result = subprocess.run(
        ["sudo", "sh", "-c", f"echo '{cmd}' > {PROC_PATH}"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        if not quiet:
            print("[warn] /proc write failed")
            print(f"cmd: {cmd}")
            print(f"stderr: {result.stderr.strip()}")
        if fatal:
            sys.exit(1)
        return False

    return True


def set_budget(pid: int, budget_mw: int):
    _proc_write(f"set {pid} {budget_mw}", fatal=True)


def clear_budget(pid: int):
    _proc_write(f"clear {pid}", fatal=False, quiet=True)


def reset_ctrl(pid: int):
    _proc_write(f"reset_ctrl {pid}", fatal=False, quiet=True)


# ─────────────────────────────────────────────────────────────
# Analysis helpers
# ─────────────────────────────────────────────────────────────

def moving_average(data: list[float], window: int) -> np.ndarray:
    result = np.empty(len(data))
    buf = deque(maxlen=window)
    for i, x in enumerate(data):
        buf.append(x)
        result[i] = sum(buf) / len(buf)
    return result


def settling_time(times, smoothed, budget, tol_pct):
    tol = budget * tol_pct / 100.0
    lo = budget - tol
    hi = budget + tol
    n_min = max(1, int(math.ceil(MIN_SETTLED_S / POLL_S)))

    for i in range(len(smoothed)):
        end = i + n_min
        if end > len(smoothed):
            break
        if np.all((smoothed[i:end] >= lo) & (smoothed[i:end] <= hi)):
            return float(times[i])
    return None


def analyse(data, window_sizes, tol_pct):
    raw = data["raw_power"]
    times = data["times"]
    budget = data["budget_mw"]

    n = len(raw)
    trans_end = max(1, n * 2 // 5)
    ss_start = max(0, n * 7 // 10)

    metrics = {}
    for w in window_sizes:
        sm = moving_average(raw.tolist(), w)
        trans_sm = sm[:trans_end]
        ss_sm = sm[ss_start:] if ss_start < n else sm[-5:]

        metrics[w] = {
            "smoothed": sm,
            "settle_s": settling_time(times, sm, budget, tol_pct),
            "overshoot": max(0.0, float(np.max(trans_sm)) - budget),
            "ss_error": float(abs(np.mean(ss_sm) - budget)),
            "ss_sigma": float(np.std(ss_sm)),
            "ss_mean": float(np.mean(ss_sm)),
        }

    return metrics


def choose_best_window(metrics, budget, tol_pct):
    tol = budget * tol_pct / 100.0
    for w in sorted(metrics):
        m = metrics[w]
        if m["settle_s"] is not None and m["ss_sigma"] <= tol:
            return w
    return min(metrics, key=lambda w: metrics[w]["ss_sigma"])


# ─────────────────────────────────────────────────────────────
# Data collection
# ─────────────────────────────────────────────────────────────

def collect(pid: int, budget_mw: int, duration_s: float):
    print(f"\nSetting budget {budget_mw} mW on PID {pid}")

    clear_budget(pid)
    reset_ctrl(pid)
    time.sleep(0.2)
    set_budget(pid, budget_mw)

    times = []
    raw_power = []
    quota_pct = []
    stop_ms = []
    integral = []
    util = []
    error = []
    energy = []

    t0 = time.monotonic()

    while True:
        t = time.monotonic() - t0
        row = read_proc(pid)

        if row:
            print(
                f"t={t:5.1f}s | "
                f"P={row['power_mw']:4d} mW | "
                f"util={row['util']:4d} | "
                f"err={row['error_mw']:4d} | "
                f"quota={row['quota_pct']:3d}% | "
                f"stop={row['stop_ms']:3d} ms | "
                f"int={row['integral']:4d}",
                flush=True,
            )

            times.append(t)
            raw_power.append(float(row["power_mw"]))
            quota_pct.append(float(row["quota_pct"]))
            stop_ms.append(float(row["stop_ms"]))
            integral.append(float(row["integral"]))
            util.append(float(row["util"]))
            error.append(float(row["error_mw"]))
            energy.append(float(row["energy_uj"]))
        else:
            print(f"t={t:5.1f}s | waiting for PID {pid} in /proc...", flush=True)

        if t >= duration_s:
            break

        time.sleep(POLL_S)

    clear_budget(pid)

    return {
        "pid": pid,
        "budget_mw": budget_mw,
        "times": np.array(times),
        "raw_power": np.array(raw_power),
        "quota_pct": np.array(quota_pct),
        "stop_ms": np.array(stop_ms),
        "integral": np.array(integral),
        "util": np.array(util),
        "error": np.array(error),
        "energy_uj": np.array(energy),
    }


# ─────────────────────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────────────────────

def print_table(metrics, budget, tol_pct):
    tol = budget * tol_pct / 100.0
    print(f"\nBudget={budget} mW | Tolerance=±{tol_pct}% = ±{tol:.1f} mW")
    print(f"Must stay inside band for ≥{MIN_SETTLED_S}s\n")
    print(f"{'Win':>4} {'Settle(s)':>10} {'Overshoot':>11} {'SS Mean':>9} {'SS Error':>9} {'SS σ':>7}")
    print("-" * 62)

    for w, m in sorted(metrics.items()):
        st = f"{m['settle_s']:.1f}" if m["settle_s"] is not None else "never"
        print(
            f"{w:>4} "
            f"{st:>10} "
            f"{m['overshoot']:>9.1f}mW "
            f"{m['ss_mean']:>8.1f} "
            f"{m['ss_error']:>8.2f} "
            f"{m['ss_sigma']:>7.2f}"
        )


def save_csv(data, metrics, path):
    ws = sorted(metrics.keys())

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "time_s", "raw_mw", "quota_pct", "stop_ms", "integral",
                "util_permille", "error_mw", "energy_uj",
            ]
            + [f"w{w}_mw" for w in ws]
        )

        for i in range(len(data["times"])):
            writer.writerow(
                [
                    f"{data['times'][i]:.3f}",
                    f"{data['raw_power'][i]:.1f}",
                    f"{data['quota_pct'][i]:.0f}",
                    f"{data['stop_ms'][i]:.0f}",
                    f"{data['integral'][i]:.0f}",
                    f"{data['util'][i]:.0f}",
                    f"{data['error'][i]:.0f}",
                    f"{data['energy_uj'][i]:.0f}",
                ]
                + [f"{metrics[w]['smoothed'][i]:.2f}" for w in ws]
            )

    print(f"CSV saved: {path}")


def plot_single(data, metrics, tol_pct, out_path):
    times = data["times"]
    raw = data["raw_power"]
    budget = data["budget_mw"]
    tol = budget * tol_pct / 100.0

    fig = plt.figure(figsize=(14, 10))
    fig.suptitle(
        f"akxOS Scheduler Duty-Cycle Budget Control\n"
        f"PID {data['pid']} | Budget={budget} mW | Band=±{tol:.1f} mW",
        fontsize=13,
        fontweight="bold",
    )

    gs = gridspec.GridSpec(3, 2, figure=fig, height_ratios=[2.2, 1.0, 1.0], hspace=0.45, wspace=0.35)

    ax_power = fig.add_subplot(gs[0, :])
    ax_power.plot(times, raw, linewidth=0.9, label="Raw power")

    for w in sorted(metrics.keys()):
        if w == 1:
            continue
        sm = metrics[w]["smoothed"]
        st = metrics[w]["settle_s"]
        label = f"w={w} ({w * POLL_S:.1f}s), settle=" + ("never" if st is None else f"{st:.1f}s")
        ax_power.plot(times, sm, linewidth=1.5, label=label)
        if st is not None:
            ax_power.axvline(st, linewidth=0.8, linestyle="--", alpha=0.5)

    ax_power.axhline(budget, linestyle="--", linewidth=1.4, label=f"Budget {budget} mW")
    ax_power.fill_between(times, [budget - tol] * len(times), [budget + tol] * len(times), alpha=0.12, label=f"±{tol_pct}% band")
    ax_power.set_xlabel("Time (s)")
    ax_power.set_ylabel("Power (mW)")
    ax_power.set_title("Power oscillation and settling")
    ax_power.grid(True, alpha=0.25)
    ax_power.legend(fontsize=8, loc="upper right")
    ax_power.set_ylim(bottom=0)

    ax_quota = fig.add_subplot(gs[1, :])
    ax_quota.plot(times, data["quota_pct"], linewidth=1.4, label="Quota (%)")
    ax_stop = ax_quota.twinx()
    ax_stop.plot(times, data["stop_ms"], linestyle="--", linewidth=1.2, label="Stop duration (ms)")
    ax_quota.set_xlabel("Time (s)")
    ax_quota.set_ylabel("Quota (%)")
    ax_stop.set_ylabel("Stop duration (ms)")
    ax_quota.set_title("Controller action")
    ax_quota.grid(True, alpha=0.25)
    lines1, labels1 = ax_quota.get_legend_handles_labels()
    lines2, labels2 = ax_stop.get_legend_handles_labels()
    ax_quota.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="lower right")

    ax_settle = fig.add_subplot(gs[2, 0])
    ws_valid = [w for w in sorted(metrics) if metrics[w]["settle_s"] is not None]
    st_valid = [metrics[w]["settle_s"] for w in ws_valid]
    if ws_valid:
        ax_settle.bar(ws_valid, st_valid)
        for w, st in zip(ws_valid, st_valid):
            ax_settle.text(w, st + 0.2, f"{st:.1f}s", ha="center", fontsize=8)
    else:
        ax_settle.text(0.5, 0.5, "No window settled", ha="center", va="center")
    ax_settle.set_xlabel("Window size")
    ax_settle.set_ylabel("Settling time (s)")
    ax_settle.set_title("Settling time vs smoothing")
    ax_settle.grid(True, axis="y", alpha=0.25)

    ax_noise = fig.add_subplot(gs[2, 1])
    ws_all = sorted(metrics)
    ss_sigma = [metrics[w]["ss_sigma"] for w in ws_all]
    ss_error = [metrics[w]["ss_error"] for w in ws_all]
    ax_noise.plot(ws_all, ss_sigma, marker="o", label="SS noise σ")
    ax_noise.plot(ws_all, ss_error, marker="s", linestyle="--", label="SS mean error")
    ax_noise.axhline(tol, linestyle=":", label=f"Tolerance {tol:.1f} mW")
    ax_noise.set_xlabel("Window size")
    ax_noise.set_ylabel("Deviation (mW)")
    ax_noise.set_title("Steady-state oscillation vs window")
    ax_noise.grid(True, alpha=0.25)
    ax_noise.legend(fontsize=8)

    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved: {out_path}")


def plot_overlay(results, best_window_by_budget, out_path):
    plt.figure(figsize=(12, 6))

    for budget, data, metrics in results:
        w = best_window_by_budget[budget]
        sm = metrics[w]["smoothed"]
        plt.plot(data["times"], sm, linewidth=1.8, label=f"Budget {budget} mW, w={w}")
        plt.axhline(budget, linestyle="--", linewidth=0.9, alpha=0.55)

    plt.title("akxOS Budget Sweep: Power Settling Across Budgets")
    plt.xlabel("Time (s)")
    plt.ylabel("Power (mW)")
    plt.grid(True, alpha=0.25)
    plt.legend(fontsize=9)
    plt.ylim(bottom=0)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Overlay plot saved: {out_path}")


def save_summary(summary_rows, path):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "budget_mw", "best_window", "settle_s", "overshoot_mw",
                "ss_mean_mw", "ss_error_mw", "ss_sigma_mw",
            ],
        )
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)
    print(f"Summary CSV saved: {path}")


def print_summary(summary_rows):
    print("\n" + "═" * 72)
    print("Budget sweep summary")
    print("═" * 72)
    print(f"{'Budget':>8} {'Best W':>8} {'Settle':>10} {'Overshoot':>11} {'SS Mean':>9} {'SS Err':>8} {'SS σ':>8}")
    print("-" * 72)
    for r in summary_rows:
        settle = "never" if r["settle_s"] is None else f"{r['settle_s']:.1f}s"
        print(
            f"{r['budget_mw']:>8} "
            f"{r['best_window']:>8} "
            f"{settle:>10} "
            f"{r['overshoot_mw']:>9.1f}mW "
            f"{r['ss_mean_mw']:>8.1f} "
            f"{r['ss_error_mw']:>8.2f} "
            f"{r['ss_sigma_mw']:>8.2f}"
        )


# ─────────────────────────────────────────────────────────────
# Workload + main
# ─────────────────────────────────────────────────────────────

def launch_workload():
    print("Launching workload: yes > /dev/null")
    return subprocess.Popen(WORKLOAD_CMD, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_one(pid, budget, duration, windows, tol):
    print("\n" + "─" * 60)
    print(f"Budget = {budget} mW | PID = {pid} | Duration = {duration}s")
    print("─" * 60)

    data = collect(pid, budget, duration)

    if len(data["times"]) < 4:
        print("Too few samples. Workload probably exited early or driver table was not readable.")
        return None, None

    metrics = analyse(data, windows, tol)
    print_table(metrics, budget, tol)

    stem = f"settling_pid{pid}_budget{budget}mw"
    plot_single(data, metrics, tol, OUTPUT_DIR / f"{stem}.png")
    save_csv(data, metrics, OUTPUT_DIR / f"{stem}.csv")

    return data, metrics


def main():
    parser = argparse.ArgumentParser(description="akxOS budget sweep settling experiment")
    parser.add_argument("--pid", type=int, default=None, help="Existing PID. If omitted, launches yes workload.")
    parser.add_argument("--budget", type=int, default=BUDGET_DEFAULT, help="Single budget in mW")
    parser.add_argument("--budgets", type=int, nargs="+", default=None, help="Budget sweep, e.g. --budgets 60 80 100")
    parser.add_argument("--duration", type=float, default=MAX_DURATION_S)
    parser.add_argument("--tol", type=float, default=TOLERANCE_PCT)
    parser.add_argument("--windows", type=int, nargs="+", default=WINDOW_SIZES)
    parser.add_argument("--warmup", type=float, default=WARMUP_S)
    parser.add_argument("--cooldown", type=float, default=COOLDOWN_S)
    args = parser.parse_args()

    check_driver_or_exit()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    budgets = args.budgets if args.budgets else [args.budget]
    windows = sorted(args.windows)

    workload = None
    pid = args.pid
    results = []
    summary_rows = []
    best_window_by_budget = {}

    try:
        if pid is None:
            workload = launch_workload()
            pid = workload.pid
            print(f"PID = {pid}")
            print(f"Warming up {args.warmup:.1f}s...")
            time.sleep(args.warmup)

        for idx, budget in enumerate(budgets):
            # Reuse same workload across sweep. This keeps PID constant and makes curves comparable.
            data, metrics = run_one(pid, budget, args.duration, windows, args.tol)
            if data is None:
                continue

            best_w = choose_best_window(metrics, budget, args.tol)
            best_window_by_budget[budget] = best_w
            best = metrics[best_w]

            summary_rows.append({
                "budget_mw": budget,
                "best_window": best_w,
                "settle_s": best["settle_s"],
                "overshoot_mw": best["overshoot"],
                "ss_mean_mw": best["ss_mean"],
                "ss_error_mw": best["ss_error"],
                "ss_sigma_mw": best["ss_sigma"],
            })
            results.append((budget, data, metrics))

            if idx != len(budgets) - 1:
                print(f"\nCooldown {args.cooldown:.1f}s before next budget...")
                clear_budget(pid)
                time.sleep(args.cooldown)

        if len(results) > 1:
            plot_overlay(results, best_window_by_budget, OUTPUT_DIR / f"budget_sweep_pid{pid}.png")
            save_summary(summary_rows, OUTPUT_DIR / f"budget_sweep_pid{pid}_summary.csv")
            print_summary(summary_rows)

    finally:
        if pid:
            clear_budget(pid)
        if workload and workload.poll() is None:
            workload.terminate()
            workload.wait()
            print("Workload terminated.")


if __name__ == "__main__":
    main()
