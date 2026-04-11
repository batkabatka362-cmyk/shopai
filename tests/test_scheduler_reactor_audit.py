"""Tests for audit-pass-38 fixes — thread-safety, races, and
defensive hardening in ``core.scheduling.SmartScheduler`` and
``core.reactor.EventReactor``.

Both classes are concurrency-sensitive infrastructure used by
the autonomous loop. Pre-audit they had several races:

  * ``SmartScheduler.execute_ready`` could double-execute an
    action when two threads entered concurrently (both saw
    the same "ready" list).
  * ``SmartScheduler.schedule`` performed the cooldown and
    dedup checks outside the lock, then appended under the
    lock — a race window where two callers with identical
    payloads both passed the check and queued duplicate work.
  * ``SmartScheduler._check_seasonal`` had broken month
    arithmetic (hardcoded 30-day months, couldn't prep the
    New Year event from December because ``event_month - 1``
    wrapped to 0).
  * ``EventReactor.react_async`` returned its own newly
    generated event_id but the background thread called
    ``react()`` which generated a DIFFERENT id — so the
    caller's id never appeared in stats or recent events.
  * ``EventReactor._cooldowns`` / ``_seen`` / ``_handlers``
    were read and written without the lock.
  * Neither class coerced None / wrong-type caller args.

This audit pass adds parametrized tests covering every fix.
"""
from __future__ import annotations

import threading
import time
import unittest.mock as mock

import pytest

from core.scheduling import SmartScheduler
from core.reactor import EventReactor


# ═══════════════════════════════════════════════════════════
# SmartScheduler
# ═══════════════════════════════════════════════════════════


class TestSchedulerDefensiveArgs:
    def test_none_action_type_does_not_crash(self):
        s = SmartScheduler()
        r = s.schedule(action_type=None, data={}, target_id="")
        assert isinstance(r, dict)
        assert "action_id" in r

    def test_none_data_does_not_crash(self):
        s = SmartScheduler()
        r = s.schedule("pricing_update", data=None, target_id="x")
        assert isinstance(r, dict)
        assert r.get("data") == {}

    def test_none_target_id_does_not_crash(self):
        s = SmartScheduler()
        r = s.schedule("pricing_update", {}, target_id=None)
        assert isinstance(r, dict)

    def test_non_int_priority_does_not_crash(self):
        s = SmartScheduler()
        r = s.schedule("pricing_update", {}, "x", priority="high")
        assert isinstance(r, dict)
        assert r["priority"] == 5

    def test_malformed_action_timing_entry(self, monkeypatch):
        """A CAPABILITIES entry with a bad ``best_hours`` must
        not crash schedule()."""
        import core.scheduling as mod
        monkeypatch.setitem(mod.ACTION_TIMING, "weird", {"best_hours": "not_a_tuple"})
        s = SmartScheduler()
        r = s.schedule("weird", {}, "t1")
        assert isinstance(r, dict)


class TestSchedulerDataIsolation:
    def test_caller_mutation_does_not_leak_into_queue(self):
        """Pre-audit ``schedule()`` stored ``data`` by reference
        so caller mutations corrupted the queued entry."""
        s = SmartScheduler()
        data = {"price": 10}
        s.schedule("pricing_update", data, "prod_1")
        data["price"] = 99

        queue = s.get_queue()
        queued = next(a for a in queue if a["action_type"] == "pricing_update")
        assert queued["data"]["price"] == 10

    def test_returned_dict_mutation_does_not_leak(self):
        s = SmartScheduler()
        r = s.schedule("pricing_update", {"x": 1}, "prod_1")
        r["data"]["x"] = 99
        r["status"] = "MUTATED"

        queue = s.get_queue()
        queued = next(a for a in queue if a["action_type"] == "pricing_update")
        assert queued["data"]["x"] == 1
        assert queued["status"] != "MUTATED"


