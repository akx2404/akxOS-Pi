#!/usr/bin/env python3
"""
akxOS Power Model
-----------------
Pure power modeling equations.

"""

import math

from power.constants import (
    ALPHA,
    C_EFF,
    LEAK_LINEAR_A,
    LEAK_QUAD_B,
    LEAK_EXP_B,
    V_NOM,
)


def compute_dynamic_power(voltage_v: float,
                          freq_hz: float,
                          activity: float) -> float:
    """
    Compute dynamic power in milliwatts.

    P_dyn = α · C_eff · V² · f · activity

    Parameters
    ----------
    voltage_v : float
        Supply voltage in Volts
    freq_hz : float
        Clock frequency in Hertz
    activity : float
        Normalized activity factor (0.0–1.0)

    Returns
    -------
    float
        Dynamic power in milliwatts
    """
    p_dyn_w = ALPHA * C_EFF * (voltage_v ** 2) * freq_hz * activity
    return p_dyn_w * 1e3  # W → mW


def compute_leakage_power(mem_kb: float,
                          voltage_v: float,
                          model: str) -> float:
    """
    Compute leakage power in milliwatts.

    Parameters
    ----------
    mem_kb : float
        Process resident memory in KB
    voltage_v : float
        Supply voltage in Volts
    model : str
        One of: 'linear', 'quadratic', 'exponential'

    Returns
    -------
    float
        Leakage power in milliwatts
    """
    M = max(mem_kb / 1024.0, 0.001)  # Normalize to MB; floor to avoid zero
    V = voltage_v

    if model == "linear":
        return LEAK_LINEAR_A * M * V

    elif model == "quadratic":
        return (
            LEAK_LINEAR_A * M * V +
            LEAK_QUAD_B  * M * (V - V_NOM) ** 2
        )

    elif model == "exponential":
        return (
            LEAK_LINEAR_A * M *
            math.exp(LEAK_EXP_B * (V - V_NOM))
        )

    else:
        raise ValueError(f"Unknown leakage model: {model!r}")
