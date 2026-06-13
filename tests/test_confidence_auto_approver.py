"""Tests for engines.confidence_auto_approver — W963-29."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from engines.confidence_auto_approver import (
    ConfidenceAutoApproverEngine,
)
from engines.confidence_auto_approver.approver import (
    TrustDecision,
    _engine_trust_score,
    auto_approve_pending,
)


def _fake_action(
    aid="a-1", engine="loyalty", action_type="mint_code",
    store_id="main",
):
    a = MagicMock()
    a.id = aid
    a.engine = engine
    a.action_type = action_type
    a.store_id = store_id
    return a


def _fake_stats(positive=5, negative=0):
    return {
        "positive_count": positive,
        "negative_count": negative,
    }


# ── _engine_trust_score ───────────────────────────────────


class TestTrustScore:
    def test_zero_sample_no_trust(self):
        q = MagicMock()
        q.engine_outcome_stats.return_value = _fake_stats(0, 0)
        earned, n, r = _engine_trust_score(
            q, "loyalty", None,
            min_sample=5, min_positive_ratio=0.8,
        )
        assert not earned
        assert n == 0
        assert r == 0.0

    def test_high_ratio_above_threshold(self):
        q = MagicMock()
        q.engine_outcome_stats.return_value = _fake_stats(
            positive=8, negative=2,
        )
        earned, n, r = _engine_trust_score(
            q, "loyalty", None,
            min_sample=5, min_positive_ratio=0.8,
        )
        assert earned
        assert n == 10
        assert abs(r - 0.8) < 0.001

    def test_high_ratio_low_sample_no_trust(self):
        q = MagicMock()
        q.engine_outcome_stats.return_value = _fake_stats(
            positive=2, negative=0,
        )
        earned, n, _ = _engine_trust_score(
            q, "loyalty", None,
            min_sample=5, min_positive_ratio=0.8,
        )
        assert not earned
        assert n == 2

    def test_sample_high_ratio_below_threshold_no_trust(self):
        q = MagicMock()
        q.engine_outcome_stats.return_value = _fake_stats(
            positive=5, negative=5,
        )
        earned, n, r = _engine_trust_score(
            q, "loyalty", None,
            min_sample=5, min_positive_ratio=0.8,
        )
        assert not earned
        assert n == 10
        assert abs(r - 0.5) < 0.001

    def test_stats_exception_returns_no_trust(self):
        q = MagicMock()
        q.engine_outcome_stats.side_effect = RuntimeError(
            "db down",
        )
        earned, n, r = _engine_trust_score(
            q, "loyalty", None,
            min_sample=5, min_positive_ratio=0.8,
        )
        assert not earned
        assert n == 0


# ── auto_approve_pending ──────────────────────────────────


class TestAutoApprovePending:
    def test_no_pending_empty_report(self):
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = []
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = auto_approve_pending(confirmed=True)
        assert r.pending_scanned == 0
        assert r.approved_count == 0

    def test_dry_run_does_not_call_approve(self):
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = [_fake_action()]
        fake_queue.engine_outcome_stats.return_value = (
            _fake_stats(positive=10, negative=0)
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = auto_approve_pending(confirmed=False)
        assert r.approved_count == 0
        assert r.skip_reasons.get("dry_run") == 1
        assert not fake_queue.approve.called

    def test_trust_earned_approves(self):
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = [_fake_action()]
        fake_queue.engine_outcome_stats.return_value = (
            _fake_stats(positive=10, negative=0)
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = auto_approve_pending(confirmed=True)
        assert r.approved_count == 1
        assert r.decisions[0].approved is True
        fake_queue.approve.assert_called_once()
        call = fake_queue.approve.call_args
        assert (
            call.kwargs.get("decided_by")
            == "confidence_auto_approver"
        )

    def test_insufficient_sample_skipped(self):
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = [_fake_action()]
        fake_queue.engine_outcome_stats.return_value = (
            _fake_stats(positive=2, negative=0)
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = auto_approve_pending(
                confirmed=True, min_sample=5,
            )
        assert r.approved_count == 0
        assert (
            r.skip_reasons.get("insufficient_sample") == 1
        )

    def test_ratio_below_threshold_skipped(self):
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = [_fake_action()]
        fake_queue.engine_outcome_stats.return_value = (
            _fake_stats(positive=5, negative=5)
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = auto_approve_pending(
                confirmed=True,
                min_sample=5,
                min_positive_ratio=0.8,
            )
        assert r.approved_count == 0
        assert (
            r.skip_reasons.get("ratio_below_threshold") == 1
        )

    def test_per_engine_trust_cache(self):
        """Repeat actions from same engine hit stats once."""
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = [
            _fake_action(aid="a-1"),
            _fake_action(aid="a-2"),
            _fake_action(aid="a-3"),
        ]
        fake_queue.engine_outcome_stats.return_value = (
            _fake_stats(positive=10, negative=0)
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            auto_approve_pending(confirmed=True)
        # Cache means engine_outcome_stats called ONCE for
        # (loyalty, main) even though there are 3 actions
        assert fake_queue.engine_outcome_stats.call_count == 1

    def test_max_approvals_caps(self):
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = [
            _fake_action(aid=f"a-{i}") for i in range(10)
        ]
        fake_queue.engine_outcome_stats.return_value = (
            _fake_stats(positive=10, negative=0)
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = auto_approve_pending(
                confirmed=True, max_approvals=3,
            )
        assert r.approved_count == 3
        assert r.skip_reasons.get("max_approvals_hit") == 7

    def test_approve_exception_captured(self):
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = [_fake_action()]
        fake_queue.engine_outcome_stats.return_value = (
            _fake_stats(positive=10, negative=0)
        )
        fake_queue.approve.side_effect = RuntimeError("nope")
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = auto_approve_pending(confirmed=True)
        assert r.approved_count == 0
        assert r.skip_reasons.get("approve_failed") == 1

    def test_missing_engine_skipped(self):
        action = _fake_action(engine="")
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = [action]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            r = auto_approve_pending(confirmed=True)
        assert (
            r.skip_reasons.get("missing_id_or_engine") == 1
        )

    def test_per_store_filter_passes_store_id(self):
        fake_queue = MagicMock()
        fake_queue.list_pending.return_value = []
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake_queue,
        ):
            auto_approve_pending(
                confirmed=True, store_id="storeA",
            )
        kwargs = fake_queue.list_pending.call_args.kwargs
        assert kwargs.get("store_id") == "storeA"


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = ConfidenceAutoApproverEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = ConfidenceAutoApproverEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = ConfidenceAutoApproverEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = ConfidenceAutoApproverEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = ConfidenceAutoApproverEngine().run({})
        assert r["meta"]["engine"] == "confidence_auto_approver"


class TestEngineActions:
    def test_double_gate_yes_without_env_stays_dry_run(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(
                "SHOPAI_CONFIDENCE_AUTO_APPROVE", None,
            )
            r = ConfidenceAutoApproverEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["operator_confirmed"] is True
        assert r["data"]["env_gate_set"] is False
        assert r["data"]["confirmed"] is False

    def test_both_gates_set_confirms(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_CONFIDENCE_AUTO_APPROVE": "1"},
            clear=False,
        ):
            r = ConfidenceAutoApproverEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["confirmed"] is True

    def test_invalid_min_sample_falls_back(self):
        r = ConfidenceAutoApproverEngine().run({
            "data": {"min_sample": "abc"},
        })
        assert r["data"]["min_sample"] == 5

    def test_ratio_clamped_to_unit(self):
        r = ConfidenceAutoApproverEngine().run({
            "data": {"min_positive_ratio": 5.0},
        })
        assert r["data"]["min_positive_ratio"] == 1.0
        r = ConfidenceAutoApproverEngine().run({
            "data": {"min_positive_ratio": -1.0},
        })
        assert r["data"]["min_positive_ratio"] == 0.0
