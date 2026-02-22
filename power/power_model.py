#!/usr/bin/env python3
"""
akxOS Power Model
-----------------
Pure power modeling equations.

"""

from power.constants import (
    ALPHA,
    C_EFF,
    K_LEAK,
    LEAK_LINEAR_A,
    LEAK_QUAD_A,
    LEAK_QUAD_B,
)


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
                          voltage_v: float,
                          model: str = "linear") -> float:
    """
    Compute leakage power in milliwatts.

    Models:
        linear     : K_LEAK * mem_kb * voltage
        quadratic  : a*(mem_kb*V) + b*(mem_kb*V)^2

    Parameters
    ----------
    mem_kb : int
        Resident memory in kilobytes
    voltage_v : float
        Supply voltage in Volts
    model : str
        Leakage model ("linear" or "quadratic")

    Returns
    -------
    float
        Leakage power in milliwatts
    """

    if model == "linear":
        return a * M * V

    elif model == "quadratic":
        # tuned quadratic (centered around nominal voltage)
        return a * M * V + b_quad * M * (V - 0.9) ** 2

    elif model == "exponential":
        # exponential sensitivity
        return a * M * math.exp(b_exp * (V - V_nom))

    else:
        raise ValueError("Unknown leakage model")
