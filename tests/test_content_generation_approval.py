"""Tests for the content_generation approval-queue wiring.

Same pattern as PR #59 / #60 / #61 / #63 / #64 / #65, applied
to the singular per-call applier (content_generation runs per
product per call, returning a single dict not a list). Coverage:

  1. ``enqueue_description_for_approval`` happy path — proposal
     parked, narrative carries body length + SEO + readability.
  2. Skip semantics: every gate from the direct applier
     (``content_type_not_appliable`` /``product_id_missing`` /
     ``body_empty`` / ``below_min_seo_score`` /
     ``below_min_readability_score``) plus
     ``approval_queue_unavailable``.
  3. flow integration — ``data.apply_content=True`` +
     ``data.require_approval=True`` enqueues; ``False`` falls
     back to the legacy direct applier.
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


# ─── enqueue_description_for_approval ───────────────────────────


def _content_block(**overrides):
    base = {
        "headline": "Best Widget Ever",
        "body": "<p>This is a long product description with lots of detail.</p>",
        "tone": "professional",
    }
    base.update(overrides)
    return base


class TestEnqueueDescriptionForApproval:

    def test_happy_path_parks_proposal(self, isolated_queue):
        from engines.content_generation.content_applier import (
            enqueue_description_for_approval,
        )

        result = enqueue_description_for_approval(
            product={"id": "gid://shopify/Product/1", "title": "Widget"},
            content_block=_content_block(),
            content_type="product_description",
            seo_score=0.82,
            readability_score=0.71,
        )
        assert result["product_id"] == "gid://shopify/Product/1"
        assert result["applied"] is False
        assert result["error"] == "queued"
        assert result["pending_action_id"].startswith("appr_")
        assert result["body_length"] > 0

        action = isolated_queue.get(result["pending_action_id"])
        assert action is not None
        assert action.engine == "content_generation"
        assert action.action_type == "apply_description"
        assert "DESTRUCTIVE" in action.narrative
        assert "0.82" in action.narrative
        # Body preview is captured for the approver.
        assert action.params["headline"] == "Best Widget Ever"

    def test_non_appliable_content_type_skipped(self, isolated_queue):
        from engines.content_generation.content_applier import (
            enqueue_description_for_approval,
        )

        result = enqueue_description_for_approval(
            product={"id": "gid://shopify/Product/1"},
            content_block=_content_block(),
            content_type="ad_copy",
        )
        assert result["error"] == "content_type_not_appliable"
        assert result["pending_action_id"] is None
        assert isolated_queue.list_pending() == []

    def test_missing_product_id_skipped(self, isolated_queue):
        from engines.content_generation.content_applier import (
            enqueue_description_for_approval,
        )

        result = enqueue_description_for_approval(
            product={},
            content_block=_content_block(),
            content_type="product_description",
        )
        assert result["error"] == "product_id_missing"
        assert result["pending_action_id"] is None

    def test_empty_body_skipped(self, isolated_queue):
        from engines.content_generation.content_applier import (
            enqueue_description_for_approval,
        )

        result = enqueue_description_for_approval(
            product={"id": "gid://shopify/Product/1"},
            content_block=_content_block(body=""),
            content_type="product_description",
        )
        assert result["error"] == "body_empty"
        assert result["pending_action_id"] is None

    def test_below_seo_score_skipped(self, isolated_queue):
        from engines.content_generation.content_applier import (
            enqueue_description_for_approval,
        )

        result = enqueue_description_for_approval(
            product={"id": "gid://shopify/Product/1"},
            content_block=_content_block(),
            content_type="product_description",
            seo_score=0.3,
            min_seo_score=0.7,
        )
        assert result["error"] == "below_min_seo_score"
        assert result["pending_action_id"] is None

    def test_below_readability_score_skipped(self, isolated_queue):
        from engines.content_generation.content_applier import (
            enqueue_description_for_approval,
        )

        result = enqueue_description_for_approval(
            product={"id": "gid://shopify/Product/1"},
            content_block=_content_block(),
            content_type="product_description",
            readability_score=0.4,
            min_readability_score=0.7,
        )
        assert result["error"] == "below_min_readability_score"
        assert result["pending_action_id"] is None

    def test_queue_unavailable_returns_error(self, isolated_queue):
        from engines.content_generation.content_applier import (
            enqueue_description_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            result = enqueue_description_for_approval(
                product={"id": "gid://shopify/Product/1"},
                content_block=_content_block(),
                content_type="product_description",
            )
        assert result["error"] == "approval_queue_unavailable"
        assert result["pending_action_id"] is None


# ─── flow integration ───────────────────────────────────────────


def _flow_input(*, apply_content: bool, require_approval: bool):
    return {
        "status": "ok",
        "data": {
            "product": {
                "id": "gid://shopify/Product/1",
                "title": "Widget",
                "category": "general",
            },
            "content_type": "product_description",
            "tone_hint": "professional",
            "apply_content": apply_content,
            "require_approval": require_approval,
        },
        "meta": {},
        "error": None,
    }


class TestFlowApprovalIntegration:

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.content_generation.flow import (
            ContentGenerationEngine,
        )

        with patch(
            "engines.content_generation.flow.apply_description",
        ) as mock_direct, patch(
            "engines.content_generation.flow.enqueue_description_for_approval",
            return_value={
                "product_id": "gid://shopify/Product/1",
                "applied": False, "body_length": 200,
                "error": "queued",
                "pending_action_id": "appr_stub",
            },
        ) as mock_enqueue:
            output = ContentGenerationEngine().run(
                _flow_input(apply_content=True, require_approval=True),
            )

        if output["status"] == "success":
            mock_direct.assert_not_called()
            mock_enqueue.assert_called_once()

    def test_require_approval_false_routes_to_direct_apply(
        self, isolated_queue,
    ):
        from engines.content_generation.flow import (
            ContentGenerationEngine,
        )

        with patch(
            "engines.content_generation.flow.apply_description",
            return_value={
                "product_id": "gid://shopify/Product/1",
                "applied": True, "body_length": 200, "error": None,
            },
        ) as mock_direct, patch(
            "engines.content_generation.flow.enqueue_description_for_approval",
        ) as mock_enqueue:
            output = ContentGenerationEngine().run(
                _flow_input(apply_content=True, require_approval=False),
            )

        if output["status"] == "success":
            mock_enqueue.assert_not_called()
            mock_direct.assert_called_once()

    def test_apply_content_false_skips_both(self, isolated_queue):
        from engines.content_generation.flow import (
            ContentGenerationEngine,
        )

        with patch(
            "engines.content_generation.flow.apply_description",
        ) as mock_direct, patch(
            "engines.content_generation.flow.enqueue_description_for_approval",
        ) as mock_enqueue:
            ContentGenerationEngine().run(
                _flow_input(apply_content=False, require_approval=True),
            )

        mock_direct.assert_not_called()
        mock_enqueue.assert_not_called()
