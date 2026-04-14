"""Auto Scheduler — runs autonomous cycles on a schedule.

Manages: cycle intervals, store rotation, health monitoring.
"""
from __future__ import annotations
import threading
import time
from collections import deque
from typing import Any
from utils.logger import get_logger
logger = get_logger("scheduler")

_RECENT_SUMMARIES_MAX = 20


def _compact_summary(result: dict) -> dict:
    """Condense a full ``cycle_result`` into a dashboard-friendly row.

    We deliberately drop the heavy sub-payloads (decisions list, raw
    data, brain internals) so the dashboard's ``/api/cycle`` endpoint
    can serialise a 20-cycle history quickly and keep the wire size
    under a few kilobytes.
    """
    phases = result.get("phases", {}) or {}
    brain = phases.get("brain", {}) or {}
    data = phases.get("data", {}) or {}
    analysis = phases.get("analysis", {}) or {}
    decisions = phases.get("decisions", {}) or {}
    return {
        "cycle_id": result.get("cycle_id", ""),
        "store_id": result.get("store_id", ""),
        "timestamp": result.get("timestamp", time.time()),
        "duration_s": result.get("duration_s", 0.0),
        "status": result.get("status", ""),
        "phase_error_count": result.get("phase_error_count", 0),
        "phase_errors": dict(result.get("phase_errors", {}) or {}),
        "products": data.get("products", 0),
        "orders": data.get("orders", 0),
        "customers": data.get("customers", 0),
        "insights": analysis.get("insights", 0),
        "actions_proposed": decisions.get("proposed", 0),
        "top_action": brain.get("top_action", ""),
        "health_score": brain.get("health_score"),
        "adapter_hooks": phases.get("adapter_hooks", {}),
        "reflection": result.get("reflection", {}),
    }


class AutoScheduler:
    """Schedules and manages autonomous cycle execution."""

    def __init__(self) -> None:
        self._running = False
        self._thread: threading.Thread | None = None
        self._interval = 600  # 10 minutes default
        self._cycles_run = 0
        self._last_result: dict = {}
        # Compact per-cycle summaries, bounded buffer. Feeds the
        # dashboard's Cycle tab so operators can scroll through
        # recent history without reloading full cycle payloads.
        self._recent_summaries: deque = deque(maxlen=_RECENT_SUMMARIES_MAX)
        self._stores: list[str] = []
        self._on_cycle_complete = None
        # Concurrency guard for ``run_once_async``. The dashboard may
        # fire multiple "Run once" clicks in quick succession and
        # AutonomousController is not thread-safe, so overlapping
        # cycles would corrupt shared state.
        self._busy_lock = threading.Lock()
        self._cycle_busy = False
        self._last_error: str = ""

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
                    self._recent_summaries.append(_compact_summary(result))
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
            except Exception as exc:
                logger.debug(".env load failed: %s", exc)

        from core.autonomous.controller import AutonomousController
        ac = AutonomousController(auto_approve=False)
        ac.initialize()
        return ac.run_cycle(store_id)

    def run_once(self, store_id: str = "deguar") -> dict:
        """Run a single cycle immediately. Blocks the caller."""
        result = self._run_cycle(store_id)
        self._last_result = result
        self._recent_summaries.append(_compact_summary(result))
        self._cycles_run += 1
        return result

    def run_once_async(self, store_id: str = "deguar") -> dict[str, Any]:
        """Fire a single cycle on a background thread.

        Returns immediately with ``{"status": "queued"}`` or, when
        another cycle is still running, ``{"status": "busy"}``. The
        dashboard polls ``/api/cycle`` to observe completion.
        """
        with self._busy_lock:
            if self._cycle_busy:
                return {"status": "busy", "store_id": store_id}
            self._cycle_busy = True

        def _worker() -> None:
            try:
                result = self._run_cycle(store_id)
                self._last_result = result
                self._recent_summaries.append(_compact_summary(result))
                self._cycles_run += 1
                self._last_error = ""
                if self._on_cycle_complete:
                    try:
                        self._on_cycle_complete(result)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("on_cycle_complete hook failed: %s", exc)
            except Exception as exc:  # noqa: BLE001
                logger.error("run_once_async [%s] failed: %s", store_id, exc)
                self._last_error = str(exc)[:200]
            finally:
                with self._busy_lock:
                    self._cycle_busy = False

        t = threading.Thread(
            target=_worker, daemon=True,
            name=f"shopai-run-once-{store_id}",
        )
        t.start()
        return {"status": "queued", "store_id": store_id}

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "busy": self._cycle_busy,
            "cycles_run": self._cycles_run,
            "interval": self._interval,
            "stores": self._stores,
            "last_duration": self._last_result.get("duration_s", 0),
            "last_error": self._last_error,
        }

    def get_last_summary(self) -> dict | None:
        """Compact summary of the most recent cycle, or None."""
        if not self._last_result:
            return None
        return _compact_summary(self._last_result)

    def get_recent_summaries(self, limit: int = 20) -> list[dict]:
        """Bounded list of compact summaries, most recent last."""
        if limit <= 0:
            return []
        items = list(self._recent_summaries)
        return items[-limit:]

    def record_cycle_result(self, result: dict) -> None:
        """External hook so callers invoking ``AutonomousController``
        directly (bypassing the scheduler loop) can still feed the
        dashboard's cycle buffer.

        Kept tolerant of a non-dict input so a bad caller can never
        corrupt the ring.
        """
        if not isinstance(result, dict):
            return
        self._last_result = result
        self._recent_summaries.append(_compact_summary(result))


_instance = None
_instance_lock = threading.Lock()


def get_scheduler():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AutoScheduler()
    return _instance
