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

    def __post_init__(self) -> None:
        # Defensive: callers occasionally construct an Event
        # with ``data=None`` (e.g. via ``Event(event_type=...,
        # source=..., data=upstream.get("data"))``). Coerce so
        # subscribers' ``event.data.get(...)`` calls can never
        # crash with AttributeError.
        if not isinstance(self.data, dict):
            self.data = {}
        if not isinstance(self.source, str):
            self.source = str(self.source) if self.source is not None else "unknown"


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

    def subscribe(self, event_type: EventType, subscriber_id: str, callback: Subscriber) -> bool:
        """Subscribe to a specific event type.

        Returns True on success, False if the args are
        malformed (non-EventType, missing id, non-callable).
        Pre-audit any of these silently joined the dispatch
        list and crashed inside ``publish``.
        """
        if not isinstance(event_type, EventType):
            logger.warning("subscribe: ignoring non-EventType %r", event_type)
            return False
        if not isinstance(subscriber_id, str) or not subscriber_id:
            logger.warning("subscribe: ignoring empty subscriber_id")
            return False
        if not callable(callback):
            logger.warning("subscribe: ignoring non-callable callback for %s", subscriber_id)
            return False
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append((subscriber_id, callback))
        logger.info("Subscribed %s to %s", subscriber_id, event_type.value)
        return True

    def subscribe_all(self, subscriber_id: str, callback: Subscriber) -> bool:
        """Subscribe to ALL events (wildcard)."""
        if not isinstance(subscriber_id, str) or not subscriber_id:
            return False
        if not callable(callback):
            return False
        with self._lock:
            self._wildcard_subscribers.append((subscriber_id, callback))
        return True

    def unsubscribe(self, event_type: EventType, subscriber_id: str) -> bool:
        """Unsubscribe from an event type.

        Returns True if at least one subscription was removed.
        Pre-audit a no-op call still mutated ``_subscribers``
        by writing back the empty list, leaving stale
        empty-key entries behind.
        """
        if not isinstance(event_type, EventType):
            return False
        with self._lock:
            subs = self._subscribers.get(event_type)
            if not subs:
                return False
            kept = [(sid, cb) for sid, cb in subs if sid != subscriber_id]
            if len(kept) == len(subs):
                return False
            if kept:
                self._subscribers[event_type] = kept
            else:
                # Drop the empty bucket entirely so
                # ``event_types_active`` in stats stays honest.
                del self._subscribers[event_type]
            return True

    def publish(self, event: Event) -> int:
        """Publish an event. Returns number of subscribers notified.

        Coerces a stray non-Event payload into a no-op so an
        upstream bug can't take down the whole bus.
        """
        if not isinstance(event, Event):
            logger.warning("publish: ignoring non-Event payload %r", type(event).__name__)
            return 0
        if not isinstance(event.event_type, EventType):
            logger.warning("publish: ignoring event with non-EventType type %r", event.event_type)
            return 0

        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                # In-place trim — pre-audit the rebind
                # ``self._history = self._history[-N:]``
                # invalidated any external snapshot a caller
                # was iterating.
                del self._history[:len(self._history) - self._max_history]
            self._stats["published"] += 1

            targets = list(self._subscribers.get(event.event_type, []))
            wildcards = list(self._wildcard_subscribers)

        delivered = 0
        for subscriber_id, callback in targets + wildcards:
            try:
                callback(copy.deepcopy(event))
                delivered += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("Event delivery failed to %s: %s", subscriber_id, exc)
                with self._lock:
                    self._stats["errors"] += 1

        with self._lock:
            self._stats["delivered"] += delivered

        return delivered

    def emit(self, event_type: EventType, source: str, data: dict[str, Any] | None = None) -> str:
        """Shorthand: create and publish an event. Returns event_id."""
        if not isinstance(event_type, EventType):
            logger.warning("emit: ignoring non-EventType %r", event_type)
            return ""
        if not isinstance(data, dict):
            data = {}
        event = Event(event_type=event_type, source=source, data=data)
        self.publish(event)
        return event.event_id

    def get_history(
        self,
        event_type: EventType | None = None,
        source: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get event history with optional filters."""
        if not isinstance(limit, int) or limit <= 0:
            return []
        with self._lock:
            events = list(self._history)

        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        if source:
            events = [e for e in events if e.source == source]

        return [
            {
                "event_id": e.event_id,
                "type": e.event_type.value,
                "source": e.source,
                "data_keys": list(e.data.keys()) if isinstance(e.data, dict) else [],
                "timestamp": e.timestamp,
            }
            for e in events[-limit:]
        ]

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._stats,
                "subscriber_count": (
                    sum(len(subs) for subs in self._subscribers.values())
                    + len(self._wildcard_subscribers)
                ),
                "event_types_active": len(self._subscribers),
                "history_size": len(self._history),
            }

    def clear(self) -> None:
        """Drop subscribers + history. Stats are preserved."""
        with self._lock:
            self._subscribers.clear()
            self._wildcard_subscribers.clear()
            self._history.clear()

    def reset(self) -> None:
        """Wipe ALL bus state including stats. Intended for tests.

        ``clear()`` only drops subscribers / history so the
        running app can keep its lifetime stats. Tests
        sharing a singleton bus need a real reset.
        """
        with self._lock:
            self._subscribers.clear()
            self._wildcard_subscribers.clear()
            self._history.clear()
            self._stats = {"published": 0, "delivered": 0, "errors": 0}
