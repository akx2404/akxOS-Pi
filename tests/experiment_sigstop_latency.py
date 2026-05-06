#!/usr/bin/env python3
"""
akxOS Experiment Utilities
--------------------------
Shared helpers for all experiment scripts.
Centralises /proc I/O, budget commands, signal analysis,
DVFS control, and output helpers so individual scripts stay thin.
"""

import csv
import os
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

# ─────────────────────────────────────────────────────────────
# Constants (must mirror akxos_sched.h)
# ─────────────────────────────────────────────────────────────

PROC_PATH       = Path("/proc/akxos_sched")
OUTPUT_DIR      = Path("tests/results")
POLL_S          = 0.5

MODEL_CONST_FP  = 162           # P = (162 * freq_khz * util_permille) / 1e9
MODEL_DIVISOR   = 1_000_000_000
FALLBACK_FREQ   = 1_500_000     # kHz

CLK_TCK         = os.sysconf("SC_CLK_TCK")   # typically 100 on Linux


# ─────────────────────────────────────────────────────────────
# Driver verification
# ─────────────────────────────────────────────────────────────

def check_driver_or_exit():
    """Abort if akxos_sched.ko is not loaded."""
    if not PROC_PATH.exists():
        print(f"[error] {PROC_PATH} not found. Load akxos_sched.ko first.",
              file=sys.stderr)
        sys.exit(1)
    lines = PROC_PATH.read_text().splitlines()
    header = lines[0] if lines else ""
    if "akxOS power budget controller" not in header:
        print(f"[error] Unexpected /proc header: {header!r}", file=sys.stderr)
        sys.exit(1)


# ─────────────────────────────────────────────────────────────
# /proc interface
# ─────────────────────────────────────────────────────────────

def proc_write(cmd: str, fatal: bool = True, quiet: bool = False) -> bool:
    r = subprocess.run(
        ["sudo", "sh", "-c", f"echo '{cmd}' > {PROC_PATH}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        if not quiet:
            print(f"[warn] /proc write failed: {cmd!r}")
            if r.stderr.strip():
                print(r.stderr.strip())
        if fatal:
            sys.exit(r.returncode)
        return False
    return True


def _parse_row(parts: list) -> dict | None:
    """Parse one /proc line into a typed dict. Returns None on malformed input."""
    try:
        return dict(
            pid       = int(parts[0]),
            budget_mw = int(parts[1]),
            freq_khz  = int(parts[2]),
            util      = int(parts[3]),
            power_mw  = int(parts[4]),
            error_mw  = int(parts[5]),
            integral  = int(parts[6]),
            quota_pct = int(parts[7]),
            stop_ms   = int(parts[8]),
            throttled = int(parts[9]),
            viol      = int(parts[10]),
            energy_uj = int(parts[11]),
        )
    except (IndexError, ValueError):
        return None


def proc_read(pid: int) -> dict | None:
    """Read a single budgeted PID from /proc/akxos_sched."""
    try:
        text = PROC_PATH.read_text()
    except FileNotFoundError:
        return None
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0].isdigit() and int(parts[0]) == pid:
            return _parse_row(parts)
    return None


def proc_read_all() -> dict:
    """Return {pid: row_dict} for every active entry in /proc."""
    try:
        text = PROC_PATH.read_text()
    except FileNotFoundError:
        return {}
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0].isdigit():
            row = _parse_row(parts)
            if row:
                out[row["pid"]] = row
    return out


# ─────────────────────────────────────────────────────────────
# Budget commands
# ─────────────────────────────────────────────────────────────

def set_budget(pid: int, mw: int):
    proc_write(f"set {pid} {mw}", fatal=True)

def clear_budget(pid: int):
    proc_write(f"clear {pid}", fatal=False, quiet=True)

def reset_ctrl(pid: int):
    proc_write(f"reset_ctrl {pid}", fatal=False, quiet=True)

def set_energy_cap(pid: int, cap_uj: int):
    proc_write(f"ecap {pid} {cap_uj}", fatal=False)

def reset_energy(pid: int):
    proc_write(f"reset_energy {pid}", fatal=False, quiet=True)


# ─────────────────────────────────────────────────────────────
# Workload helpers
# ─────────────────────────────────────────────────────────────

def launch_workload(cmd: list | None = None) -> subprocess.Popen:
    if cmd is None:
        cmd = ["yes"]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def terminate_workload(proc: subprocess.Popen):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# ─────────────────────────────────────────────────────────────
# Process stat helpers
# ─────────────────────────────────────────────────────────────

def read_exec_ticks(pid: int) -> int | None:
    """Return utime + stime (clock ticks) for pid from /proc/<pid>/stat."""
    try:
        data = Path(f"/proc/{pid}/stat").read_text().split()
        return int(data[13]) + int(data[14])
    except Exception:
        return None


