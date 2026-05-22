"""Tests for ``core.autonomous.cycle_transfer``.

Cross-store TRANSFER phase. Coverage:

  - Env gate + thresholds resolve correctly
  - find_transfer_candidates returns candidates excluding
    already-tried target actions
  - Outcomes filtering (min_positive_outcomes)
  - maybe_apply_transfers Pattern J + env gate
  - history recording on successful enqueue
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from core.autonomous import cycle_transfer as ct


_ENV_VARS = (
    "SHOPAI_AUTO_TRANSFER",
    "SHOPAI_AUTO_TRANSFER_MAX_PER_STORE",
    "SHOPAI_AUTO_TRANSFER_MIN_OUTCOMES",
)


@pytest.fixture(autouse=True)
def _clean_env():
    saved = {k: os.environ.pop(k, None) for k in _ENV_VARS}
    yield
    for k in _ENV_VARS:
        os.environ.pop(k, None)
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


def _action(
    *,
    id="a1",
    engine="loyalty",
    action_type="mint_recovery_code",
    capability="SHOPAI_CREATE_DISCOUNT",
    params=None,
):
    a = MagicMock()
    a.id = id
    a.engine = engine
    a.action_type = action_type
    a.capability = capability
    a.params = params or {"discount_pct": 10}
    return a


def _fake_queue(
    *,
    source_actions=None,
    target_actions=None,
    outcomes=None,
):
    q = MagicMock()
    target_actions = target_actions or []

    def _list(status, *, engine=None, store_id=None, limit=2000):
        from core.approval.queue import ApprovalStatus
        # Return source actions only for EXECUTED + source
        # store; target actions for all statuses on target
        # (mirrors the real semantics).
        if store_id == "target":
            return target_actions
        if status == ApprovalStatus.EXECUTED:
            return source_actions or []
        return []

    q.list_by_status.side_effect = _list
    q.get_outcomes.side_effect = lambda aid: (
        outcomes or []
    )
    q.enqueue.side_effect = lambda **kw: MagicMock(
        id="enqueued_1",
    )
    return q


class TestEnvGates:

    def test_defaults(self):
        assert ct.is_enabled() is False
        assert ct.max_per_store() == 3
        assert ct.min_outcomes() == 1

    def test_env_overrides(self):
        os.environ["SHOPAI_AUTO_TRANSFER"] = "1"
        os.environ["SHOPAI_AUTO_TRANSFER_MAX_PER_STORE"] = "5"
        os.environ["SHOPAI_AUTO_TRANSFER_MIN_OUTCOMES"] = "2"
        assert ct.is_enabled() is True
        assert ct.max_per_store() == 5
        assert ct.min_outcomes() == 2

    def test_invalid_falls_back(self):
        os.environ["SHOPAI_AUTO_TRANSFER_MAX_PER_STORE"] = "abc"
        assert ct.max_per_store() == 3


class TestFindCandidates:

    def test_empty_when_no_target_store(self):
        assert (
            ct.find_transfer_candidates(target_store_id="")
            == []
        )

    def test_empty_when_no_peers(self):
        q = _fake_queue()
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out = ct.find_transfer_candidates(
                target_store_id="target",
                fleet_store_ids=["target"],
            )
        assert out == []

    def test_candidate_found(self):
        source_actions = [
            _action(id="src1"),
        ]
        outcomes = [
            {
                "polarity": "positive",
                "metrics": {"revenue": 500.0},
            },
        ]
        q = _fake_queue(
            source_actions=source_actions,
            target_actions=[],
            outcomes=outcomes,
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out = ct.find_transfer_candidates(
                target_store_id="target",
                fleet_store_ids=["target", "peer1"],
            )
        assert len(out) == 1
        assert out[0].engine == "loyalty"
        assert out[0].source_store_id == "peer1"
        assert out[0].positive_outcomes == 1
        assert out[0].total_revenue == 500.0

    def test_already_tried_excluded(self):
        source_actions = [_action()]
        target_actions = [_action()]  # same engine + action_type
        q = _fake_queue(
            source_actions=source_actions,
            target_actions=target_actions,
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out = ct.find_transfer_candidates(
                target_store_id="target",
                fleet_store_ids=["target", "peer1"],
            )
        assert out == []

    def test_min_outcomes_filter(self):
        # source action with ZERO positive outcomes
        source_actions = [_action()]
        q = _fake_queue(
            source_actions=source_actions,
            target_actions=[],
            outcomes=[],
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out = ct.find_transfer_candidates(
                target_store_id="target",
                fleet_store_ids=["target", "peer1"],
                min_positive_outcomes=1,
            )
        # No positive outcomes -> filtered
        assert out == []

    def test_max_candidates_caps(self):
        source_actions = [
            _action(
                id=f"src{i}",
                action_type=f"action_{i}",
            )
            for i in range(10)
        ]
        outcomes = [
            {"polarity": "positive", "metrics": {}},
        ]
        q = _fake_queue(
            source_actions=source_actions,
            target_actions=[],
            outcomes=outcomes,
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out = ct.find_transfer_candidates(
                target_store_id="target",
                fleet_store_ids=["target", "peer1"],
                max_candidates=2,
            )
        assert len(out) == 2


class TestMaybeApply:

    def test_pattern_j_short_circuits(self):
        os.environ["SHOPAI_AUTO_TRANSFER"] = "1"
        source_actions = [_action()]
        outcomes = [
            {"polarity": "positive", "metrics": {}},
        ]
        q = _fake_queue(
            source_actions=source_actions,
            outcomes=outcomes,
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out = ct.maybe_apply_transfers(
                target_store_id="target",
                fleet_store_ids=["target", "peer1"],
            )
        assert out["candidates_found"] == 1
        # Pattern J: nothing applied
        assert out["applied"] == 0
        q.enqueue.assert_not_called()

    def test_env_gate_off_no_enqueue(self):
        # Env gate off + Pattern J off -- still no enqueue
        source_actions = [_action()]
        outcomes = [
            {"polarity": "positive", "metrics": {}},
        ]
        q = _fake_queue(
            source_actions=source_actions,
            outcomes=outcomes,
        )
        with patch(
            "core.autonomous.cycle_transfer."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out = ct.maybe_apply_transfers(
                target_store_id="target",
                fleet_store_ids=["target", "peer1"],
            )
        assert out["candidates_found"] == 1
        assert out["applied"] == 0
        q.enqueue.assert_not_called()

    def test_enabled_enqueues(self):
        os.environ["SHOPAI_AUTO_TRANSFER"] = "1"
        source_actions = [_action()]
        outcomes = [
            {"polarity": "positive", "metrics": {}},
        ]
        q = _fake_queue(
            source_actions=source_actions,
            outcomes=outcomes,
        )
        with patch(
            "core.autonomous.cycle_transfer."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ), patch(
            "core.autonomous.transfer_history."
            "record_transfer",
        ) as mock_record:
            out = ct.maybe_apply_transfers(
                target_store_id="target",
                fleet_store_ids=["target", "peer1"],
            )
        assert out["candidates_found"] == 1
        assert out["applied"] == 1
        q.enqueue.assert_called_once()
        # History was recorded
        mock_record.assert_called_once()


class TestComputeEffectiveness:
    """Join transfer history with queue outcomes."""

    def _event(self, **kw):
        from core.autonomous.transfer_history import (
            TransferEvent,
        )
        defaults = dict(
            target_store_id="b",
            source_store_id="a",
            engine="loyalty",
            action_type="mint",
            capability="cap",
            recorded_at=1700000000.0,
            action_id="enq_1",
            metrics={},
        )
        defaults.update(kw)
        return TransferEvent(**defaults)

    def test_empty_history_zero_stats(self):
        with patch(
            "core.autonomous.transfer_history."
            "recent_history",
            return_value=[],
        ):
            out = ct.compute_effectiveness()
        assert out["transfers_total"] == 0
        assert out["with_outcomes"] == 0
        assert out["positive_count"] == 0

    def test_aggregates_outcomes(self):
        events = [
            self._event(action_id="a1"),
            self._event(
                action_id="a2",
                source_store_id="a",
            ),
            self._event(
                action_id="a3",
                source_store_id="other",
            ),
        ]
        queue = MagicMock()
        outcomes_by_id = {
            "a1": [
                {
                    "polarity": "positive",
                    "metrics": {"revenue": 500.0},
                },
            ],
            "a2": [
                {
                    "polarity": "negative",
                    "metrics": {},
                },
            ],
            "a3": [],  # no outcomes recorded yet
        }
        queue.get_outcomes.side_effect = lambda aid: (
            outcomes_by_id.get(aid, [])
        )
        with patch(
            "core.autonomous.transfer_history."
            "recent_history",
            return_value=events,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=queue,
        ):
            out = ct.compute_effectiveness()
        assert out["transfers_total"] == 3
        # Only a1 + a2 had outcomes
        assert out["with_outcomes"] == 2
        assert out["positive_count"] == 1
        assert out["negative_count"] == 1
        assert out["total_revenue"] == 500.0
        # Per-source breakdown
        assert (
            out["by_source_store"]["a"]["transfers"] == 2
        )
        assert (
            out["by_source_store"]["a"]["positive"] == 1
        )
        assert (
            out["by_source_store"]["a"]["negative"] == 1
        )
        assert (
            out["by_source_store"]["other"]["transfers"]
            == 1
        )

    def test_missing_action_id_skipped(self):
        events = [
            self._event(action_id=None),
        ]
        queue = MagicMock()
        with patch(
            "core.autonomous.transfer_history."
            "recent_history",
            return_value=events,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=queue,
        ):
            out = ct.compute_effectiveness()
        # Transfer counted, but no outcome lookup attempted
        assert out["transfers_total"] == 1
        assert out["with_outcomes"] == 0
        queue.get_outcomes.assert_not_called()

    def test_queue_failure_returns_partial(self):
        events = [self._event()]
        with patch(
            "core.autonomous.transfer_history."
            "recent_history",
            return_value=events,
        ), patch(
            "core.approval.queue.get_approval_queue",
            side_effect=RuntimeError("queue gone"),
        ):
            out = ct.compute_effectiveness()
        # Transfers counted before queue failure
        assert out["transfers_total"] == 1
        # No outcomes joined
        assert out["with_outcomes"] == 0


class TestConfigSummary:

    def test_shape(self):
        cfg = ct.config_summary()
        assert "enabled" in cfg
        assert "max_per_store" in cfg
        assert "min_outcomes" in cfg
