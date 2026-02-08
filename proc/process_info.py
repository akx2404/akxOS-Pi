#!/usr/bin/env python3
"""
akxOS Process Info Parser v0.1.1
--------------------------------
Reads process information from /proc/[pid]/stat and computes:
- PID
- Name
- CPU usage (%)
- Memory usage (KB)
Provides data to other akxOS modules (e.g., power_model.py).
"""

import os
import time


# --- Internal Helper Functions ---

def read_total_cpu_time():
    """Reads total CPU time from /proc/stat (sum of all core ticks)."""
    with open("/proc/stat", "r") as f:
        fields = f.readline().split()[1:]
        return sum(map(int, fields))


def read_pid_cpu_time(pid):
    """Reads user + system CPU time for a given process."""
    try:
        with open(f"/proc/{pid}/stat", "r") as f:
            data = f.read().split()
            utime, stime = int(data[13]), int(data[14])
            return utime + stime
    except Exception:
        return 0


def read_pid_name_and_mem(pid):
    """Reads process name and resident memory (RSS in KB)."""
    try:
        with open(f"/proc/{pid}/stat", "r") as f:
            data = f.read().split()
            name = data[1].strip("()")
            rss_pages = int(data[23])
            mem_kb = rss_pages * 4  # 4 KB per page
            return name, mem_kb
    except Exception:
        return None, 0


# --- Core Function ---

def get_process_stats(sample_delay=0.05):
    """
    Returns a list of dicts with:
    {
        'pid': int,
        'name': str,
        'cpu': float,
        'mem': int
    }
    """
    process_data = []

    # --- First snapshot ---
    total_time_1 = read_total_cpu_time()
    pid_time_1 = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        pid_time_1[pid] = read_pid_cpu_time(pid)

    # Short sleep to compute CPU delta
    time.sleep(sample_delay)

    # --- Second snapshot ---
    total_time_2 = read_total_cpu_time()
    total_delta = total_time_2 - total_time_1
    if total_delta == 0:
        total_delta = 1  # prevent division by zero

    for pid in filter(str.isdigit, os.listdir("/proc")):
        t1 = pid_time_1.get(pid, 0)
        t2 = read_pid_cpu_time(pid)
        name, mem_kb = read_pid_name_and_mem(pid)

        if name:
            cpu_percent = 100.0 * (t2 - t1) / total_delta
            process_data.append({
                "pid": int(pid),
                "name": name,
                "cpu": round(cpu_percent, 2),
                "mem": mem_kb
            })

    return process_data


# --- Standalone Execution (for debugging) ---

if __name__ == "__main__":
    stats = get_process_stats()

    print(f"{'PID':<8}{'Name':<25}{'CPU%':<10}{'Mem(KB)':<10}")
    print("-" * 55)
    for p in sorted(stats, key=lambda x: x["cpu"], reverse=True)[:10]:
        print(f"{p['pid']:<8}{p['name']:<25}{p['cpu']:<10.2f}{p['mem']:<10}")
