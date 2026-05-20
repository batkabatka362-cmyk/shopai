"""Tests for ``engines.image_optimization.tag_applier``.

Pushes ``shopai-image-needs-work`` tags on each product whose
gallery analysis flagged fixable problems via SHOPIFY_ADD_TAGS.
Two paths (queue / direct) selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     product_id / healthy gallery skipped / poor_count or
     missing_types triggers / duplicate dedup / bad types
     handled).
  2. Direct path: SHOPIFY_ADD_TAGS called per flagged product;
     router unavailable, adapter failure, raise all handled.
  3. Queue path: each flagged product enqueues with correct
     params; queue unavailable; per-enqueue raise doesn't
     abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval propagates / blank product_id skipped.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.image_optimization.tag_applier import (
    apply_image_tags,
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


def _diag(
    *,
    pid="gid://shopify/Product/1",
    poor=1,
    missing=None,
):
    return {
        "product_id": pid,
        "quality_scores": {
            "average_score": 60.0,
            "total_images": 4,
            "excellent_count": 1,
            "poor_count": poor,
        },
        "missing_types": missing if missing is not None else [],
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_image_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_image_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_image_tags(
            ["bad", 42, _diag(pid="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_product_id_skipped(self, isolated_queue):
        results = apply_image_tags(
            [_diag(pid="")],
        )
        assert results == []

    def test_healthy_gallery_skipped(self, isolated_queue):
        # poor_count=0 AND missing_types empty → no tag
        results = apply_image_tags(
            [_diag(pid="gid://p/1", poor=0, missing=[])],
        )
        assert results == []

    def test_poor_count_triggers(self, isolated_queue):
        results = apply_image_tags(
            [_diag(pid="gid://p/1", poor=2, missing=[])],
        )
        assert len(results) == 1
        assert results[0]["poor_count"] == 2

    def test_missing_types_triggers(self, isolated_queue):
        results = apply_image_tags(
            [_diag(pid="gid://p/1", poor=0,
                   missing=["hero", "detail"])],
        )
        assert len(results) == 1
        assert results[0]["missing_types"] == ["hero", "detail"]

    def test_duplicate_product_ids_deduped(self, isolated_queue):
        results = apply_image_tags(
            [
                _diag(pid="gid://p/1", poor=1),
                _diag(pid="gid://p/1", poor=2),  # dup
                _diag(pid="gid://p/2", poor=1),
            ],
        )
        assert len(results) == 2
        pids = {r["product_id"] for r in results}
        assert pids == {"gid://p/1", "gid://p/2"}

    def test_non_int_poor_count_treated_as_zero(self, isolated_queue):
        # Bad poor_count but missing_types triggers → tag
        results = apply_image_tags(
            [{
                "product_id": "gid://p/1",
                "quality_scores": {"poor_count": "many"},
                "missing_types": ["hero"],
            }],
        )
        assert len(results) == 1
        assert results[0]["poor_count"] == 0

    def test_non_dict_quality_scores_treated_as_empty(self, isolated_queue):
        # quality_scores is not a dict → poor_count=0; with
        # missing_types empty → skip.
        results = apply_image_tags(
            [{
                "product_id": "gid://p/1",
                "quality_scores": "bad",
                "missing_types": [],
            }],
        )
        assert results == []

    def test_non_list_missing_types_treated_as_empty(self, isolated_queue):
        # missing_types not a list → empty; with poor=0 → skip
        results = apply_image_tags(
            [{
                "product_id": "gid://p/1",
                "quality_scores": {"poor_count": 0},
                "missing_types": "bad",
            }],
        )
        assert results == []


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, diagnoses, **kwargs):
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
            results = apply_image_tags(
                diagnoses, require_approval=False, **kwargs,
            )
        return results, captured

    def test_flagged_product_tagged(self):
        results, captured = self._run_direct([_diag()])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-image-needs-work"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == "gid://shopify/Product/1"

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_image_tags(
                [_diag()], require_approval=False,
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
            results = apply_image_tags(
                [_diag()], require_approval=False,
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
            results = apply_image_tags(
                [_diag()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_flagged_product_enqueues(self, isolated_queue):
        results = apply_image_tags([
            _diag(pid="gid://p/1", poor=2, missing=["hero"]),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-image-needs-work"
        assert action.params["poor_count"] == 2
        assert action.params["missing_types"] == ["hero"]
        assert action.action_type == "tag_image_needs_work"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_image_tags([_diag()])
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
        results = apply_image_tags([
            _diag(pid="gid://p/1", poor=1),
            _diag(pid="gid://p/2", poor=1),
            _diag(pid="gid://p/3", poor=1),
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
            "engines.image_optimization.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_image_tags(
                [_diag()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "image_optimization"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.image_optimization.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_image_tags(
                [_diag()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.image_optimization.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_image_tags([_diag()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        product_id="gid://shopify/Product/100",
        images=None,
    ):
        # Build images with quality issues so the analyzer
        # flags poor_count > 0.
        if images is None:
            images = [
                # Low-res image, no alt → triggers issues
                {"url": "https://cdn/x.jpg",
                 "alt": "",
                 "size_bytes": 100_000,
                 "width": 400, "height": 400},
            ]
        data = {
            "images": images,
            "product": {"id": product_id},
            "platform": "web",
        }
        if apply:
            data["apply_image_tags"] = True
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
        from engines.image_optimization.flow import (
            ImageOptimizationEngine,
        )
        with patch(
            "engines.image_optimization.tag_applier."
            "apply_image_tags",
        ) as applier_mock:
            result = ImageOptimizationEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.image_optimization.flow import (
            ImageOptimizationEngine,
        )
        with patch(
            "engines.image_optimization.tag_applier."
            "apply_image_tags",
            return_value=[
                {"product_id": "gid://shopify/Product/100",
                 "poor_count": 1,
                 "missing_types": [],
                 "tag": "shopai-image-needs-work",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = ImageOptimizationEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Default require_approval=True propagates
        assert kwargs["require_approval"] is True
        positional = applier_mock.call_args.args
        # First positional arg has a single-item list with the
        # product_id from input
        assert len(positional[0]) == 1
        assert positional[0][0]["product_id"] == (
            "gid://shopify/Product/100"
        )
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.image_optimization.flow import (
            ImageOptimizationEngine,
        )
        with patch(
            "engines.image_optimization.tag_applier."
            "apply_image_tags",
            return_value=[],
        ) as applier_mock:
            ImageOptimizationEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_blank_product_id_skips_applier(
        self, isolated_queue,
    ):
        from engines.image_optimization.flow import (
            ImageOptimizationEngine,
        )
        with patch(
            "engines.image_optimization.tag_applier."
            "apply_image_tags",
        ) as applier_mock:
            result = ImageOptimizationEngine().run(
                self._input(apply=True, product_id=""),
            )
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []
