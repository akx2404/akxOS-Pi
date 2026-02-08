#!/usr/bin/env python3
"""
akxOS CLI
---------
User-facing interface for akxOS functionality.

"""

import argparse
import os
import time
from datetime import datetime

from proc.process_info import get_process_stats
from power.power_state import get_power_states
from log.logger import PowerLogger


# ---------- Visual Styling ----------

def print_banner():
    print("\033[96m" + "=" * 75)
    print("akxOS — Power-Aware Process Monitor")
    print("=" * 75 + "\033[0m\n")


def clear_screen():
    os.system("clear" if os.name == "posix" else "cls")


# ---------- Display: Process Table ----------

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


# ---------- Display: Power Table ----------

def display_power():
    power_states = get_power_states(core_id=0)

    print(
        f"{'PID':<8}{'Name':<20}{'CPU%':<8}{'Mem(KB)':<9}"
        f"{'V(V)':<7}{'f(MHz)':<9}{'T(°C)':<8}"
        f"{'Pdyn(mW)':<12}{'Pleak(mW)':<12}{'Ptotal(mW)':<12}"
    )
    print("-" * 115)

    for ps in sorted(power_states, key=lambda x: x["cpu_percent"], reverse=True)[:10]:
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


# ---------- Refresh Mode ----------

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


# ---------- Logging ----------

def cmd_log(interval, duration):
    logger = PowerLogger(interval=interval, duration=duration)
    logger.run()


# ---------- CLI Entry ----------

def main():
    parser = argparse.ArgumentParser(description="akxOS unified CLI")
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    ps_parser = subparsers.add_parser("ps", help="Show process table")
    ps_parser.add_argument("-r", "--refresh", action="store_true")
    ps_parser.add_argument("--interval", type=float, default=1.0)

    power_parser = subparsers.add_parser("power", help="Show power table")
    power_parser.add_argument("-r", "--refresh", action="store_true")
    power_parser.add_argument("--interval", type=float, default=1.0)

    log_parser = subparsers.add_parser("log", help="Log power over time")
    log_parser.add_argument("--interval", type=float, default=1.0)
    log_parser.add_argument("--duration", type=float, default=10.0)

    args = parser.parse_args()

    if args.command == "ps":
        refresh_mode(display_ps, args.interval) if args.refresh else display_ps()

    elif args.command == "power":
        refresh_mode(display_power, args.interval) if args.refresh else display_power()

    elif args.command == "log":
        cmd_log(args.interval, args.duration)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
