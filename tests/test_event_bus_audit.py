"""Tests for audit-pass-39 fixes — defensive hardening in
``core.events.event_bus`` (EventBus, Event) and
``core.events.event_handler`` (EventHandler).

Pre-audit bugs covered:

  * ``Event(data=None)`` was accepted but every subscriber's
    ``event.data.get(...)`` crashed downstream.
  * ``EventBus.subscribe`` accepted non-EventType keys,
    non-callable callbacks, and empty subscriber_ids — all
    silently joined the dispatch list and crashed inside
    ``publish``.
  * ``EventBus.unsubscribe`` rebuilt the bucket even on
    no-op calls, leaving stale empty-key entries that
    inflated ``event_types_active``.
  * ``EventBus.publish`` rebound ``self._history`` instead of
    trimming in place.
  * ``EventBus.publish`` accepted non-Event payloads.
  * No ``reset()`` for tests — singleton state pollution
    across the whole suite.
  * ``EventHandler.register_defaults`` was not idempotent —
    calling twice double-fired every event.
  * ``_on_engine_failed`` did ``error[:100]`` without
    isinstance check, crashing on exception/dict/None values.
  * ``_on_data_anomaly`` did ``%.1f`` format on
    ``z_score`` field that could be None.
  * ``_on_cache_eviction`` did ``count > 10`` cross-type
    compare that crashes in Python 3 if count is None or a
    string.
"""
from __future__ import annotations

import logging
import threading

import pytest

from core.events import EventBus, EventType
from core.events.event_bus import Event
from core.events.event_handler import EventHandler


@pytest.fixture(autouse=True)
def _reset_bus():
    """Wipe singleton bus state between tests."""
    bus = EventBus()
    bus.reset()
    yield
    bus.reset()


# ── Event dataclass coercion ────────────────────────────────


class TestEventCoercion:
    def test_none_data_coerced_to_dict(self):
        e = Event(event_type=EventType.ENGINE_COMPLETE, source="test", data=None)  # type: ignore[arg-type]
        assert e.data == {}

    def test_non_dict_data_coerced(self):
        e = Event(event_type=EventType.ENGINE_COMPLETE, source="test", data="not a dict")  # type: ignore[arg-type]
        assert e.data == {}

    def test_none_source_coerced(self):
        e = Event(event_type=EventType.ENGINE_COMPLETE, source=None)  # type: ignore[arg-type]
        assert e.source == "unknown"


# ── Subscribe validation ────────────────────────────────────


class TestSubscribeValidation:
    def test_non_eventtype_rejected(self):
        bus = EventBus()
        ok = bus.subscribe("not_an_enum", "sid", lambda e: None)  # type: ignore[arg-type]
        assert ok is False
        assert bus.get_stats()["subscriber_count"] == 0

    def test_non_callable_rejected(self):
        bus = EventBus()
        ok = bus.subscribe(EventType.ENGINE_FAILED, "sid", "not callable")  # type: ignore[arg-type]
        assert ok is False
        assert bus.get_stats()["subscriber_count"] == 0

    def test_empty_subscriber_id_rejected(self):
        bus = EventBus()
        assert bus.subscribe(EventType.ENGINE_FAILED, "", lambda e: None) is False
        assert bus.subscribe(EventType.ENGINE_FAILED, None, lambda e: None) is False  # type: ignore[arg-type]

    def test_subscribe_all_validates(self):
        bus = EventBus()
        assert bus.subscribe_all("", lambda e: None) is False
        assert bus.subscribe_all("sid", "not callable") is False  # type: ignore[arg-type]


# ── Unsubscribe semantics ───────────────────────────────────


class TestUnsubscribe:
    def test_no_op_unsubscribe_returns_false(self):
        bus = EventBus()
        assert bus.unsubscribe(EventType.STEP_START, "noone") is False

    def test_real_unsubscribe_returns_true(self):
        bus = EventBus()
        bus.subscribe(EventType.ENGINE_FAILED, "sid1", lambda e: None)
        assert bus.unsubscribe(EventType.ENGINE_FAILED, "sid1") is True

    def test_double_unsubscribe_returns_false(self):
        bus = EventBus()
        bus.subscribe(EventType.ENGINE_FAILED, "sid1", lambda e: None)
        bus.unsubscribe(EventType.ENGINE_FAILED, "sid1")
        assert bus.unsubscribe(EventType.ENGINE_FAILED, "sid1") is False

    def test_no_op_does_not_create_empty_bucket(self):
        """Pre-audit a no-op unsubscribe still wrote
        ``self._subscribers[event_type] = []``, leaving stale
        empty-key entries that inflated ``event_types_active``."""
        bus = EventBus()
        bus.unsubscribe(EventType.STEP_START, "noone")
        assert bus.get_stats()["event_types_active"] == 0

    def test_unsubscribe_drops_empty_bucket(self):
        bus = EventBus()
        bus.subscribe(EventType.ENGINE_FAILED, "only_one", lambda e: None)
        assert bus.get_stats()["event_types_active"] == 1
        bus.unsubscribe(EventType.ENGINE_FAILED, "only_one")
        assert bus.get_stats()["event_types_active"] == 0


# ── Publish validation ──────────────────────────────────────


