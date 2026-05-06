#!/usr/bin/env python3
"""
akxOS Bursty Workload
---------------------
Alternates between a CPU-intensive compute burst and sleep.
Arguments: [burst_ms] [sleep_ms]   (default 100 100)

This simulates a realistic workload whose utilisation oscillates rather
than running at a constant 100%, exercising the PI controller's
conditional integration band.
"""

import math
import sys
import time

BURST_MS = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0
SLEEP_MS = float(sys.argv[2]) if len(sys.argv) > 2 else 100.0

BURST_S = BURST_MS / 1000.0
SLEEP_S = SLEEP_MS / 1000.0

# Pre-compute a work unit that keeps one CPU busy for ~1ms
_ITERS_PER_MS = 2000


def _spin(duration_s: float):
    """Busy-spin for approximately duration_s seconds."""
    deadline = time.monotonic() + duration_s
    i = 0
    while time.monotonic() < deadline:
        # Simple floating-point work — harder to optimise away than integer ops
        _ = math.sqrt(float(i & 0xFFFF) * 1.23456789)
        i += 1


while True:
    _spin(BURST_S)
    time.sleep(SLEEP_S)
