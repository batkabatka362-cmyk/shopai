"""Alert System — generates and stores alerts for important events.

Monitors cycle results and generates actionable alerts.
"""
from __future__ import annotations
import threading as _threading
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("system.alerts")


class AlertSystem:
    """Generates alerts from cycle results."""

    def __init__(self) -> None:
        self._alerts: list[dict[str, Any]] = []

    def check_cycle(self, cycle_result: dict) -> list[dict[str, Any]]:
        """Check cycle result and generate alerts."""
        alerts = []
        phases = cycle_result.get("phases", {})

        # Data quality alert
        dq = phases.get("data_quality", {})
        if dq.get("score", 100) < 80:
            alerts.append(self._alert("warning", "data_quality",
                "Data quality score dropped to {}".format(dq["score"])))

        # Rule health alert
        rh = phases.get("rule_health", {})
        if rh.get("health_score", 100) < 50:
            alerts.append(self._alert("warning", "rule_health",
                "Rule health {}% — {} rules never succeed".format(
                    rh["health_score"], rh.get("zero_success", 0))))

        # Execution failure alert
        ex = phases.get("execution", {})
        if ex.get("failed", 0) > 0:
            alerts.append(self._alert("critical", "execution",
                "{} actions failed to execute".format(ex["failed"])))

        # Brain health alert
        brain = phases.get("brain", {})
        if brain.get("health_score", 100) < 70:
            alerts.append(self._alert("warning", "store_health",
                "Store health dropped to {}".format(brain["health_score"])))

        # Layer failure alert
        layers = phases.get("layers", {})
        if layers.get("layers_run", 12) < 12:
            alerts.append(self._alert("warning", "layers",
                "Only {}/12 layers running".format(layers["layers_run"])))

        # Learning stagnation
        learn = phases.get("learning", {})
        if learn.get("weight_updates", 0) == 0 and learn.get("patterns_found", 0) == 0:
            alerts.append(self._alert("info", "learning",
                "No patterns or weight updates this cycle"))

        # Duration alert
        duration = cycle_result.get("duration_s", 0)
        if duration > 10:
            alerts.append(self._alert("warning", "performance",
                "Cycle took {:.1f}s — investigate bottleneck".format(duration)))

        self._alerts.extend(alerts)
        return alerts

    @staticmethod
    def _alert(severity: str, category: str, message: str) -> dict[str, Any]:
        return {
            "severity": severity,
            "category": category,
            "message": message,
            "timestamp": time.time(),
        }

    def get_recent(self, limit: int = 20) -> list[dict]:
        return self._alerts[-limit:]

    def get_stats(self) -> dict[str, Any]:
        by_sev = {}
        for a in self._alerts:
            s = a.get("severity", "info")
            by_sev[s] = by_sev.get(s, 0) + 1
        return {"total": len(self._alerts), "by_severity": by_sev}


_instance = None
_instance_lock = _threading.Lock()


def get_alert_system():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AlertSystem()
    return _instance
