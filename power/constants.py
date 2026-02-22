# akxos/power/constants.py
"""
akxOS Power Model Constants
---------------------------

This module defines parameters for the akxOS relative power model.

Power is modeled as:
    P_total = P_dyn + P_leak

Dynamic power follows classical CMOS switching theory:
    P_dyn ∝ α · C_eff · V^2 · f

Leakage power is modeled using a compact polynomial-exponential
macro-model inspired by IEEE TCAD leakage abstractions
(Helms et al., TCAD 2018).

NOTE:
This is a relative system-level model for OS power control,
not a transistor-accurate BSIM implementation.
"""

# ----------------------------------------------------------
# Dynamic Power Parameters
# ----------------------------------------------------------

# Switching activity factor (typical system workload range: 0.1–0.5)
ALPHA = 0.3

# Effective switching capacitance (abstracted workload-level value)
C_EFF = 1.2e-9


# ----------------------------------------------------------
# Leakage Power Base Scaling
# ----------------------------------------------------------

# Base proportionality constant for leakage abstraction
K_LEAK = 5e-9


# ----------------------------------------------------------
# Leakage Voltage Dependence Coefficients
# ----------------------------------------------------------

# First-order voltage dependency (captures DIBL-like behavior)
LEAK_LINEAR_A = 0.002

# Second-order voltage growth term
LEAK_QUAD_B = 0.005

# Nominal operating voltage used for normalization
V_NOM = 0.90

# Exponential sensitivity factor (subthreshold-like behavior)
LEAK_EXP_B = 2.0
