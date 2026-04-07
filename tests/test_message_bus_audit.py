"""Tests for audit-pass-29 fixes in agents/communication/message_bus.

  1. publish() iterated `_topics.get(topic, [])` and called
     subscriber callbacks while another thread could be mutating
     the same list — concurrent subscribe/unsubscribe would
     crash with RuntimeError ("dictionary/list changed size
     during iteration").
  2. Subscriber callbacks raised inside a `try: except: pass`
     swallow — broken handlers were invisible.
  3. _message_queue grew unbounded — long-running daemons with
     high-volume topics slowly leaked memory.
  4. publish() shallow-copied the payload — publisher mutating
     the original dict bled into the stored envelope.
  5. get_messages returned shallow-copied envelopes — caller
     mutation poisoned the in-memory queue.
  6. subscribe / unsubscribe / get_messages used direct dict
     access on subscriber records — KeyError on a malformed
     subscriber entry.
"""
import threading
import time

import pytest


def _bus(**kwargs):
    from agents.communication.message_bus import MessageBus
    return MessageBus(**kwargs)


# ── Concurrency safety ──────────────────────────────────────


class TestConcurrencySafety:
    def test_concurrent_publish_subscribe_no_crash(self):
        """Regression: previously the publish loop iterated the
        subscriber list while another thread mutated it, raising
        RuntimeError mid-publish."""
        bus = _bus()
        errors: list[Exception] = []

        def publisher():
            try:
                for i in range(100):
                    bus.publish("topic.x", {"i": i}, sender="p")
            except Exception as exc:
                errors.append(exc)

        def subscriber():
            try:
                for i in range(100):
                    bus.subscribe("topic.x", f"sub_{i}", callback=lambda m: None)
                    bus.unsubscribe("topic.x", f"sub_{i}")
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=publisher)
        t2 = threading.Thread(target=subscriber)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert errors == []

    def test_callbacks_run_outside_lock(self):
        """A callback that re-publishes via the bus shouldn't
        deadlock — the lock is RLock + callbacks fire outside
        the critical section."""
        bus = _bus()
        nested_received = []

        def echo_callback(msg):
            # Re-publish to a different topic — would have
            # deadlocked under a non-reentrant lock.
            bus.publish("topic.echo", {"echoed": msg["id"]}, sender="cb")
            nested_received.append(msg["id"])

        bus.subscribe("topic.original", "echoer", callback=echo_callback)
        bus.publish("topic.original", {"v": 1}, sender="p")
        assert len(nested_received) == 1
        # And the echo'd message landed in the bus
        bus.subscribe("topic.echo", "tail", callback=None)
        # Subscriber added AFTER publish — won't see the echo via
        # callback, but the message is still in the queue.
        all_echo = bus.get_messages("tail")
        assert len(all_echo) == 1
        assert all_echo[0]["payload"]["echoed"] is not None


# ── Callback failure visibility ─────────────────────────────


