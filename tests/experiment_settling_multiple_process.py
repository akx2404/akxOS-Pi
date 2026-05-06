#!/usr/bin/env python3

import subprocess
import time
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

PROC_PATH = Path("/proc/akxos_sched")
OUT_DIR = Path("tests/results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DURATION = 30
POLL_S = 0.5

PID1_BUDGET = 80
PID2_BUDGET = 100


def proc_write(cmd):
    subprocess.run(
        ["sudo", "sh", "-c", f"echo '{cmd}' > /proc/akxos_sched"],
        check=False,
    )


def read_rows():
    text = PROC_PATH.read_text()
    rows = {}

    for line in text.splitlines():
        parts = line.split()
        if not parts or not parts[0].isdigit():
            continue

        pid = int(parts[0])

        rows[pid] = {
            "pid": pid,
            "budget": int(parts[1]),
            "freq": int(parts[2]),
            "util": int(parts[3]),
            "power": int(parts[4]),
            "error": int(parts[5]),
            "integral": int(parts[6]),
            "quota": int(parts[7]),
            "stop_ms": int(parts[8]),
            "throttled": int(parts[9]),
            "viol": int(parts[10]),
            "energy": int(parts[11]),
        }

    return rows


def plot_results(samples, pid1, pid2, out_png):
    if not samples:
        print("[warn] No samples to plot.")
        return

    t = [float(s[0]) for s in samples]

    pid1_power = [float(s[3]) for s in samples]
    pid1_quota = [float(s[4]) for s in samples]
    pid1_stop = [float(s[5]) for s in samples]
    pid1_error = [float(s[6]) for s in samples]

    pid2_power = [float(s[9]) for s in samples]
    pid2_quota = [float(s[10]) for s in samples]
    pid2_stop = [float(s[11]) for s in samples]
    pid2_error = [float(s[12]) for s in samples]

    fig = plt.figure(figsize=(14, 10))
    fig.suptitle(
        f"akxOS Multi-Process Power Budget Control\n"
        f"PID {pid1}: {PID1_BUDGET} mW | PID {pid2}: {PID2_BUDGET} mW",
        fontsize=13,
        fontweight="bold",
    )

    gs = gridspec.GridSpec(
        3, 1, figure=fig,
        height_ratios=[2.0, 1.2, 1.2],
        hspace=0.38,
    )

    # Panel 1: power isolation
    ax1 = fig.add_subplot(gs[0])
    ax1.plot(t, pid1_power, label=f"PID {pid1} power")
    ax1.plot(t, pid2_power, label=f"PID {pid2} power")
    ax1.axhline(PID1_BUDGET, linestyle="--", label=f"PID {pid1} budget {PID1_BUDGET} mW")
    ax1.axhline(PID2_BUDGET, linestyle="--", label=f"PID {pid2} budget {PID2_BUDGET} mW")
    ax1.set_title("Per-process power tracking")
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Power (mW)")
    ax1.grid(True, alpha=0.25)
    ax1.legend(fontsize=8, loc="upper right")

    # Panel 2: quota control
    ax2 = fig.add_subplot(gs[1])
    ax2.plot(t, pid1_quota, label=f"PID {pid1} quota")
    ax2.plot(t, pid2_quota, label=f"PID {pid2} quota")
    ax2.set_title("Independent CPU quota control")
    ax2.set_xlabel("Time (s)")
    ax2.set_ylabel("Quota (%)")
    ax2.grid(True, alpha=0.25)
    ax2.legend(fontsize=8, loc="upper right")

    # Panel 3: stop duration + error
    ax3 = fig.add_subplot(gs[2])
    ax3.plot(t, pid1_stop, label=f"PID {pid1} stop_ms")
    ax3.plot(t, pid2_stop, label=f"PID {pid2} stop_ms")
    ax3.set_title("Duty-cycle stop window")
    ax3.set_xlabel("Time (s)")
    ax3.set_ylabel("Stop duration (ms)")
    ax3.grid(True, alpha=0.25)

    ax3b = ax3.twinx()
    ax3b.plot(t, pid1_error, linestyle=":", label=f"PID {pid1} error")
    ax3b.plot(t, pid2_error, linestyle=":", label=f"PID {pid2} error")
    ax3b.set_ylabel("Error (mW)")

    lines1, labels1 = ax3.get_legend_handles_labels()
    lines2, labels2 = ax3b.get_legend_handles_labels()
    ax3.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="upper right")

    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"Plot saved: {out_png}")


def main():
    print("Launching two CPU-bound workloads...")

    p1 = subprocess.Popen(["yes"], stdout=subprocess.DEVNULL)
    p2 = subprocess.Popen(["yes"], stdout=subprocess.DEVNULL)

    pid1 = p1.pid
    pid2 = p2.pid

    print(f"PID1={pid1} budget={PID1_BUDGET} mW")
    print(f"PID2={pid2} budget={PID2_BUDGET} mW")

    time.sleep(2)

    proc_write(f"set {pid1} {PID1_BUDGET}")
    proc_write(f"set {pid2} {PID2_BUDGET}")

    out_csv = OUT_DIR / f"multiprocess_pid{pid1}_{pid2}.csv"
    out_png = OUT_DIR / f"multiprocess_pid{pid1}_{pid2}.png"

    samples = []
    t0 = time.monotonic()

    try:
        while True:
            t = time.monotonic() - t0
            rows = read_rows()

            r1 = rows.get(pid1)
            r2 = rows.get(pid2)

            if r1 and r2:
                print(
                    f"t={t:5.1f}s | "
                    f"PID1 P={r1['power']:4d} quota={r1['quota']:3d}% stop={r1['stop_ms']:3d} | "
                    f"PID2 P={r2['power']:4d} quota={r2['quota']:3d}% stop={r2['stop_ms']:3d}",
                    flush=True,
                )

                samples.append([
                    f"{t:.3f}",
                    pid1, r1["budget"], r1["power"], r1["quota"], r1["stop_ms"], r1["error"],
                    pid2, r2["budget"], r2["power"], r2["quota"], r2["stop_ms"], r2["error"],
                ])
            else:
                print(f"t={t:5.1f}s | waiting for both PIDs...", flush=True)

            if t >= DURATION:
                break

            time.sleep(POLL_S)

    finally:
        proc_write(f"clear {pid1}")
        proc_write(f"clear {pid2}")

        p1.terminate()
        p2.terminate()

        with open(out_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "time_s",
                "pid1", "pid1_budget", "pid1_power", "pid1_quota", "pid1_stop_ms", "pid1_error",
                "pid2", "pid2_budget", "pid2_power", "pid2_quota", "pid2_stop_ms", "pid2_error",
            ])
            writer.writerows(samples)

        print(f"\nCSV saved: {out_csv}")
        plot_results(samples, pid1, pid2, out_png)


if __name__ == "__main__":
    main()
