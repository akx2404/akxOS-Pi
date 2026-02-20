#!/usr/bin/env python3
"""
akxOS Enforcement Mechanisms
----------------------------
User-space enforcement primitives for power budgeting.

"""

import os
from pathlib import Path


# ==========================================================
# Utility Helpers
# ==========================================================

def _warn(msg: str):
    print(f"[akxOS][enforcer] {msg}")


def _pid_exists(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


# ==========================================================
# 1️⃣ Scheduler Weight (nice)
# ==========================================================

def apply_nice(pid: int, nice_value: int = 10):
    """
    Apply scheduler priority shaping using nice().

    Higher nice_value → lower scheduling priority.
    """
    if not _pid_exists(pid):
        _warn(f"PID {pid} not found.")
        return

    try:
        os.setpriority(os.PRIO_PROCESS, pid, nice_value)
        print(f"[akxOS] Applied nice={nice_value} to PID {pid}")
    except PermissionError:
        _warn("Permission denied. Try running with sudo.")
    except Exception as e:
        _warn(f"apply_nice failed: {e}")


def reset_nice(pid: int):
    """
    Reset nice value to default (0).
    """
    try:
        os.setpriority(os.PRIO_PROCESS, pid, 0)
        print(f"[akxOS] Reset nice for PID {pid}")
    except Exception:
        pass


# ==========================================================
# 2️⃣ DVFS Frequency Cap
# ==========================================================

CPU_SYS_PATH = Path("/sys/devices/system/cpu")


def _cpu_list():
    return sorted(
        p for p in CPU_SYS_PATH.glob("cpu[0-9]*")
        if p.is_dir()
    )


def apply_freq_cap(freq_khz: int):
    """
    Apply max frequency cap across all CPU cores.
    """
    try:
        for cpu in _cpu_list():
            path = cpu / "cpufreq" / "scaling_max_freq"
            if path.exists():
                path.write_text(str(freq_khz))

        print(f"[akxOS] Applied frequency cap: {freq_khz} kHz")

    except PermissionError:
        _warn("Permission denied. DVFS requires sudo.")
    except Exception as e:
        _warn(f"apply_freq_cap failed: {e}")


def reset_freq_cap():
    """
    Reset max frequency to hardware maximum.
    """
    try:
        for cpu in _cpu_list():
            max_path = cpu / "cpufreq" / "cpuinfo_max_freq"
            scale_path = cpu / "cpufreq" / "scaling_max_freq"

            if max_path.exists() and scale_path.exists():
                max_freq = max_path.read_text().strip()
                scale_path.write_text(max_freq)

        print("[akxOS] Reset frequency cap to hardware maximum")

    except Exception:
        pass


# ==========================================================
# 3️⃣ CPU Quota (cgroups v2)
# ==========================================================

CGROUP_ROOT = Path("/sys/fs/cgroup")
AKXOS_GROUP = CGROUP_ROOT / "akxos_budget"


def _ensure_cgroup():
    try:
        if not AKXOS_GROUP.exists():
            AKXOS_GROUP.mkdir()
        return True
    except PermissionError:
        _warn("Permission denied creating cgroup. Requires sudo.")
        return False


def apply_cgroup_quota(pid: int, quota_us: int, period_us: int = 100000):
    """
    Apply CPU quota using cgroups v2.

    quota_us  : allowed microseconds per period
    period_us : scheduling period (default 100ms)
    """
    if not _pid_exists(pid):
        _warn(f"PID {pid} not found.")
        return

    if not _ensure_cgroup():
        return

    try:
        cpu_max = AKXOS_GROUP / "cpu.max"
        procs = AKXOS_GROUP / "cgroup.procs"

        cpu_max.write_text(f"{quota_us} {period_us}")
        procs.write_text(str(pid))

        print(
            f"[akxOS] Applied CPU quota to PID {pid} "
            f"({quota_us}/{period_us} µs)"
        )

    except Exception as e:
        _warn(f"apply_cgroup_quota failed: {e}")


def reset_cgroup(pid: int):
    """
    Move process back to root cgroup.
    """
    try:
        root_procs = CGROUP_ROOT / "cgroup.procs"
        root_procs.write_text(str(pid))
        print(f"[akxOS] Reset cgroup for PID {pid}")
    except Exception:
        pass
