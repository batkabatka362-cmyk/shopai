"""Alert Manager — alert rules and triggers."""
from __future__ import annotations
from typing import Any, Callable
from utils.logger import get_logger

logger = get_logger("monitoring.alerts")


class AlertManager:
    def __init__(self) -> None:
        self._rules: list[dict[str, Any]] = []
        self._fired: list[dict[str, Any]] = []

    def add_rule(self, name: str, condition: Callable[[dict], bool], severity: str = "warning") -> None:
        self._rules.append({"name": name, "condition": condition, "severity": severity})

    def check(self, metrics: dict[str, Any]) -> list[dict[str, Any]]:
        alerts = []
        for rule in self._rules:
            if rule["condition"](metrics):
                alert = {"rule": rule["name"], "severity": rule["severity"], "metrics": metrics}
                alerts.append(alert)
                self._fired.append(alert)
                logger.warning("Alert fired: %s (%s)", rule["name"], rule["severity"])
        return alerts

    def get_fired(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._fired[-limit:]
