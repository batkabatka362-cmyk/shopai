"""SystemMonitor — central monitoring that ties health, anomaly, and recovery together.

READ-ONLY monitoring. Never modifies engine code or system structure.
Only safe recovery actions (cache clear, restart) are automated.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.logger import get_logger
from .health_checker import HealthChecker
from .anomaly_detector import AnomalyDetector
from .auto_recovery import AutoRecovery

logger = get_logger("monitor.system")


class SystemMonitor:
    """Central system monitor — combines health, anomaly detection, and recovery.

    SAFETY: This monitor ONLY reads and reports.
    It NEVER modifies engine code, deletes files, or restructures the system.
    Recovery actions are limited to safe operations (cache clear, etc.)
    """

    def __init__(self) -> None:
        self._health = HealthChecker()
        self._anomaly = AnomalyDetector()
        self._recovery = AutoRecovery()
        self._snapshots: list[dict[str, Any]] = []
        # Protect ``_snapshots`` from concurrent full_check
        # calls. Audit pass 51.
        self._lock = threading.Lock()

    @property
    def health(self) -> HealthChecker:
        return self._health

    @property
    def anomaly(self) -> AnomalyDetector:
        return self._anomaly

    @property
    def recovery(self) -> AutoRecovery:
        return self._recovery

    def full_check(self) -> dict[str, Any]:
        """Run comprehensive system check: health + anomaly."""
        start = time.monotonic()

        health = self._health.check_all()
        if not isinstance(health, dict):
            health = {"status": "unknown", "checks": {}}
        snapshot = {
            "timestamp": time.time(),
            "health": health,
            "anomalies": [],
            "recovery_actions": [],
        }

        # Defensive: health["checks"]["modules"]["healthy"]
        # chained .get crashed if any sub-key was missing.
        # Use ``(x or {})`` pattern. Audit pass 51.
        checks = health.get("checks") or {}
        if not isinstance(checks, dict):
            checks = {}
        modules_check = checks.get("modules") or {}
        if not isinstance(modules_check, dict):
            modules_check = {}
        if not modules_check.get("healthy", True):
            recovery = self._recovery.attempt_recovery("engine_cache_stale")
            snapshot["recovery_actions"].append(recovery)

        memory_check = checks.get("memory") or {}
        if not isinstance(memory_check, dict):
            memory_check = {}
        if not memory_check.get("healthy", True):
            recovery = self._recovery.attempt_recovery("memory_pressure")
            snapshot["recovery_actions"].append(recovery)

        elapsed = time.monotonic() - start
        snapshot["elapsed_seconds"] = round(elapsed, 3)
        snapshot["status"] = health.get("status", "unknown")

        with self._lock:
            self._snapshots.append(snapshot)
            # Keep last 1000 snapshots. In-place trim so any
            # external reference to ``_snapshots`` stays valid.
            if len(self._snapshots) > 1000:
                del self._snapshots[:len(self._snapshots) - 1000]

        logger.info("System check: status=%s elapsed=%.3fs", snapshot["status"], elapsed)
        return snapshot

    def get_dashboard(self) -> dict[str, Any]:
        """Get dashboard data: current status + trends."""
        current = self.full_check()
        with self._lock:
            recent = list(self._snapshots[-100:]) if self._snapshots else []
            total_snapshots = len(self._snapshots)

        healthy_count = sum(1 for s in recent if s.get("status") == "healthy")
        total = len(recent) if recent else 1

        return {
            "current": current,
            "uptime_rate": round(healthy_count / total, 4),
            "total_checks": total_snapshots,
            "recent_recoveries": self._recovery.get_action_log(limit=10),
            "baselines": self._anomaly.get_baselines(),
        }

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent monitoring snapshots."""
        if not isinstance(limit, int) or limit <= 0:
            limit = 50
        with self._lock:
            return [dict(s) for s in self._snapshots[-limit:]]
