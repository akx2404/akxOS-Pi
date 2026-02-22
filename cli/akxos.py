#!/usr/bin/env python3
"""
akxOS CLI
---------
User-facing interface for akxOS functionality.
Includes power monitoring, logging, and power budgeting.

"""

import argparse
import os
import time
from datetime import datetime

from proc.process_info import get_process_stats
from power.power_state import get_power_states
from power.power_model import compute_leakage_power
from log.logger import PowerLogger

from budget.budget_engine import BudgetEngine
from budget.policy import BudgetPolicy

# --------------------------------------------------
# Global Budget Engine (session-scoped)
# --------------------------------------------------

budget_engine = BudgetEngine(interval=1.0)


# --------------------------------------------------
# Visual Styling
# --------------------------------------------------

def print_banner():
    print("\033[96m" + "=" * 75)
    print("akxOS — Power-Aware Process Monitor")
    print("=" * 75 + "\033[0m\n")


def clear_screen():
    os.system("clear" if os.name == "posix" else "cls")


# --------------------------------------------------
# Process Table
# --------------------------------------------------

def display_ps():
    processes = get_process_stats()

    print(f"{'PID':<8}{'Name':<25}{'CPU%':<10}{'Mem(KB)':<10}")
    print("-" * 60)

    for p in sorted(processes, key=lambda x: x["cpu"], reverse=True)[:15]:
        print(
            f"{p['pid']:<8}"
            f"{p['name']:<25}"
            f"{p['cpu']:<10.2f}"
            f"{p['mem']:<10}"
        )


# --------------------------------------------------
# Power Table
# --------------------------------------------------

def display_power(leak_model="linear", compare=False):
    """
    Display power table.

    Parameters
    ----------
    leak_model : str
        'linear' or 'quadratic'
    compare : bool
        If True, compares both leakage models side-by-side
    """

    base_states = get_power_states(core_id=0,
                                   leak_model="linear")

    # Sort once for consistency
    base_states = sorted(
        base_states,
        key=lambda x: x["cpu_percent"],
        reverse=True
    )[:10]

    if compare:

        print(
            f"{'PID':<8}{'Name':<20}"
            f"{'Linear(mW)':<15}{'Quad(mW)':<15}"
            f"{'%Diff':<10}"
        )
        print("-" * 70)

        for ps in base_states:

            # Compute quadratic leakage using same telemetry snapshot
            quad_leak = compute_leakage_power(
                mem_kb=ps["mem_kb"],
                voltage_v=ps["voltage_v"],
                model="quadratic",
            )

            linear_leak = ps["p_leak_mw"]

            diff = (
                (quad_leak - linear_leak) /
                max(linear_leak, 1e-6)
            ) * 100

            print(
                f"{ps['pid']:<8}"
                f"{ps['name']:<20}"
                f"{linear_leak:<15.2f}"
                f"{quad_leak:<15.2f}"
                f"{diff:<10.2f}"
            )

        return

    # Recompute if user selected quadratic
    if leak_model == "quadratic":
        for ps in base_states:
            ps["p_leak_mw"] = compute_leakage_power(
                mem_kb=ps["mem_kb"],
                voltage_v=ps["voltage_v"],
                model="quadratic",
            )
            ps["p_total_mw"] = ps["p_dyn_mw"] + ps["p_leak_mw"]

    print(
        f"{'PID':<8}{'Name':<20}{'CPU%':<8}{'Mem(KB)':<9}"
        f"{'V(V)':<7}{'f(MHz)':<9}{'T(°C)':<8}"
        f"{'Pdyn(mW)':<12}{'Pleak(mW)':<12}{'Ptotal(mW)':<12}"
    )
    print("-" * 115)

    for ps in base_states:
        print(
            f"{ps['pid']:<8}"
            f"{ps['name']:<20}"
            f"{ps['cpu_percent']:<8.2f}"
            f"{ps['mem_kb']:<9}"
            f"{ps['voltage_v']:<7.2f}"
            f"{ps['freq_hz'] / 1e6:<9.0f}"
            f"{ps['temperature_c']:<8.1f}"
            f"{ps['p_dyn_mw']:<12.2f}"
            f"{ps['p_leak_mw']:<12.2f}"
            f"{ps['p_total_mw']:<12.2f}"
        )


