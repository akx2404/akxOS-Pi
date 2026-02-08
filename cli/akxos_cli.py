#!/usr/bin/env python3
"""
akxOS CLI v0.2.1
----------------
Now shows live hardware telemetry (V, f, T) from sys_telemetry.py
and integrates with the updated power_model.py.
"""

import argparse
import os
import time
from datetime import datetime
from process_info import get_process_stats
from power_model import compute_pdyn, compute_pleak, get_log_file
from sys_telemetry import get_cpu_voltage, get_cpu_freq, get_cpu_temp


# ---------- Visual Styling ----------
def print_banner():
    print("\033[96m" + "=" * 75)
    print("akxOS v0.2.1 — Hardware-Aware Power Monitor (Telemetry Mode)")
    print("=" * 75 + "\033[0m\n")


def clear_screen():
    os.system("clear" if os.name == "posix" else "cls")


# ---------- Display: Process + Power ----------
def display_ps():
    processes = get_process_stats()
    print(f"{'PID':<8}{'Name':<25}{'CPU%':<10}{'Mem(KB)':<10}")
    print("-" * 60)
    for p in sorted(processes, key=lambda x: x['cpu'], reverse=True)[:15]:
        print(f"{p['pid']:<8}{p['name']:<25}{p['cpu']:<10.2f}{p['mem']:<10}")


def display_power():
    """Print per-process power with live voltage/frequency/temperature."""
    processes = get_process_stats()
    V = get_cpu_voltage(0)
    f = get_cpu_freq(0)
    T = get_cpu_temp()

    print(f"{'PID':<8}{'Name':<20}{'CPU%':<8}{'Mem(KB)':<9}{'V(V)':<7}{'f(MHz)':<9}{'T(°C)':<8}{'Pdyn(mW)':<12}{'Pleak(mW)':<12}{'Ptotal(mW)':<12}")
    print("-" * 110)

    for p in sorted(processes, key=lambda x: x['cpu'], reverse=True)[:10]:
        pdyn = compute_pdyn(p['cpu'])
        pleak = compute_pleak(p['mem'])
        ptotal = pdyn + pleak
        print(f"{p['pid']:<8}{p['name']:<20}{p['cpu']:<8.2f}{p['mem']:<9}{V:<7.2f}{f:<9.0f}{T:<8.1f}{pdyn:<12.2f}{pleak:<12.2f}{ptotal:<12.2f}")


# ---------- Refresh Mode ----------
def refresh_mode(display_func, interval=1.0):
    try:
        while True:
            clear_screen()
            print_banner()
            print(f"⏱️  Live Mode — Interval: {interval:.1f}s — {datetime.now().strftime('%H:%M:%S')}\n")
            display_func()
            print("\nPress Ctrl+C to stop...")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[akxOS] Live mode stopped.")


# ---------- Logging ----------
def cmd_log(interval, duration):
    """Log telemetry-aware power data continuously."""
    log_file = get_log_file()
    print_banner()
    print(f"[akxOS] Logging started → {log_file}")

    end_time = time.time() + duration
    with open(log_file, "a") as f:
        f.write("Timestamp,PID,Name,CPU%,Mem(KB),V(V),f(MHz),T(°C),Pdyn(mW),Pleak(mW),Ptotal(mW)\n")
        while time.time() < end_time:
            V = get_cpu_voltage(0)
            f_hz = get_cpu_freq(0)
            T = get_cpu_temp()
            processes = get_process_stats()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for p in processes:
                pdyn = compute_pdyn(p['cpu'])
                pleak = compute_pleak(p['mem'])
                ptotal = pdyn + pleak
                f.write(f"{timestamp},{p['pid']},{p['name']},{p['cpu']:.2f},{p['mem']},{V:.2f},{f_hz:.0f},{T:.1f},{pdyn:.3f},{pleak:.3f},{ptotal:.3f}\n")
            time.sleep(interval)

    print(f"[akxOS] Logging completed → {log_file}")


# ---------- CLI Entry ----------
def main():
    parser = argparse.ArgumentParser(description="akxOS unified CLI")
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    ps_parser = subparsers.add_parser("ps", help="Show process table")
    ps_parser.add_argument("-r", "--refresh", action="store_true", help="Continuous refresh")
    ps_parser.add_argument("--interval", type=float, default=1.0)

    power_parser = subparsers.add_parser("power", help="Show power table with telemetry")
    power_parser.add_argument("-r", "--refresh", action="store_true", help="Continuous refresh")
    power_parser.add_argument("--interval", type=float, default=1.0)

    log_parser = subparsers.add_parser("log", help="Continuous logging")
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
