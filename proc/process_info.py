#!/usr/bin/env python3
"""
akxOS Process Info Parser
--------------------------
Reads process information from /proc/[pid]/stat and computes:
- PID, Name, CPU usage (%), Memory usage (KB)

"""

import os
import time


# --- Internal Helpers ---

def read_total_cpu_time() -> int:
    """Reads total CPU time from /proc/stat (sum of all core ticks)."""
    try:
        with open("/proc/stat", "r") as f:
            fields = f.readline().split()[1:]
            return sum(map(int, fields))
    except Exception:
        return 1  # Prevent division by zero downstream


def _read_pid_stat(pid: str):
    """
    Read /proc/{pid}/stat once and return (name, mem_kb, cpu_ticks).

    Previously this was two separate functions (read_pid_cpu_time and
    read_pid_name_and_mem) each opening the file independently.
    Combining them halves the syscall count and removes the tiny timestamp
    skew between the two reads.

    Returns
    -------
    tuple : (name: str | None, mem_kb: int, cpu_ticks: int)
    """
    try:
        with open(f"/proc/{pid}/stat", "r") as f:
            data = f.read().split()
        name = data[1].strip("()")
        cpu_ticks = int(data[13]) + int(data[14])   # utime + stime
        mem_kb = int(data[23]) * 4                  # RSS pages × 4 KB
        return name, mem_kb, cpu_ticks
    except Exception:
        return None, 0, 0


# --- Core Function ---

def get_process_stats(sample_delay: float = 0.05) -> list:
    """
    Returns a list of dicts:
        {'pid': int, 'name': str, 'cpu': float, 'mem': int}

    Two-snapshot approach to compute CPU delta. Each PID's stat file is
    opened once per snapshot (not twice as before).
    """
    # --- First snapshot ---
    total_time_1 = read_total_cpu_time()
    snapshot_1: dict = {}

    for pid in filter(str.isdigit, os.listdir("/proc")):
        name, mem_kb, cpu_ticks = _read_pid_stat(pid)
        if name:
            snapshot_1[pid] = (name, mem_kb, cpu_ticks)

    time.sleep(sample_delay)

    # --- Second snapshot ---
    total_time_2 = read_total_cpu_time()
    total_delta = max(total_time_2 - total_time_1, 1)

    process_data = []

    for pid, (name, mem_kb, t1) in snapshot_1.items():
        _, _, t2 = _read_pid_stat(pid)

        # Clamp to 0: kernel accounting quirks can yield t2 < t1
        cpu_percent = max(0.0, 100.0 * (t2 - t1) / total_delta)

        process_data.append({
            "pid":  int(pid),
            "name": name,
            "cpu":  round(cpu_percent, 2),
            "mem":  mem_kb,
        })

    return process_data


# --- Standalone Execution ---

if __name__ == "__main__":
    stats = get_process_stats()
    print(f"{'PID':<8}{'Name':<25}{'CPU%':<10}{'Mem(KB)':<10}")
    print("-" * 55)
    for p in sorted(stats, key=lambda x: x["cpu"], reverse=True)[:10]:
        print(f"{p['pid']:<8}{p['name']:<25}{p['cpu']:<10.2f}{p['mem']:<10}")
