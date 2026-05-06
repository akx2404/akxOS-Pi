#!/usr/bin/env python3

import subprocess
import time
import csv
from pathlib import Path

PROC_PATH = Path("/proc/akxos_sched")
OUT_DIR = Path("tests/results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DURATION = 30
POLL_S = 0.5


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


def main():
    print("Launching two CPU-bound workloads...")

    p1 = subprocess.Popen(["yes"], stdout=subprocess.DEVNULL)
    p2 = subprocess.Popen(["yes"], stdout=subprocess.DEVNULL)

    pid1 = p1.pid
    pid2 = p2.pid

    print(f"PID1={pid1} budget=80 mW")
    print(f"PID2={pid2} budget=100 mW")

    time.sleep(2)

    proc_write(f"set {pid1} 80")
    proc_write(f"set {pid2} 100")

    out_csv = OUT_DIR / f"multiprocess_pid{pid1}_{pid2}.csv"

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
                    f"PID1 P={r1['power']:4d} quota={r1['quota']:3d}% | "
                    f"PID2 P={r2['power']:4d} quota={r2['quota']:3d}%",
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


if __name__ == "__main__":
    main()
