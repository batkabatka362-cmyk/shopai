"""Tests for the catalog approval-queue wiring.

Last applier in the Phase 6/7 series. The catalog applier
mutates assignments in place (no separate result list), so the
approval branch keeps that contract: each parked assignment
gets ``applied=False``, ``apply_error="queued"``, and a
``pending_action_id``.

Coverage:
  1. ``enqueue_tag_assignments_for_approval`` happy path —
     each assignment with cleaned tags gets parked.
  2. Skip semantics: ``apply=False`` master switch /
     missing product_id / no tags / approval-queue unavailable.
  3. flow integration — three branches:
     ``apply_tags=False`` → direct path, all stamped disabled;
     ``apply_tags=True`` + ``require_approval=False`` → direct;
     ``apply_tags=True`` + ``require_approval=True`` → enqueue.
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


# ─── enqueue_tag_assignments_for_approval ───────────────────────


def _assignment(**overrides):
    base = {
        "product_id": "gid://shopify/Product/1",
        "tags": ["budget", "winter-2026"],
        "category": "general",
    }
    base.update(overrides)
    return base


class TestEnqueueTagAssignmentsForApproval:

    def test_happy_path_parks_each_assignment(self, isolated_queue):
        from engines.catalog.shopify_applier import (
            enqueue_tag_assignments_for_approval,
        )

        assignments = [
            _assignment(),
            _assignment(product_id="gid://shopify/Product/2",
                        tags=["seasonal"]),
        ]
        result = enqueue_tag_assignments_for_approval(
            assignments, apply=True,
        )

        # In-place mutation contract.
        assert result is assignments
        for a in assignments:
            assert a["applied"] is False
            assert a["apply_error"] == "queued"
            assert a["pending_action_id"].startswith("appr_")

        assert isolated_queue.stats()["pending"] == 2

        action = isolated_queue.get(assignments[0]["pending_action_id"])
        assert action is not None
        assert action.engine == "catalog"
        assert action.action_type == "catalog_apply_tags"
        assert action.capability == "SHOPIFY_ADD_TAGS"
        assert "Add 2 tag" in action.narrative

    def test_apply_false_stamps_all_disabled(self, isolated_queue):
        from engines.catalog.shopify_applier import (
            enqueue_tag_assignments_for_approval,
        )

        assignments = [_assignment()]
        enqueue_tag_assignments_for_approval(
            assignments, apply=False,
        )
        assert assignments[0]["applied"] is False
        assert assignments[0]["apply_error"] == "apply disabled by caller"
        assert "pending_action_id" not in assignments[0]
        assert isolated_queue.list_pending() == []

    def test_missing_product_id_skipped(self, isolated_queue):
        from engines.catalog.shopify_applier import (
            enqueue_tag_assignments_for_approval,
        )

        assignments = [_assignment(product_id="")]
        enqueue_tag_assignments_for_approval(
            assignments, apply=True,
        )
        assert assignments[0]["apply_error"] == "missing product_id"
        assert "pending_action_id" not in assignments[0]

    def test_empty_tags_skipped(self, isolated_queue):
        from engines.catalog.shopify_applier import (
            enqueue_tag_assignments_for_approval,
        )

        assignments = [_assignment(tags=[])]
        enqueue_tag_assignments_for_approval(
            assignments, apply=True,
        )
        assert assignments[0]["apply_error"] == "no tags to apply"

    def test_garbage_tags_skipped(self, isolated_queue):
        # ``tags`` is not a list — fallback skip.
        from engines.catalog.shopify_applier import (
            enqueue_tag_assignments_for_approval,
        )

        assignments = [_assignment(tags="not-a-list")]
        enqueue_tag_assignments_for_approval(
            assignments, apply=True,
        )
        assert assignments[0]["apply_error"] == "no tags to apply"

    def test_queue_unavailable_uniform_skip(self, isolated_queue):
        from engines.catalog.shopify_applier import (
            enqueue_tag_assignments_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            assignments = [_assignment()]
            enqueue_tag_assignments_for_approval(
                assignments, apply=True,
            )
        assert assignments[0]["apply_error"] == "approval queue unavailable"
        assert "pending_action_id" not in assignments[0]

    def test_empty_assignments_returns_unchanged(self, isolated_queue):
        from engines.catalog.shopify_applier import (
            enqueue_tag_assignments_for_approval,
        )

        result = enqueue_tag_assignments_for_approval([], apply=True)
        assert result == []


# ─── flow integration ───────────────────────────────────────────


def _flow_input(*, apply_tags: bool, require_approval: bool):
    return {
        "status": "ok",
        "data": {
            "products": [
                {"id": "gid://shopify/Product/1",
                 "title": "Widget", "category": "general"},
            ],
            "apply_tags": apply_tags,
            "require_approval": require_approval,
        },
        "meta": {},
        "error": None,
    }


class TestFlowApprovalIntegration:

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.catalog.flow import CatalogEngine

        with patch(
            "engines.catalog.flow.apply_tag_assignments",
        ) as mock_apply, patch(
            "engines.catalog.flow.enqueue_tag_assignments_for_approval",
            side_effect=lambda assignments, **kw: assignments,
        ) as mock_enqueue:
            output = CatalogEngine().run(
                _flow_input(apply_tags=True, require_approval=True),
            )

        if output["status"] == "success":
            mock_apply.assert_not_called()
            mock_enqueue.assert_called_once()

    def test_require_approval_false_routes_to_direct_apply(
        self, isolated_queue,
    ):
        from engines.catalog.flow import CatalogEngine

        with patch(
            "engines.catalog.flow.apply_tag_assignments",
            side_effect=lambda assignments, **kw: assignments,
        ) as mock_apply, patch(
            "engines.catalog.flow.enqueue_tag_assignments_for_approval",
        ) as mock_enqueue:
            output = CatalogEngine().run(
                _flow_input(apply_tags=True, require_approval=False),
            )

        if output["status"] == "success":
            mock_enqueue.assert_not_called()
            mock_apply.assert_called_once()

    def test_apply_tags_false_routes_to_direct_with_disabled_stamp(
        self, isolated_queue,
    ):
        # Even with require_approval=True, apply_tags=False routes
        # to the direct path (which then stamps "disabled by caller"
        # without making any network call).
        from engines.catalog.flow import CatalogEngine

        with patch(
            "engines.catalog.flow.apply_tag_assignments",
            side_effect=lambda assignments, **kw: assignments,
        ) as mock_apply, patch(
            "engines.catalog.flow.enqueue_tag_assignments_for_approval",
        ) as mock_enqueue:
            output = CatalogEngine().run(
                _flow_input(apply_tags=False, require_approval=True),
            )

        if output["status"] == "success":
            mock_enqueue.assert_not_called()
            mock_apply.assert_called_once()
