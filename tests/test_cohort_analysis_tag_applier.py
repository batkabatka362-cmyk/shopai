"""Tests for ``engines.cohort_analysis.tag_applier``.

Pushes ``shopai-cohort-{period}`` tags on each customer in
each cohort via SHOPIFY_TAG_CUSTOMER. Two paths (queue /
direct) selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     period / missing customer_ids / blank customer_id /
     garbage period sluggable to empty).
  2. Direct path: SHOPIFY_TAG_CUSTOMER called per (cohort,
     customer); router unavailable, adapter failure, raise
     all handled.
  3. Queue path: each customer enqueues with correct params;
     queue unavailable; per-enqueue raise doesn't abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval propagates.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.cohort_analysis.tag_applier import (
    apply_cohort_tags,
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


def _cohort(*, period="2025-01", customer_ids=None):
    return {
        "period": period,
        "customer_ids": customer_ids or ["gid://shopify/Customer/1"],
        "size": len(customer_ids or ["gid://shopify/Customer/1"]),
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_cohort_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_cohort_tags(None) == []  # type: ignore

    def test_non_dict_cohort_skipped(self, isolated_queue):
        results = apply_cohort_tags(
            ["not a dict", 42, _cohort(period="2025-02")],  # type: ignore
        )
        # Only the valid 2025-02 cohort goes through
        assert len(results) == 1

    def test_missing_period_skipped(self, isolated_queue):
        results = apply_cohort_tags(
            [_cohort(period="", customer_ids=["gid://c/1"])],
        )
        assert results == []

    def test_missing_customer_ids_skipped(self, isolated_queue):
        results = apply_cohort_tags(
            [{"period": "2025-01", "size": 0}],
        )
        assert results == []

    def test_blank_customer_id_skipped(self, isolated_queue):
        results = apply_cohort_tags(
            [_cohort(customer_ids=["", "gid://c/1", None])],
        )
        # Only the valid id makes it through
        assert len(results) == 1
        assert results[0]["customer_id"] == "gid://c/1"

    def test_garbage_period_skipped(self, isolated_queue):
        # Period that slugs to empty after non-alnum strip
        results = apply_cohort_tags(
            [_cohort(period="---", customer_ids=["gid://c/1"])],
        )
        assert results == []


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, cohorts):
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
            results = apply_cohort_tags(
                cohorts, require_approval=False,
            )
        return results, captured

    def test_each_customer_in_cohort_gets_period_tag(self):
        results, captured = self._run_direct([
            _cohort(period="2025-01",
                    customer_ids=["gid://c/1", "gid://c/2"]),
            _cohort(period="2025-02",
                    customer_ids=["gid://c/3"]),
        ])
        assert all(r["applied"] for r in results)
        assert len(results) == 3
        tags = sorted(r["tag"] for r in results)
        assert tags == [
            "shopai-cohort-2025-01",
            "shopai-cohort-2025-01",
            "shopai-cohort-2025-02",
        ]
        assert len(captured["calls"]) == 3
        assert captured["calls"][0]["cap"].name == "SHOPIFY_TAG_CUSTOMER"
        # First customer's adapter input shape
        assert captured["calls"][0]["params"]["id"] == "gid://c/1"
        assert captured["calls"][0]["params"]["tags"] == [
            "shopai-cohort-2025-01",
        ]

    def test_weekly_period_tag(self):
        results, _ = self._run_direct([
            _cohort(period="2025-01-15",
                    customer_ids=["gid://c/1"]),
        ])
        assert results[0]["tag"] == "shopai-cohort-2025-01-15"

    def test_router_unavailable_per_customer_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_cohort_tags(
                [_cohort()], require_approval=False,
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
            results = apply_cohort_tags(
                [_cohort()], require_approval=False,
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
            results = apply_cohort_tags(
                [_cohort()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]

    def test_batch_continues_through_failure(self):
        call_count = {"n": 0}

        def _exec(c, p):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("transient")
            return _ok()

        router = SimpleNamespace(execute=_exec)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_cohort_tags(
                [
                    _cohort(period="2025-01",
                            customer_ids=["gid://c/1",
                                          "gid://c/2",
                                          "gid://c/3"]),
                ],
                require_approval=False,
            )
        assert len(results) == 3
        assert results[0]["applied"] is True
        assert results[1]["applied"] is False
        assert results[2]["applied"] is True


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_each_customer_enqueues(self, isolated_queue):
        results = apply_cohort_tags([
            _cohort(period="2025-01",
                    customer_ids=["gid://c/1", "gid://c/2"]),
        ])
        assert len(results) == 2
        assert all("pending_action_id" in r for r in results)
        assert all(r["applied"] is False for r in results)
        # cohort_period propagates into params
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["cohort_period"] == "2025-01"
        assert action.params["tag"] == "shopai-cohort-2025-01"
        assert action.action_type == "tag_cohort_customer"
        assert action.capability == "SHOPIFY_TAG_CUSTOMER"

    def test_queue_unavailable_per_customer_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_cohort_tags([_cohort()])
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
        results = apply_cohort_tags([
            _cohort(period="2025-01",
                    customer_ids=["gid://c/1",
                                  "gid://c/2",
                                  "gid://c/3"]),
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
            "engines.cohort_analysis.tag_applier.record_writeback",
        ) as record_mock:
            apply_cohort_tags(
                [_cohort()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "cohort_analysis"
        assert kwargs["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.cohort_analysis.tag_applier.record_writeback",
        ) as record_mock:
            apply_cohort_tags(
                [_cohort()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.cohort_analysis.tag_applier.record_writeback",
        ) as record_mock:
            apply_cohort_tags([_cohort()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(self, *, apply=False, require_approval=None):
        data = {
            "customers": [
                {"id": "gid://shopify/Customer/1",
                 "created_at": "2025-01-15T00:00:00Z"},
            ],
            "orders": [
                {"customer_id": "gid://shopify/Customer/1",
                 "created_at": "2025-01-20T00:00:00Z",
                 "total_price": "100.00"},
            ],
            "cohort_type": "monthly",
        }
        if apply:
            data["apply_cohort_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.cohort_analysis.flow import (
            CohortAnalysisEngine,
        )
        with patch(
            "engines.cohort_analysis.tag_applier.apply_cohort_tags",
        ) as applier_mock:
            result = CohortAnalysisEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.cohort_analysis.flow import (
            CohortAnalysisEngine,
        )
        with patch(
            "engines.cohort_analysis.tag_applier.apply_cohort_tags",
            return_value=[
                {"customer_id": "gid://c/1",
                 "cohort_period": "2025-01",
                 "tag": "shopai-cohort-2025-01",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = CohortAnalysisEngine().run(self._input(apply=True))
        applier_mock.assert_called_once()
        # Default require_approval=True propagates
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is True
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.cohort_analysis.flow import (
            CohortAnalysisEngine,
        )
        with patch(
            "engines.cohort_analysis.tag_applier.apply_cohort_tags",
            return_value=[],
        ) as applier_mock:
            CohortAnalysisEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False
