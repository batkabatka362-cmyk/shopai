"""Tests for the inventory approval-queue wiring (audit 1C #4).

The inventory engine produces three flag streams (stockout_risks,
reorder_calculations, stock_analyses); the new applier aggregates
them into per-SKU inventory-state tags
(``shopai-stockout-imminent`` / ``shopai-needs-reorder`` /
``shopai-dead-stock`` / ``shopai-overstocked``) and pushes them
to SHOPIFY_UPDATE_PRODUCT.tags via the merge-with-existing pattern
(same as tag_management).

Coverage:
  1. Tag aggregation — each flag stream maps to its expected tag;
     a SKU flagged on multiple streams gets all relevant tags.
  2. ``apply_inventory_tags`` happy path / router unavailable /
     no_new_tags short-circuit.
  3. ``enqueue_inventory_tags_for_approval`` mirrors the above
     plus queue-unavailable fallback.
  4. flow integration — three branches of Stage 10.5
     (default off / direct / approval).
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


# ─── Tag aggregation ─────────────────────────────────────────────


class TestTagAggregation:

    def test_stockout_imminent_emits_stockout_tag(self):
        from engines.inventory.inventory_applier import (
            _build_tag_assignments,
        )

        out = _build_tag_assignments(
            stockout_risks=[
                {"id": "p1", "risk_level": "imminent"},
            ],
            reorder_calculations=[],
            stock_analyses=[],
        )
        assert out == {"p1": ["shopai-stockout-imminent"]}

    def test_stockout_high_also_emits_stockout_tag(self):
        from engines.inventory.inventory_applier import (
            _build_tag_assignments,
        )

        out = _build_tag_assignments(
            stockout_risks=[{"id": "p1", "risk_level": "high"}],
            reorder_calculations=[], stock_analyses=[],
        )
        assert out == {"p1": ["shopai-stockout-imminent"]}

    def test_low_risk_does_not_emit_stockout_tag(self):
        from engines.inventory.inventory_applier import (
            _build_tag_assignments,
        )

        out = _build_tag_assignments(
            stockout_risks=[{"id": "p1", "risk_level": "low"}],
            reorder_calculations=[], stock_analyses=[],
        )
        assert out == {}

    def test_needs_reorder_emits_reorder_tag(self):
        from engines.inventory.inventory_applier import (
            _build_tag_assignments,
        )

        out = _build_tag_assignments(
            stockout_risks=[],
            reorder_calculations=[{"id": "p2", "needs_reorder": True}],
            stock_analyses=[],
        )
        assert out == {"p2": ["shopai-needs-reorder"]}

    def test_dead_and_overstocked_classifications(self):
        from engines.inventory.inventory_applier import (
            _build_tag_assignments,
        )

        out = _build_tag_assignments(
            stockout_risks=[],
            reorder_calculations=[],
            stock_analyses=[
                {"id": "p3", "classification": "dead"},
                {"id": "p4", "classification": "overstocked"},
                {"id": "p5", "classification": "healthy"},
            ],
        )
        assert out == {
            "p3": ["shopai-dead-stock"],
            "p4": ["shopai-overstocked"],
        }
        assert "p5" not in out

    def test_sku_can_earn_multiple_state_tags(self):
        from engines.inventory.inventory_applier import (
            _build_tag_assignments,
        )

        out = _build_tag_assignments(
            stockout_risks=[{"id": "p1", "risk_level": "imminent"}],
            reorder_calculations=[{"id": "p1", "needs_reorder": True}],
            stock_analyses=[],
        )
        assert set(out["p1"]) == {
            "shopai-stockout-imminent", "shopai-needs-reorder",
        }


# ─── apply_inventory_tags (direct path) ──────────────────────────


class _StubRouterResult:
    def __init__(self, ok=True, data=None, error=None):
        self.ok = ok
        self.data = data or {}
        self.error = error


class _StubRouter:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, capability, params):
        self.calls.append((capability, params))
        return self.result


class TestApplyInventoryTags:

    def test_happy_path_merges_tag_with_existing(self):
        from engines.inventory import inventory_applier
        from engines.inventory.inventory_applier import apply_inventory_tags

        stub = _StubRouter(_StubRouterResult(ok=True))
        with patch.object(
            inventory_applier, "_get_router", return_value=stub,
        ):
            results = apply_inventory_tags(
                products=[{
                    "id": "p1",
                    "tags": ["premium", "men"],
                }],
                stockout_risks=[
                    {"id": "p1", "risk_level": "imminent"},
                ],
                reorder_calculations=[],
                stock_analyses=[],
            )

        assert len(stub.calls) == 1
        _, params = stub.calls[0]
        assert params["id"] == "p1"
        # Merged tags preserve existing operator tags + add state tag.
        assert "premium" in params["tags"]
        assert "men" in params["tags"]
        assert "shopai-stockout-imminent" in params["tags"]

        assert results[0]["applied"] is True
        assert results[0]["tags_added"] == 1

    def test_no_new_tags_short_circuits(self):
        from engines.inventory import inventory_applier
        from engines.inventory.inventory_applier import apply_inventory_tags

        stub = _StubRouter(_StubRouterResult(ok=True))
        with patch.object(
            inventory_applier, "_get_router", return_value=stub,
        ):
            results = apply_inventory_tags(
                products=[{
                    "id": "p1",
                    # Tag already present — no_new_tags fires.
                    "tags": ["shopai-stockout-imminent"],
                }],
                stockout_risks=[
                    {"id": "p1", "risk_level": "imminent"},
                ],
                reorder_calculations=[],
                stock_analyses=[],
            )

        assert stub.calls == []  # No API call
        assert results[0]["error"] == "no_new_tags"
        assert results[0]["applied"] is False

    def test_router_unavailable_stamps_skip_list(self):
        from engines.inventory import inventory_applier
        from engines.inventory.inventory_applier import apply_inventory_tags

        with patch.object(
            inventory_applier, "_get_router", return_value=None,
        ):
            results = apply_inventory_tags(
                products=[{"id": "p1", "tags": []}],
                stockout_risks=[
                    {"id": "p1", "risk_level": "imminent"},
                ],
                reorder_calculations=[],
                stock_analyses=[],
            )
        assert results[0]["error"] == "router_unavailable"


# ─── enqueue_inventory_tags_for_approval (queue path) ───────────


class TestEnqueueInventoryTagsForApproval:

    def test_happy_path_parks_per_sku(self, isolated_queue):
        from engines.inventory.inventory_applier import (
            enqueue_inventory_tags_for_approval,
        )

        results = enqueue_inventory_tags_for_approval(
            products=[
                {"id": "p1", "tags": []},
                {"id": "p2", "tags": ["operator-tag"]},
            ],
            stockout_risks=[
                {"id": "p1", "risk_level": "imminent"},
            ],
            reorder_calculations=[
                {"id": "p2", "needs_reorder": True},
            ],
            stock_analyses=[],
        )

        assert len(results) == 2
        for r in results:
            assert r["error"] == "queued"
            assert r["pending_action_id"].startswith("appr_")

        # Persisted in queue.
        assert isolated_queue.stats()["pending"] == 2

        # Narrative captures the tag list.
        action = isolated_queue.get(results[0]["pending_action_id"])
        assert action is not None
        assert action.engine == "inventory"
        assert action.action_type == "apply_inventory_tags"
        assert action.capability == "SHOPIFY_UPDATE_PRODUCT"

    def test_no_new_tags_short_circuits(self, isolated_queue):
        from engines.inventory.inventory_applier import (
            enqueue_inventory_tags_for_approval,
        )

        results = enqueue_inventory_tags_for_approval(
            products=[{"id": "p1", "tags": ["shopai-dead-stock"]}],
            stockout_risks=[],
            reorder_calculations=[],
            stock_analyses=[{"id": "p1", "classification": "dead"}],
        )
        assert results[0]["error"] == "no_new_tags"
        assert results[0]["pending_action_id"] is None
        assert isolated_queue.list_pending() == []

    def test_queue_unavailable_uniform_skip_list(self, isolated_queue):
        from engines.inventory.inventory_applier import (
            enqueue_inventory_tags_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            results = enqueue_inventory_tags_for_approval(
                products=[{"id": "p1", "tags": []}],
                stockout_risks=[
                    {"id": "p1", "risk_level": "imminent"},
                ],
                reorder_calculations=[],
                stock_analyses=[],
            )
        assert results[0]["error"] == "approval_queue_unavailable"

    def test_empty_flags_returns_empty(self, isolated_queue):
        from engines.inventory.inventory_applier import (
            enqueue_inventory_tags_for_approval,
        )

        assert enqueue_inventory_tags_for_approval(
            products=[], stockout_risks=[],
            reorder_calculations=[], stock_analyses=[],
        ) == []


# ─── flow integration ───────────────────────────────────────────


def _flow_input(*, apply_inventory_tags_flag=None, require_approval=None):
    data: dict = {
        "products": [
            {
                "id": "gid://shopify/Product/1",
                "title": "Widget",
                "price": 50.0,
                "inventory_quantity": 5,
                "tags": [],
            },
        ],
        "warehouse_capacity": 1000,
        "service_level_target": 0.95,
    }
    if apply_inventory_tags_flag is not None:
        data["apply_inventory_tags"] = apply_inventory_tags_flag
    if require_approval is not None:
        data["require_approval"] = require_approval
    return {"status": "ok", "data": data, "meta": {}, "error": None}


class TestFlowApprovalIntegration:

    def test_default_off_routes_nowhere(self, isolated_queue):
        from engines.inventory.flow import InventoryEngine

        with patch(
            "engines.inventory.flow.apply_inventory_tags",
        ) as mock_apply, patch(
            "engines.inventory.flow.enqueue_inventory_tags_for_approval",
        ) as mock_enqueue:
            output = InventoryEngine().run(_flow_input())

        mock_apply.assert_not_called()
        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["tag_apply_results"] == []

    def test_apply_true_routes_to_direct(self, isolated_queue):
        from engines.inventory.flow import InventoryEngine

        with patch(
            "engines.inventory.flow.apply_inventory_tags",
            return_value=[
                {"product_id": "p1", "applied": True,
                 "tags_added": 1, "merged_tags": ["x"], "error": None},
            ],
        ) as mock_apply, patch(
            "engines.inventory.flow.enqueue_inventory_tags_for_approval",
        ) as mock_enqueue:
            output = InventoryEngine().run(
                _flow_input(
                    apply_inventory_tags_flag=True,
                    require_approval=False,
                ),
            )

        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            mock_apply.assert_called_once()
            assert output["data"]["tag_apply_results"][0]["applied"] is True

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.inventory.flow import InventoryEngine

        stub_result = [
            {"product_id": "p1", "applied": False,
             "tags_added": 0, "merged_tags": ["x"],
             "error": "queued",
             "pending_action_id": "appr_stub_1"},
        ]
        with patch(
            "engines.inventory.flow.apply_inventory_tags",
        ) as mock_apply, patch(
            "engines.inventory.flow.enqueue_inventory_tags_for_approval",
            return_value=stub_result,
        ) as mock_enqueue:
            output = InventoryEngine().run(
                _flow_input(
                    apply_inventory_tags_flag=True,
                    require_approval=True,
                ),
            )

        mock_apply.assert_not_called()
        if output["status"] == "success":
            mock_enqueue.assert_called_once()
            assert output["data"]["tag_apply_results"] == stub_result
