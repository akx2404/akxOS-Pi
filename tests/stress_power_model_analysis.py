import subprocess
import time
import csv
from datetime import datetime

from power.power_state import get_power_states

LOG_INTERVAL = 0.5


def run_experiment(mode_name: str,
                   output_csv: str,
                   core_id: int = 0):

    print(f"\n=== Running Mode: {mode_name} ===")

    proc = subprocess.Popen(["python3", "fixed_workload.py"])
    pid = proc.pid

    print(f"Workload PID: {pid}")

    samples = []

    start_time = time.time()
    last_sample_time = start_time

    # Give 1 second warmup for stable CPU% measurement
    time.sleep(1)

    while proc.poll() is None:
        current_time = time.time()
        delta_t = current_time - last_sample_time

        states = get_power_states(core_id=core_id)

        stress_state = next(
            (p for p in states if p["pid"] == pid),
            None
        )

        if stress_state:
            samples.append({
                "time": current_time - start_time,
                "delta_t": delta_t,
                "cpu_percent": stress_state["cpu_percent"],
                "freq_hz": stress_state["freq_hz"],
                "temp_c": stress_state["temperature_c"],
                "p_dyn_mw": stress_state["p_dyn_mw"],
                "p_leak_mw": stress_state["p_leak_mw"],
                "p_total_mw": stress_state["p_total_mw"],
            })

        last_sample_time = current_time
        time.sleep(LOG_INTERVAL)

    end_time = time.time()
    runtime = end_time - start_time

    print(f"Runtime: {runtime:.2f} sec")

    # --- Energy Integration using real delta_t ---
    energy = sum(s["p_total_mw"] * s["delta_t"] for s in samples)
    avg_power = energy / runtime if runtime > 0 else 0

    print(f"Energy Proxy (mW·s): {energy:.2f}")
    print(f"Average Power (mW): {avg_power:.2f}")

    # --- Save CSV ---
    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "time_s",
            "delta_t",
            "cpu_percent",
            "freq_hz",
            "temp_c",
            "p_dyn_mw",
            "p_leak_mw",
            "p_total_mw",
        ])
        for s in samples:
            writer.writerow([
                s["time"],
                s["delta_t"],
                s["cpu_percent"],
                s["freq_hz"],
                s["temp_c"],
                s["p_dyn_mw"],
                s["p_leak_mw"],
                s["p_total_mw"],
            ])

    print(f"Saved log to {output_csv}")

    return runtime, energy, avg_power
