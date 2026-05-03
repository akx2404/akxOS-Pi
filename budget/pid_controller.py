#!/usr/bin/env python3
"""
akxOS Quota PID Controller
--------------------------
Per-process PI controller for cpu_quota enforcement.

Control law:
    e(t)         = budget_mw - avg_power_mw
    integral(t)  = integral(t-1) + e(t) * dt   [only outside deadband]
    delta_quota  = Kp * e(t) + Ki * integral(t)
    quota(t)     = clamp(quota(t-1) + delta_quota, MIN, MAX)

"""

import time

QUOTA_MIN_PCT = 5.0
QUOTA_MAX_PCT = 100.0

DEFAULT_KP           = 0.3
DEFAULT_KI           = 0.01
DEFAULT_DEADBAND_MW  = 10.0
DEFAULT_WINDUP_LIMIT = 150.0


class QuotaPIDController:
    """PI controller with deadband for a single budgeted process."""

    def __init__(self,
                 pid:          int,
                 kp:           float = DEFAULT_KP,
                 ki:           float = DEFAULT_KI,
                 deadband_mw:  float = DEFAULT_DEADBAND_MW,
                 windup_limit: float = DEFAULT_WINDUP_LIMIT):
        self.pid          = pid
        self.kp           = kp
        self.ki           = ki
        self.deadband_mw  = deadband_mw
        self.windup_limit = windup_limit

        self._integral:       float = 0.0
        self._last_time:      float = time.monotonic()
        self._last_quota_pct: float = QUOTA_MAX_PCT

    def step(self, current_power_mw: float, budget_mw: float) -> float:
        """
        Run one PI control step.

        Parameters
        ----------
        current_power_mw : float
            Windowed-average power from BudgetRuntimeState.
        budget_mw : float
            Power budget setpoint.

        Returns
        -------
        float
            New CPU quota percentage in [QUOTA_MIN_PCT, QUOTA_MAX_PCT].
        """
        now = time.monotonic()
        dt  = now - self._last_time
        self._last_time = now

        if dt <= 0 or dt > 10.0:
            dt = 1.0

        error      = budget_mw - current_power_mw
        in_deadband = abs(error) < self.deadband_mw

        if in_deadband:
            p_term = 0.5 * self.kp * error
            i_term = self.ki * self._integral
        else:
            self._integral += error * dt
            self._integral  = max(-self.windup_limit,
                                  min(self._integral, self.windup_limit))
            p_term = self.kp * error
            i_term = self.ki * self._integral

        new_quota_pct = self._last_quota_pct + p_term + i_term
        new_quota_pct = max(QUOTA_MIN_PCT, min(new_quota_pct, QUOTA_MAX_PCT))
        self._last_quota_pct = new_quota_pct
        return new_quota_pct

    def reset(self):
        self._integral       = 0.0
        self._last_quota_pct = QUOTA_MAX_PCT
        self._last_time      = time.monotonic()

    def __str__(self):
        return (
            f"PID={self.pid} | "
            f"Quota={self._last_quota_pct:.1f}% | "
            f"Integral={self._integral:.2f} mW*s"
        )
