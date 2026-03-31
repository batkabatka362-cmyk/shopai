"""Alert System — monitors metrics and sends alerts when thresholds are breached.

Supports: log, callback, webhook. Designed for Slack/email/Telegram integration.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("alerts")


class AlertRule:
    def __init__(self, name: str, metric: str, condition: str, threshold: float,
                 severity: str = "warning", cooldown: int = 300) -> None:
        self.name = name
        self.metric = metric
        self.condition = condition  # gt, lt, eq, gte, lte
        self.threshold = threshold
        self.severity = severity
        self.cooldown = cooldown
        self.last_fired = 0.0


class AlertSystem:
    """Monitors metrics and fires alerts."""

    def __init__(self) -> None:
        self._rules: dict[str, AlertRule] = {}
        self._handlers: list[Callable[[dict], None]] = []
        self._history: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def add_rule(self, name: str, metric: str, condition: str, threshold: float,
                  severity: str = "warning", cooldown: int = 300) -> None:
        self._rules[name] = AlertRule(name, metric, condition, threshold, severity, cooldown)

    def remove_rule(self, name: str) -> bool:
        return self._rules.pop(name, None) is not None

    def add_handler(self, handler: Callable[[dict], None]) -> None:
        """Add alert handler (log, webhook, Slack, etc.)."""
        self._handlers.append(handler)

    def check(self, metrics: dict[str, float]) -> list[dict[str, Any]]:
        """Check metrics against all rules. Returns fired alerts."""
        fired = []
        now = time.time()

        for rule in self._rules.values():
            value = metrics.get(rule.metric)
            if value is None:
                continue

            if now - rule.last_fired < rule.cooldown:
                continue

            triggered = self._evaluate(value, rule.condition, rule.threshold)
            if triggered:
                alert = {
                    "alert_id": generate_id("alert"),
                    "rule": rule.name,
                    "metric": rule.metric,
                    "value": value,
                    "threshold": rule.threshold,
                    "condition": rule.condition,
                    "severity": rule.severity,
                    "message": f"{rule.name}: {rule.metric}={value} {rule.condition} {rule.threshold}",
                    "timestamp": now,
                }
                fired.append(alert)
                rule.last_fired = now

                # Dispatch to handlers
                for handler in self._handlers:
                    try:
                        handler(alert)
                    except Exception as exc:
                        logger.error("Alert handler failed: %s", exc)

                with self._lock:
                    self._history.append(alert)
                    if len(self._history) > 1000:
                        self._history = self._history[-1000:]

        return fired

    def setup_ecommerce_defaults(self) -> None:
        """Set up default e-commerce alert rules."""
        self.add_rule("stockout_warning", "stockout_products", "gt", 0, "critical", 3600)
        self.add_rule("low_conversion", "conversion_rate", "lt", 1.0, "warning", 3600)
        self.add_rule("high_bounce", "bounce_rate", "gt", 70, "warning", 3600)
        self.add_rule("low_roas", "roas", "lt", 1.5, "critical", 3600)
        self.add_rule("churn_spike", "churn_rate", "gt", 10, "warning", 3600)
        self.add_rule("revenue_drop", "revenue_change_pct", "lt", -20, "critical", 3600)
        self.add_rule("seo_degraded", "avg_seo_score", "lt", 40, "warning", 86400)
        self.add_rule("high_cpa", "cpa", "gt", 50, "warning", 3600)

    def get_history(self, severity: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            alerts = list(self._history)
        if severity:
            alerts = [a for a in alerts if a["severity"] == severity]
        return alerts[-limit:]

    def list_rules(self) -> list[dict[str, Any]]:
        return [{"name": r.name, "metric": r.metric, "condition": r.condition,
                 "threshold": r.threshold, "severity": r.severity}
                for r in self._rules.values()]

    @staticmethod
    def _evaluate(value: float, condition: str, threshold: float) -> bool:
        if condition == "gt": return value > threshold
        if condition == "lt": return value < threshold
        if condition == "gte": return value >= threshold
        if condition == "lte": return value <= threshold
        if condition == "eq": return value == threshold
        return False


# Default log handler
def log_handler(alert: dict) -> None:
    severity = alert.get("severity", "info")
    msg = alert.get("message", "")
    if severity == "critical":
        logger.error("ALERT [CRITICAL]: %s", msg)
    else:
        logger.warning("ALERT [%s]: %s", severity, msg)
