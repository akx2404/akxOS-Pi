#!/usr/bin/env python3
import os
import time

def get_all_pids():
    """Return list of all running process IDs."""
    return [pid for pid in os.listdir('/proc') if pid.isdigit()]

def read_proc_stat(pid):
    """Parse /proc/[pid]/stat and return key fields."""
    try:
        with open(f'/proc/{pid}/stat', 'r') as f:
            data = f.read().split()
        pid = int(data[0])
        name = data[1].strip('()')
        state = data[2]
        utime = int(data[13])
        stime = int(data[14])
        rss_pages = int(data[23])
        return pid, name, state, utime, stime, rss_pages
    except (FileNotFoundError, PermissionError, IndexError):
        return None

def read_total_cpu_time():
    """Return total CPU jiffies from /proc/stat."""
    with open('/proc/stat', 'r') as f:
        fields = f.readline().split()[1:]
        return sum(map(int, fields))

def rss_to_kb(rss_pages):
    """Convert RSS pages to KB."""
    page_size = os.sysconf('SC_PAGE_SIZE') // 1024
    return rss_pages * page_size

def compute_cpu_percent(pid, interval=0.05):
    """Estimate CPU% by sampling process and system deltas."""
    first = read_proc_stat(pid)
    if not first:
        return 0.0
    total1 = read_total_cpu_time()
    time.sleep(interval)
    second = read_proc_stat(pid)
    if not second:
        return 0.0
    total2 = read_total_cpu_time()

    proc_delta = (second[3] + second[4]) - (first[3] + first[4])
    total_delta = total2 - total1
    if total_delta == 0:
        return 0.0

    ncpu = os.cpu_count()
    return round((proc_delta / total_delta) * 100 * ncpu, 2)

def display_process_info():
    """Display PID, Name, State, CPU%, and Memory."""
    print(f"{'PID':<8}{'Name':<25}{'State':<8}{'CPU%':<8}{'Mem(KB)':<10}")
    print('-' * 60)

    for pid in get_all_pids():
        info = read_proc_stat(pid)
        if not info:
            continue
        pid, name, state, utime, stime, rss_pages = info
        mem_kb = rss_to_kb(rss_pages)
        cpu_percent = compute_cpu_percent(pid)
        print(f"{pid:<8}{name:<25}{state:<8}{cpu_percent:<8}{mem_kb:<10}")

if __name__ == "__main__":
    display_process_info()
