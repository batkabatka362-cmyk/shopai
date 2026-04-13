"""Notification System — delivers alerts via multiple channels.

Channels:
  - Log (always) — stored in memory
  - File — written to alerts.json
  - Console — printed for debugging
  - Webhook — POST to external URL (Slack, Discord, etc.)
"""
from __future__ import annotations
import json
import threading as _threading
import time
from pathlib import Path
from typing import Any
from utils.logger import get_logger
logger = get_logger("notifications")

_ALERTS_FILE = Path(__file__).resolve().parents[2] / "data" / "alerts.json"


class NotificationSystem:
    """Multi-channel notification delivery."""

    def __init__(self) -> None:
        self._channels: dict[str, dict] = {
            "log": {"enabled": True},
            "file": {"enabled": True, "path": str(_ALERTS_FILE)},
            "webhook": {"enabled": False, "url": ""},
        }
        self._sent: list[dict] = []

    def configure_webhook(self, url: str) -> None:
        self._channels["webhook"] = {"enabled": True, "url": url}

    def send(self, severity: str, category: str, message: str,
             data: dict | None = None) -> dict[str, Any]:
        """Send notification to all enabled channels."""
        notification = {
            "severity": severity,
            "category": category,
            "message": message,
            "data": data or {},
            "timestamp": time.time(),
            "delivered_to": [],
        }

        # Log channel (always)
        if severity == "critical":
            logger.error("ALERT [%s]: %s", category, message)
        elif severity == "warning":
            logger.warning("ALERT [%s]: %s", category, message)
        else:
            logger.info("ALERT [%s]: %s", category, message)
        notification["delivered_to"].append("log")

        # File channel
        if self._channels["file"]["enabled"]:
            self._write_file(notification)
            notification["delivered_to"].append("file")

        # Webhook channel
        if self._channels["webhook"]["enabled"]:
            url = self._channels["webhook"]["url"]
            if url:
                success = self._send_webhook(url, notification)
                if success:
                    notification["delivered_to"].append("webhook")

        # Store in memory
        self._record(notification)
        self._sent.append(notification)

        return {"delivered": len(notification["delivered_to"]),
                "channels": notification["delivered_to"]}

    def send_cycle_summary(self, cycle_result: dict) -> dict[str, Any]:
        """Send cycle completion notification."""
        phases = cycle_result.get("phases", {})
        duration = cycle_result.get("duration_s", 0)
        layers = phases.get("layers", {}).get("layers_run", 0)
        insights = phases.get("layers", {}).get("total_insights", 0)

        message = "Cycle complete: {}s, {}/12 layers, {} insights".format(
            duration, layers, insights)

        # Check for issues
        alerts = phases.get("alerts", {})
        if alerts.get("critical", 0) > 0:
            return self.send("critical", "cycle", message, cycle_result)
        elif alerts.get("warnings", 0) > 0:
            return self.send("warning", "cycle", message)
        return self.send("info", "cycle", message)

    @staticmethod
    def _write_file(notification: dict):
        try:
            _ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            existing = []
            if _ALERTS_FILE.exists():
                try:
                    existing = json.loads(_ALERTS_FILE.read_text())
                except Exception:
                    existing = []
            existing.append({
                "severity": notification["severity"],
                "category": notification["category"],
                "message": notification["message"],
                "timestamp": notification["timestamp"],
            })
            # Keep last 100
            if len(existing) > 100:
                existing = existing[-100:]
            _ALERTS_FILE.write_text(json.dumps(existing, indent=2))
        except Exception as exc:
            logger.debug("alert persistence failed: %s", exc)

    @staticmethod
    def _send_webhook(url: str, notification: dict) -> bool:
        try:
            import urllib.request
            payload = json.dumps({
                "text": "[{}] {}: {}".format(
                    notification["severity"].upper(),
                    notification["category"],
                    notification["message"]),
            }).encode()
            req = urllib.request.Request(url, data=payload, method="POST",
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception:
            return False

    @staticmethod
    def _record(notification: dict):
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            da.capture("feedback", {
                "source": "notification",
                "topic": notification["category"],
                "sentiment": "negative" if notification["severity"] == "critical" else "neutral",
                "urgency": notification["severity"],
            }, source="notifications", score=4.0)
        except Exception as exc:
            logger.debug("data-architecture capture failed: %s", exc)

    def get_history(self, limit: int = 20) -> list[dict]:
        return self._sent[-limit:]

    def get_stats(self) -> dict[str, Any]:
        by_sev = {}
        for n in self._sent:
            s = n.get("severity", "info")
            by_sev[s] = by_sev.get(s, 0) + 1
        return {"sent": len(self._sent), "by_severity": by_sev,
                "channels": {k: v["enabled"] for k, v in self._channels.items()}}


_instance = None
_instance_lock = _threading.Lock()


def get_notifications():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = NotificationSystem()
    return _instance
