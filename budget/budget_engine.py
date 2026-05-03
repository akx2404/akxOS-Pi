#!/usr/bin/env python3
"""
akxOS Budget Engine
-------------------
Closed-loop controller with persistent policy storage.

"""

import signal
import time
import json
from pathlib import Path
from typing import Dict

from power.power_state import get_power_states
from budget.policy import BudgetPolicy
from budget.state import BudgetRuntimeState
from budget.pid_controller import QuotaPIDController
from budget.enforcers import (
    apply_nice,
    reset_nice,
    apply_budget_dvfs,
    reset_freq_cap,
    apply_cgroup_quota,
    reset_cgroup,
)


CONFIG_DIR  = Path.home() / ".akxos"
CONFIG_FILE = CONFIG_DIR / "budgets.json"


class BudgetEngine:

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.policies:         Dict[int, BudgetPolicy]        = {}
        self.runtime:          Dict[int, BudgetRuntimeState]  = {}
        self.enforced:         Dict[int, bool]                = {}
        self._pid_controllers: Dict[int, QuotaPIDController] = {}
        self._running: bool = False

        self._load_policies()

    # =================================================
    # Persistence
    # =================================================

    def _ensure_config_dir(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def _save_policies(self):
        self._ensure_config_dir()
        data = [
            {
                "pid":             p.pid,
                "power_limit_mw":  p.power_limit_mw,
                "mode":            p.mode,
                "window_size":     p.window_size,
                "violation_count": p.violation_count,
                "active":          p.active,
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
                    pid            = entry["pid"],
                    power_limit_mw = entry["power_limit_mw"],
                    mode           = entry["mode"],
                    window_size    = entry.get("window_size", 10),
                )
                policy.violation_count = entry.get("violation_count", 0)
                policy.active          = entry.get("active", True)

                self.policies[policy.pid] = policy
                self.runtime [policy.pid] = BudgetRuntimeState(
                    pid=policy.pid, window_size=policy.window_size
                )
                self.enforced[policy.pid] = False

                if policy.mode == "cpu_quota":
                    self._pid_controllers[policy.pid] = QuotaPIDController(
                        pid=policy.pid
                    )

            print("[akxOS] Loaded persisted budgets.")

        except Exception as e:
            print(f"[akxOS] Failed to load budgets: {e}")

    # =================================================
    # Policy Management
    # =================================================

    def add_policy(self, policy: BudgetPolicy):
        self.policies[policy.pid] = policy
        self.runtime [policy.pid] = BudgetRuntimeState(
            pid=policy.pid, window_size=policy.window_size
        )
        self.enforced[policy.pid] = False

        if policy.mode == "cpu_quota":
            self._pid_controllers[policy.pid] = QuotaPIDController(
                pid=policy.pid
            )

        self._save_policies()
        print(f"[akxOS] Budget added: {policy}")

    def remove_policy(self, pid: int):
        if pid not in self.policies:
            return
        self._reset_enforcement(pid)
        del self.policies[pid]
        del self.runtime [pid]
        del self.enforced[pid]
        if pid in self._pid_controllers:
            self._pid_controllers[pid].reset()
            del self._pid_controllers[pid]
        self._save_policies()
        print(f"[akxOS] Budget removed for PID {pid}")

    def list_policies(self):
        if not self.policies:
            print("[akxOS] No active budgets.")
            return
        for policy in self.policies.values():
            print(policy)
        for pid, ctrl in self._pid_controllers.items():
            print(f"  └─ PI Controller: {ctrl}")

    # =================================================
    # Engine Loop
    # =================================================

    def run(self, duration: float = None):
        print("[akxOS] Budget engine started.")
        self._running = True
        start_time = time.time()

        # Catch SIGTERM (systemd stop / kill) so cleanup always runs
        def _sigterm_handler(signum, frame):
            print("\n[akxOS] SIGTERM received, shutting down cleanly...")
            self._running = False

        signal.signal(signal.SIGTERM, _sigterm_handler)

        try:
            while self._running:
                self._control_step()

                if duration and (time.time() - start_time) >= duration:
                    break

                time.sleep(self.interval)

        except KeyboardInterrupt:
            print("\n[akxOS] Budget engine stopped.")

        finally:
            self._reset_all()

    # =================================================
    # Control Step
    # =================================================

    def _control_step(self):
        # Single power snapshot per tick — no re-fetching inside enforcers
        power_states = get_power_states()
        power_map = {ps["pid"]: ps for ps in power_states}

        for pid, policy in self.policies.items():
            if not policy.active:
                continue
            if pid not in power_map:
                continue

            state         = self.runtime[pid]
            current_state = power_map[pid]
            avg_power     = state.add_sample(current_state["p_total_mw"])
            violated      = state.check_violation(policy.power_limit_mw)

            if violated:
                policy.violation_count += 1

            self._apply_enforcement(pid, policy, current_state, avg_power, violated)

    # =================================================
    # Enforcement Logic
    # =================================================

    def _apply_enforcement(self,
                           pid:           int,
                           policy:        BudgetPolicy,
                           current_state: dict,
                           avg_power_mw:  float,
                           violated:      bool):
        """
        Dispatch enforcement based on policy mode.

        sched_weight  Binary on/off. Apply nice on first violation;
                      reset when power returns within budget.

        dvfs_cap      Proportional feedback controller, runs every tick.
                      Naturally increases frequency when under budget — no
                      separate relax call needed.

        cpu_quota     PI feedback controller, runs every tick.
                      Bidirectional by design; deadband prevents hunting.
        """
        if policy.mode == "sched_weight":
            if violated and not self.enforced[pid]:
                apply_nice(pid)
                self.enforced[pid] = True

            elif not violated and self.enforced[pid]:
                reset_nice(pid)
                self.enforced[pid] = False

        elif policy.mode == "dvfs_cap":
            apply_budget_dvfs(
                current_power_mw = avg_power_mw,
                budget_mw        = policy.power_limit_mw,
                Kp               = 0.5,
            )
            self.enforced[pid] = violated

        elif policy.mode == "cpu_quota":
            self._apply_cpu_quota_pi(pid, policy, avg_power_mw)
            self.enforced[pid] = violated

    def _apply_cpu_quota_pi(self,
                             pid:          int,
                             policy:       BudgetPolicy,
                             avg_power_mw: float):
        """PI closed-loop controller for cpu_quota mode."""
        if avg_power_mw <= 0:
            return

        ctrl = self._pid_controllers.get(pid)
        if ctrl is None:
            ctrl = QuotaPIDController(pid=pid)
            self._pid_controllers[pid] = ctrl

        new_quota_pct = ctrl.step(
            current_power_mw = avg_power_mw,
            budget_mw        = policy.power_limit_mw,
        )

        period_us = 100_000
        quota_us  = int(period_us * new_quota_pct / 100.0)

        error  = policy.power_limit_mw - avg_power_mw
        db_tag = "[DB]" if abs(error) < ctrl.deadband_mw else "    "

        print(
            f"[akxOS][quota][PI]{db_tag} PID {pid}: "
            f"avg={avg_power_mw:.1f} mW  "
            f"budget={policy.power_limit_mw:.1f} mW  "
            f"err={error:+.1f} mW  "
            f"quota={new_quota_pct:.1f}%  "
            f"({quota_us}/{period_us} µs)"
        )

        apply_cgroup_quota(pid, quota_us, period_us)

    # =================================================
    # Reset Helpers
    # =================================================

    def _reset_enforcement(self, pid: int):
        reset_nice(pid)
        reset_freq_cap()
        reset_cgroup(pid)
        if pid in self._pid_controllers:
            self._pid_controllers[pid].reset()
        self.enforced[pid] = False

    def _reset_all(self):
        for pid in list(self.enforced.keys()):
            self._reset_enforcement(pid)
