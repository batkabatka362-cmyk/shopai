"""Tests for ``core.capability_planner.plan_history``.

The persistent plan-invocation log. These tests lock in:
  - record_plan_invocation returns an event_id
  - record_outcome updates the existing event
  - recent_history returns newest-first within the window
  - Test-environment guard prevents production data pollution
  - Atomic writes (corrupted file -> fail-open, empty result)
  - Plan dict serialised + round-tripped
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from core.capability_planner import plan_history as ph
from core.capability_planner.plan import Plan, PlanStep


@pytest.fixture
def temp_history(tmp_path, monkeypatch):
    """Point the recorder at a temp file + disable the
    test-env guard so the recorder actually writes."""
    history_file = tmp_path / "plan_history.json"
    monkeypatch.setattr(ph, "_HISTORY_PATH", history_file)
    # Disable the pytest-env guard for tests that need to
    # actually exercise the recording path.
    monkeypatch.setattr(
        ph, "_is_test_environment", lambda: False,
    )
    yield history_file


class TestTestEnvGuard:

    def test_guard_blocks_write_in_test_env_by_default(
        self, tmp_path, monkeypatch,
    ):
        history_file = tmp_path / "plan_history.json"
        monkeypatch.setattr(
            ph, "_HISTORY_PATH", history_file,
        )
        # Default test env -> guard active -> no write
        event_id = ph.record_plan_invocation(
            goal="x", plan={}, store_id="s",
        )
        assert event_id == ""
        assert not history_file.exists()


class TestRecordInvocation:

    def test_returns_event_id(self, temp_history):
        eid = ph.record_plan_invocation(
            goal="launch store",
            plan={"goal": "launch", "steps": []},
            store_id="store-a",
            executed=True,
        )
        assert eid
        assert eid.startswith("plan_")

    def test_event_appears_in_recent_history(
        self, temp_history,
    ):
        ph.record_plan_invocation(
            goal="seed products",
            plan={"goal": "seed", "steps": []},
            store_id="store-b",
        )
        recent = ph.recent_history(since_seconds=3600)
        assert len(recent) == 1
        assert recent[0]["goal"] == "seed products"
        assert recent[0]["store_id"] == "store-b"

    def test_multiple_events_newest_first(
        self, temp_history,
    ):
        ph.record_plan_invocation(goal="first", plan={})
        time.sleep(0.01)
        ph.record_plan_invocation(goal="second", plan={})
        time.sleep(0.01)
        ph.record_plan_invocation(goal="third", plan={})
        recent = ph.recent_history(since_seconds=3600)
        assert [e["goal"] for e in recent] == [
            "third", "second", "first",
        ]

    def test_plan_object_to_dict_conversion(
        self, temp_history,
    ):
        plan = Plan(goal="x", relevant_capabilities=["a"])
        plan.steps.append(PlanStep(
            capability_name="a",
            role="engine",
            description="...",
        ))
        ph.record_plan_invocation(
            goal="x", plan=plan, store_id="s",
        )
        recent = ph.recent_history(since_seconds=3600)
        assert recent[0]["plan"]["goal"] == "x"
        assert recent[0]["plan"]["steps"][0][
            "capability_name"
        ] == "a"

    def test_history_capped_at_1000(self, temp_history):
        # Write 1005 events; only last 1000 survive
        for i in range(1005):
            ph.record_plan_invocation(
                goal=f"goal_{i}", plan={},
            )
        recent = ph.recent_history(since_seconds=3600 * 24)
        assert len(recent) == 1000
        # Last entry is the newest one
        assert recent[0]["goal"] == "goal_1004"


class TestRecordOutcome:

    def test_updates_existing_event(self, temp_history):
        eid = ph.record_plan_invocation(
            goal="x", plan={}, executed=True,
        )
        assert ph.record_outcome(eid, "success") is True
        recent = ph.recent_history(since_seconds=3600)
        assert recent[0]["outcome"] == "success"

    def test_unknown_event_id_returns_false(
        self, temp_history,
    ):
        assert (
            ph.record_outcome("nope_id", "success")
            is False
        )

    def test_notes_persisted(self, temp_history):
        eid = ph.record_plan_invocation(
            goal="x", plan={},
        )
        ph.record_outcome(
            eid, "success",
            notes="audit pct: 60 -> 100",
        )
        recent = ph.recent_history(since_seconds=3600)
        assert recent[0]["notes"] == (
            "audit pct: 60 -> 100"
        )

    def test_empty_event_id_returns_false(
        self, temp_history,
    ):
        assert (
            ph.record_outcome("", "success") is False
        )


class TestRecentHistoryWindow:

    def test_old_events_excluded(self, temp_history):
        # Write one event, then fake a very-old timestamp
        ph.record_plan_invocation(goal="old", plan={})
        history_file = temp_history
        import json
        events = json.loads(
            history_file.read_text(encoding="utf-8"),
        )
        events[0]["timestamp"] = time.time() - 86400 * 30
        history_file.write_text(
            json.dumps(events), encoding="utf-8",
        )
        # Default 7-day window excludes the 30-day-old event
        recent = ph.recent_history(since_seconds=86400 * 7)
        assert recent == []
        # Wider window includes it
        recent = ph.recent_history(since_seconds=86400 * 60)
        assert len(recent) == 1


class TestFailOpen:

    def test_missing_file_returns_empty(
        self, tmp_path, monkeypatch,
    ):
        monkeypatch.setattr(
            ph, "_HISTORY_PATH",
            tmp_path / "nonexistent.json",
        )
        assert ph.recent_history(since_seconds=3600) == []

    def test_corrupt_file_returns_empty(
        self, tmp_path, monkeypatch,
    ):
        bad = tmp_path / "plan_history.json"
        bad.write_text("not json", encoding="utf-8")
        monkeypatch.setattr(ph, "_HISTORY_PATH", bad)
        # Don't raise, just return empty
        assert ph.recent_history(since_seconds=3600) == []

    def test_wrong_top_level_shape_returns_empty(
        self, tmp_path, monkeypatch,
    ):
        bad = tmp_path / "plan_history.json"
        bad.write_text(
            '{"not": "a list"}', encoding="utf-8",
        )
        monkeypatch.setattr(ph, "_HISTORY_PATH", bad)
        assert ph.recent_history(since_seconds=3600) == []
