#!/usr/bin/env python3
"""
akxOS Budget Engine
------------------
Closed-loop controller with persistent policy storage.

"""

import time
import json
from pathlib import Path
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


# -------------------------------------------------
# Persistence Location
# -------------------------------------------------

CONFIG_DIR = Path.home() / ".akxos"
CONFIG_FILE = CONFIG_DIR / "budgets.json"


class BudgetEngine:

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.policies: Dict[int, BudgetPolicy] = {}
        self.runtime: Dict[int, BudgetRuntimeState] = {}
        self.enforced: Dict[int, bool] = {}

        self._load_policies()

    # =================================================
    # Persistence
    # =================================================

    def _ensure_config_dir(self):
        if not CONFIG_DIR.exists():
            CONFIG_DIR.mkdir(parents=True)

    def _save_policies(self):
        self._ensure_config_dir()

        data = [
            {
                "pid": p.pid,
                "power_limit_mw": p.power_limit_mw,
                "mode": p.mode,
                "window_size": p.window_size,
                "violation_count": p.violation_count,
                "active": p.active,
            }
            for p in self.policies.values()
        ]

        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=4)

    def _load_policies(self):
        if not CONFIG_FILE.exists():
            return

        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)

            for entry in data:
                policy = BudgetPolicy(
                    pid=entry["pid"],
                    power_limit_mw=entry["power_limit_mw"],
                    mode=entry["mode"],
                    window_size=entry.get("window_size", 5),
                )
                policy.violation_count = entry.get("violation_count", 0)
                policy.active = entry.get("active", True)

                self.policies[policy.pid] = policy
                self.runtime[policy.pid] = BudgetRuntimeState(
                    pid=policy.pid,
                    window_size=policy.window_size,
                )
                self.enforced[policy.pid] = False

            print("[akxOS] Loaded persisted budgets.")

        except Exception as e:
            print(f"[akxOS] Failed to load budgets: {e}")

    # =================================================
    # Policy Management
    # =================================================

    def add_policy(self, policy: BudgetPolicy):
        self.policies[policy.pid] = policy
        self.runtime[policy.pid] = BudgetRuntimeState(
            pid=policy.pid,
            window_size=policy.window_size,
        )
        self.enforced[policy.pid] = False

        self._save_policies()
        print(f"[akxOS] Budget added: {policy}")

    def remove_policy(self, pid: int):
        if pid in self.policies:
            self._reset_enforcement(pid)

            del self.policies[pid]
            del self.runtime[pid]
            del self.enforced[pid]

            self._save_policies()
            print(f"[akxOS] Budget removed for PID {pid}")

    def list_policies(self):
        if not self.policies:
            print("[akxOS] No active budgets.")
            return

        for policy in self.policies.values():
            print(policy)

    # =================================================
    # Engine Loop
    # =================================================

    def run(self, duration: float = None):
        print("[akxOS] Budget engine started.")
        start_time = time.time()

        try:
            while True:
                self._control_step()

                if duration and (time.time() - start_time) >= duration:
                    break

                time.sleep(self.interval)

        except KeyboardInterrupt:
            print("\n[akxOS] Budget engine stopped.")

        finally:
            self._reset_all()

    def _control_step(self):
        power_states = get_power_states()
        power_map = {ps["pid"]: ps for ps in power_states}

        for pid, policy in self.policies.items():
            if not policy.active:
                continue

            if pid not in power_map:
                continue

            state = self.runtime[pid]
            avg_power = state.add_sample(power_map[pid]["p_total_mw"])
            violated = state.check_violation(policy.power_limit_mw)

            if violated:
                policy.violation_count += 1
                self._apply_enforcement(pid, policy, power_map[pid])
            else:
                self._apply_enforcement(pid, policy, power_map[pid])

    # =================================================
    # Enforcement Logic
    # =================================================

    def _apply_enforcement(self, pid: int, policy: BudgetPolicy, current_state):
        if self.enforced.get(pid, False):
            return

        if policy.mode == "sched_weight":
          apply_nice(pid)

        elif policy.mode == "dvfs_cap":
          apply_freq_cap(600000)

        elif policy.mode == "cpu_quota":

          # Get latest measurement
          power_states = get_power_states()
          power_map = {ps["pid"]: ps for ps in power_states}

          if pid not in power_map:
              return

          current_power = current_state["p_total_mw"]
          current_cpu = current_state["cpu_percent"]

          if current_power <= 0:
              return

          # Proportional scaling
          target_cpu = (
              policy.power_limit_mw / current_power
          ) * current_cpu

          # Clamp CPU% between 5% and 100%
          target_cpu = max(5.0, min(target_cpu, 100.0))

          period_us = 100000
          quota_us = int(period_us * target_cpu / 100)

          print(
              f"[akxOS][quota] PID {pid}: "
              f"{current_cpu:.1f}% → {target_cpu:.1f}% "
              f"(quota {quota_us}/{period_us})"
          )

          apply_cgroup_quota(pid, quota_us, period_us)

        self.enforced[pid] = True

    def _relax_enforcement(self, pid: int, policy: BudgetPolicy):
        if not self.enforced.get(pid, False):
            return

        self._reset_enforcement(pid)
        self.enforced[pid] = False

    def _reset_enforcement(self, pid: int):
        reset_nice(pid)
        reset_freq_cap()
        reset_cgroup(pid)

    def _reset_all(self):
        for pid in list(self.enforced.keys()):
            self._reset_enforcement(pid)
