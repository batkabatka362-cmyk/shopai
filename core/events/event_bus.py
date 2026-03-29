"""EventBus — central publish/subscribe event system.

Engines publish events, other engines/systems subscribe and react.
Thread-safe, async-capable, with event history for debugging.
"""
from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger
from utils.helpers import generate_id
from .event_types import EventType

logger = get_logger("events.bus")

Subscriber = Callable[["Event"], None]


@dataclass
class Event:
    """An event in the system."""
    event_type: EventType
    source: str
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: generate_id("evt"))
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """Thread-safe publish/subscribe event bus. Singleton."""

    _instance: EventBus | None = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> EventBus:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self) -> None:
        self._subscribers: dict[EventType, list[tuple[str, Subscriber]]] = {}
        self._wildcard_subscribers: list[tuple[str, Subscriber]] = []
        self._history: list[Event] = []
        self._lock = threading.Lock()
        self._stats = {"published": 0, "delivered": 0, "errors": 0}
        self._max_history = 5000

    def subscribe(self, event_type: EventType, subscriber_id: str, callback: Subscriber) -> None:
        """Subscribe to a specific event type."""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append((subscriber_id, callback))
        logger.info("Subscribed %s to %s", subscriber_id, event_type.value)

    def subscribe_all(self, subscriber_id: str, callback: Subscriber) -> None:
        """Subscribe to ALL events (wildcard)."""
        with self._lock:
            self._wildcard_subscribers.append((subscriber_id, callback))

    def unsubscribe(self, event_type: EventType, subscriber_id: str) -> bool:
        """Unsubscribe from an event type."""
        with self._lock:
            subs = self._subscribers.get(event_type, [])
            before = len(subs)
            self._subscribers[event_type] = [(sid, cb) for sid, cb in subs if sid != subscriber_id]
            return len(self._subscribers[event_type]) < before

    def publish(self, event: Event) -> int:
        """Publish an event. Returns number of subscribers notified."""
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            self._stats["published"] += 1

            targets = list(self._subscribers.get(event.event_type, []))
            wildcards = list(self._wildcard_subscribers)

        delivered = 0
        for subscriber_id, callback in targets + wildcards:
            try:
                callback(copy.deepcopy(event))
                delivered += 1
            except Exception as exc:
                logger.error("Event delivery failed to %s: %s", subscriber_id, exc)
                with self._lock:
                    self._stats["errors"] += 1

        with self._lock:
            self._stats["delivered"] += delivered

        return delivered

    def emit(self, event_type: EventType, source: str, data: dict[str, Any] | None = None) -> str:
        """Shorthand: create and publish an event. Returns event_id."""
        event = Event(event_type=event_type, source=source, data=data or {})
        self.publish(event)
        return event.event_id

    def get_history(self, event_type: EventType | None = None, source: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Get event history with optional filters."""
        with self._lock:
            events = list(self._history)

        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if source:
            events = [e for e in events if e.source == source]

        return [
            {"event_id": e.event_id, "type": e.event_type.value, "source": e.source,
             "data_keys": list(e.data.keys()), "timestamp": e.timestamp}
            for e in events[-limit:]
        ]

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._stats,
                "subscriber_count": sum(len(subs) for subs in self._subscribers.values()) + len(self._wildcard_subscribers),
                "event_types_active": len(self._subscribers),
                "history_size": len(self._history),
            }

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()
            self._wildcard_subscribers.clear()
            self._history.clear()