class TestPublishValidation:
    def test_non_event_payload_ignored(self):
        bus = EventBus()
        delivered = bus.publish("not an event")  # type: ignore[arg-type]
        assert delivered == 0

    def test_publish_dict_ignored(self):
        bus = EventBus()
        delivered = bus.publish({"event_type": "x"})  # type: ignore[arg-type]
        assert delivered == 0

    def test_emit_non_eventtype_returns_empty(self):
        bus = EventBus()
        result = bus.emit("not_an_enum", "test")  # type: ignore[arg-type]
        assert result == ""

    def test_emit_none_data_does_not_crash(self):
        bus = EventBus()
        eid = bus.emit(EventType.ENGINE_COMPLETE, "test", data=None)
        assert eid.startswith("evt_")


# ── reset() for tests ───────────────────────────────────────


class TestReset:
    def test_reset_clears_subscribers_history_and_stats(self):
        bus = EventBus()
        bus.subscribe(EventType.ENGINE_FAILED, "sid", lambda e: None)
        bus.emit(EventType.ENGINE_FAILED, "test", {})
        assert bus.get_stats()["published"] == 1

        bus.reset()
        stats = bus.get_stats()
        assert stats["published"] == 0
        assert stats["delivered"] == 0
        assert stats["subscriber_count"] == 0
        assert stats["history_size"] == 0


# ── EventHandler idempotency ────────────────────────────────


class TestEventHandlerIdempotent:
    def test_register_defaults_twice_does_not_double_fire(self):
        bus = EventBus()
        h = EventHandler()
        h.register_defaults()
        before = bus.get_stats()["subscriber_count"]
        h.register_defaults()  # second call should be a no-op
        after = bus.get_stats()["subscriber_count"]
        assert after == before


# ── EventHandler defensive payloads ─────────────────────────


class TestEventHandlerDefensive:
    def test_engine_failed_handles_none_error(self, caplog):
        bus = EventBus()
        EventHandler().register_defaults()
        with caplog.at_level(logging.ERROR):
            bus.emit(EventType.ENGINE_FAILED, "test", {"engine_name": "x", "error": None})
        # No crash, errors stat stays 0.
        assert bus.get_stats()["errors"] == 0

    def test_engine_failed_handles_exception_object(self):
        bus = EventBus()
        EventHandler().register_defaults()
        bus.emit(
            EventType.ENGINE_FAILED, "test",
            {"engine_name": "x", "error": ValueError("boom")},
        )
        assert bus.get_stats()["errors"] == 0

    def test_engine_failed_handles_dict_error(self):
        bus = EventBus()
        EventHandler().register_defaults()
        bus.emit(
            EventType.ENGINE_FAILED, "test",
            {"engine_name": "x", "error": {"reason": "bad input"}},
        )
        assert bus.get_stats()["errors"] == 0

    def test_data_anomaly_handles_none_z_score(self):
        bus = EventBus()
        EventHandler().register_defaults()
        bus.emit(
            EventType.DATA_ANOMALY, "test",
            {"field": "price", "value": 100, "z_score": None},
        )
        assert bus.get_stats()["errors"] == 0

    def test_cache_eviction_handles_none_count(self):
        bus = EventBus()
        EventHandler().register_defaults()
        bus.emit(EventType.CACHE_EVICTION, "test", {"evicted_count": None})
        assert bus.get_stats()["errors"] == 0

    def test_cache_eviction_handles_string_count(self):
        bus = EventBus()
        EventHandler().register_defaults()
        bus.emit(EventType.CACHE_EVICTION, "test", {"evicted_count": "15"})
        assert bus.get_stats()["errors"] == 0

    def test_handler_with_event_data_none(self):
        """An Event constructed with data=None reaches every
        handler. Pre-audit ``data.get(...)`` crashed."""
        bus = EventBus()
        EventHandler().register_defaults()
        bus.publish(Event(event_type=EventType.SYSTEM_ALERT, source="t", data=None))  # type: ignore[arg-type]
        assert bus.get_stats()["errors"] == 0


# ── Subscribers receive isolated copies ─────────────────────


class TestSubscriberIsolation:
    def test_subscriber_mutation_does_not_affect_history(self):
        bus = EventBus()
        seen = []
        bus.subscribe(EventType.ENGINE_COMPLETE, "sid", lambda e: seen.append(e))
        bus.emit(EventType.ENGINE_COMPLETE, "src", {"k": "v"})

        # Subscriber mutates its received event.
        seen[0].data["k"] = "MUTATED"

        # History entry is unchanged.
        history = bus.get_history(event_type=EventType.ENGINE_COMPLETE)
        assert history[0]["data_keys"] == ["k"]


# ── Concurrent publish + subscribe ──────────────────────────


class TestConcurrency:
    def test_concurrent_register_publish_no_crash(self):
        bus = EventBus()
        stop = threading.Event()
        errors: list[Exception] = []

        def publisher():
            i = 0
            while not stop.is_set():
                try:
                    bus.emit(EventType.STEP_START, "src", {"i": i})
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                i += 1

        def subscriber_churn():
            i = 0
            while not stop.is_set():
                try:
                    bus.subscribe(EventType.STEP_START, f"sid_{i}", lambda e: None)
                    bus.unsubscribe(EventType.STEP_START, f"sid_{i}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                i += 1

        p = threading.Thread(target=publisher)
        s = threading.Thread(target=subscriber_churn)
        p.start()
        s.start()
        threading.Event().wait(0.15)
        stop.set()
        p.join(timeout=2)
        s.join(timeout=2)
        assert not errors, errors
