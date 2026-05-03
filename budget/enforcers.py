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
# 1. Scheduler Weight (nice)
# ==========================================================

def apply_nice(pid: int, nice_value: int = 10):
    """
    Apply scheduler priority shaping via nice().
    Higher nice_value → lower scheduling priority.
    """
    if not _pid_exists(pid):
        _warn(f"PID {pid} not found.")
        return
    try:
        os.setpriority(os.PRIO_PROCESS, pid, nice_value)
        print(f"[akxOS] Applied nice={nice_value} to PID {pid}")
    except PermissionError:
        _warn("Permission denied. Run with sudo.")
    except Exception as e:
        _warn(f"apply_nice failed: {e}")


def reset_nice(pid: int):
    """Reset nice value to default (0)."""
    try:
        os.setpriority(os.PRIO_PROCESS, pid, 0)
        print(f"[akxOS] Reset nice for PID {pid}")
    except Exception:
        pass


# ==========================================================
# 2. DVFS Frequency Cap
# ==========================================================

CPU_SYS_PATH = Path("/sys/devices/system/cpu")
CPU0_FREQ    = CPU_SYS_PATH / "cpu0/cpufreq"


def _cpu_list():
    return sorted(
        p for p in CPU_SYS_PATH.glob("cpu[0-9]*") if p.is_dir()
    )


def get_current_freq() -> int | None:
    path = CPU0_FREQ / "scaling_cur_freq"
    if path.exists():
        return int(path.read_text().strip())
    return None


def get_available_freqs() -> list[int]:
    path = CPU0_FREQ / "scaling_available_frequencies"
    if path.exists():
        return sorted(int(f) for f in path.read_text().split())
    return []


def apply_budget_dvfs(current_power_mw: float,
                      budget_mw: float,
                      Kp: float = 0.5):
    """
    Proportional DVFS feedback controller.

    Scales CPU frequency up or down based on the error between current
    average power and the budget setpoint. Runs every control tick so
    it naturally relaxes (increases frequency) when under budget.
    """
    if current_power_mw <= 0:
        return

    current_freq = get_current_freq()
    if current_freq is None:
        return

    error_ratio = (budget_mw - current_power_mw) / current_power_mw
    ratio = 1 + Kp * error_ratio
    target_freq = int(current_freq * ratio)

    freqs = get_available_freqs()
    if not freqs:
        return

    target_freq = min(freqs, key=lambda f: abs(f - target_freq))
    target_freq = max(min(freqs), min(target_freq, max(freqs)))

    try:
        for cpu in _cpu_list():
            path = cpu / "cpufreq" / "scaling_max_freq"
            if path.exists():
                path.write_text(str(target_freq))
        print(
            f"[akxOS][dvfs] "
            f"{current_power_mw:.1f} mW → budget {budget_mw:.1f} mW | "
            f"{current_freq} → {target_freq} kHz"
        )
    except PermissionError:
        _warn("Permission denied. DVFS requires sudo.")


def reset_freq_cap():
    """Reset scaling_max_freq to the hardware maximum."""
    try:
        for cpu in _cpu_list():
            max_path   = cpu / "cpufreq" / "cpuinfo_max_freq"
            scale_path = cpu / "cpufreq" / "scaling_max_freq"
            if max_path.exists() and scale_path.exists():
                scale_path.write_text(max_path.read_text().strip())
        print("[akxOS] Reset frequency cap to hardware maximum.")
    except Exception:
        pass


# ==========================================================
# 3. CPU Quota (cgroups v2)
# ==========================================================

CGROUP_ROOT = Path("/sys/fs/cgroup")


def apply_cgroup_quota(pid: int, quota_us: int, period_us: int = 100_000):
    """
    Enforce a CPU time quota for `pid` via a per-PID cgroup v2 group.

    Creates /sys/fs/cgroup/akxos_{pid} if it does not exist, writes the
    cpu.max budget, and assigns the process to the group.
    """
    if not _pid_exists(pid):
        _warn(f"PID {pid} not found.")
        return

    group_path = CGROUP_ROOT / f"akxos_{pid}"

    try:
        group_path.mkdir(exist_ok=True)
        (group_path / "cpu.max"      ).write_text(f"{quota_us} {period_us}")
        (group_path / "cgroup.procs" ).write_text(str(pid))
        print(
            f"[akxOS] Applied CPU quota to PID {pid} "
            f"({quota_us}/{period_us} µs)"
        )
    except Exception as e:
        _warn(f"apply_cgroup_quota failed: {e}")


def reset_cgroup(pid: int):
    """
    Move `pid` back to the root cgroup and remove its per-PID group.
    Guards against the process already being dead before attempting the
    cgroup.procs write.
    """
    group_path = CGROUP_ROOT / f"akxos_{pid}"

    try:
        if _pid_exists(pid):
            (CGROUP_ROOT / "cgroup.procs").write_text(str(pid))

        if group_path.exists():
            group_path.rmdir()

        print(f"[akxOS] Reset cgroup for PID {pid}")
    except Exception:
        pass
