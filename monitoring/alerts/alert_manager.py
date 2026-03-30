"""Alert rule management and evaluation engine."""

import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional


class AlertManager:
    """Manage alert rules, evaluate metrics against them, and track alert lifecycle."""

    CONDITION_OPS = {
        "gt": lambda v, t: v > t,
        "lt": lambda v, t: v < t,
        "eq": lambda v, t: v == t,
        "gte": lambda v, t: v >= t,
        "lte": lambda v, t: v <= t,
    }

    def __init__(self):
        self._rules: dict[str, dict] = {}
        self._active_alerts: list[dict] = []
        self._history: list[dict] = []

    def add_rule(
        self,
        rule_id: str,
        metric: str,
        condition: str,
        threshold: float,
        action: str,
    ) -> None:
        """Add or update an alert rule.

        Args:
            rule_id: Unique rule identifier.
            metric: Metric name to watch.
            condition: One of gt, lt, eq, gte, lte.
            threshold: Numeric threshold value.
            action: Action description (e.g. "notify_slack", "page_oncall", "log").
        """
        if condition not in self.CONDITION_OPS:
            raise ValueError(f"Invalid condition '{condition}'. Must be one of: {list(self.CONDITION_OPS.keys())}")
        self._rules[rule_id] = {
            "rule_id": rule_id,
            "metric": metric,
            "condition": condition,
            "threshold": threshold,
            "action": action,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "enabled": True,
        }

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID. Returns True if found and removed."""
        return self._rules.pop(rule_id, None) is not None

    def check(self, metrics: dict) -> list[dict]:
        """Evaluate all rules against provided metrics dict.

        Args:
            metrics: Dict mapping metric names to current numeric values.

        Returns:
            List of newly triggered alert dicts.
        """
        triggered = []
        for rule_id, rule in self._rules.items():
            if not rule["enabled"]:
                continue
            metric_name = rule["metric"]
            if metric_name not in metrics:
                continue
            value = metrics[metric_name]
            op = self.CONDITION_OPS[rule["condition"]]
            if op(value, rule["threshold"]):
                alert = {
                    "alert_id": uuid.uuid4().hex[:12],
                    "rule_id": rule_id,
                    "metric": metric_name,
                    "condition": rule["condition"],
                    "threshold": rule["threshold"],
                    "actual_value": value,
                    "action": rule["action"],
                    "status": "active",
                    "triggered_at": datetime.now(timezone.utc).isoformat(),
                    "acknowledged": False,
                }
                self._active_alerts.append(alert)
                self._history.append(alert)
                triggered.append(alert)
        return triggered

    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge an active alert. Returns True if found."""
        for alert in self._active_alerts:
            if alert["alert_id"] == alert_id:
                alert["acknowledged"] = True
                alert["status"] = "acknowledged"
                alert["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
                return True
        return False

    def get_active_alerts(self) -> list[dict]:
        """Return all currently active (unacknowledged) alerts."""
        return [a for a in self._active_alerts if not a["acknowledged"]]

    def get_alert_history(self, hours: int = 24) -> list[dict]:
        """Return alert history within the last N hours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        return [a for a in self._history if a["triggered_at"] >= cutoff]
