#!/usr/bin/env python3
"""
akxOS sys_telemetry.py
Reads live voltage, frequency, and temperature from Raspberry Pi 4 /sys.

"""

import os
from pathlib import Path

DEFAULT_VOLTAGE = 0.95  # volts

def _read_value(path: str):
    """Read numeric value from sysfs, return None if missing."""
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None

def get_cpu_freq(core: int = 0) -> float:
    """Return current CPU frequency (MHz)."""
    val = _read_value(f"/sys/devices/system/cpu/cpu{core}/cpufreq/scaling_cur_freq")
    return (val / 1000.0) if val else 0.0

def get_cpu_voltage(core: int = 0) -> float:
    """Return CPU voltage (V)."""
    paths = [
        "/sys/class/regulator/regulator.0/microvolts",
        "/sys/class/regulator/regulator.1/microvolts",
    ]
    for p in paths:
        val = _read_value(p)
        if val:
            return val / 1e6
    return DEFAULT_VOLTAGE

def get_cpu_temp() -> float:
    """Return SoC temperature (°C)."""
    val = _read_value("/sys/class/thermal/thermal_zone0/temp")
    return (val / 1000.0) if val else 0.0

def read_all_cores():
    """Return dict of {core: {V, f, T}}."""
    cpu_dir = Path("/sys/devices/system/cpu/")
    cores = [int(d.name[3:]) for d in cpu_dir.iterdir() if d.name.startswith("cpu") and d.name[3:].isdigit()]
    temp = get_cpu_temp()
    return {core: {"V": get_cpu_voltage(core), "f": get_cpu_freq(core), "T": temp} for core in cores}

if __name__ == "__main__":
    print("akxOS v0.2.1 — sys_telemetry test\n")
    for c, v in read_all_cores().items():
        print(f"Core {c}: V={v['V']:.2f} V, f={v['f']:.0f} MHz, T={v['T']:.1f} °C")
