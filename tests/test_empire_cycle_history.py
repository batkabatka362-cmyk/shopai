"""Tests for engines._cycle_history (empire cycle runs).

Not to be confused with core.autonomous.cycle_history which
tracks the older `shopai autonomous-cycle` command's
invocations. This module tracks the newer Tier 1-2b
`shopai cycle run` empire entry.
"""
from __future__ import annotations

import pytest

from engines._cycle_history import (
    CycleRun,
    record_cycle_run,
    recent_runs,
    last_run,
    runs_for_store,
    clear_history,
)


@pytest.fixture
def isolated_history(monkeypatch, tmp_path):
    """Each test gets a fresh history file."""
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


class TestCycleRun:

    def test_success_rate(self):
        r = CycleRun(
            run_id="x", started_at=0.0,
            cycle_label="t", mode="live",
            total_invoked=10, total_ok=8, total_errors=2,
        )
        assert r.success_rate == 0.8

    def test_verdict_clean(self):
        r = CycleRun(
            run_id="x", started_at=0.0,
            cycle_label="t", mode="live",
            total_invoked=10, total_ok=10, total_errors=0,
        )
        assert r.verdict == "clean"

    def test_verdict_mostly_ok(self):
        r = CycleRun(
            run_id="x", started_at=0.0,
            cycle_label="t", mode="live",
            total_invoked=10, total_ok=8, total_errors=2,
        )
        assert r.verdict == "mostly_ok"

    def test_verdict_degraded(self):
        r = CycleRun(
            run_id="x", started_at=0.0,
            cycle_label="t", mode="live",
            total_invoked=10, total_ok=6, total_errors=4,
        )
        assert r.verdict == "degraded"

    def test_verdict_failed(self):
        r = CycleRun(
            run_id="x", started_at=0.0,
            cycle_label="t", mode="live",
            total_invoked=10, total_ok=2, total_errors=8,
        )
        assert r.verdict == "failed"

    def test_verdict_empty(self):
        r = CycleRun(
            run_id="x", started_at=0.0,
            cycle_label="t", mode="live",
        )
        assert r.verdict == "empty"

    def test_verdict_dry_run(self):
        r = CycleRun(
            run_id="x", started_at=0.0,
            cycle_label="t", mode="dry_run",
        )
        assert r.verdict == "dry_run"


class TestPersistence:

    def test_record_and_read(self, isolated_history):
        record_cycle_run(
            cycle_label="test",
            mode="live",
            total_stores=2,
            total_invoked=10,
            total_ok=9,
            total_errors=1,
        )
        runs = recent_runs(limit=5)
        assert len(runs) == 1
        assert runs[0].total_stores == 2
        assert runs[0].mode == "live"

    def test_last_run(self, isolated_history):
        record_cycle_run(
            cycle_label="t1", mode="live", total_stores=1,
        )
        record_cycle_run(
            cycle_label="t2", mode="live", total_stores=2,
        )
        last = last_run()
        assert last is not None
        assert last.cycle_label == "t2"

    def test_no_runs_returns_none(self, isolated_history):
        assert last_run() is None

    def test_clear_history(self, isolated_history):
        record_cycle_run(
            cycle_label="t", mode="live", total_stores=1,
        )
        assert len(recent_runs()) == 1
        clear_history()
        assert recent_runs() == []


class TestStoreFilter:

    def test_runs_for_store(self, isolated_history):
        record_cycle_run(
            cycle_label="t1", mode="live", total_stores=1,
            per_store=[
                {"store_id": "A", "ok": 5, "errors": 0},
            ],
        )
        record_cycle_run(
            cycle_label="t2", mode="live", total_stores=1,
            per_store=[
                {"store_id": "B", "ok": 5, "errors": 0},
            ],
        )
        a_runs = runs_for_store("A")
        assert len(a_runs) == 1
        assert a_runs[0].cycle_label == "t1"

    def test_runs_for_unknown_store_returns_empty(
        self, isolated_history,
    ):
        record_cycle_run(
            cycle_label="t", mode="live", total_stores=1,
            per_store=[{"store_id": "A"}],
        )
        assert runs_for_store("does-not-exist") == []
