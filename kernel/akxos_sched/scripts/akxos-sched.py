#!/usr/bin/env python3
"""
akxOS Scheduler Controller CLI
==============================

Wrapper around /proc/akxos_sched.

Commands:
  akxos-sched status
  akxos-sched set <pid> <budget_mw>
  akxos-sched clear <pid>
  akxos-sched reset <pid>
  akxos-sched watch [--interval 0.5]
  akxos-sched run --budget 80 --duration 30
  akxos-sched sweep --budgets 60 80 100 --duration 30

NO SUDO!!
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

PROC_PATH = Path("/proc/akxos_sched")
REPO_ROOT = Path.home() / "akxOS-Pi"
EXPERIMENT_SCRIPT = REPO_ROOT / "tests" / "experiment_settling.py"


def die(msg: str, code: int = 1):
    print(f"[akxOS][error] {msg}", file=sys.stderr)
    sys.exit(code)


def ensure_proc_exists():
    if not PROC_PATH.exists():
        die("/proc/akxos_sched not found. Load the driver first: ./scripts/install_sched_driver.sh")


def proc_read() -> str:
    ensure_proc_exists()
    return PROC_PATH.read_text()


def proc_write(cmd: str, fatal: bool = True) -> bool:
    ensure_proc_exists()
    result = subprocess.run(
        ["sudo", "sh", "-c", f"echo '{cmd}' > {PROC_PATH}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[akxOS][warn] /proc write failed: {cmd}")
        if result.stderr.strip():
            print(result.stderr.strip())
        if fatal:
            sys.exit(result.returncode)
        return False
    return True


def cmd_status(_args):
    print(proc_read(), end="")


def cmd_set(args):
    proc_write(f"set {args.pid} {args.budget_mw}")
    print(f"[akxOS] Set PID {args.pid} budget = {args.budget_mw} mW")
    print(proc_read(), end="")


def cmd_clear(args):
    proc_write(f"clear {args.pid}", fatal=False)
    print(f"[akxOS] Cleared PID {args.pid}")


def cmd_reset(args):
    proc_write(f"reset_ctrl {args.pid}", fatal=False)
    print(f"[akxOS] Reset controller state for PID {args.pid}")


def cmd_watch(args):
    ensure_proc_exists()
    try:
        while True:
            os.system("clear")
            print(proc_read(), end="")
            print(f"\nRefreshing every {args.interval}s. Ctrl+C to stop.")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[akxOS] watch stopped.")


def run_experiment(extra_args):
    if not EXPERIMENT_SCRIPT.exists():
        die(f"Experiment script not found: {EXPERIMENT_SCRIPT}")
    cmd = ["python3", str(EXPERIMENT_SCRIPT)] + extra_args
    print("[akxOS] Running:", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(REPO_ROOT))


def cmd_run(args):
    extra = ["--budget", str(args.budget), "--duration", str(args.duration)]
    if args.pid is not None:
        extra += ["--pid", str(args.pid)]
    if args.tol is not None:
        extra += ["--tol", str(args.tol)]
    sys.exit(run_experiment(extra))


def cmd_sweep(args):
    extra = ["--budgets"] + [str(b) for b in args.budgets] + ["--duration", str(args.duration)]
    if args.pid is not None:
        extra += ["--pid", str(args.pid)]
    if args.tol is not None:
        extra += ["--tol", str(args.tol)]
    sys.exit(run_experiment(extra))


def main():
    parser = argparse.ArgumentParser(description="akxOS scheduler power-budget CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status", help="Show /proc/akxos_sched")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("set", help="Set power budget for PID")
    p.add_argument("pid", type=int)
    p.add_argument("budget_mw", type=int)
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("clear", help="Clear budget for PID")
    p.add_argument("pid", type=int)
    p.set_defaults(func=cmd_clear)

    p = sub.add_parser("reset", help="Reset controller state for PID")
    p.add_argument("pid", type=int)
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("watch", help="Live watch /proc/akxos_sched")
    p.add_argument("--interval", type=float, default=0.5)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("run", help="Run single-budget experiment")
    p.add_argument("--pid", type=int, default=None)
    p.add_argument("--budget", type=int, default=80)
    p.add_argument("--duration", type=float, default=30)
    p.add_argument("--tol", type=float, default=None)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("sweep", help="Run multi-budget sweep experiment")
    p.add_argument("--pid", type=int, default=None)
    p.add_argument("--budgets", type=int, nargs="+", default=[60, 80, 100])
    p.add_argument("--duration", type=float, default=30)
    p.add_argument("--tol", type=float, default=None)
    p.set_defaults(func=cmd_sweep)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
