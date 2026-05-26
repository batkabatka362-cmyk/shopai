"""Tests for engines._approval_velocity."""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from engines._approval_velocity import (
    EngineVelocity, VelocityReport, compute_velocity_report,
)


def _action(*, engine, proposed_at=None, decided_at=None,
            action_id="x"):
    return SimpleNamespace(
        id=action_id,
        engine=engine,
        proposed_at=proposed_at,
        decided_at=decided_at,
    )


def _fake_queue(*, pending=None, approved=None, rejected=None):
    q = MagicMock()

    def _list_by_status(status):
        return {
            "pending": pending or [],
            "approved": approved or [],
            "rejected": rejected or [],
        }.get(status, [])

    q.list_by_status.side_effect = _list_by_status
    return q


class TestEngineVelocityProperties:

    def test_rejection_rate_zero_when_no_decisions(self):
        e = EngineVelocity(engine="x")
        assert e.rejection_rate == 0.0

    def test_rejection_rate_computed(self):
        e = EngineVelocity(
            engine="x", approved_count=3, rejected_count=1,
        )
        assert e.rejection_rate == 0.25

    def test_avg_latency_none_when_no_decisions(self):
        e = EngineVelocity(engine="x")
        assert e.avg_latency_hours is None

    def test_avg_latency_computed(self):
        e = EngineVelocity(
            engine="x",
            total_decision_latency_hours=10.0,
            decisions_with_latency=2,
        )
        assert e.avg_latency_hours == 5.0


class TestReport:

    def test_empty(self):
        q = _fake_queue()
        r = compute_velocity_report(queue=q)
        assert r.total_actions_in_window == 0
        assert r.per_engine == []
        assert r.top_engine is None

    def test_groups_by_engine(self):
        now = time.time()
        q = _fake_queue(
            pending=[
                _action(engine="loyalty", proposed_at=now - 100),
                _action(engine="loyalty", proposed_at=now - 200),
            ],
            approved=[
                _action(engine="pricing", proposed_at=now - 300),
            ],
        )
        r = compute_velocity_report(queue=q)
        per_engine_map = {e.engine: e for e in r.per_engine}
        assert per_engine_map["loyalty"].pending_count == 2
        assert per_engine_map["loyalty"].proposed_count == 2
        assert per_engine_map["pricing"].approved_count == 1

    def test_window_filter_drops_old_actions(self):
        now = time.time()
        old = now - 1_000_000  # >7 days ago
        q = _fake_queue(
            pending=[
                _action(engine="loyalty", proposed_at=now - 60),
                _action(engine="loyalty", proposed_at=old),
            ],
        )
        r = compute_velocity_report(
            window_hours=168.0, queue=q,
        )
        # Only the fresh one counts
        per_engine_map = {e.engine: e for e in r.per_engine}
        assert per_engine_map["loyalty"].pending_count == 1

    def test_top_engine_highest_proposed(self):
        now = time.time()
        q = _fake_queue(
            pending=[
                _action(engine="big", proposed_at=now),
                _action(engine="big", proposed_at=now),
                _action(engine="big", proposed_at=now),
                _action(engine="small", proposed_at=now),
            ],
        )
        r = compute_velocity_report(queue=q)
        assert r.top_engine == "big"

    def test_highest_rejection_surfaced(self):
        now = time.time()
        q = _fake_queue(
            approved=[
                _action(
                    engine="trustworthy", proposed_at=now,
                ),
                _action(
                    engine="trustworthy", proposed_at=now,
                ),
                _action(
                    engine="trustworthy", proposed_at=now,
                ),
            ],
            rejected=[
                _action(engine="misfire", proposed_at=now),
                _action(engine="misfire", proposed_at=now),
                _action(engine="misfire", proposed_at=now),
                _action(engine="misfire", proposed_at=now),
            ],
        )
        # misfire has 100% rejection rate
        q.list_by_status.side_effect = lambda s: (
            {"pending": [],
             "approved": [_action(engine="misfire", proposed_at=now)],
             "rejected": [
                 _action(engine="misfire", proposed_at=now),
                 _action(engine="misfire", proposed_at=now),
                 _action(engine="misfire", proposed_at=now),
                 _action(engine="misfire", proposed_at=now),
             ]}.get(s, [])
        )
        r = compute_velocity_report(queue=q)
        assert r.highest_rejection_engine == "misfire"

    def test_decision_latency_aggregated(self):
        proposed = time.time() - 7200  # 2h ago
        decided = time.time() - 3600   # 1h ago, so latency=1h
        q = _fake_queue(
            approved=[
                _action(
                    engine="x", proposed_at=proposed,
                    decided_at=decided,
                ),
            ],
        )
        r = compute_velocity_report(queue=q)
        per_engine_map = {e.engine: e for e in r.per_engine}
        # Latency ~= 1h
        assert (
            0.9 < per_engine_map["x"].avg_latency_hours < 1.1
        )