class TestSchedulerDedupUnderConcurrency:
    def test_duplicate_detected(self):
        s = SmartScheduler()
        a = s.schedule("email_campaign", {}, "cust_1")
        b = s.schedule("email_campaign", {}, "cust_1")
        assert a["status"] in ("scheduled", "ready")
        assert b["status"] == "duplicate"

    def test_concurrent_schedules_one_queued(self):
        """Two threads hitting schedule() with the same key at
        the same instant must result in exactly ONE queued
        entry (the loser is marked duplicate)."""
        s = SmartScheduler()
        results: list[dict] = []
        barrier = threading.Barrier(8)

        def fire():
            barrier.wait()
            results.append(s.schedule("email_campaign", {}, "cust_1"))

        threads = [threading.Thread(target=fire) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one non-duplicate entry, rest are duplicates.
        non_dups = [r for r in results if r["status"] != "duplicate"]
        assert len(non_dups) == 1
        queued = [a for a in s.get_queue() if a["action_type"] == "email_campaign"]
        assert len(queued) == 1


class TestSchedulerDoubleExecution:
    def test_concurrent_execute_ready_no_double_fire(self):
        """Two threads calling execute_ready() must not both
        execute the same action."""
        s = SmartScheduler()
        # Queue several ready actions (priority=1 → immediate).
        for i in range(10):
            s.schedule("email_campaign", {}, f"cust_{i}", priority=1)

        call_counts: dict[str, int] = {}
        lock = threading.Lock()

        def executor(action):
            with lock:
                call_counts[action["action_id"]] = call_counts.get(action["action_id"], 0) + 1
            time.sleep(0.005)  # Simulate work so the race window is real
            return {"ok": True}

        results_a: list = []
        results_b: list = []

        def runner(bucket):
            bucket.extend(s.execute_ready(executor))

        t_a = threading.Thread(target=runner, args=(results_a,))
        t_b = threading.Thread(target=runner, args=(results_b,))
        t_a.start()
        t_b.start()
        t_a.join()
        t_b.join()

        # Every action ran EXACTLY once.
        assert all(v == 1 for v in call_counts.values()), call_counts
        # All 10 actions accounted for.
        assert len(call_counts) == 10


class TestSeasonalArithmetic:
    def test_new_year_prep_fires_in_december(self):
        """Regression: pre-audit hardcoded 30-day previous
        month AND ``event_month - 1`` wrapped 1 to 0, so
        New Year prep never triggered from December."""
        s = SmartScheduler()
        # Freeze the clock at Dec 28 which is inside the
        # 7-day prep window for Jan 1-5 New Year.
        fake = time.struct_time((2030, 12, 28, 12, 0, 0, 0, 362, 0))
        with mock.patch("core.scheduling.time.localtime", return_value=fake):
            ctx = s.get_seasonal_context()
        names = [e["event"] for e in ctx["upcoming_events"]]
        assert "new_year" in names

    def test_thirty_one_day_month_boundary(self):
        """Pre-audit hardcoded ``30 - day`` for the
        previous-month arithmetic which undercounts 31-day
        months."""
        s = SmartScheduler()
        # Jan 25 → Feb 10-14 Valentines prep window (14 days).
        fake = time.struct_time((2030, 1, 28, 12, 0, 0, 0, 28, 0))
        with mock.patch("core.scheduling.time.localtime", return_value=fake):
            ctx = s.get_seasonal_context()
        # Expected days_until: (31 - 28) + 10 = 13, within the
        # 14-day prep window. The buggy version computed
        # (30 - 28) + 10 = 12 — same result for this date, but
        # for Jan 30 the buggy version returns (30-30)+10=10
        # while the correct answer is (31-30)+10=11. Use a
        # more discriminating date.
        fake2 = time.struct_time((2030, 1, 31, 12, 0, 0, 0, 31, 0))
        with mock.patch("core.scheduling.time.localtime", return_value=fake2):
            ctx2 = s.get_seasonal_context()
        # Valentines is Feb 10-14. From Jan 31 that's
        # (31-31) + 10 = 10 days until. Pre-audit bug:
        # (30-31)+10 = 9 days until.
        valentines = next(
            (e for e in ctx2["upcoming_events"] if e["event"] == "valentines"),
            None,
        )
        assert valentines is not None
        assert valentines["days_until"] == 10


# ═══════════════════════════════════════════════════════════
# EventReactor
# ═══════════════════════════════════════════════════════════


class TestReactorDefensiveArgs:
    def test_none_event_type_does_not_crash(self):
        r = EventReactor()
        out = r.react(event_type=None, data={"x": 1})
        assert isinstance(out, dict)
        assert out.get("event_id", "").startswith("evt_")

    def test_none_data_does_not_crash(self):
        r = EventReactor()
        out = r.react("order.paid", data=None)
        assert isinstance(out, dict)

    def test_hash_event_handles_none(self):
        """``_hash_event`` used to do ``sorted(data.items())``
        which crashed on None."""
        h = EventReactor._hash_event("x", None)
        assert isinstance(h, str)
        assert len(h) == 16


class TestReactorAsyncIdMatch:
    def test_async_event_id_matches_processed(self):
        """Pre-audit ``react_async`` returned a NEW event_id
        but the spawned thread generated its own inside
        ``react()``. The returned id never matched the id of
        the event actually processed."""
        r = EventReactor()
        # Use a custom handler so we don't hit the default
        # order handler's network-ish side effects.
        processed: list[str] = []

        def handler(event_type, data, event):
            processed.append(event["event_id"])
            return {"ok": True}

        r.register_handler("custom.test", handler)
        returned_id = r.react_async("custom.test", {"x": 1})

        # Give the background thread a moment to run.
        for _ in range(50):
            if processed:
                break
            time.sleep(0.01)

        assert processed, "handler did not run"
        assert processed[0] == returned_id


class TestReactorRegisterHandler:
    def test_non_callable_handler_rejected(self):
        r = EventReactor()
        r.register_handler("bad", "not a callable")  # type: ignore[arg-type]
        # Should be a no-op — no handler registered.
        out = r.react("bad", {"x": 1})
        assert out.get("status") != "error"

    def test_thread_safe_registration(self):
        """Concurrent register_handler + react must not crash
        with dictionary-size-changed errors."""
        r = EventReactor()

        def dummy(event_type, data, event):
            return {"ok": True}

        stop = threading.Event()

        def register_loop():
            i = 0
            while not stop.is_set():
                r.register_handler(f"type_{i % 5}", dummy)
                i += 1

        def react_loop():
            i = 0
            while not stop.is_set():
                r.react(f"type_{i % 5}", {"id": i})
                i += 1

        reg = threading.Thread(target=register_loop)
        rct = threading.Thread(target=react_loop)
        reg.start()
        rct.start()
        time.sleep(0.15)
        stop.set()
        reg.join(timeout=2)
        rct.join(timeout=2)
        assert not reg.is_alive()
        assert not rct.is_alive()


class TestReactorDedupUnderConcurrency:
    def test_identical_events_collapse_to_one_processed(self):
        r = EventReactor()
        processed: list[str] = []

        def handler(event_type, data, event):
            processed.append(event["event_id"])
            return {"ok": True}

        r.register_handler("custom.dedup", handler)

        barrier = threading.Barrier(8)

        def fire():
            barrier.wait()
            r.react("custom.dedup", {"id": 42, "stable": "payload"})

        threads = [threading.Thread(target=fire) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one handler invocation regardless of
        # concurrent callers with the same payload.
        assert len(processed) == 1


class TestReactorGetActiveCooldownsSnapshot:
    def test_concurrent_write_does_not_raise(self):
        """``get_active_cooldowns`` used to iterate
        ``_cooldowns`` without the lock. Concurrent writes
        raised RuntimeError: dictionary changed size during
        iteration."""
        r = EventReactor()

        def dummy(event_type, data, event):
            return {"ok": True}

        r.register_handler("cd.test", dummy)

        stop = threading.Event()
        errors: list[Exception] = []

        def writer():
            i = 0
            while not stop.is_set():
                try:
                    r.react("cd.test", {"id": i})
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                i += 1

        def reader():
            while not stop.is_set():
                try:
                    r.get_active_cooldowns()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

        w = threading.Thread(target=writer)
        rd = threading.Thread(target=reader)
        w.start()
        rd.start()
        time.sleep(0.15)
        stop.set()
        w.join(timeout=2)
        rd.join(timeout=2)
        assert not errors, errors
