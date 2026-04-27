"""Tests for the search_optimization approval-queue wiring.

Same pattern as PR #59 / #60 / #61 / #63 / #64 / #65 / #66,
applied to the per-recommendation SEO writer. Coverage:

  1. ``enqueue_meta_for_approval`` happy path — recommendations
     with at least one diff (title or description) are parked,
     narrative reflects which fields will change.
  2. Skip semantics: ``no_changes`` (proposed equals current) /
     queue-unavailable.
  3. Partial diffs: title-only and description-only land
     correctly with the right ``*_updated`` flags.
  4. flow integration — ``data.apply_seo=True`` +
     ``data.require_approval=True`` enqueues; ``False`` falls
     back to the legacy direct ``apply_meta``.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


# ─── enqueue_meta_for_approval ───────────────────────────────────


def _rec(**overrides):
    base = {
        "product_id": "gid://shopify/Product/1",
        "title": "Best Widget for Camping",
        "description": "Durable widget — top pick.",
        "keywords": ["widget", "camping"],
        "improvements": [],
    }
    base.update(overrides)
    return base


def _current(pid: str, title: str, description: str):
    return {"product_id": pid, "title": title, "description": description}


class TestEnqueueMetaForApproval:

    def test_happy_path_full_update(self, isolated_queue):
        from engines.search_optimization.seo_applier import (
            enqueue_meta_for_approval,
        )

        results = enqueue_meta_for_approval(
            recommendations=[_rec()],
            current_meta=[_current("gid://shopify/Product/1",
                                   "Old title", "Old desc")],
        )
        assert results[0]["error"] == "queued"
        assert results[0]["title_updated"] is True
        assert results[0]["description_updated"] is True
        assert results[0]["pending_action_id"].startswith("appr_")

        action = isolated_queue.get(results[0]["pending_action_id"])
        assert action is not None
        assert action.engine == "search_optimization"
        assert action.action_type == "apply_seo_meta"
        assert "title" in action.narrative
        assert "description" in action.narrative
        assert action.params["proposed_title"] == "Best Widget for Camping"
        assert action.params["proposed_description"] is not None

    def test_partial_title_only_diff(self, isolated_queue):
        from engines.search_optimization.seo_applier import (
            enqueue_meta_for_approval,
        )

        results = enqueue_meta_for_approval(
            recommendations=[_rec()],
            current_meta=[_current(
                "gid://shopify/Product/1",
                "Old title",
                "Durable widget — top pick.",  # matches recommendation
            )],
        )
        assert results[0]["error"] == "queued"
        assert results[0]["title_updated"] is True
        assert results[0]["description_updated"] is False

        action = isolated_queue.get(results[0]["pending_action_id"])
        assert action is not None
        assert action.params["proposed_title"] is not None
        assert action.params["proposed_description"] is None

    def test_no_changes_skipped(self, isolated_queue):
        from engines.search_optimization.seo_applier import (
            enqueue_meta_for_approval,
        )

        results = enqueue_meta_for_approval(
            recommendations=[_rec()],
            current_meta=[_current(
                "gid://shopify/Product/1",
                "Best Widget for Camping",
                "Durable widget — top pick.",
            )],
        )
        assert results[0]["error"] == "no_changes"
        assert results[0]["pending_action_id"] is None
        assert isolated_queue.list_pending() == []

    def test_no_current_meta_means_full_diff(self, isolated_queue):
        # Without a current_meta entry, every proposed value is a diff.
        from engines.search_optimization.seo_applier import (
            enqueue_meta_for_approval,
        )

        results = enqueue_meta_for_approval(
            recommendations=[_rec()],
            current_meta=None,
        )
        assert results[0]["error"] == "queued"
        assert results[0]["title_updated"] is True
        assert results[0]["description_updated"] is True

    def test_queue_unavailable_uniform_skip_list(self, isolated_queue):
        from engines.search_optimization.seo_applier import (
            enqueue_meta_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            results = enqueue_meta_for_approval(
                recommendations=[_rec()],
            )
        assert results[0]["error"] == "approval_queue_unavailable"
        assert results[0]["pending_action_id"] is None

    def test_empty_recommendations_returns_empty(self, isolated_queue):
        from engines.search_optimization.seo_applier import (
            enqueue_meta_for_approval,
        )

        assert enqueue_meta_for_approval(recommendations=[]) == []


# ─── flow integration ───────────────────────────────────────────


def _flow_input(*, apply_seo: bool, require_approval: bool):
    return {
        "status": "ok",
        "data": {
            "products": [
                {"id": "gid://shopify/Product/1",
                 "title": "Widget",
                 "description": "Old description",
                 "category": "general",
                 "tags": []},
            ],
            "search_queries": [],
            "current_meta": [
                {"product_id": "gid://shopify/Product/1",
                 "title": "Old SEO title",
                 "description": "Old SEO desc"},
            ],
            "competitors": [],
            "apply_seo": apply_seo,
            "require_approval": require_approval,
        },
        "meta": {},
        "error": None,
    }


class TestFlowApprovalIntegration:

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.search_optimization.flow import (
            SearchOptimizationEngine,
        )

        with patch(
            "engines.search_optimization.flow.apply_meta",
        ) as mock_apply, patch(
            "engines.search_optimization.flow.enqueue_meta_for_approval",
            return_value=[
                {"product_id": "gid://shopify/Product/1",
                 "applied": False, "title_updated": True,
                 "description_updated": True,
                 "error": "queued",
                 "pending_action_id": "appr_stub_1"},
            ],
        ) as mock_enqueue:
            output = SearchOptimizationEngine().run(
                _flow_input(apply_seo=True, require_approval=True),
            )

        if output["status"] == "success":
            mock_apply.assert_not_called()
            mock_enqueue.assert_called_once()
            assert (
                output["data"]["apply_results"][0]["pending_action_id"]
                == "appr_stub_1"
            )

    def test_require_approval_false_routes_to_direct_apply(
        self, isolated_queue,
    ):
        from engines.search_optimization.flow import (
            SearchOptimizationEngine,
        )

        with patch(
            "engines.search_optimization.flow.apply_meta",
            return_value=[
                {"product_id": "gid://shopify/Product/1",
                 "applied": True, "title_updated": True,
                 "description_updated": True, "error": None},
            ],
        ) as mock_apply, patch(
            "engines.search_optimization.flow.enqueue_meta_for_approval",
        ) as mock_enqueue:
            output = SearchOptimizationEngine().run(
                _flow_input(apply_seo=True, require_approval=False),
            )

        if output["status"] == "success":
            mock_enqueue.assert_not_called()
            mock_apply.assert_called_once()

    def test_apply_seo_false_skips_both(self, isolated_queue):
        from engines.search_optimization.flow import (
            SearchOptimizationEngine,
        )

        with patch(
            "engines.search_optimization.flow.apply_meta",
        ) as mock_apply, patch(
            "engines.search_optimization.flow.enqueue_meta_for_approval",
        ) as mock_enqueue:
            output = SearchOptimizationEngine().run(
                _flow_input(apply_seo=False, require_approval=True),
            )

        if output["status"] == "success":
            mock_apply.assert_not_called()
            mock_enqueue.assert_not_called()
            assert output["data"]["apply_results"] == []
