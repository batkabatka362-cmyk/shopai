"""Tests for the customer_segmentation approval-queue wiring.

The engine's ``segment_builder`` output classifies each customer
into exactly one named segment ("VIP Champions", "At-Risk
Loyalists", "Dormant Cart-Abandoners", etc.). Pre-fix the segment
names landed only in the engine output — the merchant couldn't
pull a "show me all VIPs" view in Shopify admin without manually
saving a search per segment.

The applier closes the loop. Per customer, push a tag
``shopai-segment-{slug}`` via SHOPIFY_TAG_CUSTOMER (additive,
no need to merge with existing tags).

Coverage:
  1. ``_build_tag`` slugifies segment names.
  2. ``_build_proposals`` filters Unclassified, blanks.
  3. ``apply_segment_tags`` happy path, router unavailable,
     adapter failure, adapter raised.
  4. ``enqueue_segment_tags_for_approval`` happy + queue
     unavailable.
  5. Flow integration — three branches of Stage 9.5.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _segments():
    return [
        {
            "name": "VIP Champions",
            "size": 2,
            "customers": [
                "gid://shopify/Customer/1",
                "gid://shopify/Customer/2",
            ],
            "avg_clv": 500.0,
            "strategy": "retain",
        },
        {
            "name": "At-Risk Loyalists",
            "size": 1,
            "customers": ["gid://shopify/Customer/3"],
            "avg_clv": 200.0,
            "strategy": "winback",
        },
    ]


# ─── _build_tag helper ─────────────────────────────────────────


class TestBuildTag:

    def test_vip_champions(self):
        from engines.customer_segmentation.customer_applier import (
            _build_tag,
        )
        assert _build_tag("VIP Champions") == (
            "shopai-segment-vip-champions"
        )

    def test_at_risk_loyalists(self):
        from engines.customer_segmentation.customer_applier import (
            _build_tag,
        )
        assert _build_tag("At-Risk Loyalists") == (
            "shopai-segment-at-risk-loyalists"
        )

    def test_collapses_consecutive_separators(self):
        from engines.customer_segmentation.customer_applier import (
            _build_tag,
        )
        assert _build_tag("Dormant  /  Inactive") == (
            "shopai-segment-dormant-inactive"
        )

    def test_blank_falls_back(self):
        from engines.customer_segmentation.customer_applier import (
            _build_tag,
        )
        assert _build_tag("") == "shopai-segment-unknown"


# ─── _build_proposals helper ───────────────────────────────────


class TestBuildProposals:

    def test_happy_path_one_per_customer(self):
        from engines.customer_segmentation.customer_applier import (
            _build_proposals,
        )
        proposals = _build_proposals(_segments())
        assert len(proposals) == 3
        assert {p["customer_id"] for p in proposals} == {
            "gid://shopify/Customer/1",
            "gid://shopify/Customer/2",
            "gid://shopify/Customer/3",
        }
        # VIP Champions customers got the right tag.
        vips = [p for p in proposals if p["segment"] == "VIP Champions"]
        assert len(vips) == 2
        assert all(p["tag"] == "shopai-segment-vip-champions" for p in vips)

    def test_filters_unclassified(self):
        from engines.customer_segmentation.customer_applier import (
            _build_proposals,
        )
        segs = [
            {
                "name": "Unclassified",
                "customers": ["gid://shopify/Customer/99"],
            },
            {
                "name": "VIP Champions",
                "customers": ["gid://shopify/Customer/1"],
            },
        ]
        proposals = _build_proposals(segs)
        # Only the VIP — Unclassified is noise.
        assert len(proposals) == 1
        assert proposals[0]["segment"] == "VIP Champions"

    def test_skips_blank_customer_ids(self):
        from engines.customer_segmentation.customer_applier import (
            _build_proposals,
        )
        segs = [{
            "name": "VIP Champions",
            "customers": ["gid://shopify/Customer/1", "", "  "],
        }]
        proposals = _build_proposals(segs)
        assert len(proposals) == 1

    def test_skips_blank_segment_name(self):
        from engines.customer_segmentation.customer_applier import (
            _build_proposals,
        )
        segs = [{"name": "", "customers": ["c1"]}]
        assert _build_proposals(segs) == []

    def test_non_list_returns_empty(self):
        from engines.customer_segmentation.customer_applier import (
            _build_proposals,
        )
        assert _build_proposals(None) == []
        assert _build_proposals("garbage") == []


# ─── apply_segment_tags (direct path) ──────────────────────────


class TestApplySegmentTags:

    def test_happy_path_calls_router_per_customer(self):
        from engines.customer_segmentation import customer_applier

        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.data = {}
        fake_router = MagicMock()
        fake_router.execute = MagicMock(return_value=fake_result)

        with patch.object(
            customer_applier, "_get_router", return_value=fake_router,
        ):
            results = customer_applier.apply_segment_tags(
                segments=_segments(),
            )

        assert len(results) == 3
        assert all(r["applied"] for r in results)
        assert all(r["error"] is None for r in results)
        assert fake_router.execute.call_count == 3
        # Adapter received the right shape.
        call_args = fake_router.execute.call_args_list[0]
        payload = call_args[0][1]
        assert payload["id"].startswith("gid://shopify/Customer/")
        assert payload["tags"] == ["shopai-segment-vip-champions"]

    def test_no_segments_returns_empty(self):
        from engines.customer_segmentation import customer_applier

        assert customer_applier.apply_segment_tags(segments=[]) == []

    def test_router_unavailable_returns_structured_skip(self):
        from engines.customer_segmentation import customer_applier

        with patch.object(
            customer_applier, "_get_router", return_value=None,
        ):
            results = customer_applier.apply_segment_tags(
                segments=_segments(),
            )
        assert len(results) == 3
        assert all(r["applied"] is False for r in results)
        assert all(r["error"] == "router_unavailable" for r in results)

    def test_adapter_failed_per_customer(self):
        from engines.customer_segmentation import customer_applier

        fake_result = MagicMock()
        fake_result.ok = False
        fake_result.error = "customer not found"
        fake_router = MagicMock()
        fake_router.execute = MagicMock(return_value=fake_result)

        with patch.object(
            customer_applier, "_get_router", return_value=fake_router,
        ):
            results = customer_applier.apply_segment_tags(
                segments=_segments()[:1],  # 2 customers
            )

        assert len(results) == 2
        assert all(r["applied"] is False for r in results)
        assert all(
            r["error"].startswith("adapter_failed:") for r in results
        )

    def test_adapter_raised_continues_batch(self):
        """One customer raising shouldn't halt the rest."""
        from engines.customer_segmentation import customer_applier

        call_count = {"n": 0}

        def _flaky_execute(_cap, _params):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient")
            ok = MagicMock()
            ok.ok = True
            ok.data = {}
            return ok

        fake_router = MagicMock()
        fake_router.execute = MagicMock(side_effect=_flaky_execute)

        with patch.object(
            customer_applier, "_get_router", return_value=fake_router,
        ):
            results = customer_applier.apply_segment_tags(
                segments=_segments(),
            )

        assert len(results) == 3
        # First raised, rest succeeded.
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]
        assert all(r["applied"] for r in results[1:])


