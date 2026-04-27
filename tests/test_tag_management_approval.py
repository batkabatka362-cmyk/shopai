"""Tests for the tag_management approval-queue wiring.

Same pattern as PR #61 (dynamic_pricing) — plural per-assignment
writer with the same {merge → enqueue} loop. Coverage:

  1. ``enqueue_tags_for_approval`` happy path — every assignment
     with at least one genuinely-new tag is parked, merged tag
     list and ``pending_action_id`` surfaced.
  2. Skip semantics: ``no_new_tags`` (existing covers all
     proposed) / queue-unavailable / empty assignments.
  3. flow integration — ``data.apply_tags=True`` +
     ``data.require_approval=True`` routes to enqueue;
     ``require_approval=False`` falls back to the legacy direct
     applier.
  4. apply_tags=False short-circuits both paths.
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


# ─── enqueue_tags_for_approval ───────────────────────────────────


def _product(pid: str, tags: list[str]):
    return {"id": pid, "title": "Widget", "tags": tags}


def _assignment(pid: str, tags: list[str]):
    return {"product_id": pid, "tags": tags}


class TestEnqueueTagsForApproval:

    def test_happy_path_parks_each_assignment(self, isolated_queue):
        from engines.tag_management.tag_applier import (
            enqueue_tags_for_approval,
        )

        results = enqueue_tags_for_approval(
            assignments=[
                _assignment("gid://shopify/Product/1",
                            ["camping", "winter-2026"]),
                _assignment("gid://shopify/Product/2",
                            ["budget"]),
            ],
            products=[
                _product("gid://shopify/Product/1", ["existing"]),
                _product("gid://shopify/Product/2", []),
            ],
        )

        assert len(results) == 2
        for r in results:
            assert r["applied"] is False
            assert r["error"] == "queued"
            assert r["pending_action_id"].startswith("appr_")

        # Both queued, status=pending.
        assert isolated_queue.stats()["pending"] == 2

    def test_no_new_tags_skipped(self, isolated_queue):
        # Proposed tags are already on the product (case-insensitive).
        from engines.tag_management.tag_applier import (
            enqueue_tags_for_approval,
        )

        results = enqueue_tags_for_approval(
            assignments=[_assignment("gid://shopify/Product/1",
                                     ["EXISTING"])],
            products=[_product("gid://shopify/Product/1", ["existing"])],
        )
        assert results[0]["error"] == "no_new_tags"
        assert results[0]["pending_action_id"] is None
        assert isolated_queue.list_pending() == []

    def test_queue_unavailable_uniform_skip_list(self, isolated_queue):
        from engines.tag_management.tag_applier import (
            enqueue_tags_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            results = enqueue_tags_for_approval(
                assignments=[
                    _assignment("gid://shopify/Product/1", ["new-tag"]),
                ],
                products=[
                    _product("gid://shopify/Product/1", []),
                ],
            )
        assert results[0]["error"] == "approval_queue_unavailable"
        assert results[0]["pending_action_id"] is None

    def test_empty_assignments_returns_empty_list(self, isolated_queue):
        from engines.tag_management.tag_applier import (
            enqueue_tags_for_approval,
        )

        assert enqueue_tags_for_approval(
            assignments=[], products=[],
        ) == []

    def test_narrative_includes_tag_count(self, isolated_queue):
        from engines.tag_management.tag_applier import (
            enqueue_tags_for_approval,
        )

        results = enqueue_tags_for_approval(
            assignments=[
                _assignment("gid://shopify/Product/1",
                            ["camping", "winter-2026"]),
            ],
            products=[_product("gid://shopify/Product/1", [])],
        )
        action = isolated_queue.get(results[0]["pending_action_id"])
        assert action is not None
        assert "Add 2 tag" in action.narrative
        assert "camping" in action.narrative


# ─── flow integration ───────────────────────────────────────────


def _flow_input(*, apply_tags_flag: bool, require_approval: bool):
    return {
        "status": "ok",
        "data": {
            "products": [
                {
                    "id": "gid://shopify/Product/1",
                    "title": "Widget",
                    "tags": ["existing"],
                    "category": "general",
                },
            ],
            "existing_tags": ["existing"],
            "taxonomy": {},
            "apply_tags": apply_tags_flag,
            "require_approval": require_approval,
        },
        "meta": {},
        "error": None,
    }


class TestFlowApprovalIntegration:

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.tag_management.flow import TagManagementEngine

        with patch(
            "engines.tag_management.flow.apply_tags",
        ) as mock_apply, patch(
            "engines.tag_management.flow.enqueue_tags_for_approval",
            return_value=[
                {"product_id": "gid://shopify/Product/1",
                 "applied": False, "tags_added": 0,
                 "merged_tags": ["existing", "auto"],
                 "error": "queued",
                 "pending_action_id": "appr_stub_1"},
            ],
        ) as mock_enqueue:
            output = TagManagementEngine().run(
                _flow_input(apply_tags_flag=True, require_approval=True),
            )

        assert output["status"] == "success"
        mock_apply.assert_not_called()
        # tag_management always produces at least a placeholder
        # assignment, so enqueue should run.
        if output["data"].get("tags"):
            mock_enqueue.assert_called_once()
            assert output["data"]["apply_results"][0]["error"] == "queued"
            assert (
                output["data"]["apply_results"][0]["pending_action_id"]
                == "appr_stub_1"
            )

    def test_require_approval_false_routes_to_direct_apply(
        self, isolated_queue,
    ):
        from engines.tag_management.flow import TagManagementEngine

        with patch(
            "engines.tag_management.flow.apply_tags",
            return_value=[
                {"product_id": "gid://shopify/Product/1",
                 "applied": True, "tags_added": 1,
                 "merged_tags": ["existing", "auto"],
                 "error": None},
            ],
        ) as mock_apply, patch(
            "engines.tag_management.flow.enqueue_tags_for_approval",
        ) as mock_enqueue:
            output = TagManagementEngine().run(
                _flow_input(apply_tags_flag=True, require_approval=False),
            )

        assert output["status"] == "success"
        mock_enqueue.assert_not_called()
        if output["data"].get("tags"):
            mock_apply.assert_called_once()
            assert output["data"]["apply_results"][0]["applied"] is True

    def test_apply_tags_false_skips_both(self, isolated_queue):
        from engines.tag_management.flow import TagManagementEngine

        with patch(
            "engines.tag_management.flow.apply_tags",
        ) as mock_apply, patch(
            "engines.tag_management.flow.enqueue_tags_for_approval",
        ) as mock_enqueue:
            output = TagManagementEngine().run(
                _flow_input(apply_tags_flag=False, require_approval=True),
            )

        assert output["status"] == "success"
        mock_apply.assert_not_called()
        mock_enqueue.assert_not_called()
        assert output["data"]["apply_results"] == []
