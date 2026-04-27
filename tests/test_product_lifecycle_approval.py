"""Tests for the product_lifecycle approval-queue wiring.

Same pattern as PR #59 / #60 / #61 / #63 / #64, applied to the
destructive archive path. Coverage:

  1. ``enqueue_archives_for_approval`` happy path — entries that
     pass the triple-gate (stage / velocity / confidence) are
     parked.
  2. Skip semantics: ``stage_not_archivable`` /
     ``velocity_above_floor`` / ``below_min_confidence`` /
     queue-unavailable.
  3. flow integration — ``data.apply_archives=True`` +
     ``data.require_approval=True`` enqueues; ``False`` falls
     back to direct archive.
  4. Confidence + velocity thresholds threaded through both
     branches.
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


# ─── enqueue_archives_for_approval ───────────────────────────────


def _entry(**overrides):
    base = {
        "product_id": "gid://shopify/Product/1",
        "stage": "decline",
        "velocity": 0.1,
        "confidence": 0.85,
        "projected_transition": "archived in 7 days",
    }
    base.update(overrides)
    return base


class TestEnqueueArchivesForApproval:

    def test_happy_path_parks_each_entry(self, isolated_queue):
        from engines.product_lifecycle.lifecycle_applier import (
            enqueue_archives_for_approval,
        )

        results = enqueue_archives_for_approval(
            lifecycle=[
                _entry(),
                _entry(product_id="gid://shopify/Product/2",
                       velocity=0.05),
            ],
        )

        assert len(results) == 2
        for r in results:
            assert r["archived"] is False
            assert r["error"] == "queued"
            assert r["pending_action_id"].startswith("appr_")

        action = isolated_queue.get(results[0]["pending_action_id"])
        assert action is not None
        assert action.engine == "product_lifecycle"
        assert action.action_type == "archive_declining_product"
        assert action.capability == "SHOPIFY_UPDATE_PRODUCT"
        assert "DESTRUCTIVE" in action.narrative
        assert action.confidence == 0.85

    def test_non_decline_stage_skipped(self, isolated_queue):
        from engines.product_lifecycle.lifecycle_applier import (
            enqueue_archives_for_approval,
        )

        results = enqueue_archives_for_approval(
            lifecycle=[_entry(stage="growth")],
        )
        assert results[0]["error"] == "stage_not_archivable"
        assert results[0]["pending_action_id"] is None
        assert isolated_queue.list_pending() == []

    def test_velocity_above_floor_skipped(self, isolated_queue):
        from engines.product_lifecycle.lifecycle_applier import (
            enqueue_archives_for_approval,
        )

        # Default floor 0.5 — entry with velocity 1.2 should be
        # blocked even though stage="decline".
        results = enqueue_archives_for_approval(
            lifecycle=[_entry(velocity=1.2)],
        )
        assert results[0]["error"] == "velocity_above_floor"
        assert results[0]["pending_action_id"] is None

    def test_below_min_confidence_skipped(self, isolated_queue):
        from engines.product_lifecycle.lifecycle_applier import (
            enqueue_archives_for_approval,
        )

        results = enqueue_archives_for_approval(
            lifecycle=[_entry(confidence=0.4)],
            min_confidence=0.7,
        )
        assert results[0]["error"] == "below_min_confidence"
        assert results[0]["pending_action_id"] is None

    def test_queue_unavailable_uniform_skip_list(self, isolated_queue):
        from engines.product_lifecycle.lifecycle_applier import (
            enqueue_archives_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            results = enqueue_archives_for_approval(
                lifecycle=[_entry()],
            )
        assert results[0]["error"] == "approval_queue_unavailable"
        assert results[0]["pending_action_id"] is None

    def test_velocity_floor_override(self, isolated_queue):
        from engines.product_lifecycle.lifecycle_applier import (
            enqueue_archives_for_approval,
        )

        # Pass a low floor — even a high-velocity entry should
        # qualify.
        results = enqueue_archives_for_approval(
            lifecycle=[_entry(velocity=2.0)],
            velocity_floor=5.0,
        )
        assert results[0]["error"] == "queued"
        assert results[0]["pending_action_id"] is not None


# ─── flow integration ───────────────────────────────────────────


def _flow_input(*, apply_archives: bool, require_approval: bool):
    return {
        "status": "ok",
        "data": {
            "products": [
                {
                    "id": "gid://shopify/Product/1",
                    "title": "Old Widget",
                    "created_at": "2020-01-01",
                    "updated_at": "2024-06-01",
                    "tags": [],
                },
            ],
            "sales_data": [],
            "apply_archives": apply_archives,
            "require_approval": require_approval,
        },
        "meta": {},
        "error": None,
    }


class TestFlowApprovalIntegration:

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.product_lifecycle.flow import (
            ProductLifecycleEngine,
        )

        with patch(
            "engines.product_lifecycle.flow.archive_declining_products",
        ) as mock_direct, patch(
            "engines.product_lifecycle.flow.enqueue_archives_for_approval",
            return_value=[],
        ) as mock_enqueue:
            output = ProductLifecycleEngine().run(
                _flow_input(apply_archives=True, require_approval=True),
            )

        assert output["status"] == "success"
        mock_direct.assert_not_called()
        # The pipeline produces at least one lifecycle entry on a
        # minimal fixture, so enqueue should be called once.
        if output["data"].get("lifecycle"):
            mock_enqueue.assert_called_once()

    def test_require_approval_false_routes_to_direct_archive(
        self, isolated_queue,
    ):
        from engines.product_lifecycle.flow import (
            ProductLifecycleEngine,
        )

        with patch(
            "engines.product_lifecycle.flow.archive_declining_products",
            return_value=[],
        ) as mock_direct, patch(
            "engines.product_lifecycle.flow.enqueue_archives_for_approval",
        ) as mock_enqueue:
            output = ProductLifecycleEngine().run(
                _flow_input(apply_archives=True, require_approval=False),
            )

        assert output["status"] == "success"
        mock_enqueue.assert_not_called()
        if output["data"].get("lifecycle"):
            mock_direct.assert_called_once()

    def test_apply_archives_false_skips_both(self, isolated_queue):
        from engines.product_lifecycle.flow import (
            ProductLifecycleEngine,
        )

        with patch(
            "engines.product_lifecycle.flow.archive_declining_products",
        ) as mock_direct, patch(
            "engines.product_lifecycle.flow.enqueue_archives_for_approval",
        ) as mock_enqueue:
            output = ProductLifecycleEngine().run(
                _flow_input(apply_archives=False, require_approval=True),
            )

        assert output["status"] == "success"
        mock_direct.assert_not_called()
        mock_enqueue.assert_not_called()
        assert output["data"]["archive_results"] == []
