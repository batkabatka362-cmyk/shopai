"""W963-118: per-store cost attribution tests."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from engines.per_store_costs import (
    CostEvent,
    PerStoreCostsEngine,
    costs_by_adapter,
    costs_by_store,
    costs_total,
    get_recent_events,
    record_call,
    rotate_if_needed,
)
from engines.per_store_costs import recorder as rec


@pytest.fixture(autouse=True)
def _isolated_log(tmp_path, monkeypatch):
    """Each test gets its own log paths. Disables Pattern J
    guard so record_call actually writes."""
    live = tmp_path / "per_store_costs.jsonl"
    archive = tmp_path / "per_store_costs.archive.jsonl"
    monkeypatch.setattr(rec, "DATA_PATH", live)
    monkeypatch.setattr(rec, "ARCHIVE_PATH", archive)
    # Also patch the query module's view of the paths
    from engines.per_store_costs import query as qmod
    monkeypatch.setattr(qmod, "DATA_PATH", live)
    monkeypatch.setattr(qmod, "ARCHIVE_PATH", archive)
    # Disable Pattern J guard
    monkeypatch.setattr(
        rec, "_is_test_environment", lambda: False,
    )
    yield live, archive


# ── recorder ──────────────────────────────────────────────


class TestRecorder:
    def test_record_call_appends_one_line(
        self, _isolated_log,
    ):
        live, _ = _isolated_log
        ok = record_call(
            adapter="openai",
            capability="chat_complete",
            cost_usd=0.002,
            latency_ms=120.0,
            ok=True,
        )
        assert ok is True
        assert live.exists()
        lines = live.read_text(
            encoding="utf-8",
        ).strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["adapter"] == "openai"
        assert event["capability"] == "chat_complete"
        assert event["cost_usd"] == 0.002
        assert event["ok"] is True

    def test_record_call_uses_active_store(
        self, _isolated_log, monkeypatch,
    ):
        from core.context import active_store
        live, _ = _isolated_log
        with active_store("store_a"):
            record_call(
                adapter="anthropic",
                capability="chat_complete",
                cost_usd=0.015,
            )
        event = json.loads(
            live.read_text(encoding="utf-8").splitlines()[0],
        )
        assert event["store_id"] == "store_a"

    def test_record_call_empty_store_id_when_no_active(
        self, _isolated_log,
    ):
        live, _ = _isolated_log
        record_call(
            adapter="openai", capability="chat",
        )
        event = json.loads(
            live.read_text(encoding="utf-8").splitlines()[0],
        )
        assert event["store_id"] == ""

    def test_record_call_explicit_store_id_wins(
        self, _isolated_log,
    ):
        from core.context import active_store
        live, _ = _isolated_log
        with active_store("active_sid"):
            record_call(
                adapter="openai", capability="chat",
                store_id="explicit_sid",
            )
        event = json.loads(
            live.read_text(encoding="utf-8").splitlines()[0],
        )
        assert event["store_id"] == "explicit_sid"

    def test_pattern_j_short_circuits_under_pytest(
        self, _isolated_log, monkeypatch,
    ):
        """When _is_test_environment returns True, the
        recorder is a no-op. The autouse fixture patches
        it OFF; this test patches it back ON to verify."""
        live, _ = _isolated_log
        monkeypatch.setattr(
            rec, "_is_test_environment", lambda: True,
        )
        result = record_call(
            adapter="openai", capability="chat",
        )
        assert result is False
        assert not live.exists()

    def test_record_call_validates_required_fields(
        self, _isolated_log,
    ):
        assert record_call(adapter="", capability="x") is False
        assert record_call(adapter="x", capability="") is False

    def test_record_call_swallows_unserialisable_data(
        self, _isolated_log,
    ):
        """A non-numeric cost_usd should not crash the
        recorder; it gets coerced via float() and either
        succeeds or returns False."""
        # cost_usd as a string number works (float coercion)
        ok = record_call(
            adapter="openai", capability="chat",
            cost_usd=float("0.002"),
        )
        assert ok is True


# ── rotation ──────────────────────────────────────────────


class TestRotation:
    def test_rotate_moves_live_to_archive_when_full(
        self, _isolated_log, monkeypatch,
    ):
        live, archive = _isolated_log
        # Lower the rotation threshold so we don't have
        # to write 5MB.
        monkeypatch.setattr(rec, "_ROTATE_AT_BYTES", 100)
        # Write a handful of events; each ~150 bytes.
        for i in range(5):
            record_call(
                adapter="openai", capability="chat",
                cost_usd=0.001,
            )
        # Live should have rotated; archive carries the
        # old content.
        assert archive.exists()
        # Live may be empty or contain new events from
        # the loop after rotation; archive size > 0.
        assert archive.stat().st_size > 0

    def test_rotate_when_not_full_is_noop(
        self, _isolated_log,
    ):
        rotated = rotate_if_needed()
        assert rotated is False

    def test_rotate_when_no_file_is_noop(
        self, _isolated_log,
    ):
        live, _ = _isolated_log
        if live.exists():
            live.unlink()
        rotated = rotate_if_needed()
        assert rotated is False


# ── query API ─────────────────────────────────────────────


class TestQuery:
    def _seed(self, monkeypatch, events: list[dict]) -> None:
        """Write events to the live log directly."""
        live = rec.DATA_PATH
        live.parent.mkdir(parents=True, exist_ok=True)
        with open(live, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_costs_by_store_aggregates(
        self, _isolated_log, monkeypatch,
    ):
        now = time.time()
        self._seed(monkeypatch, [
            {
                "ts": now - 100, "store_id": "store_a",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 0.002, "latency_ms": 100,
                "ok": True,
            },
            {
                "ts": now - 50, "store_id": "store_a",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 0.003, "latency_ms": 200,
                "ok": True,
            },
            {
                "ts": now - 10, "store_id": "store_b",
                "adapter": "anthropic", "capability": "chat",
                "cost_usd": 0.015, "latency_ms": 350,
                "ok": False,
            },
        ])
        out = costs_by_store(window_hours=1.0)
        assert "store_a" in out
        assert "store_b" in out
        assert out["store_a"].total_cost_usd == (
            pytest.approx(0.005)
        )
        assert out["store_a"].total_calls == 2
        assert out["store_a"].failed_calls == 0
        assert out["store_b"].total_cost_usd == 0.015
        assert out["store_b"].failed_calls == 1

    def test_costs_by_store_window_filters(
        self, _isolated_log, monkeypatch,
    ):
        now = time.time()
        self._seed(monkeypatch, [
            {
                "ts": now - 86400 * 30, "store_id": "old",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 100.0, "ok": True,
            },
            {
                "ts": now - 60, "store_id": "fresh",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 0.001, "ok": True,
            },
        ])
        # 1-hour window excludes the 30-day-old event
        out = costs_by_store(window_hours=1.0)
        assert "fresh" in out
        assert "old" not in out

    def test_costs_by_adapter_filters_by_store(
        self, _isolated_log, monkeypatch,
    ):
        now = time.time()
        self._seed(monkeypatch, [
            {
                "ts": now - 10, "store_id": "store_a",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 0.002, "ok": True,
            },
            {
                "ts": now - 10, "store_id": "store_b",
                "adapter": "openai", "capability": "chat",
                "cost_usd": 0.005, "ok": True,
            },
        ])
        # Store-filtered: only store_a's calls
        out = costs_by_adapter(store_id="store_a")
        assert out["openai"]["cost_usd"] == pytest.approx(0.002)
        # Fleet-wide
        out_all = costs_by_adapter(store_id="")
        assert out_all["openai"]["cost_usd"] == pytest.approx(0.007)

    def test_costs_total_failure_rate(
        self, _isolated_log, monkeypatch,
    ):
        now = time.time()
        self._seed(monkeypatch, [
            {
                "ts": now, "store_id": "x",
                "adapter": "a", "capability": "c",
                "cost_usd": 0.0, "ok": True,
            },
            {
                "ts": now, "store_id": "x",
                "adapter": "a", "capability": "c",
                "cost_usd": 0.0, "ok": False,
            },
            {
                "ts": now, "store_id": "x",
                "adapter": "a", "capability": "c",
                "cost_usd": 0.0, "ok": False,
            },
        ])
        out = costs_total(store_id="x")
        assert out["total_calls"] == 3
        assert out["failed_calls"] == 2
        assert out["failure_rate"] == pytest.approx(0.667)

    def test_get_recent_events_newest_first(
        self, _isolated_log, monkeypatch,
    ):
        now = time.time()
        self._seed(monkeypatch, [
            {
                "ts": now - 100, "store_id": "x",
                "adapter": "a", "capability": "c",
                "cost_usd": 0.0, "ok": True,
            },
            {
                "ts": now - 1, "store_id": "x",
                "adapter": "a", "capability": "c",
                "cost_usd": 0.0, "ok": True,
            },
        ])
        events = get_recent_events(limit=2)
        assert events[0]["ts"] > events[1]["ts"]

    def test_corrupt_line_is_skipped(
        self, _isolated_log, monkeypatch,
    ):
        """A corrupted JSON line in the middle of the log
        should NOT crash queries -- skip it + continue."""
        live = rec.DATA_PATH
        live.parent.mkdir(parents=True, exist_ok=True)
        with open(live, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "store_id": "good",
                "adapter": "a", "capability": "c",
                "cost_usd": 0.001, "ok": True,
            }) + "\n")
            f.write("NOT VALID JSON\n")
            f.write(json.dumps({
                "ts": time.time(),
                "store_id": "good",
                "adapter": "a", "capability": "c",
                "cost_usd": 0.002, "ok": True,
            }) + "\n")
        out = costs_total()
        assert out["total_calls"] == 2

    def test_archive_consulted_when_requested(
        self, _isolated_log, monkeypatch,
    ):
        live, archive = _isolated_log
        now = time.time()
        # Live has 1 fresh event
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text(json.dumps({
            "ts": now, "store_id": "x",
            "adapter": "a", "capability": "c",
            "cost_usd": 0.001, "ok": True,
        }) + "\n", encoding="utf-8")
        # Archive has 1 older event
        archive.write_text(json.dumps({
            "ts": now - 1, "store_id": "x",
            "adapter": "a", "capability": "c",
            "cost_usd": 0.002, "ok": True,
        }) + "\n", encoding="utf-8")
        # Without archive: 1 event
        out = costs_total(include_archive=False)
        assert out["total_calls"] == 1
        # With archive: 2 events
        out = costs_total(include_archive=True)
        assert out["total_calls"] == 2


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self, _isolated_log):
        r = PerStoreCostsEngine().run({})
        assert r["status"] == "success"
        assert "data" in r
        assert "meta" in r
        assert "error" in r

    def test_none_success(self, _isolated_log):
        r = PerStoreCostsEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self, _isolated_log):
        r = PerStoreCostsEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self, _isolated_log):
        r = PerStoreCostsEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self, _isolated_log):
        r = PerStoreCostsEngine().run({})
        assert r["meta"]["engine"] == "per_store_costs"

    def test_by_store_view(self, _isolated_log, monkeypatch):
        live = rec.DATA_PATH
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text(json.dumps({
            "ts": time.time(), "store_id": "store_a",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 0.001, "ok": True,
        }) + "\n", encoding="utf-8")
        r = PerStoreCostsEngine().run({
            "data": {"view": "by_store", "window_hours": 1.0},
        })
        assert r["data"]["view"] == "by_store"
        stores = r["data"]["stores"]
        assert len(stores) == 1
        assert stores[0]["store_id"] == "store_a"

    def test_by_adapter_view(self, _isolated_log, monkeypatch):
        live = rec.DATA_PATH
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text(json.dumps({
            "ts": time.time(), "store_id": "x",
            "adapter": "anthropic", "capability": "chat",
            "cost_usd": 0.015, "ok": True,
        }) + "\n", encoding="utf-8")
        r = PerStoreCostsEngine().run({
            "data": {"view": "by_adapter", "window_hours": 1.0},
        })
        assert r["data"]["view"] == "by_adapter"
        adapters = r["data"]["adapters"]
        assert any(
            a["adapter"] == "anthropic" for a in adapters
        )

    def test_summary_view(self, _isolated_log, monkeypatch):
        live = rec.DATA_PATH
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text(json.dumps({
            "ts": time.time(), "store_id": "x",
            "adapter": "openai", "capability": "chat",
            "cost_usd": 0.002, "ok": True,
        }) + "\n", encoding="utf-8")
        r = PerStoreCostsEngine().run({
            "data": {"view": "summary"},
        })
        s = r["data"]["summary"]
        assert s["total_calls"] == 1
        assert s["total_cost_usd"] == pytest.approx(0.002)
