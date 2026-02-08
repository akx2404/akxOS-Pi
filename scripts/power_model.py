#!/usr/bin/env python3
"""
akxOS Power Model v0.2.1
------------------------
Hardware-aware power estimation using live telemetry
from /sys via sys_telemetry.py (for Raspberry Pi 4).
"""

import os
import csv
from datetime import datetime
from process_info import get_process_stats
from sys_telemetry import get_cpu_voltage, get_cpu_freq, get_cpu_temp

# --- Constants ---
ALPHA = 0.3        # switching activity factor
C_EFF = 1.2e-9     # effective capacitance (F)
K_LEAK = 5e-9      # scaling factor for leakage (mW per KB per V)
LOG_DIR = "../logs/"


def compute_pdyn(cpu_percent, core_id=0):
    """
    Compute dynamic power (mW) using live voltage/frequency.
    Pdyn = α * C * V^2 * f * activity
    """
    V = get_cpu_voltage(core_id)
    f = get_cpu_freq(core_id) * 1e6  # MHz → Hz
    pdyn = ALPHA * C_EFF * (V ** 2) * f * (cpu_percent / 100)
    return pdyn * 1e3  # W → mW


def compute_pleak(mem_kb, core_id=0):
    """
    Compute leakage power (mW) proportional to memory * voltage.
    """
    V = get_cpu_voltage(core_id)
    pleak = K_LEAK * mem_kb * V
    return pleak * 1e3  # W → mW


def compute_system_power():
    """
    Compute per-core power using telemetry for debug/testing.
    Returns dict of {core: {V, f, T, Pdyn}} and total power.
    """
    cores = [0, 1, 2, 3]
    core_data = {}
    total = 0.0
    T = get_cpu_temp()
    for c in cores:
        V = get_cpu_voltage(c)
        f = get_cpu_freq(c)
        Pdyn = ALPHA * C_EFF * (V ** 2) * (f * 1e6)
        core_data[c] = {"V": V, "f": f, "T": T, "Pdyn": Pdyn * 1e3}
        total += Pdyn * 1e3
    return core_data, total


def get_log_file():
    """Generate timestamped log filename."""
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join(LOG_DIR, f"power_log_{timestamp}.csv")


def main():
    """Quick test — log one snapshot with real telemetry."""
    processes = get_process_stats()
    log_file = get_log_file()

    with open(log_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Timestamp", "PID", "Name", "CPU%", "Mem(KB)",
            "Voltage(V)", "Freq(MHz)", "Temp(°C)",
            "Pdyn(mW)", "Pleak(mW)", "Ptotal(mW)"
        ])

        for p in processes:
            V = get_cpu_voltage(0)
            f = get_cpu_freq(0)
            T = get_cpu_temp()
            pdyn = compute_pdyn(p["cpu"])
            pleak = compute_pleak(p["mem"])
            ptotal = pdyn + pleak
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                p["pid"], p["name"], f"{p['cpu']:.2f}", p["mem"],
                f"{V:.2f}", f"{f:.0f}", f"{T:.1f}",
                f"{pdyn:.3f}", f"{pleak:.3f}", f"{ptotal:.3f}"
            ])

    print(f"[akxOS] Hardware-aware power log → {log_file}")


if __name__ == "__main__":
    main()