class TestCallbackFailureVisibility:
    def test_broken_callback_logs_warning(self, monkeypatch):
        from agents.communication import message_bus as mb_mod

        warnings: list[str] = []
        monkeypatch.setattr(
            mb_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        bus = mb_mod.MessageBus()

        def broken(message):
            raise RuntimeError("callback boom")

        bus.subscribe("topic.x", "broken_sub", callback=broken)
        bus.publish("topic.x", {"v": 1}, sender="p")

        assert any("broken_sub" in w and "callback boom" in w for w in warnings)

    def test_one_broken_callback_does_not_block_others(self):
        bus = _bus()
        good_received = []

        def broken(message):
            raise RuntimeError("nope")

        def good(message):
            good_received.append(message["id"])

        bus.subscribe("topic.x", "bad", callback=broken)
        bus.subscribe("topic.x", "good", callback=good)
        bus.publish("topic.x", {"v": 1}, sender="p")
        assert len(good_received) == 1


# ── Bounded queue ───────────────────────────────────────────


class TestBoundedQueue:
    def test_queue_capped_per_topic(self):
        bus = _bus(max_messages_per_topic=10)
        for i in range(50):
            bus.publish("topic.x", {"i": i}, sender="p")
        # Subscribe AFTER publishing so we read from the queue
        bus.subscribe("topic.x", "tail")
        msgs = bus.get_messages("tail")
        # Cap holds; only the last 10 are retained
        assert len(msgs) == 10
        # FIFO retention — keep the most recent
        retained_indices = [m["payload"]["i"] for m in msgs]
        assert retained_indices == list(range(40, 50))


# ── Defensive payload copies ────────────────────────────────


class TestPayloadDefensiveCopies:
    def test_publisher_mutation_after_publish_does_not_leak(self):
        bus = _bus()
        bus.subscribe("topic.x", "tail")

        msg = {"items": ["a", "b"]}
        bus.publish("topic.x", msg, sender="p")
        msg["items"].append("MUTATED")
        msg["new_key"] = "leak"

        retrieved = bus.get_messages("tail")
        assert retrieved[0]["payload"]["items"] == ["a", "b"]
        assert "new_key" not in retrieved[0]["payload"]

    def test_get_messages_returns_independent_copies(self):
        bus = _bus()
        bus.subscribe("topic.x", "tail")
        bus.publish("topic.x", {"items": ["x"]}, sender="p")

        m1 = bus.get_messages("tail")
        m1[0]["payload"]["items"].append("POISON")
        m1[0]["payload"]["new"] = "leak"

        m2 = bus.get_messages("tail")
        assert m2[0]["payload"]["items"] == ["x"]
        assert "new" not in m2[0]["payload"]

    def test_non_dict_message_wrapped(self):
        bus = _bus()
        bus.subscribe("topic.x", "tail")
        # Previously: dict("not a dict") crashed with TypeError
        msg_id = bus.publish("topic.x", "not a dict", sender="p")
        assert msg_id.startswith("msg-")
        retrieved = bus.get_messages("tail")
        assert retrieved[0]["payload"] == {"raw": "not a dict"}


# ── Defensive .get on subscriber records ───────────────────


class TestSubscriberRecordDefensive:
    def test_subscribe_handles_missing_id_in_existing_records(self):
        bus = _bus()
        # Inject a malformed subscriber directly (no subscriber_id)
        bus._topics["x"] = [{"callback": None}]
        # Subscribe normally — should not crash on the malformed entry
        bus.subscribe("x", "real_sub", callback=None)
        assert any(s.get("subscriber_id") == "real_sub" for s in bus._topics["x"])

    def test_unsubscribe_handles_missing_id(self):
        bus = _bus()
        bus._topics["x"] = [
            {"callback": None},
            {"subscriber_id": "real", "callback": None},
        ]
        bus.unsubscribe("x", "real")
        # Real subscriber removed; malformed entry is also dropped
        # because it has no matching subscriber_id (filter keeps
        # entries whose .get(...) doesn't match — including the
        # malformed one with .get returning None).
        ids = [s.get("subscriber_id") for s in bus._topics["x"]]
        assert "real" not in ids


# ── Stats helper ────────────────────────────────────────────


class TestStats:
    def test_stats_reports_topic_depths(self):
        bus = _bus()
        bus.subscribe("a", "s1")
        bus.subscribe("b", "s2")
        bus.publish("a", {"x": 1}, sender="p")
        bus.publish("a", {"x": 2}, sender="p")
        bus.publish("b", {"y": 1}, sender="p")

        stats = bus.get_stats()
        assert stats["topics"]["a"]["queued_messages"] == 2
        assert stats["topics"]["a"]["subscribers"] == 1
        assert stats["topics"]["b"]["queued_messages"] == 1
        assert stats["topics"]["b"]["subscribers"] == 1
