#!/usr/bin/env python3
"""
akxOS Budget Runtime State
-------------------------
Tracks recent power samples for budgeted processes
and computes windowed statistics for violation detection.

"""

from collections import deque
from typing import Deque


class BudgetRuntimeState:
    """
    Runtime state for a single budgeted process.
    """

    def __init__(self, pid: int, window_size: int):
        self.pid = pid
        self.window_size = window_size

        # Sliding window of recent power samples (mW)
        self.samples: Deque[float] = deque(maxlen=window_size)

        self.last_avg: float = 0.0
        self.violated: bool = False

    # ---------- Core Operations ----------

    def add_sample(self, power_mw: float) -> float:
        """
        Add a new power sample and update moving average.

        Parameters
        ----------
        power_mw : float
            Total power consumption in milliwatts

        Returns
        -------
        float
            Updated moving average power
        """
        self.samples.append(power_mw)
        self.last_avg = self.average()
        return self.last_avg

    def average(self) -> float:
        """
        Compute the current moving average power.

        Returns
        -------
        float
            Average power over the window (mW)
        """
        if not self.samples:
            return 0.0
        return sum(self.samples) / len(self.samples)

    # ---------- Violation Detection ----------

    def check_violation(self, limit_mw: float) -> bool:
        """
        Check whether the current average violates the budget.

        Parameters
        ----------
        limit_mw : float
            Power budget limit in milliwatts

        Returns
        -------
        bool
            True if violated, False otherwise
        """
        self.violated = self.last_avg > limit_mw
        return self.violated

    # ---------- Debug / Introspection ----------

    def __str__(self):
        return (
            f"PID={self.pid} | "
            f"Avg={self.last_avg:.2f} mW | "
            f"Samples={len(self.samples)}/{self.window_size} | "
            f"Violated={self.violated}"
        )