# ─── enqueue_segment_tags_for_approval ─────────────────────────


class TestEnqueueSegmentTagsForApproval:

    def test_happy_path_parks_per_customer(self, isolated_queue):
        from engines.customer_segmentation.customer_applier import (
            enqueue_segment_tags_for_approval,
        )

        results = enqueue_segment_tags_for_approval(
            segments=_segments(),
        )
        assert len(results) == 3
        for r in results:
            assert r["pending_action_id"].startswith("appr_")
            assert r["error"] == "queued"
            action = isolated_queue.get(r["pending_action_id"])
            assert action is not None
            assert action.engine == "customer_segmentation"
            assert action.action_type == "apply_segment_tag"
            assert action.capability == "SHOPIFY_TAG_CUSTOMER"

    def test_no_segments_returns_empty(self, isolated_queue):
        from engines.customer_segmentation.customer_applier import (
            enqueue_segment_tags_for_approval,
        )

        assert enqueue_segment_tags_for_approval(segments=[]) == []
        assert isolated_queue.list_pending() == []

    def test_queue_unavailable_returns_structured_skip(
        self, isolated_queue,
    ):
        from engines.customer_segmentation.customer_applier import (
            enqueue_segment_tags_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            results = enqueue_segment_tags_for_approval(
                segments=_segments(),
            )
        assert len(results) == 3
        assert all(
            r["error"] == "approval_queue_unavailable" for r in results
        )


# ─── Flow integration ──────────────────────────────────────────


def _flow_input(
    *, apply_segment_tags=None, require_approval=None,
):
    data: dict = {
        "customers": [
            {
                "id": f"gid://shopify/Customer/{i}",
                "first_purchase": "2026-01-01",
                "last_purchase": "2026-04-01",
                "total_orders": 5 + i,
                "total_spent": 500.0 + 100 * i,
                "avg_order_value": 100.0,
                "days_since_last": 30 + 10 * i,
                "categories_bought": ["x"],
                "email_opens": 5,
                "cart_abandons": 0,
            }
            for i in range(1, 4)
        ],
    }
    if apply_segment_tags is not None:
        data["apply_segment_tags"] = apply_segment_tags
    if require_approval is not None:
        data["require_approval"] = require_approval
    return {"status": "ok", "data": data, "meta": {}, "error": None}


class TestFlowApprovalIntegration:

    def test_default_off_writes_nothing(self, isolated_queue):
        from engines.customer_segmentation.flow import (
            CustomerSegmentationEngine,
        )

        with patch(
            "engines.customer_segmentation.flow.apply_segment_tags",
        ) as mock_apply, patch(
            "engines.customer_segmentation.flow.enqueue_segment_tags_for_approval",
        ) as mock_enqueue:
            output = CustomerSegmentationEngine().run(_flow_input())

        mock_apply.assert_not_called()
        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["segment_apply_results"] == []

    def test_apply_true_routes_to_direct(self, isolated_queue):
        from engines.customer_segmentation.flow import (
            CustomerSegmentationEngine,
        )

        stub_results = [
            {
                "customer_id": "gid://shopify/Customer/1",
                "segment": "VIP Champions",
                "tag": "shopai-segment-vip-champions",
                "applied": True,
                "error": None,
            },
        ]
        with patch(
            "engines.customer_segmentation.flow.apply_segment_tags",
            return_value=stub_results,
        ) as mock_apply, patch(
            "engines.customer_segmentation.flow.enqueue_segment_tags_for_approval",
        ) as mock_enqueue:
            output = CustomerSegmentationEngine().run(
                _flow_input(
                    apply_segment_tags=True,
                    require_approval=False,
                ),
            )

        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            mock_apply.assert_called_once()
            assert output["data"]["segment_apply_results"] == stub_results

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.customer_segmentation.flow import (
            CustomerSegmentationEngine,
        )

        stub_results = [
            {
                "customer_id": "gid://shopify/Customer/1",
                "segment": "VIP Champions",
                "tag": "shopai-segment-vip-champions",
                "applied": False,
                "error": "queued",
                "pending_action_id": "appr_stub_1",
            },
        ]
        with patch(
            "engines.customer_segmentation.flow.apply_segment_tags",
        ) as mock_apply, patch(
            "engines.customer_segmentation.flow.enqueue_segment_tags_for_approval",
            return_value=stub_results,
        ) as mock_enqueue:
            output = CustomerSegmentationEngine().run(
                _flow_input(
                    apply_segment_tags=True,
                    require_approval=True,
                ),
            )

        mock_apply.assert_not_called()
        if output["status"] == "success":
            mock_enqueue.assert_called_once()
            assert output["data"]["segment_apply_results"] == stub_results
