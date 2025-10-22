#!/usr/bin/env python3
"""
akxOS Power Model v0.1.2
------------------------
Computes per-process dynamic and leakage power
based on CPU% and memory usage from process_info.py.
Logs timestamped results into logs/power_log_<date>.csv
"""

import os
import csv
from datetime import datetime
from process_info import get_process_stats  # reuse your existing function

# --- Configurable constants ---
VOLTAGE = 1.0          # volts (approx for RPi)
FREQ = 1.5e9           # Hz (1.5 GHz)
K_DYN = 2e-9           # scaling factor for dynamic power
K_LEAK = 5e-9          # scaling factor for leakage power
LOG_DIR = "../logs/"   # relative to scripts directory


def compute_pdyn(cpu_percent):
    """Estimate dynamic power in mW."""
    return K_DYN * cpu_percent * (VOLTAGE ** 2) * FREQ * 1e3


def compute_pleak(mem_kb):
    """Estimate leakage power in mW."""
    return K_LEAK * mem_kb * VOLTAGE * 1e3


def get_log_file():
    """Generate timestamped log filename."""
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join(LOG_DIR, f"power_log_{timestamp}.csv")


def main():
    processes = get_process_stats()  # [{'pid':.., 'name':.., 'cpu':.., 'mem':..}, ...]
    log_file = get_log_file()

    with open(log_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "PID", "Name", "CPU%", "Mem(KB)", "Pdyn(mW)", "Pleak(mW)", "Ptotal(mW)"])

        for p in processes:
            pdyn = compute_pdyn(p["cpu"])
            pleak = compute_pleak(p["mem"])
            ptotal = pdyn + pleak
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                p["pid"], p["name"], f"{p['cpu']:.2f}", p["mem"],
                f"{pdyn:.3f}", f"{pleak:.3f}", f"{ptotal:.3f}"
            ])

    print(f"[akxOS] Power log created → {log_file}")


if __name__ == "__main__":
    main()
