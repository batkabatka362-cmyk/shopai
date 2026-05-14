"""Tests for ``core.approval.executor.execute_action``.

Closes the loop the queue (PR #57) and the nine engine wireups
opened. Coverage:

  1. Registry — all nine action_types register on first call.
  2. ``execute_action`` lifecycle:
     * unknown id → None.
     * non-APPROVED state → None (idempotent: no mutation).
     * dispatcher success → status=EXECUTED, result populated.
     * dispatcher failure → status=FAILED, result.error populated.
     * dispatcher raise → caught, status=FAILED with
       ``dispatcher_raised:`` prefix.
  3. Per-dispatcher params validation — every dispatcher
     surfaces a structured ``error`` on missing required fields.
  4. Router-call dispatchers (7 of 9) forward the right friendly
     params shape; the two mint dispatchers reuse the shared
     ``mint_recovery_code`` helper.
  5. ``apply_description`` refuses replay when the parked body
     was truncated (a known limitation flagged at enqueue time).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core.approval.executor import (
    _DISPATCHERS,
    _ensure_dispatchers_loaded,
    execute_action,
    list_registered_action_types,
)
from core.approval.queue import ApprovalQueue, ApprovalStatus


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


@pytest.fixture
def loaded_dispatchers():
    """Force the dispatcher registry to load before the test runs."""
    _ensure_dispatchers_loaded()
    yield


# ─── registry ────────────────────────────────────────────────────


class TestRegistry:

    def test_all_action_types_register(self, loaded_dispatchers):
        """Every engine's enqueued ``action_type`` MUST have a
        matching dispatcher — otherwise approval succeeds but
        execution returns ``no executor registered``.

        End-to-end live verification 2026-05-15 against the
        ts0efe-ih dev store caught a 12-dispatcher gap (the 1C
        wirebacks PRs #75-#86 added enqueue helpers without
        wiring dispatchers). The fix added the missing
        dispatchers; this test asserts the full set so a future
        engine wireup can't silently regress.
        """
        types = set(list_registered_action_types())
        assert types == {
            # Original 9 (PR #69 capstone)
            "mint_strategy_code",
            "mint_loyalty_code",
            "apply_price_change",
            "apply_tags",
            "pay_commission",
            "archive_declining_product",
            "apply_description",
            "apply_seo_meta",
            "catalog_apply_tags",
            # 1C wireup-queue dispatchers (this PR)
            "mint_cart_recovery_code",     # PR #75
            "mint_browse_recovery_code",   # PR #76
            "apply_inventory_tags",        # PR #77
            "mint_wholesale_code",         # PR #78
            "tag_return_decision",         # PR #79
            "apply_shipping_strategy",     # PR #80
            "mint_campaign_code",          # PR #81
            "apply_strategic_price",       # PR #82
            "apply_segment_tag",           # PR #83
            "apply_bundle_product",        # PR #84
            "apply_landing_page",          # PR #85
            "apply_legal_document",        # PR #86
        }

    def test_dispatchers_are_callables(self, loaded_dispatchers):
        for action_type, fn in _DISPATCHERS.items():
            assert callable(fn), f"{action_type} dispatcher is not callable"


# ─── execute_action lifecycle ───────────────────────────────────


class TestExecuteActionLifecycle:

    def test_unknown_id_returns_none(self, isolated_queue, loaded_dispatchers):
        assert execute_action("appr_does_not_exist_123") is None

    def test_pending_action_is_noop(self, isolated_queue, loaded_dispatchers):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["x"]},
        )
        # Not approved yet — execute must refuse.
        assert execute_action(action.id) is None
        # State unchanged.
        current = isolated_queue.get(action.id)
        assert current is not None
        assert current.status == ApprovalStatus.PENDING

    def test_already_executed_action_is_noop(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["x"]},
        )
        isolated_queue.approve(action.id)
        with patch(
            "core.approval.dispatchers._router_call",
            return_value=(True, {"id": "p1"}),
        ):
            execute_action(action.id)
        # Second execute returns None (idempotent).
        assert execute_action(action.id) is None
        current = isolated_queue.get(action.id)
        assert current is not None
        assert current.status == ApprovalStatus.EXECUTED

    def test_dispatcher_success_flips_to_executed(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["x"]},
        )
        isolated_queue.approve(action.id, decided_by="op")

        with patch(
            "core.approval.dispatchers._router_call",
            return_value=(True, {"shopify_id": "gid://1"}),
        ):
            result = execute_action(action.id)

        assert result is not None
        assert result.status == ApprovalStatus.EXECUTED
        assert result.result == {"shopify_id": "gid://1"}

    def test_dispatcher_failure_flips_to_failed(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["x"]},
        )
        isolated_queue.approve(action.id)

        with patch(
            "core.approval.dispatchers._router_call",
            return_value=(False, {"error": "scope_missing"}),
        ):
            result = execute_action(action.id)

        assert result is not None
        assert result.status == ApprovalStatus.FAILED
        assert result.result == {"error": "scope_missing"}

    def test_dispatcher_raise_caught_and_marked_failed(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["x"]},
        )
        isolated_queue.approve(action.id)

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=RuntimeError("network"),
        ):
            result = execute_action(action.id)

        assert result is not None
        assert result.status == ApprovalStatus.FAILED
        assert "dispatcher_raised" in result.result["error"]
        assert "network" in result.result["error"]

    def test_unknown_action_type_marks_failed(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = isolated_queue.enqueue(
            engine="future_engine",
            action_type="do_something_new",
            capability="SHOPIFY_UNKNOWN",
            params={},
        )
        isolated_queue.approve(action.id)

        result = execute_action(action.id)
        assert result is not None
        assert result.status == ApprovalStatus.FAILED
        assert "no executor registered" in result.result["error"]


# ─── per-dispatcher param validation ────────────────────────────


class TestPerDispatcherValidation:

    @pytest.mark.parametrize("action_type, bad_params", [
        # ─ Original 9 ─
        ("apply_tags", {}),  # missing product_id + tags
        ("apply_tags", {"product_id": "p1", "merged_tags": []}),
        ("catalog_apply_tags", {"product_id": "", "tags": ["x"]}),
        ("catalog_apply_tags", {"product_id": "p1", "tags": []}),
        ("apply_seo_meta", {}),
        ("apply_seo_meta", {"product_id": "p1"}),  # no title or desc
        ("archive_declining_product", {}),
        ("apply_price_change", {"product_id": "p1", "new_price": 10}),  # no variant_ids
        ("apply_price_change", {"product_id": "p1", "new_price": "abc",
                                 "variant_ids": ["v1"]}),
        ("pay_commission", {}),
        ("mint_loyalty_code", {}),
        ("mint_loyalty_code", {"customer_id": "c1"}),  # no percentage
        ("mint_strategy_code", {}),
        ("apply_description", {}),
        # ─ 12 new dispatchers (1C wireup queue) ─
        ("mint_cart_recovery_code", {}),  # missing token + value
        ("mint_cart_recovery_code", {"token": "t"}),  # value missing
        ("mint_cart_recovery_code", {"token": "t", "value": "abc"}),  # bad value
        ("mint_browse_recovery_code", {}),
        ("mint_campaign_code", {}),
        ("mint_wholesale_code", {}),
        ("apply_inventory_tags", {}),  # no product_id + merged_tags
        ("apply_inventory_tags", {"product_id": "p1", "merged_tags": []}),
        ("apply_segment_tag", {}),  # no customer + tag
        ("apply_segment_tag", {"customer_id": "c1"}),  # no tag
        ("apply_bundle_product", {}),  # no adapter_params
        ("apply_bundle_product", {"adapter_params": {}}),  # empty
        ("apply_landing_page", {}),
        ("apply_legal_document", {}),
        ("apply_shipping_strategy", {}),
        ("apply_strategic_price", {}),
        ("apply_strategic_price", {"product_id": "p1", "new_price": 10}),
        ("apply_strategic_price", {"product_id": "p1", "new_price": "abc",
                                    "variant_ids": ["v1"]}),
        ("tag_return_decision", {}),
        ("tag_return_decision", {"order_id": "o1"}),  # no tags
        ("tag_return_decision", {"order_id": "o1", "tags": []}),
    ])
    def test_missing_params_surface_structured_error(
        self, action_type, bad_params, loaded_dispatchers,
    ):
        dispatcher = _DISPATCHERS[action_type]
        success, result = dispatcher(bad_params)
        assert success is False
        assert isinstance(result, dict)
        assert "error" in result and result["error"]


# ─── per-dispatcher happy-path forwarding ──────────────────────


class TestRouterForwardingDispatchers:

    def test_apply_tags_forwards_merged_list(self, loaded_dispatchers):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["cap"] = cap_name
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            success, _ = _DISPATCHERS["apply_tags"]({
                "product_id": "p1",
                "merged_tags": ["existing", "auto-tag"],
            })

        assert success is True
        assert captured["cap"] == "SHOPIFY_UPDATE_PRODUCT"
        assert captured["params"] == {
            "id": "p1", "tags": ["existing", "auto-tag"],
        }

    def test_catalog_uses_add_tags_capability(self, loaded_dispatchers):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["cap"] = cap_name
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            _DISPATCHERS["catalog_apply_tags"]({
                "product_id": "p1", "tags": ["a", "b"],
            })

        assert captured["cap"] == "SHOPIFY_ADD_TAGS"
        assert captured["params"] == {"id": "p1", "tags": ["a", "b"]}

    def test_seo_meta_emits_only_changed_fields(self, loaded_dispatchers):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            _DISPATCHERS["apply_seo_meta"]({
                "product_id": "p1",
                "proposed_title": "New Title",
                "proposed_description": None,
            })

        assert captured["params"] == {
            "id": "p1", "seo_title": "New Title",
        }
        assert "seo_description" not in captured["params"]

    def test_archive_uses_status_archived(self, loaded_dispatchers):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            _DISPATCHERS["archive_declining_product"]({
                "product_id": "p1", "status": "ARCHIVED",
            })

        assert captured["params"] == {"id": "p1", "status": "ARCHIVED"}

    def test_price_change_rebuilds_variants_payload(
        self, loaded_dispatchers,
    ):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            _DISPATCHERS["apply_price_change"]({
                "product_id": "p1",
                "new_price": 19.5,
                "variant_ids": ["v1", "v2"],
            })

        assert captured["params"]["product_id"] == "p1"
        assert captured["params"]["variants"] == [
            {"id": "v1", "price": "19.50"},
            {"id": "v2", "price": "19.50"},
        ]

    def test_pay_commission_forwards_params_directly(
        self, loaded_dispatchers,
    ):
        # Affiliate's enqueue already builds the gift-card friendly
        # form, so the dispatcher is a direct forward.
        captured: dict = {}

        def _capture(cap_name, params):
            captured["cap"] = cap_name
            captured["params"] = params
            return True, {}

        gift_params = {
            "initial_value": 50.0,
            "currency": "USD",
            "note": "Affiliate commission test",
            "recipient_email": "a@example.com",
        }
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            _DISPATCHERS["pay_commission"](gift_params)

        assert captured["cap"] == "SHOPIFY_CREATE_GIFT_CARD"
        # Direct copy — every field passed through.
        assert captured["params"] == gift_params


# ─── mint dispatchers ──────────────────────────────────────────


class TestMintDispatchers:

    def test_mint_loyalty_calls_shared_helper(self, loaded_dispatchers):
        captured: dict = {}

        def _stub_mint(**kwargs):
            captured.update(kwargs)
            return {"code": "LOYALTY-X", "discount_id": "1"}

        with patch(
            "engines._recovery_codes.mint_recovery_code",
            side_effect=_stub_mint,
        ):
            success, result = _DISPATCHERS["mint_loyalty_code"]({
                "customer_id": "gid://shopify/Customer/123",
                "percentage": 10.0,
                "ttl_days": 14,
            })

        assert success is True
        assert result["code"] == "LOYALTY-X"
        assert captured["code_prefix"] == "LOYALTY"
        assert captured["value"] == 10.0
        assert captured["value_kind"] == "percentage"
        assert captured["ttl_days"] == 14
        # Token derived from customer_id.
        assert captured["token"]

    def test_mint_strategy_uses_storewide_flags(self, loaded_dispatchers):
        captured: dict = {}

        def _stub_mint(**kwargs):
            captured.update(kwargs)
            return {"code": "PROMO-Y"}

        with patch(
            "engines._recovery_codes.mint_recovery_code",
            side_effect=_stub_mint,
        ):
            success, result = _DISPATCHERS["mint_strategy_code"]({
                "audience": "all",
                "percentage": 15.0,
                "ttl_days": 7,
            })

        assert success is True
        assert captured["code_prefix"] == "PROMO"
        # Storewide flags differ from loyalty.
        assert captured["usage_limit"] is None
        assert captured["applies_once_per_customer"] is False

    def test_mint_returns_none_marks_failed(self, loaded_dispatchers):
        with patch(
            "engines._recovery_codes.mint_recovery_code",
            return_value=None,
        ):
            success, result = _DISPATCHERS["mint_loyalty_code"]({
                "customer_id": "gid://shopify/Customer/1",
                "percentage": 10.0,
            })
        assert success is False
        assert result["error"] == "mint_returned_none"


# ─── apply_description body-truncation guard ───────────────────


class TestApplyDescriptionGuard:
    """Backwards-compat path — params with only body_preview.

    Pre-follow-up rows in production queues only carry
    ``body_preview`` (capped at 200 chars). The dispatcher must
    still replay them safely when the original body fit under
    the cap, and must refuse when the preview was a truncation
    of a larger body.
    """

    def test_legacy_truncated_body_refuses_replay(
        self, loaded_dispatchers,
    ):
        # body_length > len(body_preview) AND no full ``body``
        # field → legacy queue row, original was truncated.
        # Refuse rather than write partial.
        success, result = _DISPATCHERS["apply_description"]({
            "product_id": "p1",
            "body_length": 5000,
            "body_preview": "x" * 200,
        })
        assert success is False
        assert "body_truncated_in_queue" in result["error"]

    def test_legacy_short_body_replays_from_preview(
        self, loaded_dispatchers,
    ):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            # Legacy row, original body fit in preview.
            success, _ = _DISPATCHERS["apply_description"]({
                "product_id": "p1",
                "body_length": 50,
                "body_preview": "x" * 50,
            })

        assert success is True
        assert captured["params"]["id"] == "p1"
        assert captured["params"]["description_html"] == "x" * 50


class TestApplyDescriptionFullBody:
    """Post-follow-up path — params carry full ``body`` field.

    The enqueue path now stores the full body alongside the
    200-char ``body_preview`` (used by the merchant approval
    page summary). The dispatcher prefers the full body, so a
    long original description replays verbatim.
    """

    def test_full_body_replayed_verbatim(self, loaded_dispatchers):
        captured: dict = {}

        def _capture(cap_name, params):
            captured["params"] = params
            return True, {}

        long_body = "<p>" + ("widget " * 700) + "</p>"
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            success, _ = _DISPATCHERS["apply_description"]({
                "product_id": "p1",
                "body": long_body,
                "body_preview": long_body[:200],
                "body_length": len(long_body),
            })

        assert success is True
        assert captured["params"]["id"] == "p1"
        # Full body sent to Shopify, not the 200-char preview.
        assert captured["params"]["description_html"] == long_body
        assert len(captured["params"]["description_html"]) > 200

    def test_full_body_preferred_over_preview(self, loaded_dispatchers):
        # When both ``body`` and ``body_preview`` are present, the
        # dispatcher must pick ``body`` (the full one) so the
        # backwards-compat preview-replay branch never accidentally
        # fires on a post-follow-up row.
        captured: dict = {}

        def _capture(cap_name, params):
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            _DISPATCHERS["apply_description"]({
                "product_id": "p1",
                "body": "FULL BODY",
                "body_preview": "PREVIEW",
                "body_length": 9,
            })

        assert captured["params"]["description_html"] == "FULL BODY"

    def test_full_body_missing_product_id_skipped(
        self, loaded_dispatchers,
    ):
        success, result = _DISPATCHERS["apply_description"]({
            "body": "x" * 1000,
            "body_length": 1000,
        })
        assert success is False
        assert result["error"] == "missing_product_id"


# ─── 1C wireup-queue dispatchers (PRs #75-#86) ─────────────────


class TestOneCDispatchers:
    """Per-dispatcher happy-path forwarding for the 12
    dispatchers added after end-to-end live verification caught
    them missing. Each test mocks ``_router_call`` (for the
    route-through dispatchers) or ``mint_recovery_code`` (for
    the four mint variants) and asserts the dispatcher rebuilt
    the right friendly params shape from the parked queue
    entry."""

    def test_mint_cart_recovery_uses_RECOVER_prefix(
        self, loaded_dispatchers,
    ):
        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return {"code": "RECOVER-x", "discount_id": "1",
                    "ends_at": "2099", "applies_once": True}

        with patch(
            "engines._recovery_codes.mint_recovery_code",
            side_effect=_capture,
        ):
            success, result = _DISPATCHERS["mint_cart_recovery_code"]({
                "token": "cust_acme",
                "value": 10,
                "value_kind": "percentage",
                "ttl_days": 7,
                "code_prefix": "RECOVER",
            })
        assert success is True
        assert captured["code_prefix"] == "RECOVER"
        assert captured["usage_limit"] == 1
        assert captured["applies_once_per_customer"] is True

    def test_mint_browse_recovery_uses_BROWSE_prefix(
        self, loaded_dispatchers,
    ):
        captured = {}
        with patch(
            "engines._recovery_codes.mint_recovery_code",
            side_effect=lambda **kw: captured.update(kw) or {
                "code": "x", "discount_id": "1",
                "ends_at": "x", "applies_once": True,
            },
        ):
            success, _ = _DISPATCHERS["mint_browse_recovery_code"]({
                "token": "user_xyz",
                "value": 15,
                "code_prefix": "BROWSE",
            })
        assert success is True
        assert captured["code_prefix"] == "BROWSE"

    def test_mint_campaign_code_uses_multi_use_flags(
        self, loaded_dispatchers,
    ):
        captured = {}
        with patch(
            "engines._recovery_codes.mint_recovery_code",
            side_effect=lambda **kw: captured.update(kw) or {
                "code": "x", "discount_id": "1",
                "ends_at": "x", "applies_once": False,
            },
        ):
            success, _ = _DISPATCHERS["mint_campaign_code"]({
                "token": "spring",
                "value": 12,
                "code_prefix": "EMAIL",
                "ttl_days": 30,
            })
        assert success is True
        # Multi-use (no limit, reusable per customer)
        assert captured["usage_limit"] is None
        assert captured["applies_once_per_customer"] is False

    def test_mint_wholesale_uses_WHOLESALE_prefix(
        self, loaded_dispatchers,
    ):
        captured = {}
        with patch(
            "engines._recovery_codes.mint_recovery_code",
            side_effect=lambda **kw: captured.update(kw) or {
                "code": "x", "discount_id": "1",
                "ends_at": "x", "applies_once": True,
            },
        ):
            _DISPATCHERS["mint_wholesale_code"]({
                "token": "cust_acme",
                "value": 15,
                "code_prefix": "WHOLESALE",
                "ttl_days": 14,
            })
        assert captured["code_prefix"] == "WHOLESALE"
        # Wholesale TTL flows through from params
        assert captured["ttl_days"] == 14

    def test_apply_inventory_tags_forwards_merged_list(
        self, loaded_dispatchers,
    ):
        captured = {}

        def _capture(cap, params):
            captured["cap"] = cap
            captured["params"] = params
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_capture,
        ):
            _DISPATCHERS["apply_inventory_tags"]({
                "product_id": "gid://shopify/Product/1",
                "merged_tags": ["a", "shopai-stockout-imminent"],
                "state_tags": ["shopai-stockout-imminent"],
                "tags_added": 1,
            })
        assert captured["cap"] == "SHOPIFY_UPDATE_PRODUCT"
        assert captured["params"]["tags"] == (
            ["a", "shopai-stockout-imminent"]
        )

    def test_apply_segment_tag_forwards_tagsAdd_shape(
        self, loaded_dispatchers,
    ):
        captured = {}
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=lambda c, p: (captured.update(
                cap=c, params=p,
            ) or (True, {})),
        ):
            _DISPATCHERS["apply_segment_tag"]({
                "customer_id": "gid://shopify/Customer/1",
                "tag": "shopai-segment-vip-champions",
                "segment": "VIP Champions",
            })
        assert captured["cap"] == "SHOPIFY_TAG_CUSTOMER"
        assert captured["params"]["tags"] == [
            "shopai-segment-vip-champions",
        ]

    def test_apply_bundle_product_forwards_adapter_params(
        self, loaded_dispatchers,
    ):
        captured = {}
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=lambda c, p: (captured.update(
                cap=c, params=p,
            ) or (True, {})),
        ):
            _DISPATCHERS["apply_bundle_product"]({
                "adapter_params": {
                    "title": "Bundle: A + B",
                    "status": "DRAFT",
                    "product_type": "Bundle",
                    "tags": ["shopai-bundle"],
                    "body_html": "<p>test</p>",
                },
            })
        assert captured["cap"] == "SHOPIFY_CREATE_PRODUCT"
        assert captured["params"]["status"] == "DRAFT"

    def test_apply_landing_page_forwards_adapter_params(
        self, loaded_dispatchers,
    ):
        captured = {}
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=lambda c, p: (captured.update(
                cap=c, params=p,
            ) or (True, {})),
        ):
            _DISPATCHERS["apply_landing_page"]({
                "adapter_params": {
                    "title": "Test page",
                    "body_html": "<h1>x</h1>",
                    "is_published": False,
                },
            })
        assert captured["cap"] == "SHOPIFY_CREATE_PAGE"
        assert captured["params"]["is_published"] is False

    def test_apply_legal_document_forwards_adapter_params(
        self, loaded_dispatchers,
    ):
        captured = {}
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=lambda c, p: (captured.update(
                cap=c, params=p,
            ) or (True, {})),
        ):
            _DISPATCHERS["apply_legal_document"]({
                "adapter_params": {
                    "title": "Privacy Policy",
                    "body_html": "<article>x</article>",
                    "is_published": False,
                },
            })
        assert captured["cap"] == "SHOPIFY_CREATE_PAGE"

    def test_apply_shipping_strategy_forwards_adapter_params(
        self, loaded_dispatchers,
    ):
        captured = {}
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=lambda c, p: (captured.update(
                cap=c, params=p,
            ) or (True, {})),
        ):
            _DISPATCHERS["apply_shipping_strategy"]({
                "adapter_params": {
                    "title": "Free shipping over $75",
                    "starts_at": "2026-05-15T00:00:00Z",
                    "ends_at": "2026-06-15T00:00:00Z",
                    "minimum_subtotal": 75.0,
                },
            })
        assert captured["cap"] == (
            "SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING"
        )

    def test_apply_strategic_price_rebuilds_variant_payload(
        self, loaded_dispatchers,
    ):
        captured = {}
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=lambda c, p: (captured.update(
                cap=c, params=p,
            ) or (True, {})),
        ):
            _DISPATCHERS["apply_strategic_price"]({
                "product_id": "gid://shopify/Product/1",
                "new_price": 24.99,
                "variant_ids": [
                    "gid://shopify/ProductVariant/1",
                    "gid://shopify/ProductVariant/2",
                ],
            })
        assert captured["cap"] == "SHOPIFY_UPDATE_VARIANTS"
        # Money string rounded to 2 decimals
        assert captured["params"]["variants"][0]["price"] == "24.99"
        assert len(captured["params"]["variants"]) == 2

    def test_tag_return_decision_forwards_order_tag(
        self, loaded_dispatchers,
    ):
        captured = {}
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=lambda c, p: (captured.update(
                cap=c, params=p,
            ) or (True, {})),
        ):
            _DISPATCHERS["tag_return_decision"]({
                "order_id": "gid://shopify/Order/1",
                "tags": ["shopai-return-approved"],
            })
        assert captured["cap"] == "SHOPIFY_TAG_ORDER"
        assert captured["params"]["tags"] == [
            "shopai-return-approved",
        ]
