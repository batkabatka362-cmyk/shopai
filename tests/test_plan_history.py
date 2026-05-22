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


class TestOutcomeBreakdown:
    """Aggregate outcomes across the history window. Powers
    operator-facing 'success rate' summaries + future
    planner learning."""

    def test_breakdown_counts_outcomes(self, temp_history):
        # Three executed invocations with different outcomes
        e1 = ph.record_plan_invocation(
            goal="g1", plan={}, executed=True,
        )
        ph.record_outcome(e1, "success")
        e2 = ph.record_plan_invocation(
            goal="g2", plan={}, executed=True,
        )
        ph.record_outcome(e2, "partial")
        e3 = ph.record_plan_invocation(
            goal="g3", plan={}, executed=True,
        )
        ph.record_outcome(e3, "success")
        # One dry-run
        ph.record_plan_invocation(
            goal="g4", plan={}, executed=False,
            outcome="skipped",
        )
        b = ph.outcome_breakdown(since_seconds=3600)
        assert b["total"] == 4
        assert b["executed_total"] == 3
        assert b["by_outcome"]["success"] == 2
        assert b["by_outcome"]["partial"] == 1
        assert b["by_outcome"]["skipped"] == 1
        # 2 success / 3 executed = ~66.7%
        assert abs(b["success_rate"] - 0.667) < 0.01

    def test_breakdown_filter_by_goal(self, temp_history):
        ph.record_plan_invocation(
            goal="mobile design",
            plan={}, executed=True,
            outcome="success",
        )
        ph.record_plan_invocation(
            goal="launch store",
            plan={}, executed=True,
            outcome="fail",
        )
        b = ph.outcome_breakdown(
            since_seconds=3600, goal="mobile",
        )
        # Only the "mobile design" event matches
        assert b["total"] == 1
        assert b["by_outcome"]["success"] == 1

    def test_breakdown_filter_by_capability(
        self, temp_history,
    ):
        # Two plans, only one uses store_design_engine
        ph.record_plan_invocation(
            goal="g1",
            plan={
                "steps": [
                    {"capability_name": "store_design_engine"},
                    {"capability_name": "apply_design"},
                ],
            },
            executed=True,
            outcome="success",
        )
        ph.record_plan_invocation(
            goal="g2",
            plan={
                "steps": [
                    {"capability_name": "launch_store"},
                ],
            },
            executed=True,
            outcome="success",
        )
        b = ph.outcome_breakdown(
            since_seconds=3600,
            capability="store_design_engine",
        )
        assert b["total"] == 1


class TestGoalBreakdown:

    def test_per_goal_aggregates(self, temp_history):
        # 3x "launch store" all successful
        for _ in range(3):
            eid = ph.record_plan_invocation(
                goal="launch store",
                plan={}, executed=True,
            )
            ph.record_outcome(eid, "success")
        # 2x "mobile design", one success + one partial
        eid = ph.record_plan_invocation(
            goal="mobile design",
            plan={}, executed=True,
        )
        ph.record_outcome(eid, "success")
        eid = ph.record_plan_invocation(
            goal="mobile design",
            plan={}, executed=True,
        )
        ph.record_outcome(eid, "partial")

        rows = ph.goal_breakdown(since_seconds=3600)
        # Sorted by count desc -> launch store first
        assert rows[0]["goal"] == "launch store"
        assert rows[0]["count"] == 3
        assert rows[0]["success_rate"] == 1.0
        # mobile design: 1/2 success
        mobile = next(
            r for r in rows if r["goal"] == "mobile design"
        )
        assert mobile["count"] == 2
        assert mobile["success_rate"] == 0.5

    def test_top_n_limit(self, temp_history):
        for i in range(5):
            ph.record_plan_invocation(
                goal=f"goal_{i}",
                plan={}, executed=True,
                outcome="success",
            )
        rows = ph.goal_breakdown(
            since_seconds=3600, top_n=3,
        )
        assert len(rows) == 3


