"""Tests for audit-pass-49 fixes — defensive + real-bug
hardening across ``data_pipeline.tracking`` (price_history.py,
event_collector.py).

Real bugs fixed:

  * EventCollector._flush buffer leak: pre-audit, if any
    event in the buffer raised during ``conn.execute``, the
    for loop aborted mid-iteration, ``conn.commit()`` and
    ``self._buffer.clear()`` never ran, and EVERY subsequent
    ``track()`` call appended MORE events to the already-full
    buffer. Buffer grew unbounded until memory exhaustion —
    a real resource leak. Now the buffer is cleared BEFORE
    the write loop, each row is try/except-guarded, and the
    commit is rollback-safe.

  * EventCollector.track / add_training_sample /
    get_training_data / get_events used bare
    ``json.dumps(value)`` / ``json.loads(column)``.
    Non-serialisable values (sets, datetimes, custom
    objects) crashed writes; corrupted JSON columns crashed
    reads. Same bug class fixed in pass 48 for the store DB.

  * PriceHistory.record_prices_batch had the same bare
    ``float()`` + non-dict item crash as the store upsert
    methods.

  * PriceHistory.record_price / record_outcome /
    record_competitor_price accepted arbitrary numeric types
    at the public API but passed them unvalidated into the
    REAL-typed SQL columns.

  * Both singleton accessors (``get_event_collector``,
    ``get_price_history``) had the check-then-assign race
    from pass 47/48.
"""
from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from unittest import mock

import pytest

from data_pipeline.tracking import event_collector as ec_mod
from data_pipeline.tracking import price_history as ph_mod
from data_pipeline.tracking.event_collector import (
    EventCollector,
    _safe_json_dumps,
    _safe_json_loads,
    get_event_collector,
)
from data_pipeline.tracking.price_history import (
    PriceHistory,
    get_price_history,
)


@pytest.fixture
def ph(tmp_path):
    instance = PriceHistory(db_path=tmp_path / "price_history.db")
    yield instance
    instance.close()


@pytest.fixture
def ec(tmp_path):
    instance = EventCollector(db_path=tmp_path / "events.db")
    yield instance
    instance.close()


# ═══════════════════════════════════════════════════════════
# EventCollector — buffer leak regression
# ═══════════════════════════════════════════════════════════


class TestFlushBufferLeak:
    def test_buffer_cleared_after_flush(self, ec):
        """Happy path: buffer empty after flush."""
        ec.track("s1", "evt1")
        ec.track("s1", "evt2")
        assert len(ec._buffer) == 2
        ec.flush()
        assert len(ec._buffer) == 0

    def test_buffer_cleared_even_when_write_fails(self, ec, monkeypatch):
        """Regression: pre-audit a failing ``conn.execute``
        aborted the for loop mid-iteration, and the buffer
        stayed FULL. Every subsequent ``track()`` appended
        to the already-full buffer. Buffer grew unbounded.

        Fix: clear the buffer BEFORE the write loop — drop-
        on-failure is the right policy for a fire-and-forget
        collector."""
        ec.track("s1", "evt1")
        ec.track("s1", "evt2")
        ec.track("s1", "evt3")

        # Wrap _get_conn() to return an object whose execute
        # raises on INSERT INTO events. sqlite3.Connection
        # itself is immutable so we can't monkeypatch attrs.
        real_conn = ec._get_conn()

        class FailingConn:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, params=()):
                import sqlite3
                if sql.startswith("INSERT INTO events"):
                    raise sqlite3.Error("simulated write failure")
                return self._real.execute(sql, params)

            def commit(self):
                return self._real.commit()

            def rollback(self):
                return self._real.rollback()

        failing = FailingConn(real_conn)
        monkeypatch.setattr(ec, "_get_conn", lambda: failing)
        ec.flush()

        # Buffer must be EMPTY even though every write failed.
        assert len(ec._buffer) == 0

    def test_next_track_after_failure_starts_fresh(self, ec, monkeypatch):
        """After a failed flush, the NEXT track() call must
        not see stale events in the buffer."""
        ec.track("s1", "evt1")

        real_conn = ec._get_conn()
        fail_mode = [True]

        class FlakyConn:
            def execute(self, sql, params=()):
                if fail_mode[0] and sql.startswith("INSERT INTO events"):
                    import sqlite3
                    raise sqlite3.Error("simulated")
                return real_conn.execute(sql, params)

            def commit(self):
                return real_conn.commit()

            def rollback(self):
                return real_conn.rollback()

        flaky = FlakyConn()
        monkeypatch.setattr(ec, "_get_conn", lambda: flaky)
        ec.flush()  # Fails, buffer cleared.

        fail_mode[0] = False  # Stop simulating failures.
        ec.track("s1", "evt_new")
        assert len(ec._buffer) == 1
        ec.flush()
        assert len(ec._buffer) == 0
        # Clean up monkeypatch and query via the real connection.
        monkeypatch.undo()
        events = ec.get_events("s1")
        assert any(e.get("event_type") == "evt_new" for e in events)
        assert not any(e.get("event_type") == "evt1" for e in events)


