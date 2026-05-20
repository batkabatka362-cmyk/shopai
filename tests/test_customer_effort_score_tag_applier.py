"""Tests for ``engines.customer_effort_score.tag_applier``.

Pushes ``shopai-ces-{bucket}`` tags on each customer (worst
effort_score wins per customer) via SHOPIFY_TAG_CUSTOMER. Two
paths (queue / direct) selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     customer_id / 'unknown' literal / non-numeric score /
     out-of-range score / low+medium gated by include flags /
     worst-score-wins dedup).
  2. Direct path: SHOPIFY_TAG_CUSTOMER called per customer;
     router unavailable, adapter failure, raise all handled.
  3. Queue path: each customer enqueues with correct params;
     queue unavailable; per-enqueue raise doesn't abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval / include_low / include_medium propagate.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.customer_effort_score.tag_applier import (
    apply_ces_tags,
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


def _interaction(*, cid="gid://shopify/Customer/1", score=6.5):
    return {
        "customer_id": cid,
        "touchpoint": "support",
        "effort_score": score,
        "step_score": score,
        "time_score": score,
        "resolved": True,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_ces_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_ces_tags(None) == []  # type: ignore

    def test_non_dict_interaction_skipped(self, isolated_queue):
        results = apply_ces_tags(
            ["bad", 42, _interaction(cid="gid://c/1", score=6.5)],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_customer_id_skipped(self, isolated_queue):
        results = apply_ces_tags(
            [_interaction(cid="", score=6.5)],
        )
        assert results == []

    def test_unknown_customer_id_skipped(self, isolated_queue):
        # The scorer uses "unknown" as a default — not a real
        # customer, don't tag.
        results = apply_ces_tags(
            [_interaction(cid="unknown", score=6.5)],
        )
        assert results == []

    def test_non_numeric_score_skipped(self, isolated_queue):
        results = apply_ces_tags(
            [{"customer_id": "gid://c/1",
              "effort_score": "very high"}],
        )
        assert results == []

    def test_out_of_range_score_skipped(self, isolated_queue):
        results = apply_ces_tags(
            [
                _interaction(cid="gid://c/1", score=0.5),
                _interaction(cid="gid://c/2", score=8.0),
                _interaction(cid="gid://c/3", score=6.5),  # valid
            ],
        )
        assert len(results) == 1
        assert results[0]["customer_id"] == "gid://c/3"

    def test_low_excluded_by_default(self, isolated_queue):
        # Default: only "high" bucket is tagged
        results = apply_ces_tags(
            [
                _interaction(cid="gid://c/1", score=1.5),  # low
                _interaction(cid="gid://c/2", score=3.5),  # med
                _interaction(cid="gid://c/3", score=6.5),  # high
            ],
        )
        assert len(results) == 1
        assert results[0]["bucket"] == "high"

    def test_include_low_opts_in(self, isolated_queue):
        results = apply_ces_tags(
            [_interaction(cid="gid://c/1", score=1.5)],
            include_low=True,
        )
        assert len(results) == 1
        assert results[0]["bucket"] == "low"
        assert results[0]["tag"] == "shopai-ces-low"

    def test_include_medium_opts_in(self, isolated_queue):
        results = apply_ces_tags(
            [_interaction(cid="gid://c/1", score=3.5)],
            include_medium=True,
        )
        assert len(results) == 1
        assert results[0]["bucket"] == "medium"
        assert results[0]["tag"] == "shopai-ces-medium"

    def test_worst_score_wins_dedup(self, isolated_queue):
        # Same customer with one smooth and one frustrating
        # interaction — the frustrating one is the signal.
        results = apply_ces_tags(
            [
                _interaction(cid="gid://c/1", score=1.5),  # low
                _interaction(cid="gid://c/1", score=6.5),  # high (wins)
            ],
        )
        assert len(results) == 1
        assert results[0]["bucket"] == "high"
        assert results[0]["effort_score"] == 6.5

    def test_correct_bucketing_boundaries(self, isolated_queue):
        # Verify boundary math: 2.5 -> low, 2.51+ -> medium,
        # 5.0 -> medium, 5.01+ -> high.
        results = apply_ces_tags(
            [
                _interaction(cid="gid://c/1", score=2.5),
                _interaction(cid="gid://c/2", score=2.6),
                _interaction(cid="gid://c/3", score=5.0),
                _interaction(cid="gid://c/4", score=5.1),
            ],
            include_low=True, include_medium=True,
        )
        buckets = {r["customer_id"]: r["bucket"] for r in results}
        assert buckets["gid://c/1"] == "low"
        assert buckets["gid://c/2"] == "medium"
        assert buckets["gid://c/3"] == "medium"
        assert buckets["gid://c/4"] == "high"


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, interactions, **kwargs):
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
            results = apply_ces_tags(
                interactions, require_approval=False, **kwargs,
            )
        return results, captured

    def test_high_customer_tagged(self):
        results, captured = self._run_direct([
            _interaction(cid="gid://c/1", score=6.5),
        ])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-ces-high"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_TAG_CUSTOMER"
        assert captured["calls"][0]["params"]["id"] == "gid://c/1"

    def test_router_unavailable_per_customer_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_ces_tags(
                [_interaction()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_adapter_failure_per_customer_error(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_ces_tags(
                [_interaction()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "rate_limited" in results[0]["error"]

    def test_adapter_raise_per_customer_error(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_ces_tags(
                [_interaction()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_each_customer_enqueues(self, isolated_queue):
        results = apply_ces_tags([
            _interaction(cid="gid://c/1", score=6.5),
            _interaction(cid="gid://c/2", score=7.0),
        ])
        assert len(results) == 2
        assert all("pending_action_id" in r for r in results)
        assert all(r["applied"] is False for r in results)
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["tag"] == "shopai-ces-high"
        assert action.params["bucket"] == "high"
        assert action.action_type == "tag_ces_customer"
        assert action.capability == "SHOPIFY_TAG_CUSTOMER"

    def test_queue_unavailable_per_customer_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_ces_tags([_interaction()])
        assert results[0]["applied"] is False
        assert results[0]["error"] == "approval_queue_unavailable"

    def test_enqueue_raise_per_customer(self, isolated_queue):
        original = isolated_queue.enqueue
        call_count = {"n": 0}

        def _enqueue(**kw):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("boom")
            return original(**kw)

        isolated_queue.enqueue = _enqueue
        results = apply_ces_tags([
            _interaction(cid="gid://c/1", score=6.5),
            _interaction(cid="gid://c/2", score=6.5),
            _interaction(cid="gid://c/3", score=6.5),
        ])
        # Exactly one should have failed
        failed = [
            r for r in results
            if r.get("error") and "enqueue_raised" in r["error"]
        ]
        assert len(failed) == 1


# ─── Pattern Z ───────────────────────────────────────────────


class TestRecordWritebackIntegration:

    def test_record_called_on_direct_success(self):
        router = SimpleNamespace(execute=lambda c, p: _ok())
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.customer_effort_score.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_ces_tags(
                [_interaction()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "customer_effort_score"
        assert kwargs["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.customer_effort_score.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_ces_tags(
                [_interaction()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.customer_effort_score.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_ces_tags([_interaction()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        include_low=None, include_medium=None,
    ):
        data = {
            "interactions": [
                {
                    "customer_id": "gid://shopify/Customer/1",
                    "touchpoint": "support",
                    "steps_taken": 10,
                    "time_spent": 400,
                    "resolved": True,
                },
            ],
        }
        if apply:
            data["apply_ces_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if include_low is not None:
            data["include_low"] = include_low
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
        from engines.customer_effort_score.flow import (
            CustomerEffortScoreEngine,
        )
        with patch(
            "engines.customer_effort_score.tag_applier."
            "apply_ces_tags",
        ) as applier_mock:
            result = CustomerEffortScoreEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.customer_effort_score.flow import (
            CustomerEffortScoreEngine,
        )
        with patch(
            "engines.customer_effort_score.tag_applier."
            "apply_ces_tags",
            return_value=[
                {"customer_id": "gid://c/1",
                 "effort_score": 6.5,
                 "bucket": "high",
                 "tag": "shopai-ces-high",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = CustomerEffortScoreEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Defaults propagate
        assert kwargs["require_approval"] is True
        assert kwargs["include_low"] is False
        assert kwargs["include_medium"] is False
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.customer_effort_score.flow import (
            CustomerEffortScoreEngine,
        )
        with patch(
            "engines.customer_effort_score.tag_applier."
            "apply_ces_tags",
            return_value=[],
        ) as applier_mock:
            CustomerEffortScoreEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_include_low_propagates(self, isolated_queue):
        from engines.customer_effort_score.flow import (
            CustomerEffortScoreEngine,
        )
        with patch(
            "engines.customer_effort_score.tag_applier."
            "apply_ces_tags",
            return_value=[],
        ) as applier_mock:
            CustomerEffortScoreEngine().run(
                self._input(apply=True, include_low=True),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["include_low"] is True

    def test_include_medium_propagates(self, isolated_queue):
        from engines.customer_effort_score.flow import (
            CustomerEffortScoreEngine,
        )
        with patch(
            "engines.customer_effort_score.tag_applier."
            "apply_ces_tags",
            return_value=[],
        ) as applier_mock:
            CustomerEffortScoreEngine().run(
                self._input(apply=True, include_medium=True),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["include_medium"] is True
