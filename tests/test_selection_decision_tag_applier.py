"""Tests for ``engines.selection_decision.tag_applier``.

Pushes ``shopai-selection-selected`` tags on AI-selected
products via SHOPIFY_ADD_TAGS. Two paths (queue / direct)
selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     product_id / "unknown" literal / non-selected verdict /
     below min_confidence / dedup keeps highest confidence /
     case-insensitive verdict).
  2. Direct path: SHOPIFY_ADD_TAGS called per selected
     product; router unavailable, adapter failure, raise all
     handled.
  3. Queue path: each selected product enqueues with correct
     params; queue unavailable; per-enqueue raise doesn't
     abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval / min_confidence propagate.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.selection_decision.tag_applier import (
    apply_selection_tags,
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


def _sel(
    *,
    pid="gid://shopify/Product/1",
    verdict="selected",
    confidence=0.8,
    title="P1",
):
    return {
        "product_id": pid,
        "title": title,
        "verdict": verdict,
        "confidence": confidence,
        "reasons": ["high_score"],
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_selection_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_selection_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_selection_tags(
            ["bad", 42, _sel(pid="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_product_id_skipped(self, isolated_queue):
        results = apply_selection_tags(
            [_sel(pid="")],
        )
        assert results == []

    def test_unknown_product_id_skipped(self, isolated_queue):
        results = apply_selection_tags(
            [_sel(pid="unknown")],
        )
        assert results == []

    def test_non_selected_verdict_skipped(self, isolated_queue):
        results = apply_selection_tags(
            [
                _sel(pid="gid://p/1", verdict="selected"),
                _sel(pid="gid://p/2", verdict="rejected"),
            ],
        )
        assert len(results) == 1
        assert results[0]["product_id"] == "gid://p/1"

    def test_case_insensitive_verdict(self, isolated_queue):
        results = apply_selection_tags(
            [
                _sel(pid="gid://p/1", verdict="SELECTED"),
                _sel(pid="gid://p/2", verdict="Selected"),
            ],
        )
        assert len(results) == 2

    def test_below_min_confidence_skipped(self, isolated_queue):
        results = apply_selection_tags(
            [
                _sel(pid="gid://p/1", confidence=0.5),
                _sel(pid="gid://p/2", confidence=0.9),
            ],
            min_confidence=0.7,
        )
        assert len(results) == 1
        assert results[0]["product_id"] == "gid://p/2"

    def test_dedup_keeps_highest_confidence(self, isolated_queue):
        results = apply_selection_tags(
            [
                _sel(pid="gid://p/1", confidence=0.5),
                _sel(pid="gid://p/1", confidence=0.95),
            ],
        )
        assert len(results) == 1
        assert results[0]["confidence"] == 0.95

    def test_bad_confidence_coerced_to_zero(self, isolated_queue):
        results = apply_selection_tags(
            [{
                "product_id": "gid://p/1",
                "verdict": "selected",
                "confidence": "high",
            }],
        )
        assert len(results) == 1
        assert results[0]["confidence"] == 0.0


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, sel, **kwargs):
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
            results = apply_selection_tags(
                sel, require_approval=False, **kwargs,
            )
        return results, captured

    def test_selected_product_tagged(self):
        results, captured = self._run_direct([_sel()])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-selection-selected"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == (
            "gid://shopify/Product/1"
        )

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_selection_tags(
                [_sel()], require_approval=False,
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
            results = apply_selection_tags(
                [_sel()], require_approval=False,
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
            results = apply_selection_tags(
                [_sel()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_selected_product_enqueues(self, isolated_queue):
        results = apply_selection_tags([
            _sel(pid="gid://p/1", confidence=0.85, title="Top"),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-selection-selected"
        assert action.params["confidence"] == 0.85
        assert action.params["title"] == "Top"
        assert action.action_type == "tag_selection_selected"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_selection_tags([_sel()])
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
        results = apply_selection_tags([
            _sel(pid="gid://p/1"),
            _sel(pid="gid://p/2"),
            _sel(pid="gid://p/3"),
        ])
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
            "engines.selection_decision.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_selection_tags(
                [_sel()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "selection_decision"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.selection_decision.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_selection_tags(
                [_sel()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.selection_decision.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_selection_tags([_sel()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        min_confidence=None,
    ):
        data = {
            "ranked_products": [
                {"id": "gid://p/1", "title": "Top",
                 "rank": 1, "score": 90.0},
                {"id": "gid://p/2", "title": "Mid",
                 "rank": 2, "score": 60.0},
            ],
            "constraints": {},
        }
        if apply:
            data["apply_selection_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if min_confidence is not None:
            data["min_confidence"] = min_confidence
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.selection_decision.flow import (
            SelectionDecisionEngine,
        )
        with patch(
            "engines.selection_decision.tag_applier."
            "apply_selection_tags",
        ) as applier_mock:
            result = SelectionDecisionEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.selection_decision.flow import (
            SelectionDecisionEngine,
        )
        with patch(
            "engines.selection_decision.tag_applier."
            "apply_selection_tags",
            return_value=[
                {"product_id": "gid://p/1",
                 "verdict": "selected",
                 "confidence": 0.85,
                 "tag": "shopai-selection-selected",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = SelectionDecisionEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Defaults propagate
        assert kwargs["require_approval"] is True
        assert kwargs["min_confidence"] == 0.0
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.selection_decision.flow import (
            SelectionDecisionEngine,
        )
        with patch(
            "engines.selection_decision.tag_applier."
            "apply_selection_tags",
            return_value=[],
        ) as applier_mock:
            SelectionDecisionEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_min_confidence_propagates(self, isolated_queue):
        from engines.selection_decision.flow import (
            SelectionDecisionEngine,
        )
        with patch(
            "engines.selection_decision.tag_applier."
            "apply_selection_tags",
            return_value=[],
        ) as applier_mock:
            SelectionDecisionEngine().run(
                self._input(apply=True, min_confidence=0.7),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["min_confidence"] == 0.7