# ═══════════════════════════════════════════════════════════
# EventCollector — JSON helpers
# ═══════════════════════════════════════════════════════════


class TestEventCollectorJsonHelpers:
    def test_safe_json_dumps_set(self):
        """Non-serialisable set coerced via default=str."""
        result = _safe_json_dumps({"tags": {"a", "b"}})
        assert isinstance(result, str)
        assert "a" in result and "b" in result

    def test_safe_json_dumps_datetime(self):
        import datetime
        result = _safe_json_dumps({"when": datetime.datetime(2024, 1, 1)})
        assert isinstance(result, str)

    def test_safe_json_dumps_custom_object(self):
        class Foo:
            def __str__(self):
                return "foo"
        result = _safe_json_dumps({"obj": Foo()})
        assert "foo" in result

    def test_safe_json_loads_bad(self):
        assert _safe_json_loads("{not json", default={}) == {}

    def test_safe_json_loads_none(self):
        assert _safe_json_loads(None, default=[]) == []

    def test_safe_json_loads_valid(self):
        assert _safe_json_loads('{"a": 1}', default={}) == {"a": 1}


# ═══════════════════════════════════════════════════════════
# EventCollector — defensive entry
# ═══════════════════════════════════════════════════════════


class TestEventCollectorDefensive:
    def test_track_with_non_serializable_data(self, ec):
        """Regression: pre-audit json.dumps crashed on sets."""
        ec.track("s1", "test", "product", "p1", {"tags": {"a", "b", "c"}})
        ec.flush()
        events = ec.get_events("s1")
        assert len(events) == 1
        assert "tags" in events[0]["data"]

    def test_track_order_with_none(self, ec):
        """Regression: pre-audit order.get() crashed on None."""
        ec.track_order("s1", None)  # type: ignore[arg-type]
        # Should not crash.

    def test_track_product_added_with_none(self, ec):
        ec.track_product_added("s1", None)  # type: ignore[arg-type]

    def test_track_empty_event_type_dropped(self, ec):
        ec.track("s1", "")  # Empty event_type
        ec.track("s1", None)  # type: ignore[arg-type]
        assert len(ec._buffer) == 0

    def test_track_price_change_currency_strings(self, ec):
        """Regression: bare float() on prices crashed."""
        ec.track_price_change("s1", "p1", "$10.00", "$12.50")  # type: ignore[arg-type]
        ec.flush()
        history = ec.get_price_history("s1", "p1")
        assert len(history) == 1
        assert history[0]["old_price"] == 10.0
        assert history[0]["new_price"] == 12.5


# ═══════════════════════════════════════════════════════════
# EventCollector — training data JSON safety
# ═══════════════════════════════════════════════════════════


