#!/usr/bin/env python3
"""
akxOS Budget Policy
-------------------
Defines declarative power budget policies.

"""

from dataclasses import dataclass
from typing import Literal


# Supported enforcement modes
EnforcementMode = Literal[
    "sched_weight",
    "dvfs_cap",
    "cpu_quota"
]


@dataclass
class BudgetPolicy:
    """
    Represents a power budget policy for a single process.
    """

    pid: int
    power_limit_mw: float
    mode: EnforcementMode

    window_size: int = 5
    violation_count: int = 0
    active: bool = True

    # -----------------------------------------------------
    # Validation
    # -----------------------------------------------------

    def __post_init__(self):

        if self.pid <= 0:
            raise ValueError("PID must be positive.")

        if self.power_limit_mw <= 0:
            raise ValueError("Power limit must be positive.")

        if self.mode not in ("sched_weight", "dvfs_cap", "cpu_quota"):
            raise ValueError(
                f"Invalid enforcement mode: {self.mode}"
            )

        if self.window_size < 1:
            raise ValueError("Window size must be >= 1.")

    # -----------------------------------------------------
    # Utility
    # -----------------------------------------------------

    def __str__(self):
        return (
            f"PID={self.pid} | "
            f"Limit={self.power_limit_mw:.2f} mW | "
            f"Mode={self.mode} | "
            f"Window={self.window_size} | "
            f"Violations={self.violation_count} | "
            f"Active={self.active}"
        )
