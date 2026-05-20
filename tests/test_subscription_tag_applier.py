"""Tests for ``engines.subscription.tag_applier``.

Pushes ``shopai-subscription-at-risk`` tags on high-risk
subscribers (optionally medium-risk) via SHOPIFY_TAG_CUSTOMER.
Two paths (queue / direct) selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     subscriber_id / "unknown" literal skipped / non-high
     skipped / medium gated by include_medium / dedup / bad
     risk coerced).
  2. Direct path: SHOPIFY_TAG_CUSTOMER called per
     at-risk subscriber; router unavailable, adapter failure,
     raise all handled.
  3. Queue path: each at-risk subscriber enqueues with
     correct params; queue unavailable; per-enqueue raise
     doesn't abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval / include_medium propagate.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.subscription.tag_applier import (
    apply_subscription_tags,
)


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _ok(data=None):
    return SimpleNamespace(ok=True, data=data or {}, error=None)


def _fail(err="rejected"):
    return SimpleNamespace(ok=False, data=None, error=err)


def _risk(
    *,
    sid="gid://shopify/Customer/1",
    level="high",
    score=0.75,
    action="immediate_retention_outreach",
):
    return {
        "subscriber_id": sid,
        "risk": score,
        "risk_level": level,
        "churn_factors": ["multiple_payment_failures (2)"],
        "recommended_action": action,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_subscription_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_subscription_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_subscription_tags(
            ["bad", 42, _risk(sid="gid://c/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_subscriber_id_skipped(self, isolated_queue):
        results = apply_subscription_tags(
            [_risk(sid="")],
        )
        assert results == []

    def test_unknown_subscriber_id_skipped(self, isolated_queue):
        # The engine uses "unknown" as a default — not a real
        # subscriber, don't tag.
        results = apply_subscription_tags(
            [_risk(sid="unknown")],
        )
        assert results == []

    def test_only_high_tagged_by_default(self, isolated_queue):
        results = apply_subscription_tags(
            [
                _risk(sid="gid://c/1", level="high"),
                _risk(sid="gid://c/2", level="medium"),
                _risk(sid="gid://c/3", level="low"),
                _risk(sid="gid://c/4", level="minimal"),
            ],
        )
        assert len(results) == 1
        assert results[0]["risk_level"] == "high"

    def test_include_medium_opts_in(self, isolated_queue):
        results = apply_subscription_tags(
            [
                _risk(sid="gid://c/1", level="high"),
                _risk(sid="gid://c/2", level="medium"),
                _risk(sid="gid://c/3", level="low"),
            ],
            include_medium=True,
        )
        assert len(results) == 2
        levels = {r["risk_level"] for r in results}
        assert levels == {"high", "medium"}

    def test_duplicate_subscribers_deduped(self, isolated_queue):
        results = apply_subscription_tags(
            [
                _risk(sid="gid://c/1", level="high"),
                _risk(sid="gid://c/1", level="high"),  # dup
                _risk(sid="gid://c/2", level="high"),
            ],
        )
        assert len(results) == 2
        sids = {r["subscriber_id"] for r in results}
        assert sids == {"gid://c/1", "gid://c/2"}

    def test_bad_risk_score_coerced_to_zero(self, isolated_queue):
        # Bad risk score is fine — bucket is still high
        # (gated by risk_level, not risk number).
        results = apply_subscription_tags(
            [{
                "subscriber_id": "gid://c/1",
                "risk_level": "high",
                "risk": "very",
            }],
        )
        assert len(results) == 1
        assert results[0]["risk"] == 0.0

    def test_case_insensitive_risk_level(self, isolated_queue):
        # "HIGH" / "High" should still match
        results = apply_subscription_tags(
            [
                _risk(sid="gid://c/1", level="HIGH"),
                _risk(sid="gid://c/2", level="High"),
            ],
        )
        assert len(results) == 2


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, risks, **kwargs):
        captured = {}

        def _exec(cap, params):
            captured.setdefault("calls", []).append({
                "cap": cap, "params": params,
            })
            return _ok()

        router = SimpleNamespace(execute=_exec)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_subscription_tags(
                risks, require_approval=False, **kwargs,
            )
        return results, captured

    def test_high_risk_subscriber_tagged(self):
        results, captured = self._run_direct([_risk()])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-subscription-at-risk"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_TAG_CUSTOMER"
        assert captured["calls"][0]["params"]["id"] == (
            "gid://shopify/Customer/1"
        )

    def test_router_unavailable_per_subscriber_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_subscription_tags(
                [_risk()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_adapter_failure_per_subscriber_error(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_subscription_tags(
                [_risk()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "rate_limited" in results[0]["error"]

    def test_adapter_raise_per_subscriber_error(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_subscription_tags(
                [_risk()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_each_at_risk_subscriber_enqueues(self, isolated_queue):
        results = apply_subscription_tags([
            _risk(sid="gid://c/1", level="high", score=0.85),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        # The dispatcher reads `customer_id` from params; the
        # applier stores subscriber_id under that key.
        assert action.params["customer_id"] == "gid://c/1"
        assert action.params["tag"] == "shopai-subscription-at-risk"
        assert action.params["risk"] == 0.85
        assert action.params["risk_level"] == "high"
        assert action.action_type == "tag_subscription_at_risk"
        assert action.capability == "SHOPIFY_TAG_CUSTOMER"

    def test_queue_unavailable_per_subscriber_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_subscription_tags([_risk()])
        assert results[0]["applied"] is False
        assert results[0]["error"] == "approval_queue_unavailable"

    def test_enqueue_raise_per_subscriber(self, isolated_queue):
        original = isolated_queue.enqueue
        call_count = {"n": 0}

        def _enqueue(**kw):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("boom")
            return original(**kw)

        isolated_queue.enqueue = _enqueue
        results = apply_subscription_tags([
            _risk(sid="gid://c/1"),
            _risk(sid="gid://c/2"),
            _risk(sid="gid://c/3"),
        ])
        assert "pending_action_id" in results[0]
        assert "enqueue_raised" in results[1]["error"]
        assert "pending_action_id" in results[2]


# ─── Pattern Z ───────────────────────────────────────────────


class TestRecordWritebackIntegration:

    def test_record_called_on_direct_success(self):
        router = SimpleNamespace(execute=lambda c, p: _ok())
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.subscription.tag_applier.record_writeback",
        ) as record_mock:
            apply_subscription_tags(
                [_risk()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "subscription"
        assert kwargs["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.subscription.tag_applier.record_writeback",
        ) as record_mock:
            apply_subscription_tags(
                [_risk()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.subscription.tag_applier.record_writeback",
        ) as record_mock:
            apply_subscription_tags([_risk()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        include_medium=None,
    ):
        # One past_due subscriber with multiple payment
        # failures → high risk → tagged.
        data = {
            "subscribers": [
                {
                    "id": "gid://shopify/Customer/1",
                    "status": "past_due",
                    "join_date": "2026-04-01",
                    "lifetime_value": 30.0,
                },
            ],
            "plans": [],
            "billing_history": [
                {"subscriber_id": "gid://shopify/Customer/1",
                 "status": "failed",
                 "amount": 9.99,
                 "date": "2026-05-01"},
                {"subscriber_id": "gid://shopify/Customer/1",
                 "status": "failed",
                 "amount": 9.99,
                 "date": "2026-05-15"},
            ],
            "products": [],
        }
        if apply:
            data["apply_subscription_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if include_medium is not None:
            data["include_medium"] = include_medium
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.subscription.flow import SubscriptionEngine
        with patch(
            "engines.subscription.tag_applier."
            "apply_subscription_tags",
        ) as applier_mock:
            result = SubscriptionEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.subscription.flow import SubscriptionEngine
        with patch(
            "engines.subscription.tag_applier."
            "apply_subscription_tags",
            return_value=[
                {"subscriber_id": "gid://c/1",
                 "risk": 0.85, "risk_level": "high",
                 "tag": "shopai-subscription-at-risk",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = SubscriptionEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Defaults propagate
        assert kwargs["require_approval"] is True
        assert kwargs["include_medium"] is False
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.subscription.flow import SubscriptionEngine
        with patch(
            "engines.subscription.tag_applier."
            "apply_subscription_tags",
            return_value=[],
        ) as applier_mock:
            SubscriptionEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_include_medium_propagates(self, isolated_queue):
        from engines.subscription.flow import SubscriptionEngine
        with patch(
            "engines.subscription.tag_applier."
            "apply_subscription_tags",
            return_value=[],
        ) as applier_mock:
            SubscriptionEngine().run(
                self._input(apply=True, include_medium=True),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["include_medium"] is True
