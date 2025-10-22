#!/usr/bin/env python3
"""
akxOS v0.2.1 — power_model.py
Computes per-core dynamic power using live telemetry (V, f) from sys_telemetry.py
"""

from scripts.sys_telemetry import get_cpu_voltage, get_cpu_freq

# Constants (will later be per-process calibrated)
ALPHA = 0.3          # switching activity
C_EFF = 1.2e-9       # effective capacitance per core (F)
SCALING_FACTOR = 1e3 # convert W → mW

def compute_dynamic_power(core_id=0):
    """
    Compute Pdyn per core using live telemetry.
    Pdyn = α * C * V^2 * f
    Returns power in milliwatts.
    """
    V = get_cpu_voltage(core_id)
    f = get_cpu_freq(core_id) * 1e6  # MHz → Hz
    P = ALPHA * C_EFF * (V ** 2) * f
    return P * SCALING_FACTOR  # mW

def compute_system_power():
    """Compute total dynamic power across all cores."""
    import scripts.sys_telemetry as st
    telemetry = st.read_all_cores()
    total = 0.0
    core_data = {}
    for core, vals in telemetry.items():
        p = ALPHA * C_EFF * (vals["V"] ** 2) * (vals["f"] * 1e6)
        p_mw = p * SCALING_FACTOR
        core_data[core] = {**vals, "Pdyn": p_mw}
        total += p_mw
    return core_data, total

if __name__ == "__main__":
    print("akxOS v0.2.1 — Dynamic Power Test\n")
    data, total = compute_system_power()
    for c, v in data.items():
        print(f"Core {c}: V={v['V']:.2f}V, f={v['f']:.0f}MHz, T={v['T']:.1f}°C → Pdyn={v['Pdyn']:.2f} mW")
    print(f"\nTotal Dynamic Power ≈ {total:.2f} mW")
