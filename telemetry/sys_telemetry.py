#!/usr/bin/env python3
"""
akxOS sys_telemetry.py
Reads live voltage, frequency, and temperature from Raspberry Pi 4 /sys.

"""

from pathlib import Path

DEFAULT_VOLTAGE = 0.95   # Volts — used when regulator sysfs is unavailable
DEFAULT_FREQ    = 1200.0 # MHz  — Pi 4 base clock, used when sysfs is unavailable


def _read_value(path: str):
    """Read a numeric value from sysfs. Returns None if missing or unreadable."""
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def get_cpu_freq(core: int = 0) -> float:
    """
    Return current CPU frequency in MHz.

    On Raspberry Pi 4, all cores share a single clock domain, so `core`
    only affects which sysfs path is tried — the value is always the same
    across cores. Falls back to DEFAULT_FREQ if sysfs is unavailable
    (was previously returning 0.0, which silently zeroed dynamic power).
    """
    val = _read_value(
        f"/sys/devices/system/cpu/cpu{core}/cpufreq/scaling_cur_freq"
    )
    return (val / 1000.0) if val else DEFAULT_FREQ  # kHz → MHz


def get_cpu_voltage(core: int = 0) -> float:
    """
    Return CPU voltage in Volts.

    NOTE: The `core` argument is accepted for API symmetry but is NOT used —
    on Raspberry Pi 4 all cores share a single voltage domain and the
    regulator paths are global. Falls back to DEFAULT_VOLTAGE if unavailable.
    """
    paths = [
        "/sys/class/regulator/regulator.0/microvolts",
        "/sys/class/regulator/regulator.1/microvolts",
    ]
    for p in paths:
        val = _read_value(p)
        if val:
            return val / 1e6  # µV → V
    return DEFAULT_VOLTAGE


def get_cpu_temp() -> float:
    """Return SoC temperature in °C."""
    val = _read_value("/sys/class/thermal/thermal_zone0/temp")
    return (val / 1000.0) if val else 0.0


def read_all_cores() -> dict:
    """Return {core_id: {'V': float, 'f': float, 'T': float}} for all cores."""
    cpu_dir = Path("/sys/devices/system/cpu/")
    cores = [
        int(d.name[3:])
        for d in cpu_dir.iterdir()
        if d.name.startswith("cpu") and d.name[3:].isdigit()
    ]
    temp = get_cpu_temp()
    return {
        core: {
            "V": get_cpu_voltage(core),
            "f": get_cpu_freq(core),
            "T": temp,
        }
        for core in cores
    }


if __name__ == "__main__":
    print("akxOS — sys_telemetry test\n")
    for c, v in read_all_cores().items():
        print(f"Core {c}: V={v['V']:.2f} V  f={v['f']:.0f} MHz  T={v['T']:.1f} °C")
