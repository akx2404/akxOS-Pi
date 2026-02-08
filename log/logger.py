#akxos logging stub
#!/usr/bin/env python3
"""
akxOS Power Logger
------------------
Time-series logger for per-process power states.

"""

import csv
import os
import time
from datetime import datetime
from typing import List, Dict

from power.power_state import get_power_states


DEFAULT_LOG_DIR = "logs"


class PowerLogger:
    """
    Periodic logger for akxOS power states.
    """

    def __init__(self,
                 interval: float = 1.0,
                 duration: float = 10.0,
                 log_dir: str = DEFAULT_LOG_DIR):
        """
        Parameters
        ----------
        interval : float
            Sampling interval in seconds
        duration : float
            Total logging duration in seconds
        log_dir : str
            Directory to store log files
        """
        self.interval = interval
        self.duration = duration
        self.log_dir = log_dir
        self.log_file = self._create_log_file()

    # ---------- Internal Helpers ----------

    def _create_log_file(self) -> str:
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return os.path.join(self.log_dir, f"power_log_{timestamp}.csv")

    def _write_header(self, writer: csv.writer):
        writer.writerow([
            "timestamp",
            "pid",
            "name",
            "cpu_percent",
            "mem_kb",
            "voltage_v",
            "freq_hz",
            "temperature_c",
            "p_dyn_mw",
            "p_leak_mw",
            "p_total_mw",
        ])

    # ---------- Core Logging ----------

    def run(self):
        """
        Run the logging loop.
        """
        print(f"[akxOS] Logging started → {self.log_file}")
        print(f"[akxOS] Interval: {self.interval}s | Duration: {self.duration}s")

        end_time = time.time() + self.duration

        with open(self.log_file, "w", newline="") as f:
            writer = csv.writer(f)
            self._write_header(writer)

            while time.time() < end_time:
                self._log_snapshot(writer)
                time.sleep(self.interval)

        print(f"[akxOS] Logging completed → {self.log_file}")

    def _log_snapshot(self, writer: csv.writer):
        """
        Capture and log one power-state snapshot.
        """
        power_states: List[Dict] = get_power_states()

        for ps in power_states:
            writer.writerow([
                ps["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                ps["pid"],
                ps["name"],
                f"{ps['cpu_percent']:.2f}",
                ps["mem_kb"],
                f"{ps['voltage_v']:.3f}",
                f"{ps['freq_hz']:.0f}",
                f"{ps['temperature_c']:.1f}",
                f"{ps['p_dyn_mw']:.3f}",
                f"{ps['p_leak_mw']:.3f}",
                f"{ps['p_total_mw']:.3f}",
            ])
