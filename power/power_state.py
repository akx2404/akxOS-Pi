#!/usr/bin/env python3
"""
akxOS Power State
-----------------
Composes per-process OS statistics with hardware telemetry
and power models to produce per-process power state.

"""

from typing import List, Dict
from datetime import datetime

from proc.process_info import get_process_stats
from telemetry.sys_telemetry import (
    get_cpu_voltage,
    get_cpu_freq,
    get_cpu_temp,
)
from power.power_model import (
    compute_dynamic_power,
    compute_leakage_power,
)


def get_power_states(core_id: int = 0) -> List[Dict]:
    """
    Compute power state for all active processes.

    Parameters
    ----------
    core_id : int
        CPU core index for telemetry sampling (default: 0)

    Returns
    -------
    List[Dict]
        List of power-annotated process states
    """
    # --- Sample hardware telemetry ONCE ---
    voltage_v = get_cpu_voltage(core_id)
    freq_hz = get_cpu_freq(core_id) * 1e6  # MHz → Hz
    temperature_c = get_cpu_temp()

    timestamp = datetime.now()

    power_states = []

    # --- Fetch per-process OS stats ---
    processes = get_process_stats()

    for proc in processes:
        cpu_activity = proc["cpu"] / 100.0

        p_dyn = compute_dynamic_power(
            voltage_v=voltage_v,
            freq_hz=freq_hz,
            activity=cpu_activity,
        )

        p_leak = compute_leakage_power(
            mem_kb=proc["mem"],
            voltage_v=voltage_v,
        )

        power_states.append({
            "timestamp": timestamp,
            "pid": proc["pid"],
            "name": proc["name"],
            "cpu_percent": proc["cpu"],
            "mem_kb": proc["mem"],
            "voltage_v": voltage_v,
            "freq_hz": freq_hz,
            "temperature_c": temperature_c,
            "p_dyn_mw": p_dyn,
            "p_leak_mw": p_leak,
            "p_total_mw": p_dyn + p_leak,
        })

    return power_states
