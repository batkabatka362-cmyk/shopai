"""EventHandler — built-in event handlers for system reactions."""
from __future__ import annotations
from typing import Any

from utils.logger import get_logger
from .event_bus import Event, EventBus
from .event_types import EventType

logger = get_logger("events.handler")


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce a value to int, returning default on failure."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (ValueError, OverflowError):
            return default
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce a value to float, returning default on failure."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


class EventHandler:
    """Registers built-in event handlers for system automation."""

    def __init__(self) -> None:
        self._bus = EventBus()
        self._registered = False

    def register_defaults(self) -> None:
        """Register default system event handlers.

        Idempotent — calling this twice on the same instance
        is a no-op so the bus doesn't accumulate duplicate
        subscriptions and double-fire every event.
        """
        if self._registered:
            return
        self._bus.subscribe(EventType.ENGINE_FAILED, "error_logger", self._on_engine_failed)
        self._bus.subscribe(EventType.DATA_ANOMALY, "anomaly_logger", self._on_data_anomaly)
        self._bus.subscribe(EventType.SYSTEM_ALERT, "alert_handler", self._on_system_alert)
        self._bus.subscribe(EventType.CACHE_EVICTION, "cache_monitor", self._on_cache_eviction)
        self._registered = True
        logger.info("Default event handlers registered")

    @staticmethod
    def _on_engine_failed(event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        engine = data.get("engine_name", "unknown")
        error = data.get("error", "unknown error")
        # Defensive: ``error[:100]`` crashes if error is an
        # exception object, dict, or None. Stringify first.
        error_str = str(error) if error is not None else "unknown error"
        logger.error("ENGINE FAILED: %s — %s", engine, error_str[:100])

    @staticmethod
    def _on_data_anomaly(event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        field_name = data.get("field", "unknown")
        value = data.get("value", "?")
        # ``%f`` format crashes on None / non-numeric — coerce.
        z_score = _safe_float(data.get("z_score"))
        logger.warning("DATA ANOMALY: %s = %s (z=%.1f)", field_name, value, z_score)

    @staticmethod
    def _on_system_alert(event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        alert_type = data.get("alert_type", "unknown")
        message = data.get("message", "")
        logger.warning("SYSTEM ALERT [%s]: %s", alert_type, message)

    @staticmethod
    def _on_cache_eviction(event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        # ``count > 10`` crashes when count is None or a
        # string in Python 3 (TypeError on cross-type compare).
        count = _safe_int(data.get("evicted_count"))
        if count > 10:
            logger.warning("CACHE: %d entries evicted — consider increasing cache size", count)
