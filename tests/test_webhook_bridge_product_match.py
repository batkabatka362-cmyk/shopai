"""Tests for the product-id matching path on WebhookFeedbackBridge.

The original bridge only matched on discount codes — engines like
tag_management, dynamic_pricing, product_lifecycle,
content_generation, image_optimization, catalog all mutate
products without minting codes, so their downstream outcomes were
invisible to LearningLoop.

Strategy 2 (this PR): if a webhook payload exposes
``line_items[].product_id`` and an EXECUTED action's
``params.product_id`` matches, attribute the order/refund to
that action. Looser than code matching but better than zero
signal.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


@pytest.fixture
def fresh_bridge(isolated_queue):
    from core.feedback import webhook_bridge as wb
    wb._INSTANCE = None
    bridge = wb.WebhookFeedbackBridge()
    bridge._learning_loop = MagicMock()
    yield bridge


def _seed_product_action(
    queue,
    *,
    engine: str,
    product_id: str,
    action_type: str = "apply_tags",
):
    a = queue.enqueue(
        engine=engine,
        action_type=action_type,
        capability="SHOPIFY_UPDATE_PRODUCT",
        params={"product_id": product_id, "tags": ["x"]},
        narrative="",
    )
    queue.approve(a.id, decided_by="op")
    queue.attach_result(
        a.id, success=True, result={"applied": True},
    )
    return a


# ─── _extract_product_ids ─────────────────────────────────────────


class TestExtractProductIds:

    @pytest.mark.parametrize("payload, expected", [
        # Standard order shape
        ({"line_items": [{"product_id": 12345}]}, ["12345"]),
        # Multiple line items
        (
            {"line_items": [
                {"product_id": "111"}, {"product_id": "222"},
            ]},
            ["111", "222"],
        ),
        # Refund — nested order
        (
            {"order": {"line_items": [{"product_id": "777"}]}},
            ["777"],
        ),
        # Refund line items
        (
            {"refund_line_items": [
                {"line_item": {"product_id": "888"}},
            ]},
            ["888"],
        ),
        # Mixed: top-level + nested order
        (
            {
                "line_items": [{"product_id": "111"}],
                "order": {"line_items": [{"product_id": "222"}]},
            },
            ["111", "222"],
        ),
        # Empty / missing
        ({}, []),
        ({"line_items": []}, []),
        ({"line_items": [{"product_id": ""}]}, []),
    ])
    def test_extracts_ids(self, payload, expected):
        from core.feedback.webhook_bridge import _extract_product_ids
        assert _extract_product_ids(payload) == expected


# ─── _normalise_product_id ────────────────────────────────────────


class TestNormaliseProductId:

    def test_bare_numeric_passes_through(self):
        from core.feedback.webhook_bridge import _normalise_product_id
        assert _normalise_product_id("12345") == "12345"
        assert _normalise_product_id(12345) == "12345"

    def test_gid_stripped(self):
        from core.feedback.webhook_bridge import _normalise_product_id
        assert _normalise_product_id(
            "gid://shopify/Product/12345",
        ) == "12345"

    def test_empty_or_none(self):
        from core.feedback.webhook_bridge import _normalise_product_id
        assert _normalise_product_id(None) == ""
        assert _normalise_product_id("") == ""
        assert _normalise_product_id("   ") == ""

    def test_match_across_forms(self):
        """An action minted with gid form should match a webhook
        that carries the bare numeric form, and vice versa."""
        from core.feedback.webhook_bridge import _normalise_product_id
        a = _normalise_product_id("gid://shopify/Product/12345")
        b = _normalise_product_id("12345")
        assert a == b


# ─── matched path: product_id ─────────────────────────────────────


class TestMatchByProductId:

    def test_order_matches_action_by_product_id(
        self, isolated_queue, fresh_bridge,
    ):
        a = _seed_product_action(
            isolated_queue, engine="tag_management", product_id="12345",
        )
        report = fresh_bridge.handle_event(
            "orders/create",
            {
                "id": "order_1",
                "line_items": [{"product_id": "12345", "price": "49.99"}],
            },
        )
        assert report["status"] == "matched"
        assert report["engine"] == "tag_management"
        assert report["matched_action_id"] == a.id
        # And LearningLoop fed the engine-specific category
        fresh_bridge._learning_loop.learn.assert_called_once()
        kw = fresh_bridge._learning_loop.learn.call_args.kwargs
        assert kw["category"] == "tag_management"

    def test_refund_matches_via_nested_order(
        self, isolated_queue, fresh_bridge,
    ):
        a = _seed_product_action(
            isolated_queue, engine="dynamic_pricing",
            product_id="9876", action_type="apply_price_change",
        )
        report = fresh_bridge.handle_event(
            "refunds/create",
            {
                "id": "refund_1",
                "order": {
                    "line_items": [{"product_id": "9876"}],
                },
            },
        )
        assert report["status"] == "matched"
        assert report["engine"] == "dynamic_pricing"
        assert report["polarity"] == "negative"

    def test_no_product_match_falls_to_orphan(
        self, isolated_queue, fresh_bridge,
    ):
        # No matching action seeded
        report = fresh_bridge.handle_event(
            "orders/create",
            {
                "id": "order_x",
                "line_items": [{"product_id": "unknown_99"}],
            },
        )
        assert report["status"] == "orphan"

    def test_code_match_takes_priority_over_product(
        self, isolated_queue, fresh_bridge,
    ):
        """When both strategies could match, the discount-code
        path wins — it's a stronger attribution signal."""
        # Action mints a code
        code_action = isolated_queue.enqueue(
            engine="cart_recovery", action_type="mint_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={"product_id": "12345"}, narrative="",
        )
        isolated_queue.approve(code_action.id, decided_by="op")
        isolated_queue.attach_result(
            code_action.id, success=True, result={"code": "RECOV-1"},
        )
        # Another action acts on the same product
        prod_action = isolated_queue.enqueue(
            engine="tag_management", action_type="apply_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params={"product_id": "12345", "tags": ["x"]},
            narrative="",
        )
        isolated_queue.approve(prod_action.id, decided_by="op")
        isolated_queue.attach_result(
            prod_action.id, success=True, result={"applied": True},
        )

        report = fresh_bridge.handle_event(
            "orders/create",
            {
                "id": "order_1",
                "discount_codes": [{"code": "RECOV-1"}],
                "line_items": [{"product_id": "12345"}],
            },
        )
        # cart_recovery wins via the code path
        assert report["engine"] == "cart_recovery"

    def test_gid_form_matches_numeric_payload(
        self, isolated_queue, fresh_bridge,
    ):
        """Engine pins gid form; webhook carries numeric. Should
        still match via _normalise_product_id."""
        _seed_product_action(
            isolated_queue, engine="content_generation",
            product_id="gid://shopify/Product/55555",
            action_type="apply_description",
        )
        report = fresh_bridge.handle_event(
            "orders/create",
            {"id": "x", "line_items": [{"product_id": "55555"}]},
        )
        assert report["status"] == "matched"
        assert report["engine"] == "content_generation"

    def test_backward_compat_match_to_action_alias(
        self, isolated_queue, fresh_bridge,
    ):
        """Tests written against the old _match_to_action name
        still work via the backward-compat alias."""
        # The alias is the code-matcher
        action = isolated_queue.enqueue(
            engine="loyalty", action_type="mint_code",
            capability="X", params={}, narrative="",
        )
        isolated_queue.approve(action.id)
        isolated_queue.attach_result(
            action.id, success=True, result={"code": "VIP-1"},
        )
        matched = fresh_bridge._match_to_action(["VIP-1"])
        assert matched is not None
        assert matched["engine"] == "loyalty"