# --------------------------------------------------
# Refresh Mode
# --------------------------------------------------

def refresh_mode(display_func, interval=1.0):
    try:
        while True:
            clear_screen()
            print_banner()
            print(
                f"⏱️  Live Mode — Interval: {interval:.1f}s — "
                f"{datetime.now().strftime('%H:%M:%S')}\n"
            )
            display_func()
            print("\nPress Ctrl+C to stop...")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[akxOS] Live mode stopped.")


# --------------------------------------------------
# Logging
# --------------------------------------------------

def cmd_log(interval, duration):
    logger = PowerLogger(interval=interval, duration=duration)
    logger.run()


# --------------------------------------------------
# CLI Entry
# --------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="akxOS unified CLI")
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # ---------------- ps ----------------
    ps_parser = subparsers.add_parser("ps", help="Show process table")
    ps_parser.add_argument("-r", "--refresh", action="store_true")
    ps_parser.add_argument("--interval", type=float, default=1.0)

    # ---------------- power ----------------
    power_parser = subparsers.add_parser("power", help="Show power table")
    power_parser.add_argument("-r", "--refresh", action="store_true")
    power_parser.add_argument("--interval", type=float, default=1.0)
    power_parser.add_argument(
    "--leak-model",
    choices=["linear", "quadratic"],
    default="linear",
    help="Select leakage power model")
    power_parser.add_argument(
    "--compare-models",
    action="store_true",
    help="Compare linear and quadratic leakage models" )

    # ---------------- log ----------------
    log_parser = subparsers.add_parser("log", help="Log power over time")
    log_parser.add_argument("--interval", type=float, default=1.0)
    log_parser.add_argument("--duration", type=float, default=10.0)

    # ---------------- budget ----------------
    budget_parser = subparsers.add_parser(
        "budget", help="Manage per-process power budgets"
    )
    budget_sub = budget_parser.add_subparsers(dest="budget_cmd")

    # budget add
    add_parser = budget_sub.add_parser("add", help="Add a power budget")
    add_parser.add_argument("pid", type=int, help="Process ID")
    add_parser.add_argument("limit_mw", type=float, help="Power limit in mW")
    add_parser.add_argument(
        "--mode",
        choices=["sched_weight", "dvfs_cap", "cpu_quota"],
        default="sched_weight",
        help="Enforcement mode",
    )

    # budget list
    budget_sub.add_parser("list", help="List active budgets")

    # budget remove
    remove_parser = budget_sub.add_parser("remove", help="Remove a power budget")
    remove_parser.add_argument("pid", type=int, help="Process ID")

    # budget run
    run_parser = budget_sub.add_parser("run", help="Run budget enforcement engine")
    run_parser.add_argument("--duration", type=float, default=None)

    args = parser.parse_args()

    # ---------------- Dispatch ----------------

    if args.command == "ps":
        refresh_mode(display_ps, args.interval) if args.refresh else display_ps()

    elif args.command == "power":
      if args.refresh:
          refresh_mode(
              lambda: display_power(
                  leak_model=args.leak_model,
                  compare=args.compare_models
              ),
              args.interval
          )
      else:
          display_power(
              leak_model=args.leak_model,
              compare=args.compare_models
          )

    elif args.command == "log":
        cmd_log(args.interval, args.duration)

    elif args.command == "budget":

        if args.budget_cmd == "add":
            policy = BudgetPolicy(
                pid=args.pid,
                power_limit_mw=args.limit_mw,
                mode=args.mode,
            )
            budget_engine.add_policy(policy)

        elif args.budget_cmd == "list":
            budget_engine.list_policies()

        elif args.budget_cmd == "remove":
            budget_engine.remove_policy(args.pid)

        elif args.budget_cmd == "run":
            budget_engine.run(duration=args.duration)

        else:
            budget_parser.print_help()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
