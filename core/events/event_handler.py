"""EventHandler — built-in event handlers for system reactions."""
from __future__ import annotations
from typing import Any

from utils.logger import get_logger
from .event_bus import Event, EventBus
from .event_types import EventType

logger = get_logger("events.handler")


class EventHandler:
    """Registers built-in event handlers for system automation."""

    def __init__(self) -> None:
        self._bus = EventBus()

    def register_defaults(self) -> None:
        """Register default system event handlers."""
        self._bus.subscribe(EventType.ENGINE_FAILED, "error_logger", self._on_engine_failed)
        self._bus.subscribe(EventType.DATA_ANOMALY, "anomaly_logger", self._on_data_anomaly)
        self._bus.subscribe(EventType.SYSTEM_ALERT, "alert_handler", self._on_system_alert)
        self._bus.subscribe(EventType.CACHE_EVICTION, "cache_monitor", self._on_cache_eviction)
        logger.info("Default event handlers registered")

    @staticmethod
    def _on_engine_failed(event: Event) -> None:
        engine = event.data.get("engine_name", "unknown")
        error = event.data.get("error", "unknown error")
        logger.error("ENGINE FAILED: %s — %s", engine, error[:100])

    @staticmethod
    def _on_data_anomaly(event: Event) -> None:
        field = event.data.get("field", "unknown")
        value = event.data.get("value", "?")
        logger.warning("DATA ANOMALY: %s = %s (z=%.1f)", field, value, event.data.get("z_score", 0))

    @staticmethod
    def _on_system_alert(event: Event) -> None:
        alert_type = event.data.get("alert_type", "unknown")
        message = event.data.get("message", "")
        logger.warning("SYSTEM ALERT [%s]: %s", alert_type, message)

    @staticmethod
    def _on_cache_eviction(event: Event) -> None:
        count = event.data.get("evicted_count", 0)
        if count > 10:
            logger.warning("CACHE: %d entries evicted — consider increasing cache size", count)