def pid_cpu_pct(pid: int, window_s: float = POLL_S) -> float | None:
    """Measure CPU utilisation of pid over window_s seconds (blocking)."""
    t0 = read_exec_ticks(pid)
    w0 = time.monotonic()
    time.sleep(window_s)
    t1 = read_exec_ticks(pid)
    w1 = time.monotonic()
    if t0 is None or t1 is None:
        return None
    delta_cpu  = t1 - t0
    delta_wall = (w1 - w0) * CLK_TCK
    return 100.0 * delta_cpu / max(delta_wall, 1)


# ─────────────────────────────────────────────────────────────
# Signal analysis
# ─────────────────────────────────────────────────────────────

def moving_average(vals: list, w: int) -> np.ndarray:
    buf, out = deque(maxlen=w), np.empty(len(vals))
    for i, x in enumerate(vals):
        buf.append(x)
        out[i] = sum(buf) / len(buf)
    return out


def settling_time(
    times:     np.ndarray,
    smoothed:  np.ndarray,
    budget:    float,
    tol_pct:   float = 5.0,
    min_s:     float = 3.0,
) -> float | None:
    tol = budget * tol_pct / 100.0
    n   = max(1, int(np.ceil(min_s / POLL_S)))
    for i in range(len(smoothed) - n + 1):
        if np.all(np.abs(smoothed[i:i+n] - budget) <= tol):
            return float(times[i])
    return None


def compute_metrics(times, raw, budget, smooth_w=10, tol_pct=5.0):
    """Return dict of standard control-loop metrics."""
    sm      = moving_average(raw.tolist(), smooth_w)
    n       = len(sm)
    trans   = sm[:max(1, n * 2 // 5)]
    ss      = sm[max(0, n * 7 // 10):]
    st      = settling_time(times, sm, budget, tol_pct)
    return dict(
        smoothed    = sm,
        settle_s    = st,
        overshoot   = max(0.0, float(np.max(trans)) - budget),
        ss_mean     = float(np.mean(ss)),
        ss_error    = float(abs(np.mean(ss) - budget)),
        ss_sigma    = float(np.std(ss)),
    )


# ─────────────────────────────────────────────────────────────
# DVFS helpers
# ─────────────────────────────────────────────────────────────

def get_available_freqs_khz() -> list:
    p = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_frequencies")
    if not p.exists():
        return []
    return sorted(int(f) for f in p.read_text().split())


def set_cpu_freq_khz(freq_khz: int):
    """Lock all CPUs to freq_khz via scaling_min/max_freq."""
    cpu_dir = Path("/sys/devices/system/cpu")
    for cpu in sorted(cpu_dir.glob("cpu[0-9]*")):
        for attr in ("scaling_min_freq", "scaling_max_freq"):
            p = cpu / "cpufreq" / attr
            if p.exists():
                subprocess.run(
                    ["sudo", "sh", "-c", f"echo {freq_khz} > {p}"],
                    capture_output=True,
                )
    time.sleep(0.6)   # wait for governor to settle


def reset_cpu_freq():
    """Restore hardware min/max limits."""
    cpu_dir = Path("/sys/devices/system/cpu")
    for cpu in sorted(cpu_dir.glob("cpu[0-9]*")):
        fd = cpu / "cpufreq"
        if not fd.exists():
            continue
        for attr, hw_attr in [
            ("scaling_min_freq", "cpuinfo_min_freq"),
            ("scaling_max_freq", "cpuinfo_max_freq"),
        ]:
            hw, sc = fd / hw_attr, fd / attr
            if hw.exists() and sc.exists():
                subprocess.run(
                    ["sudo", "sh", "-c", f"echo {hw.read_text().strip()} > {sc}"],
                    capture_output=True,
                )


# ─────────────────────────────────────────────────────────────
# Power model
# ─────────────────────────────────────────────────────────────

def model_predict_mw(freq_khz: int, util_permille: int = 1000) -> float:
    """Reproduce the kernel's linear power model."""
    return (MODEL_CONST_FP * freq_khz * util_permille) / MODEL_DIVISOR


# ─────────────────────────────────────────────────────────────
# dmesg helpers
# ─────────────────────────────────────────────────────────────

def dmesg_grep(pattern: str, n: int = 50) -> list:
    """Return recent dmesg lines containing pattern."""
    try:
        r = subprocess.run(["sudo", "dmesg", "--notime"],
                           capture_output=True, text=True)
        return [l for l in r.stdout.splitlines()[-400:] if pattern in l][-n:]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────────────────────

def ensure_output():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_csv(path: Path, fieldnames: list, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"CSV saved: {path}")


def print_header(title: str):
    bar = "═" * (len(title) + 4)
    print(f"\n{bar}")
    print(f"  {title}")
    print(f"{bar}\n")
