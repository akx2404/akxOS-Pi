#!/usr/bin/env python3
"""
akxOS Power Model
-----------------
Pure power modeling equations.

"""

from power.constants import ALPHA, C_EFF, K_LEAK


def compute_dynamic_power(voltage_v: float,
                          freq_hz: float,
                          activity: float) -> float:
    """
    Compute dynamic power in milliwatts.

    P_dyn depends on C_eff * V² * f * activity

    Parameters
    ----------
    voltage_v : float
        Supply voltage in Volts
    freq_hz : float
        Clock frequency in Hertz
    activity : float
        Normalized activity factor (0.0-1.0)

    Returns
    -------
    float
        Dynamic power in milliwatts
    """
    p_dyn_w = ALPHA * C_EFF * (voltage_v ** 2) * freq_hz * activity
    return p_dyn_w * 1e3  # W → mW


def compute_leakage_power(mem_kb: int,
                          voltage_v: float) -> float:
    """
    Compute leakage power in milliwatts.

    P_leak depends on memory footprint * voltage

    Parameters
    ----------
    mem_kb : int
        Resident memory in kilobytes
    voltage_v : float
        Supply voltage in Volts

    Returns
    -------
    float
        Leakage power in milliwatts
    """
    p_leak_w = K_LEAK * mem_kb * voltage_v
    return p_leak_w * 1e3  # W → mW
