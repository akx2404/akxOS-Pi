import subprocess
import time
import csv
import os
from datetime import datetime

from power_state import get_power_states  # your file above

LOG_INTERVAL = 0.5  # seconds


def run_experiment(mode_name: str,
                   output_csv: str,
                   core_id: int = 0):
    """
    Run one fixed-workload experiment and log power until completion.
    """

    print(f"\n=== Running Mode: {mode_name} ===")

    # Start workload
    stress = subprocess.Popen([
        "stress-ng",
        "--cpu", "1",
        "--cpu-method", "prime",
        "--cpu-ops", "500000"
    ])

    pid = stress.pid
    print(f"Stress PID: {pid}")

    samples = []

    start_time = time.time()

    while stress.poll() is None:
        states = get_power_states(core_id=core_id)

        # Find stress process entry
        stress_state = next(
            (p for p in states if p["pid"] == pid),
            None
        )

        if stress_state:
            timestamp = time.time() - start_time
            samples.append([
                timestamp,
                stress_state["cpu_percent"],
                stress_state["freq_hz"],
                stress_state["temperature_c"],
                stress_state["p_dyn_mw"],
                stress_state["p_leak_mw"],
                stress_state["p_total_mw"],
            ])

        time.sleep(LOG_INTERVAL)

    end_time = time.time()
    runtime = end_time - start_time

    print(f"Runtime: {runtime:.2f} sec")

    # --- Compute Energy ---
    energy = sum(row[6] * LOG_INTERVAL for row in samples)  # p_total_mw
    print(f"Energy Proxy (mW·s): {energy:.2f}")

    # --- Save CSV ---
    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "time_s",
            "cpu_percent",
            "freq_hz",
            "temp_c",
            "p_dyn_mw",
            "p_leak_mw",
            "p_total_mw",
        ])
        writer.writerows(samples)

    print(f"Saved log to {output_csv}")

    return runtime, energy


if __name__ == "__main__":

    mode = "baseline"  # change per run
    output_file = f"{mode}_{datetime.now().strftime('%H%M%S')}.csv"

    run_experiment(mode_name=mode, output_csv=output_file)
