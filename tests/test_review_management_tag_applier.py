"""Tests for ``engines.review_management.tag_applier``.

Pushes ``shopai-review-{top-rated|low-rated}`` tags on each
product via SHOPIFY_ADD_TAGS based on avg_rating thresholds.
Two paths (queue / direct) selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     product_id / below min_reviews / middle-rated skipped /
     non-numeric values rejected / boundary math / dedup).
  2. Direct path: SHOPIFY_ADD_TAGS called per product; router
     unavailable, adapter failure, raise all handled.
  3. Queue path: each product enqueues with correct params;
     queue unavailable; per-enqueue raise doesn't abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval / min_reviews propagate / blank
     product_id skipped.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.review_management.tag_applier import (
    apply_review_tags,
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


def _summary(*, pid="gid://shopify/Product/1", avg=4.8, total=10):
    return {
        "product_id": pid,
        "avg_rating": avg,
        "total_reviews": total,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_review_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_review_tags(None) == []  # type: ignore

    def test_non_dict_summary_skipped(self, isolated_queue):
        results = apply_review_tags(
            ["bad", 42, _summary(pid="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_product_id_skipped(self, isolated_queue):
        results = apply_review_tags(
            [_summary(pid="")],
        )
        assert results == []

    def test_below_min_reviews_skipped(self, isolated_queue):
        # Default min_reviews=5; one with 3 should be filtered
        results = apply_review_tags(
            [_summary(total=3)],
        )
        assert results == []

    def test_middle_rated_skipped(self, isolated_queue):
        # 2.5 < avg_rating < 4.5 → no tag emitted
        results = apply_review_tags(
            [
                _summary(pid="gid://p/1", avg=3.5, total=10),
                _summary(pid="gid://p/2", avg=4.0, total=10),
            ],
        )
        assert results == []

    def test_top_rated_tagged(self, isolated_queue):
        results = apply_review_tags(
            [_summary(pid="gid://p/1", avg=4.8, total=10)],
        )
        assert len(results) == 1
        assert results[0]["bucket"] == "top-rated"
        assert results[0]["tag"] == "shopai-review-top-rated"

    def test_low_rated_tagged(self, isolated_queue):
        results = apply_review_tags(
            [_summary(pid="gid://p/1", avg=1.8, total=10)],
        )
        assert len(results) == 1
        assert results[0]["bucket"] == "low-rated"
        assert results[0]["tag"] == "shopai-review-low-rated"

    def test_boundary_math(self, isolated_queue):
        # avg=4.5 → top-rated (>=4.5)
        # avg=4.49 → middle (no tag)
        # avg=2.5 → low-rated (<=2.5)
        # avg=2.51 → middle
        results = apply_review_tags(
            [
                _summary(pid="gid://p/1", avg=4.5, total=10),
                _summary(pid="gid://p/2", avg=4.49, total=10),
                _summary(pid="gid://p/3", avg=2.5, total=10),
                _summary(pid="gid://p/4", avg=2.51, total=10),
            ],
        )
        buckets = {r["product_id"]: r["bucket"] for r in results}
        assert buckets == {
            "gid://p/1": "top-rated",
            "gid://p/3": "low-rated",
        }

    def test_non_numeric_avg_skipped(self, isolated_queue):
        results = apply_review_tags(
            [{"product_id": "gid://p/1",
              "avg_rating": "high",
              "total_reviews": 10}],
        )
        assert results == []

    def test_non_numeric_total_skipped(self, isolated_queue):
        results = apply_review_tags(
            [{"product_id": "gid://p/1",
              "avg_rating": 4.8,
              "total_reviews": "many"}],
        )
        assert results == []

    def test_duplicate_product_ids_deduped(self, isolated_queue):
        results = apply_review_tags(
            [
                _summary(pid="gid://p/1", avg=4.8, total=10),
                _summary(pid="gid://p/1", avg=4.9, total=20),  # dup
                _summary(pid="gid://p/2", avg=4.7, total=8),
            ],
        )
        assert len(results) == 2

    def test_custom_min_reviews(self, isolated_queue):
        results = apply_review_tags(
            [_summary(pid="gid://p/1", avg=4.8, total=10)],
            min_reviews=20,
        )
        assert results == []


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, summaries, **kwargs):
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
            results = apply_review_tags(
                summaries, require_approval=False, **kwargs,
            )
        return results, captured

    def test_top_rated_tagged_via_router(self):
        results, captured = self._run_direct([
            _summary(pid="gid://p/1", avg=4.8, total=10),
        ])
        assert results[0]["applied"] is True
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == "gid://p/1"
        assert captured["calls"][0]["params"]["tags"] == [
            "shopai-review-top-rated",
        ]

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_review_tags(
                [_summary()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_adapter_failure_per_product_error(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_review_tags(
                [_summary()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "rate_limited" in results[0]["error"]

    def test_adapter_raise_per_product_error(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_review_tags(
                [_summary()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_product_enqueues(self, isolated_queue):
        results = apply_review_tags([
            _summary(pid="gid://p/1", avg=4.8, total=10),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["tag"] == "shopai-review-top-rated"
        assert action.params["avg_rating"] == 4.8
        assert action.params["total_reviews"] == 10
        assert action.action_type == "tag_review_product"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_review_tags([_summary()])
        assert results[0]["applied"] is False
        assert results[0]["error"] == "approval_queue_unavailable"

    def test_enqueue_raise_per_product(self, isolated_queue):
        original = isolated_queue.enqueue
        call_count = {"n": 0}

        def _enqueue(**kw):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("boom")
            return original(**kw)

        isolated_queue.enqueue = _enqueue
        results = apply_review_tags([
            _summary(pid="gid://p/1", avg=4.8, total=10),
            _summary(pid="gid://p/2", avg=4.9, total=10),
            _summary(pid="gid://p/3", avg=4.7, total=10),
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
            "engines.review_management.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_review_tags(
                [_summary()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "review_management"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.review_management.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_review_tags(
                [_summary()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.review_management.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_review_tags([_summary()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        min_reviews=None, product_id="gid://shopify/Product/100",
        reviews=None,
    ):
        # Build at least 5 high-rated reviews so the
        # aggregator's avg_rating clears the top-rated bar.
        if reviews is None:
            reviews = [
                {"id": f"r{i}", "rating": 5,
                 "text": "Love it!",
                 "date": "2026-01-01",
                 "verified": True}
                for i in range(10)
            ]
        data = {
            "product_id": product_id,
            "reviews": reviews,
        }
        if apply:
            data["apply_review_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if min_reviews is not None:
            data["min_reviews"] = min_reviews
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.review_management.flow import (
            ReviewManagementEngine,
        )
        with patch(
            "engines.review_management.tag_applier."
            "apply_review_tags",
        ) as applier_mock:
            result = ReviewManagementEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.review_management.flow import (
            ReviewManagementEngine,
        )
        with patch(
            "engines.review_management.tag_applier."
            "apply_review_tags",
            return_value=[
                {"product_id": "gid://shopify/Product/100",
                 "avg_rating": 5.0,
                 "total_reviews": 10,
                 "bucket": "top-rated",
                 "tag": "shopai-review-top-rated",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = ReviewManagementEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Defaults propagate
        assert kwargs["require_approval"] is True
        assert kwargs["min_reviews"] == 5
        # First positional arg has the per-product summary
        positional = applier_mock.call_args.args
        # The applier is called with a single positional list
        summaries = positional[0]
        assert len(summaries) == 1
        assert summaries[0]["product_id"] == "gid://shopify/Product/100"
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.review_management.flow import (
            ReviewManagementEngine,
        )
        with patch(
            "engines.review_management.tag_applier."
            "apply_review_tags",
            return_value=[],
        ) as applier_mock:
            ReviewManagementEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_min_reviews_propagates(self, isolated_queue):
        from engines.review_management.flow import (
            ReviewManagementEngine,
        )
        with patch(
            "engines.review_management.tag_applier."
            "apply_review_tags",
            return_value=[],
        ) as applier_mock:
            ReviewManagementEngine().run(
                self._input(apply=True, min_reviews=20),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["min_reviews"] == 20

    def test_blank_product_id_skips_applier(
        self, isolated_queue,
    ):
        from engines.review_management.flow import (
            ReviewManagementEngine,
        )
        with patch(
            "engines.review_management.tag_applier."
            "apply_review_tags",
        ) as applier_mock:
            result = ReviewManagementEngine().run(
                self._input(apply=True, product_id=""),
            )
        # No product_id → applier never invoked; results empty
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []
