"""Tests for engines.agi_evening_brief — W963-55."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from unittest.mock import patch

from engines.agi_evening_brief import AgiEveningBriefEngine
from engines.agi_evening_brief.briefer import (
    EveningBrief,
    _build_headline,
    _build_next_action,
    build_evening_brief,
)


# ── _build_headline ───────────────────────────────────────


class TestHeadline:
    def test_quiet_day(self):
        b = EveningBrief(store_id="")
        h = _build_headline(b)
        assert "Quiet day" in h

    def test_active_no_verdict_change(self):
        b = EveningBrief(
            store_id="",
            cycle_runs_today=3,
            actions_executed_today=12,
            current_verdict="earning",
        )
        h = _build_headline(b)
        assert "3 cycle" in h
        assert "12 action" in h
        assert "verdict=earning" in h
        assert "CHANGED" not in h

    def test_verdict_changed(self):
        b = EveningBrief(
            store_id="",
            cycle_runs_today=1,
            actions_executed_today=1,
            current_verdict="attributed_loss",
            previous_verdict="earning",
            verdict_changed=True,
        )
        h = _build_headline(b)
        assert "VERDICT CHANGED" in h
        assert "earning -> attributed_loss" in h


# ── _build_next_action ────────────────────────────────────


class TestNextAction:
    def test_failed_cycles_priority(self):
        b = EveningBrief(
            store_id="",
            cycle_runs_today=2,
            cycle_failed_runs=1,
        )
        n = _build_next_action(b)
        assert "shopai engine alerts" in n

    def test_ran_but_no_executed(self):
        b = EveningBrief(
            store_id="",
            cycle_runs_today=2,
            actions_executed_today=0,
        )
        n = _build_next_action(b)
        assert "approvals digest" in n

    def test_verdict_changed_notes_morning(self):
        b = EveningBrief(
            store_id="",
            cycle_runs_today=2,
            actions_executed_today=2,
            verdict_changed=True,
            current_verdict="earning",
        )
        n = _build_next_action(b)
        assert "morning-brief" in n

    def test_no_cycles(self):
        b = EveningBrief(store_id="")
        n = _build_next_action(b)
        assert "cycle schedule" in n

    def test_clean_day(self):
        b = EveningBrief(
            store_id="",
            cycle_runs_today=3,
            actions_executed_today=5,
        )
        n = _build_next_action(b)
        assert "Clean day" in n


# ── build_evening_brief (integration via mocks) ───────────


@dataclass
class _FakeRun:
    started_at: float = 0.0
    verdict: str = "clean"


@dataclass
class _FakeAction:
    id: str = "a1"
    decided_at: float = 0.0


@dataclass
class _FakeSummary:
    verdict: str = "earning"
    fleet_gross_profit: float = 150.0
    fleet_attribution_pct: float = 60.0


class TestBuildEveningBrief:
    def test_composes_substrate(self):
        now = time.time()
        runs = [
            _FakeRun(
                started_at=now - 3600, verdict="clean",
            ),
            _FakeRun(
                started_at=now - 7200, verdict="failed",
            ),
            _FakeRun(
                started_at=now - 86400 * 5,
                verdict="clean",
            ),  # outside window
        ]

        # Approval queue: 2 executed today + 1 outside
        execs = [
            _FakeAction(id="a1", decided_at=now - 1800),
            _FakeAction(id="a2", decided_at=now - 3600),
            _FakeAction(
                id="a3", decided_at=now - 86400 * 5,
            ),
        ]
        rejs = []

        def list_by_status(status):
            if status == "executed":
                return execs
            if status == "rejected":
                return rejs
            return []

        def get_outcomes(aid):
            return [
                {"recorded_at": now - 1000},
                {"recorded_at": now - 86400 * 10},
            ]

        with patch(
            "engines._cycle_history.recent_runs",
            return_value=runs,
        ), patch(
            "core.approval.queue.get_approval_queue",
        ) as fake_q, patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
            return_value=_FakeSummary(),
        ), patch(
            "engines.agi_earnings_history.store.query",
            return_value=[
                {
                    "ts": now - 86400 * 1.5,
                    "verdict": "organic_only",
                },
            ],
        ), patch(
            "engines.agi_earnings_history.store."
            "compute_trend",
            return_value={"verdict": "improving"},
        ):
            q = fake_q.return_value
            q.list_by_status.side_effect = list_by_status
            q.get_outcomes.side_effect = get_outcomes
            b = build_evening_brief(window_hours=24.0)

        assert b.cycle_runs_today == 2
        assert b.cycle_success_runs == 1
        assert b.cycle_failed_runs == 1
        assert b.actions_executed_today == 2
        # Outcomes: walks ALL executed actions (backfill
        # can record an outcome today for an action
        # executed days ago). 3 actions × 1 fresh outcome
        # = 3.
        assert b.outcomes_recorded_today == 3
        assert b.current_verdict == "earning"
        assert b.previous_verdict == "organic_only"
        assert b.verdict_changed is True
        assert b.history_trend == "improving"
        assert "VERDICT CHANGED" in b.headline

    def test_resilient_when_substrate_raises(self):
        with patch(
            "engines._cycle_history.recent_runs",
            side_effect=RuntimeError("x"),
        ), patch(
            "core.approval.queue.get_approval_queue",
            side_effect=RuntimeError("y"),
        ), patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
            side_effect=RuntimeError("z"),
        ), patch(
            "engines.agi_earnings_history.store.query",
            side_effect=RuntimeError("a"),
        ):
            b = build_evening_brief()
        assert b.cycle_runs_today == 0
        assert b.headline.startswith("Quiet day")
        assert "cycle schedule" in b.next_action

    def test_window_hours_floor(self):
        b = build_evening_brief(window_hours=0.0)
        assert b.window_hours == 1.0


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = AgiEveningBriefEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = AgiEveningBriefEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = AgiEveningBriefEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = AgiEveningBriefEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = AgiEveningBriefEngine().run({})
        assert (
            r["meta"]["engine"] == "agi_evening_brief"
        )

    def test_invalid_window_falls_back(self):
        r = AgiEveningBriefEngine().run({
            "data": {"window_hours": "xyz"},
        })
        assert r["data"]["window_hours"] == 24.0

    def test_has_headline(self):
        r = AgiEveningBriefEngine().run({})
        assert r["data"]["headline"]
