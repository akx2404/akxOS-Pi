#!/usr/bin/env python3
"""
akxOS Budget Policy
-------------------
Defines power budget policies for processes.

"""

from dataclasses import dataclass, field
from typing import Literal


EnforcementMode = Literal["soft", "med", "strong"]


@dataclass
class BudgetPolicy:
    """
    Power budget policy for a single process.
    """

    pid: int
    power_limit_mw: float
    mode: EnforcementMode = "soft"

    window_size: int = 5        # number of samples for averaging
    violation_count: int = 0    # total violations observed
    active: bool = True         # allow disabling without deletion

    def __post_init__(self):
        if self.power_limit_mw <= 0:
            raise ValueError("Power limit must be positive")

        if self.window_size < 1:
            raise ValueError("Window size must be >= 1")

        if self.mode not in ("soft", "med", "strong"):
            raise ValueError(f"Invalid enforcement mode: {self.mode}")

    def __str__(self):
        return (
            f"PID={self.pid} | "
            f"Limit={self.power_limit_mw} mW | "
            f"Mode={self.mode} | "
            f"Window={self.window_size} | "
            f"Violations={self.violation_count} | "
            f"Active={self.active}"
        )
