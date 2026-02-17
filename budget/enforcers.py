#!/usr/bin/env python3
"""
akxOS Budget Policy
-------------------
Defines power budget intent for a process.

Policy describes:
- WHAT the limit is
- WHICH OS control plane is used

"""

from dataclasses import dataclass
from typing import Literal


EnforcementMode = Literal[
    "sched_weight",
    "dvfs_cap",
    "cpu_quota"
]


@dataclass
class BudgetPolicy:
    pid: int
    power_limit_mw: float
    mode: EnforcementMode

    window_size: int = 5
    violation_count: int = 0
    active: bool = True

    def __post_init__(self):
        if self.power_limit_mw <= 0:
            raise ValueError("Power limit must be positive")

        if self.window_size < 1:
            raise ValueError("Window size must be >= 1")

        if self.mode not in ("sched_weight", "dvfs_cap", "cpu_quota"):
            raise ValueError(f"Invalid enforcement mode: {self.mode}")

    def __str__(self):
        return (
            f"PID={self.pid} | "
            f"Limit={self.power_limit_mw}mW | "
            f"Mode={self.mode} | "
            f"Window={self.window_size} | "
            f"Violations={self.violation_count}"
        )
