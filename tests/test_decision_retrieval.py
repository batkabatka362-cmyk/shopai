"""Tests for the decision-time RAG retriever
(``core.decision_retrieval``).

AGI roadmap Phase 2 layer 2. Verifies:

  - Engine filtering (cross-engine candidates dropped)
  - Action-type / capability / params / recency scoring
  - Top-k truncation
  - Outcome joining + summary aggregation
  - Status filter (default executed+failed; configurable)
  - Resilience: empty pools, missing fields, queue raise
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from core.decision_retrieval import DecisionRetrieval
from core.decision_retrieval.retriever import (
    _params_overlap,
    _summarize_outcomes,
)


# ─── Fake queue ──────────────────────────────────────────────


class _FakeAction:
    """Minimal ApprovalAction stand-in -- carries to_dict()."""

    def __init__(self, **fields):
        self._fields = fields

    def to_dict(self):
        return dict(self._fields)


class _FakeStatus:
    """Mimics ApprovalStatus.executed.value etc."""
    def __init__(self, value):
        self.value = value


def _fake_queue(*, actions_by_status=None, outcomes=None):
    """Build a MagicMock queue with seeded actions + outcomes.

    actions_by_status is a dict {status_name: [_FakeAction, ...]}.
    """
    q = MagicMock()
    actions_by_status = actions_by_status or {}
    outcomes = outcomes or {}

    def _list_by_status(status, *, engine=None, limit=100):
        candidates = actions_by_status.get(status.value, [])
        if engine:
            candidates = [
                a for a in candidates
                if a._fields.get("engine") == engine
            ]
        return candidates[:limit]

    def _get_outcomes(action_id):
        return outcomes.get(action_id, [])

    q.list_by_status.side_effect = _list_by_status
    q.get_outcomes.side_effect = _get_outcomes
    return q


# ─── _params_overlap helper ──────────────────────────────────


class TestParamsOverlap:

    def test_identical_dicts(self):
        a = {"discount_pct": 10, "code": "WELCOME"}
        assert _params_overlap(a, dict(a)) == 1.0

    def test_disjoint_keys(self):
        # No key overlap → Jaccard = 0, value match path skipped
        a = {"x": 1}
        b = {"y": 2}
        assert _params_overlap(a, b) == 0.0

    def test_partial_key_overlap_same_values(self):
        a = {"discount_pct": 10, "code": "W"}
        b = {"discount_pct": 10, "duration": 7}
        # Jaccard: 1/3, value_match: 1/1 = 1.0
        # → 0.5*0.333 + 0.5*1.0 ≈ 0.667
        score = _params_overlap(a, b)
        assert 0.6 < score < 0.7

    def test_partial_key_overlap_diff_values(self):
        a = {"discount_pct": 10}
        b = {"discount_pct": 15, "duration": 7}
        # Jaccard: 1/2, value_match: 0/1 = 0
        # → 0.5*0.5 + 0.5*0 = 0.25
        assert _params_overlap(a, b) == 0.25

    def test_both_empty(self):
        assert _params_overlap({}, {}) == 0.0


# ─── _summarize_outcomes helper ──────────────────────────────


class TestOutcomeSummary:

    def test_empty(self):
        s = _summarize_outcomes([])
        assert s["count"] == 0
        assert s["has_positive"] is False
        assert s["has_negative"] is False
        assert s["total_revenue"] == 0.0

    def test_mixed_polarities(self):
        outcomes = [
            {"polarity": "positive", "metrics": {"revenue": 100.0}},
            {"polarity": "positive", "metrics": {"revenue": 50.0}},
            {"polarity": "negative", "metrics": {"revenue": -20.0}},
            {"polarity": "neutral", "metrics": {}},
        ]
        s = _summarize_outcomes(outcomes)
        assert s["count"] == 4
        assert s["polarity_counts"]["positive"] == 2
        assert s["polarity_counts"]["negative"] == 1
        assert s["polarity_counts"]["neutral"] == 1
        assert s["has_positive"] is True
        assert s["has_negative"] is True
        # 100 + 50 + (-20) = 130, +0 from neutral
        assert s["total_revenue"] == 130.0

    def test_unparseable_revenue_ignored(self):
        outcomes = [
            {"polarity": "positive", "metrics": {"revenue": "not a number"}},
            {"polarity": "positive", "metrics": {"revenue": 50.0}},
        ]
        s = _summarize_outcomes(outcomes)
        assert s["total_revenue"] == 50.0


# ─── Retrieval ───────────────────────────────────────────────


class TestRetrieval:

    def test_returns_empty_when_no_candidates(self):
        from core.approval.queue import ApprovalStatus

        q = _fake_queue(actions_by_status={})
        r = DecisionRetrieval(queue=q)
        results = r.retrieve(engine="loyalty")
        assert results == []

    def test_engine_filter_drops_cross_engine(self):
        from core.approval.queue import ApprovalStatus

        q = _fake_queue(actions_by_status={
            "executed": [
                _FakeAction(
                    id="a1", engine="loyalty", action_type="mint",
                    capability="C", params={}, status="executed",
                    decided_at=time.time(), proposed_at=time.time(),
                ),
                _FakeAction(
                    id="a2", engine="dynamic_pricing", action_type="mint",
                    capability="C", params={}, status="executed",
                    decided_at=time.time(), proposed_at=time.time(),
                ),
            ],
        })
        r = DecisionRetrieval(queue=q)
        results = r.retrieve(engine="loyalty")
        # The fake queue's engine filter dropped the dynamic_pricing one
        assert len(results) == 1
        assert results[0]["action_id"] == "a1"

    def test_action_type_boosts_relevance(self):
        now = time.time()
        q = _fake_queue(actions_by_status={
            "executed": [
                _FakeAction(
                    id="match", engine="loyalty", action_type="mint",
                    capability="C", params={}, status="executed",
                    decided_at=now, proposed_at=now,
                ),
                _FakeAction(
                    id="other", engine="loyalty", action_type="archive",
                    capability="C", params={}, status="executed",
                    decided_at=now, proposed_at=now,
                ),
            ],
        })
        r = DecisionRetrieval(queue=q)
        results = r.retrieve(engine="loyalty", action_type="mint")
        # 'match' (with matching action_type) should rank first
        assert results[0]["action_id"] == "match"
        # Its action_type score component is 1.0, the other's is 0.0
        assert results[0]["score_components"]["action_type"] == 1.0

    def test_capability_boosts_relevance(self):
        now = time.time()
        q = _fake_queue(actions_by_status={
            "executed": [
                _FakeAction(
                    id="c_match", engine="loyalty", action_type="mint",
                    capability="X_CAP", params={}, status="executed",
                    decided_at=now, proposed_at=now,
                ),
                _FakeAction(
                    id="c_other", engine="loyalty", action_type="mint",
                    capability="Y_CAP", params={}, status="executed",
                    decided_at=now, proposed_at=now,
                ),
            ],
        })
        r = DecisionRetrieval(queue=q)
        results = r.retrieve(engine="loyalty", capability="X_CAP")
        assert results[0]["action_id"] == "c_match"

    def test_params_overlap_boosts_relevance(self):
        now = time.time()
        q = _fake_queue(actions_by_status={
            "executed": [
                _FakeAction(
                    id="p_match", engine="loyalty", action_type="mint",
                    capability="C",
                    params={"discount_pct": 10, "code": "WELCOME"},
                    status="executed",
                    decided_at=now, proposed_at=now,
                ),
                _FakeAction(
                    id="p_other", engine="loyalty", action_type="mint",
                    capability="C",
                    params={"unrelated": "stuff"},
                    status="executed",
                    decided_at=now, proposed_at=now,
                ),
            ],
        })
        r = DecisionRetrieval(queue=q)
        results = r.retrieve(
            engine="loyalty",
            params={"discount_pct": 10, "code": "WELCOME"},
        )
        assert results[0]["action_id"] == "p_match"

    def test_recency_decay(self):
        now = time.time()
        old = now - 14 * 86_400.0  # 14 days = 0.25 weight
        q = _fake_queue(actions_by_status={
            "executed": [
                _FakeAction(
                    id="recent", engine="loyalty", action_type="mint",
                    capability="C", params={}, status="executed",
                    decided_at=now, proposed_at=now,
                ),
                _FakeAction(
                    id="old", engine="loyalty", action_type="mint",
                    capability="C", params={}, status="executed",
                    decided_at=old, proposed_at=old,
                ),
            ],
        })
        r = DecisionRetrieval(queue=q)
        results = r.retrieve(engine="loyalty")
        # Recent should outrank old via recency component
        assert results[0]["action_id"] == "recent"
        recent_rec = results[0]["score_components"]["recency"]
        old_rec = results[1]["score_components"]["recency"]
        assert recent_rec > old_rec
        assert recent_rec > 0.9  # ~1.0 minus tiny epsilon
        assert old_rec < 0.3     # 14 days = 2 half-lives = 0.25

    def test_k_truncates(self):
        now = time.time()
        q = _fake_queue(actions_by_status={
            "executed": [
                _FakeAction(
                    id=f"a{i}", engine="loyalty", action_type="mint",
                    capability="C", params={}, status="executed",
                    decided_at=now - i, proposed_at=now - i,
                )
                for i in range(20)
            ],
        })
        r = DecisionRetrieval(queue=q)
        results = r.retrieve(engine="loyalty", k=5)
        assert len(results) == 5

    def test_includes_executed_and_failed_by_default(self):
        now = time.time()
        q = _fake_queue(actions_by_status={
            "executed": [
                _FakeAction(
                    id="exec", engine="loyalty", action_type="mint",
                    capability="C", params={}, status="executed",
                    decided_at=now, proposed_at=now,
                ),
            ],
            "failed": [
                _FakeAction(
                    id="fail", engine="loyalty", action_type="mint",
                    capability="C", params={}, status="failed",
                    decided_at=now, proposed_at=now,
                ),
            ],
            "rejected": [
                _FakeAction(
                    id="rej", engine="loyalty", action_type="mint",
                    capability="C", params={}, status="rejected",
                    decided_at=now, proposed_at=now,
                ),
            ],
        })
        r = DecisionRetrieval(queue=q)
        results = r.retrieve(engine="loyalty")
        ids = {e["action_id"] for e in results}
        assert "exec" in ids
        assert "fail" in ids
        assert "rej" not in ids  # not in default status set

    def test_statuses_argument_widens_pool(self):
        now = time.time()
        q = _fake_queue(actions_by_status={
            "rejected": [
                _FakeAction(
                    id="rej", engine="loyalty", action_type="mint",
                    capability="C", params={}, status="rejected",
                    decided_at=now, proposed_at=now,
                ),
            ],
        })
        r = DecisionRetrieval(queue=q)
        results = r.retrieve(
            engine="loyalty",
            statuses=("executed", "failed", "rejected"),
        )
        assert results and results[0]["action_id"] == "rej"

    def test_outcomes_attached_to_top_k(self):
        now = time.time()
        q = _fake_queue(
            actions_by_status={
                "executed": [
                    _FakeAction(
                        id="with_outcome",
                        engine="loyalty", action_type="mint",
                        capability="C", params={},
                        status="executed",
                        decided_at=now, proposed_at=now,
                    ),
                ],
            },
            outcomes={
                "with_outcome": [
                    {"polarity": "positive",
                     "metrics": {"revenue": 75.0},
                     "recorded_at": now},
                ],
            },
        )
        r = DecisionRetrieval(queue=q)
        results = r.retrieve(engine="loyalty")
        entry = results[0]
        assert entry["outcomes"][0]["polarity"] == "positive"
        assert entry["outcome_summary"]["has_positive"] is True
        assert entry["outcome_summary"]["total_revenue"] == 75.0

    def test_queue_raise_degrades(self):
        q = MagicMock()
        q.list_by_status.side_effect = RuntimeError("queue down")
        r = DecisionRetrieval(queue=q)
        results = r.retrieve(engine="loyalty")
        # No crash, just empty
        assert results == []
