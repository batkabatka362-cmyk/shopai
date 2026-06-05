"""Tests for engines.agi_week_review — W963-56."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from unittest.mock import patch

from engines.agi_week_review import AgiWeekReviewEngine
from engines.agi_week_review.reviewer import (
    WeekReview,
    _build_headline,
    _build_next_action,
    _classify_week_verdict,
    build_week_review,
)


# ── _classify_week_verdict ────────────────────────────────


def _wr(timeline=None, cycle_total=0, snapshot_count=0):
    r = WeekReview(
        store_id="", cycle_total=cycle_total,
        snapshot_count=snapshot_count,
    )
    r.verdict_timeline = timeline or []
    return r


class TestClassifyWeekVerdict:
    def test_quiet_zero(self):
        assert _classify_week_verdict(_wr()) == "quiet"

    def test_running_blind(self):
        r = _wr(cycle_total=5, snapshot_count=0)
        assert _classify_week_verdict(r) == "running_blind"

    def test_growing_strong(self):
        timeline = [
            {"verdict": "organic_only"},
            {"verdict": "earning"},
        ]
        r = _wr(timeline=timeline, snapshot_count=2)
        assert _classify_week_verdict(r) == "growing"

    def test_recovering_one_step(self):
        # attributed_loss (2) -> earning (3) = +1
        timeline = [
            {"verdict": "attributed_loss"},
            {"verdict": "earning"},
        ]
        r = _wr(timeline=timeline, snapshot_count=2)
        assert _classify_week_verdict(r) == "recovering"

    def test_regressing_strong(self):
        timeline = [
            {"verdict": "earning"},
            {"verdict": "no_data"},
        ]
        r = _wr(timeline=timeline, snapshot_count=2)
        assert _classify_week_verdict(r) == "regressing"

    def test_softening_one_step(self):
        # earning (3) -> attributed_loss (2) = -1
        timeline = [
            {"verdict": "earning"},
            {"verdict": "attributed_loss"},
        ]
        r = _wr(timeline=timeline, snapshot_count=2)
        assert _classify_week_verdict(r) == "softening"

    def test_stable_earning(self):
        timeline = [
            {"verdict": "earning"},
            {"verdict": "earning"},
        ]
        r = _wr(timeline=timeline, snapshot_count=2)
        assert (
            _classify_week_verdict(r) == "stable_earning"
        )

    def test_stable_organic(self):
        timeline = [
            {"verdict": "organic_only"},
            {"verdict": "organic_only"},
        ]
        r = _wr(timeline=timeline, snapshot_count=2)
        assert (
            _classify_week_verdict(r) == "stable_organic"
        )

    def test_stable_loss(self):
        timeline = [
            {"verdict": "attributed_loss"},
            {"verdict": "attributed_loss"},
        ]
        r = _wr(timeline=timeline, snapshot_count=2)
        assert _classify_week_verdict(r) == "stable_loss"


# ── _build_headline ───────────────────────────────────────


class TestHeadline:
    def test_each_verdict_has_specific_form(self):
        for v, marker in (
            ("growing", "GROWING"),
            ("recovering", "RECOVERING"),
            ("regressing", "REGRESSING"),
            ("softening", "SOFTENING"),
            ("stable_earning", "STABLE EARNING"),
            ("stable_organic", "STABLE ORGANIC"),
            ("stable_loss", "STABLE LOSS"),
            ("running_blind", "RUNNING BLIND"),
            ("quiet", "QUIET WEEK"),
        ):
            r = WeekReview(store_id="", week_verdict=v)
            assert marker in _build_headline(r)


# ── _build_next_action ────────────────────────────────────


class TestNextAction:
    def test_each_branch(self):
        cases = [
            ("regressing", "engine alerts"),
            ("growing", "transfer scan"),
            ("running_blind", "morning-brief --record"),
            ("stable_loss", "shopai roas"),
            ("stable_organic", "engine ranking"),
            ("quiet", "cycle run"),
            ("recovering", "morning-brief"),
            ("softening", "action-critic"),
            ("stable_earning", "batch-review"),
        ]
        for verdict, marker in cases:
            r = WeekReview(store_id="", week_verdict=verdict)
            n = _build_next_action(r)
            assert marker in n, (
                f"{verdict} missing {marker} in {n}"
            )


# ── build_week_review (integration via mocks) ─────────────


@dataclass
class _FakeRun:
    started_at: float = 0.0
    verdict: str = "clean"


@dataclass
class _FakeAction:
    decided_at: float = 0.0


@dataclass
class _FakeRecon:
    fleet_attribution_pct: float = 42.0
    fleet_orphan_action_count: int = 1


class TestBuildWeekReview:
    def test_composes_substrate(self):
        now = time.time()
        runs = [
            _FakeRun(started_at=now - 3600, verdict="clean"),
            _FakeRun(
                started_at=now - 7200, verdict="mostly_ok",
            ),
            _FakeRun(
                started_at=now - 10800, verdict="failed",
            ),
            _FakeRun(
                started_at=now - 86400 * 30,
                verdict="clean",
            ),  # outside 7d
        ]
        execs = [
            _FakeAction(decided_at=now - 3600),
            _FakeAction(decided_at=now - 86400 * 30),
        ]
        rejs = [_FakeAction(decided_at=now - 7200)]

        def list_by_status(status):
            if status == "executed":
                return execs
            if status == "rejected":
                return rejs
            return []

        # Snapshots oldest-to-newest after reversing
        snaps_newest_first = [
            {
                "ts": now - 3600,
                "verdict": "earning",
                "gross_profit": 200.0,
            },
            {
                "ts": now - 3 * 86400,
                "verdict": "organic_only",
                "gross_profit": 100.0,
            },
            {
                "ts": now - 5 * 86400,
                "verdict": "no_data",
                "gross_profit": 0.0,
            },
        ]

        with patch(
            "engines._cycle_history.recent_runs",
            return_value=runs,
        ), patch(
            "core.approval.queue.get_approval_queue",
        ) as fake_q, patch(
            "engines.agi_earnings_history.store.query",
            return_value=snaps_newest_first,
        ), patch(
            "engines.revenue_reconciliation.reconciler."
            "reconcile_fleet",
            return_value=_FakeRecon(),
        ):
            q = fake_q.return_value
            q.list_by_status.side_effect = list_by_status
            r = build_week_review(days=7)

        assert r.cycle_total == 3
        # 2 ok of 3 decided
        assert abs(r.cycle_success_rate - 0.667) < 0.01
        assert r.actions_executed == 1
        assert r.actions_rejected == 1
        assert r.rejection_rate == 0.5
        assert r.snapshot_count == 3
        # Timeline reversed: oldest = no_data, newest = earning
        # rank delta = 3 - 0 = 3 -> growing
        assert r.week_verdict == "growing"
        assert "GROWING" in r.headline
        assert "transfer scan" in r.next_action
        assert r.fleet_attribution_pct == 42.0

    def test_resilient_when_substrate_raises(self):
        with patch(
            "engines._cycle_history.recent_runs",
            side_effect=RuntimeError("a"),
        ), patch(
            "core.approval.queue.get_approval_queue",
            side_effect=RuntimeError("b"),
        ), patch(
            "engines.agi_earnings_history.store.query",
            side_effect=RuntimeError("c"),
        ), patch(
            "engines.revenue_reconciliation.reconciler."
            "reconcile_fleet",
            side_effect=RuntimeError("d"),
        ):
            r = build_week_review()
        assert r.week_verdict == "quiet"
        assert r.cycle_total == 0
        assert r.snapshot_count == 0

    def test_days_floor(self):
        r = build_week_review(days=1)
        assert r.days == 2

    def test_days_ceiling(self):
        r = build_week_review(days=999)
        assert r.days == 90


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = AgiWeekReviewEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = AgiWeekReviewEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = AgiWeekReviewEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = AgiWeekReviewEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = AgiWeekReviewEngine().run({})
        assert r["meta"]["engine"] == "agi_week_review"

    def test_invalid_days_falls_back(self):
        r = AgiWeekReviewEngine().run({
            "data": {"days": "abc"},
        })
        assert r["data"]["days"] == 7

    def test_has_headline(self):
        r = AgiWeekReviewEngine().run({})
        assert r["data"]["headline"]
