#!/usr/bin/env python3
"""
akxOS Budget Engine
------------------
Closed-loop controller for enforcing per-process power budgets
using user-space OS mechanisms.

"""

import time
from typing import Dict

from power.power_state import get_power_states
from budget.policy import BudgetPolicy
from budget.state import BudgetRuntimeState
from budget.enforcers import (
    apply_nice,
    reset_nice,
    apply_freq_cap,
    reset_freq_cap,
    apply_cgroup_quota,
    reset_cgroup,
)


class BudgetEngine:
    """
    Power budget enforcement engine.
    """

    def __init__(self, interval: float = 1.0):
        self.interval = interval

        # pid → BudgetPolicy
        self.policies: Dict[int, BudgetPolicy] = {}

        # pid → BudgetRuntimeState
        self.runtime: Dict[int, BudgetRuntimeState] = {}

        # Track enforcement status
        self.enforced: Dict[int, bool] = {}

    # -------------------------------------------------
    # Policy management
    # -------------------------------------------------

    def add_policy(self, policy: BudgetPolicy):
        pid = policy.pid
        self.policies[pid] = policy
        self.runtime[pid] = BudgetRuntimeState(
            pid=pid,
            window_size=policy.window_size,
        )
        self.enforced[pid] = False

        print(f"[akxOS][budget] Added: {policy}")

    def remove_policy(self, pid: int):
        if pid in self.policies:
            self._reset_enforcement(pid)
            del self.policies[pid]
            del self.runtime[pid]
            del self.enforced[pid]

            print(f"[akxOS][budget] Removed budget for PID {pid}")

    def list_policies(self):
        for policy in self.policies.values():
            print(policy)

    # -------------------------------------------------
    # Core control loop
    # -------------------------------------------------

    def run(self, duration: float = None):
        """
        Start budget enforcement loop.

        Parameters
        ----------
        duration : float or None
            How long to run (seconds). None = run forever.
        """
        print("[akxOS][budget] Engine started")
        start_time = time.time()

        try:
            while True:
                self._control_step()

                if duration is not None and (time.time() - start_time) >= duration:
                    break

                time.sleep(self.interval)

        except KeyboardInterrupt:
            print("\n[akxOS][budget] Engine stopped")

        finally:
            self._reset_all()

    # -------------------------------------------------
    # One control step
    # -------------------------------------------------

    def _control_step(self):
        power_states = get_power_states()

        # Index power by PID
        power_map = {ps["pid"]: ps for ps in power_states}

        for pid, policy in self.policies.items():
            if not policy.active:
                continue

            if pid not in power_map:
                continue  # process may have exited

            ps = power_map[pid]
            state = self.runtime[pid]

            avg_power = state.add_sample(ps["p_total_mw"])
            violated = state.check_violation(policy.power_limit_mw)

            if violated:
                policy.violation_count += 1
                self._apply_enforcement(pid, policy)
            else:
                self._relax_enforcement(pid, policy)

    # -------------------------------------------------
    # Enforcement logic
    # -------------------------------------------------

    def _apply_enforcement(self, pid: int, policy: BudgetPolicy):
        if self.enforced.get(pid, False):
            return  # already enforced

        print(
            f"[akxOS][budget] PID {pid} violated budget "
            f"({policy.power_limit_mw} mW) → enforcing {policy.mode}"
        )

        if policy.mode == "sched_weight":
            apply_nice(pid, nice_value=10)

        elif policy.mode == "dvfs_cap":
            apply_freq_cap(freq_khz=600000)

        elif policy.mode == "cpu_quota":
            apply_cgroup_quota(pid, quota_us=20000)

        self.enforced[pid] = True

    def _relax_enforcement(self, pid: int, policy: BudgetPolicy):
        if not self.enforced.get(pid, False):
            return  # nothing to relax

        print(f"[akxOS][budget] PID {pid} back under budget → relaxing")

        self._reset_enforcement(pid)
        self.enforced[pid] = False

    def _reset_enforcement(self, pid: int):
        """
        Reset enforcement effects for a PID.
        """
        reset_nice(pid)
        reset_freq_cap()
        reset_cgroup(pid)

    def _reset_all(self):
        """
        Reset all enforced policies on shutdown.
        """
        for pid in list(self.enforced.keys()):
            self._reset_enforcement(pid)