class TestTrainingDataJsonSafety:
    def test_add_training_sample_with_set_features(self, ec):
        """Non-serializable features don't crash the write."""
        ec.add_training_sample("pricing", {"tags": {"a", "b"}}, 0.85)
        samples = ec.get_training_data("pricing")
        assert len(samples) == 1

    def test_get_training_data_corrupted_row(self, ec):
        """Regression: corrupted features/label column crashed
        the read."""
        ec.add_training_sample("test", {"x": 1}, "label1")
        conn = ec._get_conn()
        conn.execute("UPDATE training_data SET features = '{not json' WHERE model_type = ?", ("test",))
        conn.commit()
        samples = ec.get_training_data("test")
        assert len(samples) == 1
        assert samples[0]["features"] == {}

    def test_add_training_sample_empty_model_type(self, ec):
        ec.add_training_sample("", {"x": 1}, "label")
        samples = ec.get_training_data("")
        # Empty model_type should not have written.
        assert len(samples) == 0


class TestGetEventsCorruptedData:
    def test_corrupted_data_column(self, ec):
        ec.track("s1", "test", data={"ok": True})
        ec.flush()
        conn = ec._get_conn()
        conn.execute("UPDATE events SET data = '{not json' WHERE store_id = ?", ("s1",))
        conn.commit()
        events = ec.get_events("s1")
        assert len(events) == 1
        assert events[0]["data"] == {}


# ═══════════════════════════════════════════════════════════
# EventCollector — singleton thread safety
# ═══════════════════════════════════════════════════════════


class TestEventCollectorSingleton:
    def test_concurrent_first_callers_see_same_instance(self, monkeypatch):
        ec_mod._collector = None
        instances: list = []
        barrier = threading.Barrier(8)

        def fire():
            barrier.wait()
            instances.append(get_event_collector())

        threads = [threading.Thread(target=fire) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len({id(i) for i in instances}) == 1
        # Cleanup
        ec_mod._collector = None


# ═══════════════════════════════════════════════════════════
# PriceHistory — defensive
# ═══════════════════════════════════════════════════════════


class TestPriceHistoryDefensive:
    def test_record_price_none_product_id(self, ph):
        assert ph.record_price(None, 99.99) == 0

    def test_record_price_negative(self, ph):
        assert ph.record_price("p1", -5) == 0

    def test_record_price_zero(self, ph):
        assert ph.record_price("p1", 0) == 0

    def test_record_price_currency_string(self, ph):
        """safe_float handles "$99.99"."""
        row_id = ph.record_price("p1", "$99.99")  # type: ignore[arg-type]
        assert row_id > 0
        history = ph.get_price_history("p1")
        assert history[0]["price"] == 99.99

    def test_record_prices_batch_none(self, ph):
        assert ph.record_prices_batch(None) == 0  # type: ignore[arg-type]

    def test_record_prices_batch_non_list(self, ph):
        assert ph.record_prices_batch("not a list") == 0  # type: ignore[arg-type]

    def test_record_prices_batch_mixed(self, ph):
        """Non-dict items skipped; valid items recorded."""
        count = ph.record_prices_batch([
            None,
            "bad",
            42,
            {"id": "p1", "price": "$50.00", "cost": "$20.00"},
            {"id": "p2", "price": "N/A"},  # price coerced to 0 → skipped
            {"id": "p3", "price": 30, "cost": 10},
        ])
        assert count == 2  # p1 + p3

    def test_record_outcome_currency_strings(self, ph):
        """Regression: pre-audit the comparison ``revenue_after
        > 0`` crashed when revenue_after was a string."""
        ph.record_outcome("p1", "$99.99", revenue_after="$500", orders_after="5")  # type: ignore[arg-type]
        # Must not crash.

    def test_record_competitor_price_negative(self, ph):
        ph.record_competitor_price("p1", "comp1", -10)
        competitors = ph.get_competitor_prices("p1")
        # Negative price rejected.
        assert len(competitors) == 0

    def test_record_competitor_price_none(self, ph):
        ph.record_competitor_price(None, "comp1", 10)  # type: ignore[arg-type]
        # Should not crash.


# ═══════════════════════════════════════════════════════════
# PriceHistory — singleton thread safety
# ═══════════════════════════════════════════════════════════


class TestPriceHistorySingleton:
    def test_concurrent_first_callers_see_same_instance(self):
        ph_mod._instance = None
        instances: list = []
        barrier = threading.Barrier(8)

        def fire():
            barrier.wait()
            instances.append(get_price_history())

        threads = [threading.Thread(target=fire) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len({id(i) for i in instances}) == 1
        ph_mod._instance = None
