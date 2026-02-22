import subprocess
import time
import csv
from datetime import datetime

from power.power_state import get_power_states

LOG_INTERVAL = 0.5
BUDGET_VALUE = "80"


def apply_budget(pid, mode):
    subprocess.run([
        "sudo", "akxos", "budget", "add",
        str(pid),
        BUDGET_VALUE,
        "--mode", mode
    ])

def start_budget_runner():
    return subprocess.Popen(
        ["sudo", "akxos", "budget", "run"]
    )

def stop_budget_runner(proc):
    proc.terminate()
    proc.wait()

def reset_budget(pid):
    subprocess.run([
        "sudo", "akxos", "budget",
        "remove", str(pid)
    ])


def run_single(mode_name, core_id=0):

    print(f"\n=== Running Mode: {mode_name} ===")

    workload = subprocess.Popen(["python3", "tests/fixed_workload.py"])
    pid = workload.pid

    print(f"PID: {pid}")

    budget_runner = None

    if mode_name != "baseline":
        time.sleep(0.5)
        apply_budget(pid, mode_name)
        budget_runner = start_budget_runner()

    samples = []
    start_time = time.time()
    last_sample_time = start_time

    time.sleep(1)

    while workload.poll() is None:
        current_time = time.time()
        delta_t = current_time - last_sample_time

        states = get_power_states(core_id=core_id)
        state = next((p for p in states if p["pid"] == pid), None)

        if state:
            samples.append({
                "delta_t": delta_t,
                "p_total_mw": state["p_total_mw"]
            })

        last_sample_time = current_time
        time.sleep(LOG_INTERVAL)

    runtime = time.time() - start_time
    energy = sum(s["p_total_mw"] * s["delta_t"] for s in samples)

    print(f"Runtime: {runtime:.2f} sec")
    print(f"Energy: {energy:.2f}")

    if budget_runner:
        stop_budget_runner(budget_runner)

    print("Cooling down 30 sec...")
    time.sleep(30)

    return runtime, energy


if __name__ == "__main__":

    modes = ["baseline", "cpu_quota", "dvfs_cap"]

    results = []

    for mode in modes:
        runtime, energy = run_single(mode)
        results.append((mode, runtime, energy))

    print("\n=== Summary ===")
    for r in results:
        print(r)
