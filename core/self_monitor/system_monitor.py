"""SystemMonitor — central monitoring that ties health, anomaly, and recovery together.

READ-ONLY monitoring. Never modifies engine code or system structure.
Only safe recovery actions (cache clear, restart) are automated.
"""
from __future__ import annotations

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
        snapshot = {
            "timestamp": time.time(),
            "health": health,
            "anomalies": [],
            "recovery_actions": [],
        }

        # Auto-recover known issues
        if not health["checks"]["modules"]["healthy"]:
            recovery = self._recovery.attempt_recovery("engine_cache_stale")
            snapshot["recovery_actions"].append(recovery)

        if not health["checks"].get("memory", {}).get("healthy", True):
            recovery = self._recovery.attempt_recovery("memory_pressure")
            snapshot["recovery_actions"].append(recovery)

        elapsed = time.monotonic() - start
        snapshot["elapsed_seconds"] = round(elapsed, 3)
        snapshot["status"] = health["status"]

        self._snapshots.append(snapshot)
        # Keep last 1000 snapshots
        if len(self._snapshots) > 1000:
            self._snapshots = self._snapshots[-1000:]

        logger.info("System check: status=%s elapsed=%.3fs", snapshot["status"], elapsed)
        return snapshot

    def get_dashboard(self) -> dict[str, Any]:
        """Get dashboard data: current status + trends."""
        current = self.full_check()
        recent = self._snapshots[-100:] if self._snapshots else []

        healthy_count = sum(1 for s in recent if s.get("status") == "healthy")
        total = len(recent) if recent else 1

        return {
            "current": current,
            "uptime_rate": round(healthy_count / total, 4),
            "total_checks": len(self._snapshots),
            "recent_recoveries": self._recovery.get_action_log(limit=10),
            "baselines": self._anomaly.get_baselines(),
        }

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent monitoring snapshots."""
        return list(self._snapshots[-limit:])
