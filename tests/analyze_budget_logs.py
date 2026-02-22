#!/usr/bin/env python3
"""
akxOS Budget Log Analyzer (PID-Specific)
----------------------------------------
Analyzes power behaviour of a specific PID
between baseline and budgeted logs.

Outputs:
- Avg power
- Peak power
- Overshoot %
- Settling time
- Steady-state error
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path


# ==============================
# CONFIG
# ==============================

LOG_DIR = Path("logs")

BASELINE_FILE = LOG_DIR / "power_log_1_window_size_10.csv"
BUDGET_FILE = LOG_DIR / "power_log_2_window_size_10.csv"

TARGET_PID = 1158
BUDGET_LIMIT_MW = 80
SETTLING_TOLERANCE = 0.05  # ±5% band


# ==============================
# Helper Functions
# ==============================

def load_pid_power(file_path, pid):
    df = pd.read_csv(file_path)

    if df.empty:
        raise ValueError(f"{file_path} is empty.")

    if "pid" not in df.columns:
        raise ValueError(f"'pid' column not found in {file_path}")

    if "p_total_mw" not in df.columns:
        raise ValueError(f"'p_total_mw' column not found in {file_path}")

    # Filter by PID
    df = df[df["pid"] == pid].copy()

    if df.empty:
        raise ValueError(f"No entries found for PID {pid} in {file_path}")

    # Detect time column
    time_col = None
    for col in df.columns:
        if "time" in col.lower():
            time_col = col
            break

    if time_col is None:
        raise ValueError(f"No time column found in {file_path}")

    # Normalize time
    if pd.api.types.is_numeric_dtype(df[time_col]):
        df["time"] = df[time_col] - df[time_col].iloc[0]
    else:
        df[time_col] = pd.to_datetime(df[time_col])
        df["time"] = (df[time_col] - df[time_col].iloc[0]).dt.total_seconds()

    df = df[["time", "p_total_mw"]]

    return df


def compute_metrics(df, budget=None):

    power = df["p_total_mw"]
    time = df["time"]

    avg_power = power.mean()
    peak_power = power.max()
    steady_state = power.tail(10).mean()

    overshoot = None
    settling_time = None
    steady_error = None

    if budget is not None:
        overshoot = ((peak_power - budget) / budget) * 100
        steady_error = abs(steady_state - budget)

        tol = SETTLING_TOLERANCE * budget

        within_band = np.where(np.abs(power - budget) <= tol)[0]
        if len(within_band) > 0:
            settling_time = time.iloc[within_band[0]]

    return {
        "avg": avg_power,
        "peak": peak_power,
        "steady": steady_state,
        "overshoot": overshoot,
        "settling_time": settling_time,
        "steady_error": steady_error,
    }


# ==============================
# Load Data
# ==============================

baseline_df = load_pid_power(BASELINE_FILE, TARGET_PID)
budget_df = load_pid_power(BUDGET_FILE, TARGET_PID)

baseline_metrics = compute_metrics(baseline_df)
budget_metrics = compute_metrics(budget_df, BUDGET_LIMIT_MW)


# ==============================
# Print Results
# ==============================

print("\n===== akxOS PID Budget Analysis =====\n")

print(f"Target PID: {TARGET_PID}\n")

print("Baseline:")
print(f"  Avg Power: {baseline_metrics['avg']:.2f} mW")
print(f"  Peak Power: {baseline_metrics['peak']:.2f} mW")
print(f"  Steady-State: {baseline_metrics['steady']:.2f} mW")

print("\nBudgeted:")
print(f"  Avg Power: {budget_metrics['avg']:.2f} mW")
print(f"  Peak Power: {budget_metrics['peak']:.2f} mW")
print(f"  Overshoot: {budget_metrics['overshoot']:.2f} %")
print(f"  Settling Time: {budget_metrics['settling_time']}")
print(f"  Steady-State Error: {budget_metrics['steady_error']:.2f} mW")


# ==============================
# Plot
# ==============================

plt.figure(figsize=(10,6))

plt.plot(baseline_df["time"], baseline_df["p_total_mw"],
         label="Baseline (PID)")

plt.plot(budget_df["time"], budget_df["p_total_mw"],
         label="Budgeted (PID)")

plt.axhline(BUDGET_LIMIT_MW, linestyle="--", label="Budget (80 mW)")

plt.xlabel("Time (s)")
plt.ylabel("PID Power (mW)")
plt.title(f"PID {TARGET_PID} Budget Controller Analysis")
plt.legend()
plt.grid(True)

plt.show()
