#!/usr/bin/env python3
"""
akxOS CLI v0.1.3
----------------
Unified command-line interface for akxOS monitoring tools.

Usage:
    akxos ps [-r] [--interval 1]
    akxos power [-r] [--interval 1]
    akxos log --interval 1 --duration 10
"""

import argparse
import os
import time
from datetime import datetime
from process_info import get_process_stats
from power_model import compute_pdyn, compute_pleak, get_log_file


# ---------- Visual Styling ----------
def print_banner():
    """Show a consistent banner for all commands."""
    print("\033[96m" + "=" * 60)
    print("🌀  akxOS v0.1.3 — Power-Aware Process Monitor")
    print("=" * 60 + "\033[0m\n")


def clear_screen():
    """Clears the terminal screen."""
    os.system("clear" if os.name == "posix" else "cls")


# ---------- Process & Power Display ----------
def display_ps():
    """Print process stats once."""
    processes = get_process_stats()
    print_banner()
    print(f"{'PID':<8}{'Name':<25}{'CPU%':<10}{'Mem(KB)':<10}")
    print("-" * 55)
    for p in sorted(processes, key=lambda x: x['cpu'], reverse=True)[:15]:
        print(f"{p['pid']:<8}{p['name']:<25}{p['cpu']:<10.2f}{p['mem']:<10}")


def display_power():
    """Print per-process power once."""
    processes = get_process_stats()
    print_banner()
    print(f"{'PID':<8}{'Name':<25}{'CPU%':<10}{'Mem(KB)':<10}{'Pdyn(mW)':<12}{'Pleak(mW)':<12}{'Ptotal(mW)':<12}")
    print("-" * 85)
    for p in sorted(processes, key=lambda x: x['cpu'], reverse=True)[:15]:
        pdyn = compute_pdyn(p['cpu'])
        pleak = compute_pleak(p['mem'])
        ptotal = pdyn + pleak
        print(f"{p['pid']:<8}{p['name']:<25}{p['cpu']:<10.2f}{p['mem']:<10}{pdyn:<12.3f}{pleak:<12.3f}{ptotal:<12.3f}")


# ---------- Refresh Mode ----------
def refresh_mode(display_func, interval=1.0):
    """Continuously refresh output like top."""
    try:
        while True:
            clear_screen()
            print_banner()
            print(f"⏱️  Live Refresh Mode (interval: {interval:.1f}s) — {datetime.now().strftime('%H:%M:%S')}\n")
            display_func()
            print("\nPress Ctrl+C to stop...")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[akxOS] Live mode stopped.")


# ---------- Logging ----------
def cmd_log(interval, duration):
    """Log power data continuously for given duration."""
    log_file = get_log_file()
    print_banner()
    print(f"[akxOS] Logging started → {log_file}")

    end_time = time.time() + duration
    with open(log_file, "a") as f:
        f.write("Timestamp,PID,Name,CPU%,Mem(KB),Pdyn(mW),Pleak(mW),Ptotal(mW)\n")
        while time.time() < end_time:
            processes = get_process_stats()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for p in processes:
                pdyn = compute_pdyn(p['cpu'])
                pleak = compute_pleak(p['mem'])
                ptotal = pdyn + pleak
                f.write(f"{timestamp},{p['pid']},{p['name']},{p['cpu']:.2f},{p['mem']},{pdyn:.3f},{pleak:.3f},{ptotal:.3f}\n")
            time.sleep(interval)

    print(f"[akxOS] Logging completed → {log_file}")


# ---------- CLI Entry ----------
def main():
    parser = argparse.ArgumentParser(description="akxOS unified CLI")
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # --- PS command ---
    ps_parser = subparsers.add_parser("ps", help="Show process table")
    ps_parser.add_argument("-r", "--refresh", action="store_true", help="Enable continuous refresh mode")
    ps_parser.add_argument("--interval", type=float, default=1.0, help="Refresh interval (seconds)")

    # --- Power command ---
    power_parser = subparsers.add_parser("power", help="Show power table")
    power_parser.add_argument("-r", "--refresh", action="store_true", help="Enable continuous refresh mode")
    power_parser.add_argument("--interval", type=float, default=1.0, help="Refresh interval (seconds)")

    # --- Log command ---
    log_parser = subparsers.add_parser("log", help="Continuous logging")
    log_parser.add_argument("--interval", type=float, default=1.0, help="Sampling interval in seconds")
    log_parser.add_argument("--duration", type=float, default=10.0, help="Total logging duration in seconds")

    args = parser.parse_args()

    if args.command == "ps":
        if args.refresh:
            refresh_mode(display_ps, args.interval)
        else:
            display_ps()

    elif args.command == "power":
        if args.refresh:
            refresh_mode(display_power, args.interval)
        else:
            display_power()

    elif args.command == "log":
        cmd_log(args.interval, args.duration)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
