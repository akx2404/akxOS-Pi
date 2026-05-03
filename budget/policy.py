#!/usr/bin/env python3
"""
akxOS Budget Policy
-------------------
Defines declarative power budget policies.

"""

from dataclasses import dataclass, field
from typing import Literal


EnforcementMode = Literal["sched_weight", "dvfs_cap", "cpu_quota"]

WINDOW_SIZE_MIN = 1
WINDOW_SIZE_MAX = 100


@dataclass
class BudgetPolicy:
    """
    Represents a power budget policy for a single process.
    """

    pid:            int
    power_limit_mw: float
    mode:           EnforcementMode

    window_size:     int  = 10   # Raised default from 5 → 10 for smoother feedback
    violation_count: int  = 0
    active:          bool = True

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def __post_init__(self):
        if self.pid <= 0:
            raise ValueError("PID must be positive.")

        if self.power_limit_mw <= 0:
            raise ValueError("Power limit must be positive.")

        if self.mode not in ("sched_weight", "dvfs_cap", "cpu_quota"):
            raise ValueError(f"Invalid enforcement mode: {self.mode!r}")

        if not (WINDOW_SIZE_MIN <= self.window_size <= WINDOW_SIZE_MAX):
            raise ValueError(
                f"window_size must be between {WINDOW_SIZE_MIN} "
                f"and {WINDOW_SIZE_MAX}, got {self.window_size}."
            )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def __str__(self):
        return (
            f"PID={self.pid} | "
            f"Limit={self.power_limit_mw:.2f} mW | "
            f"Mode={self.mode} | "
            f"Window={self.window_size} | "
            f"Violations={self.violation_count} | "
            f"Active={self.active}"
        )
