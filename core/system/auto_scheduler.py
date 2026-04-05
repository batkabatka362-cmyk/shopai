"""Auto Scheduler — runs autonomous cycles on a schedule.

Manages: cycle intervals, store rotation, health monitoring.
"""
from __future__ import annotations
import threading
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("scheduler")


class AutoScheduler:
    """Schedules and manages autonomous cycle execution."""

    def __init__(self) -> None:
        self._running = False
        self._thread: threading.Thread | None = None
        self._interval = 600  # 10 minutes default
        self._cycles_run = 0
        self._last_result: dict = {}
        self._stores: list[str] = []
        self._on_cycle_complete = None

    def start(self, stores: list[str] | None = None,
              interval_seconds: int = 600,
              on_complete=None) -> dict[str, Any]:
        """Start scheduled autonomous cycles."""
        if self._running:
            return {"status": "already_running"}

        self._stores = stores or ["deguar"]
        self._interval = interval_seconds
        self._on_cycle_complete = on_complete
        self._running = True

        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="shopai-scheduler")
        self._thread.start()

        logger.info("Scheduler started: %d stores, %ds interval",
                    len(self._stores), self._interval)
        return {
            "status": "started",
            "stores": self._stores,
            "interval": self._interval,
        }

    def stop(self) -> dict[str, Any]:
        """Stop the scheduler."""
        self._running = False
        logger.info("Scheduler stopped after %d cycles", self._cycles_run)
        return {"status": "stopped", "cycles_run": self._cycles_run}

    def _run_loop(self) -> None:
        while self._running:
            for store_id in self._stores:
                if not self._running:
                    break
                try:
                    result = self._run_cycle(store_id)
                    self._last_result = result
                    self._cycles_run += 1
                    if self._on_cycle_complete:
                        self._on_cycle_complete(result)
                except Exception as exc:
                    logger.error("Scheduler cycle error [%s]: %s", store_id, exc)

            # Wait for next interval
            for _ in range(self._interval):
                if not self._running:
                    break
                time.sleep(1)

    @staticmethod
    def _run_cycle(store_id: str) -> dict:
        import os
        # Load env if not loaded
        if not os.environ.get("SHOPAI_SHOPIFY_URL"):
            try:
                with open(".env") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ[k] = v
            except Exception:
                pass

        from core.autonomous.controller import AutonomousController
        ac = AutonomousController(auto_approve=False)
        ac.initialize()
        return ac.run_cycle(store_id)

    def run_once(self, store_id: str = "deguar") -> dict:
        """Run a single cycle immediately."""
        result = self._run_cycle(store_id)
        self._last_result = result
        self._cycles_run += 1
        return result

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "cycles_run": self._cycles_run,
            "interval": self._interval,
            "stores": self._stores,
            "last_duration": self._last_result.get("duration_s", 0),
        }


_instance = None
def get_scheduler():
    global _instance
    if _instance is None:
        _instance = AutoScheduler()
    return _instance