class TestCapabilityLeaderboard:
    """Per-capability reliability ranking. Operator-facing
    leaderboard primitive: ``shopai capabilities
    reliability``."""

    def _record_outcome(
        self, caps, outcome, store_id="s",
    ):
        eid = ph.record_plan_invocation(
            goal="g",
            plan={
                "steps": [
                    {"capability_name": c} for c in caps
                ],
            },
            store_id=store_id,
            executed=True,
        )
        ph.record_outcome(eid, outcome)

    def test_per_cap_success_rate_computed(
        self, temp_history,
    ):
        # cap_a: 3 plans, 3 success -> 100%
        # cap_b: 4 plans, 2 success -> 50%
        for _ in range(3):
            self._record_outcome(
                ["cap_a"], "success",
            )
        for _ in range(2):
            self._record_outcome(
                ["cap_b"], "success",
            )
        for _ in range(2):
            self._record_outcome(["cap_b"], "fail")
        rows = ph.capability_leaderboard(
            since_seconds=3600,
        )
        by_cap = {r["capability"]: r for r in rows}
        assert by_cap["cap_a"]["success_rate"] == 1.0
        assert by_cap["cap_b"]["success_rate"] == 0.5

    def test_sample_size_cutoff(self, temp_history):
        # cap_x: 1 success -> below default min (2),
        # excluded
        # cap_y: 2 successes -> included
        self._record_outcome(["cap_x"], "success")
        self._record_outcome(["cap_y"], "success")
        self._record_outcome(["cap_y"], "success")
        rows = ph.capability_leaderboard(
            since_seconds=3600, min_sample_size=2,
        )
        names = {r["capability"] for r in rows}
        assert "cap_x" not in names
        assert "cap_y" in names

    def test_ranking_by_success_rate(self, temp_history):
        # higher rate ranks first
        for _ in range(3):
            self._record_outcome(["high"], "success")
        for _ in range(3):
            self._record_outcome(["low"], "fail")
        # low needs at least 2 executed for visibility
        rows = ph.capability_leaderboard(
            since_seconds=3600, min_sample_size=2,
        )
        assert rows[0]["capability"] == "high"
        if "low" in [r["capability"] for r in rows]:
            assert (
                [r["capability"] for r in rows].index(
                    "high",
                )
                < [r["capability"] for r in rows].index(
                    "low",
                )
            )

    def test_duplicate_step_in_plan_counted_once(
        self, temp_history,
    ):
        # A plan with cap_a appearing twice should still
        # count as ONE outcome contribution for cap_a.
        eid = ph.record_plan_invocation(
            goal="g",
            plan={
                "steps": [
                    {"capability_name": "cap_a"},
                    {"capability_name": "cap_a"},
                ],
            },
            store_id="s",
            executed=True,
        )
        ph.record_outcome(eid, "success")
        # need one more to clear min_sample_size=2
        self._record_outcome(["cap_a"], "success")
        rows = ph.capability_leaderboard(
            since_seconds=3600,
        )
        cap_a = next(
            r for r in rows
            if r["capability"] == "cap_a"
        )
        # 2 plans, both counted -> executed=2
        assert cap_a["executed_count"] == 2


class TestSuccessfulPlans:
    """Cross-store recommendation surface. Lists successful
    past plans ranked by frequency + recency."""

    def _seed_invocation(
        self, goal, store_id, caps,
        outcome, sleep_ts=0,
    ):
        eid = ph.record_plan_invocation(
            goal=goal,
            plan={
                "steps": [
                    {"capability_name": c} for c in caps
                ],
                "cli_sequence": [f"shopai {goal}"],
            },
            store_id=store_id,
            executed=True,
        )
        ph.record_outcome(eid, outcome)
        if sleep_ts:
            time.sleep(sleep_ts)

    def test_returns_only_success_outcomes(
        self, temp_history,
    ):
        self._seed_invocation(
            "g1", "s1", ["launch_store"], "success",
        )
        self._seed_invocation(
            "g2", "s1", ["launch_store"], "fail",
        )
        self._seed_invocation(
            "g3", "s1", ["launch_store"], "partial",
        )
        rows = ph.successful_plans(since_seconds=3600)
        # Only the success outcome
        goals = {r["goal"] for r in rows}
        assert goals == {"g1"}

    def test_groups_by_goal_and_capabilities(
        self, temp_history,
    ):
        # Same goal + caps from two stores
        self._seed_invocation(
            "launch", "store-a", ["launch_store"],
            "success",
        )
        self._seed_invocation(
            "launch", "store-b", ["launch_store"],
            "success",
        )
        rows = ph.successful_plans(since_seconds=3600)
        assert len(rows) == 1
        assert rows[0]["success_count"] == 2
        assert set(rows[0]["stores"]) == {
            "store-a", "store-b",
        }

    def test_exclude_store_filter(self, temp_history):
        self._seed_invocation(
            "g", "store-a", ["x"], "success",
        )
        self._seed_invocation(
            "g", "store-b", ["x"], "success",
        )
        rows = ph.successful_plans(
            since_seconds=3600,
            exclude_store_id="store-a",
        )
        # Only store-b's success surfaces
        assert len(rows) == 1
        assert rows[0]["stores"] == ["store-b"]

    def test_ranked_by_count_desc(self, temp_history):
        # 3 successes for "popular"; 1 for "rare"
        for _ in range(3):
            self._seed_invocation(
                "popular", "s", ["x"], "success",
            )
        self._seed_invocation(
            "rare", "s", ["y"], "success",
        )
        rows = ph.successful_plans(since_seconds=3600)
        assert rows[0]["goal"] == "popular"
        assert rows[0]["success_count"] == 3
        assert rows[1]["goal"] == "rare"


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
