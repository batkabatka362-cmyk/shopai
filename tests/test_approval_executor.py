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
        types = set(list_registered_action_types())
        # W963-156: this is a SUPERSET check. The dispatch
        # catalogue grows whenever a new approval-class engine
        # ships (W963-143 propose_product_batch, W963-149
        # apply_brand_identity, etc.) -- a strict equality
        # made every new wireup require a test edit even when
        # the new types were correctly registered. The
        # surviving invariant we care about: the historical
        # set still registers.
        expected_subset = {
            "mint_strategy_code",
            "mint_loyalty_code",
            "mint_cart_recovery_code",
            "mint_browse_recovery_code",
            "mint_campaign_code",
            "mint_wholesale_code",
            "apply_price_change",
            "apply_strategic_price",
            "apply_tags",
            "apply_inventory_tags",
            "apply_segment_tag",
            "apply_landing_page",
            "apply_legal_document",
            "apply_shipping_strategy",
            "apply_bundle_product",
            "tag_return_decision",
            "pay_commission",
            "archive_declining_product",
            "apply_description",
            "apply_seo_meta",
            "catalog_apply_tags",
            "apply_fraud_tag",
        }
        missing = expected_subset - types
        assert not missing, (
            f"historical action types unregistered: "
            f"{sorted(missing)}"
        )

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


# ─── generic per-customer/per-segment mint dispatchers ──────────


class TestGenericMintDispatchers:
    """The 4 mint_*_code dispatchers (cart_recovery, browse_recovery,
    email_marketing, wholesale_b2b) share a generic body — closes
    Pattern K gaps surfaced by the dispatcher coverage audit.
    """

    _CASES = [
        ("mint_cart_recovery_code", 7),
        ("mint_browse_recovery_code", 7),
        ("mint_campaign_code", 14),
        ("mint_wholesale_code", 30),
    ]

    def _good_params(self, code_prefix="RECOVER"):
        return {
            "token": "CUSTOMER123",
            "value": 10.0,
            "value_kind": "percentage",
            "code_prefix": code_prefix,
        }

    @pytest.mark.parametrize("action_type,default_ttl", _CASES)
    def test_happy_path_calls_mint_with_params(
        self, action_type, default_ttl, loaded_dispatchers,
    ):
        captured: dict = {}

        def _stub(**kwargs):
            captured.update(kwargs)
            return {"code": "X-1", "discount_id": "d_1"}

        with patch(
            "engines._recovery_codes.mint_recovery_code",
            side_effect=_stub,
        ):
            success, result = _DISPATCHERS[action_type](
                self._good_params(),
            )

        assert success is True
        assert result["code"] == "X-1"
        # Wire-format unchanged from enqueue → dispatch.
        assert captured["token"] == "CUSTOMER123"
        assert captured["value"] == 10.0
        assert captured["value_kind"] == "percentage"
        assert captured["code_prefix"] == "RECOVER"

    @pytest.mark.parametrize("action_type,default_ttl", _CASES)
    def test_uses_engine_default_ttl_when_omitted(
        self, action_type, default_ttl, loaded_dispatchers,
    ):
        """Each engine has its own sensible default TTL (cart 7d,
        campaign 14d, wholesale 30d). When the engine omits
        ttl_days, the dispatcher fills in that default rather than
        a global constant."""
        captured: dict = {}

        def _stub(**kwargs):
            captured.update(kwargs)
            return {"code": "X", "discount_id": "d"}

        params = self._good_params()
        params.pop("ttl_days", None)  # explicitly absent

        with patch(
            "engines._recovery_codes.mint_recovery_code",
            side_effect=_stub,
        ):
            _DISPATCHERS[action_type](params)

        assert captured["ttl_days"] == default_ttl

    @pytest.mark.parametrize("action_type,_", _CASES)
    def test_explicit_ttl_overrides_default(
        self, action_type, _, loaded_dispatchers,
    ):
        captured: dict = {}

        def _stub(**kwargs):
            captured.update(kwargs)
            return {"code": "X", "discount_id": "d"}

        params = self._good_params()
        params["ttl_days"] = 3

        with patch(
            "engines._recovery_codes.mint_recovery_code",
            side_effect=_stub,
        ):
            _DISPATCHERS[action_type](params)

        assert captured["ttl_days"] == 3

    @pytest.mark.parametrize("action_type,_", _CASES)
    def test_missing_token_fails(self, action_type, _, loaded_dispatchers):
        params = self._good_params()
        params["token"] = ""
        success, result = _DISPATCHERS[action_type](params)
        assert success is False
        assert "missing_or_invalid_mint_params" in result["error"]

    @pytest.mark.parametrize("action_type,_", _CASES)
    def test_invalid_value_kind_fails(
        self, action_type, _, loaded_dispatchers,
    ):
        params = self._good_params()
        params["value_kind"] = "bogus"
        success, result = _DISPATCHERS[action_type](params)
        assert success is False

    @pytest.mark.parametrize("action_type,_", _CASES)
    def test_non_numeric_ttl_fails(
        self, action_type, _, loaded_dispatchers,
    ):
        params = self._good_params()
        params["ttl_days"] = "soon"
        success, result = _DISPATCHERS[action_type](params)
        assert success is False
        assert result["error"] == "invalid_ttl_days"

    @pytest.mark.parametrize("action_type,_", _CASES)
    def test_mint_returns_none_marks_failed(
        self, action_type, _, loaded_dispatchers,
    ):
        with patch(
            "engines._recovery_codes.mint_recovery_code",
            return_value=None,
        ):
            success, result = _DISPATCHERS[action_type](
                self._good_params(),
            )
        assert success is False
        assert result["error"] == "mint_returned_none"

    @pytest.mark.parametrize("action_type,_", _CASES)
    def test_mint_raises_caught(
        self, action_type, _, loaded_dispatchers,
    ):
        with patch(
            "engines._recovery_codes.mint_recovery_code",
            side_effect=RuntimeError("network down"),
        ):
            success, result = _DISPATCHERS[action_type](
                self._good_params(),
            )
        assert success is False
        assert "mint_raised" in result["error"]
        assert "network down" in result["error"]


# ─── apply_segment_tag (SHOPIFY_TAG_CUSTOMER) ──────────────────


class TestApplySegmentTagDispatcher:
    """customer_segmentation enqueues {customer_id, tag, segment};
    dispatcher translates to {id, tags: [tag]} for SHOPIFY_TAG_CUSTOMER."""

    def test_happy_path_forwards_translated_payload(self, loaded_dispatchers):
        captured: dict = {}

        def _stub(capability, payload):
            captured["capability"] = capability
            captured["payload"] = payload
            return True, {"id": "cust_99"}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_stub,
        ):
            success, result = _DISPATCHERS["apply_segment_tag"]({
                "customer_id": "gid://shopify/Customer/99",
                "tag": "vip-2026",
                "segment": "loyalty-tier-1",
            })

        assert success is True
        assert captured["capability"] == "SHOPIFY_TAG_CUSTOMER"
        # Wire-format: id (not customer_id) + tags as a list
        assert captured["payload"] == {
            "id": "gid://shopify/Customer/99",
            "tags": ["vip-2026"],
        }

    def test_missing_customer_id_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_segment_tag"]({
            "customer_id": "",
            "tag": "vip",
        })
        assert success is False
        assert "missing_customer_id_or_tag" in result["error"]

    def test_missing_tag_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_segment_tag"]({
            "customer_id": "c1",
            "tag": "",
        })
        assert success is False
        assert "missing_customer_id_or_tag" in result["error"]

    def test_segment_field_ignored_at_dispatch(self, loaded_dispatchers):
        """The `segment` field is operator-context only — it
        shouldn't bleed into the Shopify mutation."""
        captured: dict = {}

        def _stub(capability, payload):
            captured["payload"] = payload
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_stub,
        ):
            _DISPATCHERS["apply_segment_tag"]({
                "customer_id": "c1",
                "tag": "vip",
                "segment": "should-not-appear",
            })

        assert "segment" not in captured["payload"]


# ─── apply_landing_page (SHOPIFY_CREATE_PAGE) ──────────────────


class TestApplyLandingPageDispatcher:
    """landing_page pre-builds the wire format at enqueue time
    under `adapter_params`; the dispatcher forwards verbatim."""

    def test_happy_path_forwards_adapter_params(self, loaded_dispatchers):
        captured: dict = {}

        def _stub(capability, payload):
            captured["capability"] = capability
            captured["payload"] = payload
            return True, {"id": "page_42", "handle": "summer-sale"}

        adapter_params = {
            "title": "Summer Sale 2026",
            "handle": "summer-sale-2026",
            "body_html": "<p>Up to 40% off</p>",
            "template_suffix": "landing",
        }

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_stub,
        ):
            success, result = _DISPATCHERS["apply_landing_page"]({
                "title": "Summer Sale 2026",
                "handle": "summer-sale-2026",
                "best_variant": "v2",
                "estimated_conversion": 0.18,
                "adapter_params": adapter_params,
            })

        assert success is True
        assert captured["capability"] == "SHOPIFY_CREATE_PAGE"
        # Wire-format: forwarded verbatim (engine pre-built it)
        assert captured["payload"] == adapter_params

    def test_missing_adapter_params_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_landing_page"]({
            "title": "X", "handle": "x",
        })
        assert success is False
        assert "missing_adapter_params" in result["error"]

    def test_empty_adapter_params_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_landing_page"]({
            "adapter_params": {},
        })
        assert success is False
        assert "missing_adapter_params" in result["error"]

    def test_non_dict_adapter_params_fails(self, loaded_dispatchers):
        """Defensive: if a malformed row somehow lands with
        adapter_params as a string or list, fail-fast rather
        than passing it to the router."""
        success, result = _DISPATCHERS["apply_landing_page"]({
            "adapter_params": "not a dict",
        })
        assert success is False


# ─── apply_inventory_tags (SHOPIFY_UPDATE_PRODUCT.tags) ────────


class TestApplyInventoryTagsDispatcher:
    """inventory enqueues {product_id, merged_tags, state_tags,
    tags_added}; only id + tags reach Shopify. merged_tags is
    already deduped on the engine side."""

    def test_happy_path_forwards_merged_tags(self, loaded_dispatchers):
        captured: dict = {}

        def _stub(capability, payload):
            captured["capability"] = capability
            captured["payload"] = payload
            return True, {"id": "p1"}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_stub,
        ):
            success, _ = _DISPATCHERS["apply_inventory_tags"]({
                "product_id": "p1",
                "merged_tags": ["low-stock", "needs-reorder"],
                "state_tags": ["needs-reorder"],
                "tags_added": 1,
            })

        assert success is True
        assert captured["capability"] == "SHOPIFY_UPDATE_PRODUCT"
        # state_tags / tags_added are operator-context, NOT sent
        assert captured["payload"] == {
            "id": "p1",
            "tags": ["low-stock", "needs-reorder"],
        }

    def test_missing_product_id_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_inventory_tags"]({
            "product_id": "",
            "merged_tags": ["x"],
        })
        assert success is False
        assert "missing_product_id_or_tags" in result["error"]

    def test_empty_merged_tags_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_inventory_tags"]({
            "product_id": "p1",
            "merged_tags": [],
        })
        assert success is False


# ─── apply_legal_document (SHOPIFY_CREATE_PAGE pre-built) ──────


class TestApplyLegalDocumentDispatcher:
    """Same pattern as apply_landing_page — adapter_params is
    pre-built at proposal time and forwarded verbatim."""

    def test_happy_path_forwards_adapter_params(self, loaded_dispatchers):
        captured: dict = {}

        def _stub(capability, payload):
            captured["capability"] = capability
            captured["payload"] = payload
            return True, {"id": "page_77"}

        adapter_params = {
            "title": "Privacy Policy",
            "handle": "privacy-policy",
            "body_html": "<p>Effective 2026-05-15</p>",
        }

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_stub,
        ):
            success, _ = _DISPATCHERS["apply_legal_document"]({
                "type": "privacy",
                "title": "Privacy Policy",
                "handle": "privacy-policy",
                "adapter_params": adapter_params,
            })

        assert success is True
        assert captured["capability"] == "SHOPIFY_CREATE_PAGE"
        assert captured["payload"] == adapter_params

    def test_missing_adapter_params_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_legal_document"]({
            "type": "tos",
        })
        assert success is False
        assert "missing_adapter_params" in result["error"]


# ─── apply_shipping_strategy (CREATE_AUTOMATIC_FREE_SHIPPING) ──


class TestApplyShippingStrategyDispatcher:

    def test_happy_path_forwards_adapter_params(self, loaded_dispatchers):
        captured: dict = {}

        def _stub(capability, payload):
            captured["capability"] = capability
            captured["payload"] = payload
            return True, {"id": "disc_99"}

        adapter_params = {
            "title": "Free shipping over $50",
            "starts_at": "2026-05-15T00:00:00Z",
            "ends_at": "2026-06-15T00:00:00Z",
            "minimum_subtotal": 50.0,
        }

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_stub,
        ):
            success, _ = _DISPATCHERS["apply_shipping_strategy"]({
                "strategy_id": "free_shipping_threshold",
                "threshold": 50.0,
                "title": "Free shipping over $50",
                "starts_at": "2026-05-15T00:00:00Z",
                "ends_at": "2026-06-15T00:00:00Z",
                "ttl_days": 31,
                "estimated_savings_monthly": 1200.0,
                "adapter_params": adapter_params,
            })

        assert success is True
        assert (
            captured["capability"]
            == "SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING"
        )
        assert captured["payload"] == adapter_params

    def test_missing_adapter_params_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_shipping_strategy"]({
            "strategy_id": "x",
        })
        assert success is False
        assert "missing_adapter_params" in result["error"]


# ─── apply_strategic_price (SHOPIFY_UPDATE_VARIANTS) ───────────


class TestApplyStrategicPriceDispatcher:
    """pricing enqueues {product_id, new_price, variant_ids, ...};
    dispatcher re-assembles the bulk variant payload as
    {product_id, variants: [{id, price}, ...]}."""

    def test_happy_path_builds_variants_payload(self, loaded_dispatchers):
        captured: dict = {}

        def _stub(capability, payload):
            captured["capability"] = capability
            captured["payload"] = payload
            return True, {"product_id": "p1"}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_stub,
        ):
            success, _ = _DISPATCHERS["apply_strategic_price"]({
                "product_id": "gid://shopify/Product/1",
                "new_price": 19.99,
                "strategy": "demand_uplift",
                "confidence": 0.91,
                "variant_ids": [
                    "gid://shopify/ProductVariant/11",
                    "gid://shopify/ProductVariant/12",
                ],
                "old_price_examples": [22.0, 21.5],
            })

        assert success is True
        assert captured["capability"] == "SHOPIFY_UPDATE_VARIANTS"
        # Price formatted to 2dp, same as live applier
        assert captured["payload"] == {
            "product_id": "gid://shopify/Product/1",
            "variants": [
                {"id": "gid://shopify/ProductVariant/11", "price": "19.99"},
                {"id": "gid://shopify/ProductVariant/12", "price": "19.99"},
            ],
        }

    def test_price_formatted_to_two_decimals(self, loaded_dispatchers):
        captured: dict = {}

        def _stub(capability, payload):
            captured["payload"] = payload
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_stub,
        ):
            _DISPATCHERS["apply_strategic_price"]({
                "product_id": "p1",
                "new_price": 10,  # bare int
                "variant_ids": ["v1"],
            })
        assert captured["payload"]["variants"][0]["price"] == "10.00"

    def test_missing_product_id_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_strategic_price"]({
            "product_id": "",
            "new_price": 5,
            "variant_ids": ["v1"],
        })
        assert success is False
        assert "missing_product_id_or_variants" in result["error"]

    def test_empty_variants_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_strategic_price"]({
            "product_id": "p1",
            "new_price": 5,
            "variant_ids": [],
        })
        assert success is False
        assert "missing_product_id_or_variants" in result["error"]

    def test_non_numeric_price_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_strategic_price"]({
            "product_id": "p1",
            "new_price": "many dollars",
            "variant_ids": ["v1"],
        })
        assert success is False
        assert "invalid_new_price" in result["error"]

    def test_non_positive_price_fails(self, loaded_dispatchers):
        """Defensive: zero / negative prices shouldn't reach the
        adapter — they're almost certainly a calculation bug
        upstream, not a real desired write."""
        success, result = _DISPATCHERS["apply_strategic_price"]({
            "product_id": "p1",
            "new_price": -5.0,
            "variant_ids": ["v1"],
        })
        assert success is False
        assert "non_positive_price" in result["error"]

    def test_falsy_variant_ids_skipped(self, loaded_dispatchers):
        """Empty-string / None variant ids filtered out before
        building the payload — keeps the wire format clean."""
        captured: dict = {}

        def _stub(capability, payload):
            captured["payload"] = payload
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_stub,
        ):
            success, _ = _DISPATCHERS["apply_strategic_price"]({
                "product_id": "p1",
                "new_price": 9.99,
                "variant_ids": ["v1", "", None, "v2"],
            })
        assert success is True
        assert len(captured["payload"]["variants"]) == 2


# ─── tag_return_decision (SHOPIFY_TAG_ORDER) ───────────────────


class TestTagReturnDecisionDispatcher:
    """returns_management enqueues {return_id, order_id, tags,
    refund_amount, decision_status, rejection_reason}; only
    order_id + tags reach Shopify."""

    def test_happy_path_translates_to_order_id(self, loaded_dispatchers):
        captured: dict = {}

        def _stub(capability, payload):
            captured["capability"] = capability
            captured["payload"] = payload
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_stub,
        ):
            success, _ = _DISPATCHERS["tag_return_decision"]({
                "return_id": "ret_1",
                "order_id": "gid://shopify/Order/123",
                "tags": ["return-approved", "refund-issued"],
                "refund_amount": 50.0,
                "decision_status": "approved",
                "rejection_reason": None,
            })

        assert success is True
        assert captured["capability"] == "SHOPIFY_TAG_ORDER"
        # Translation: order_id → id; only tags forwarded
        assert captured["payload"] == {
            "id": "gid://shopify/Order/123",
            "tags": ["return-approved", "refund-issued"],
        }

    def test_missing_order_id_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["tag_return_decision"]({
            "order_id": "",
            "tags": ["x"],
        })
        assert success is False
        assert "missing_order_id_or_tags" in result["error"]

    def test_empty_tags_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["tag_return_decision"]({
            "order_id": "o1",
            "tags": [],
        })
        assert success is False


# ─── apply_bundle_product (SHOPIFY_CREATE_PRODUCT) ─────────────


class TestApplyBundleProductDispatcher:
    """Closes the last Pattern K gap. Bundle engine pre-builds
    the full Shopify CREATE_PRODUCT payload (title, variants from
    components, bundle pricing) under adapter_params at proposal
    time; dispatcher forwards verbatim. Operator-context fields
    (components / bundle_price / savings_pct / estimated_uplift)
    stay queue-side and don't reach Shopify."""

    def test_happy_path_forwards_adapter_params(self, loaded_dispatchers):
        captured: dict = {}

        def _stub(capability, payload):
            captured["capability"] = capability
            captured["payload"] = payload
            return True, {"id": "gid://shopify/Product/100"}

        adapter_params = {
            "title": "Camera Starter Bundle",
            "variants": [
                {"sku": "BUNDLE-CAM-01", "price": "199.99"},
            ],
            "vendor": "ShopAI",
            "product_type": "Bundle",
        }

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_stub,
        ):
            success, _ = _DISPATCHERS["apply_bundle_product"]({
                "title": "Camera Starter Bundle",
                "components": ["sku-A", "sku-B", "sku-C"],
                "bundle_price": 199.99,
                "savings_pct": 0.15,
                "estimated_uplift": 320.0,
                "adapter_params": adapter_params,
            })

        assert success is True
        assert captured["capability"] == "SHOPIFY_CREATE_PRODUCT"
        # Verbatim forward — engine authored the wire format
        assert captured["payload"] == adapter_params

    def test_operator_context_not_forwarded(self, loaded_dispatchers):
        """components / bundle_price / savings_pct / estimated_uplift
        are queue-side review fields, NOT part of the Shopify
        mutation. The dispatcher must not leak them."""
        captured: dict = {}

        def _stub(capability, payload):
            captured["payload"] = payload
            return True, {}

        adapter_params = {"title": "X", "variants": []}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=_stub,
        ):
            _DISPATCHERS["apply_bundle_product"]({
                "title": "X",
                "components": ["a", "b"],
                "bundle_price": 99.0,
                "savings_pct": 0.1,
                "estimated_uplift": 50.0,
                "adapter_params": adapter_params,
            })

        # Only the engine-authored fields are forwarded
        assert captured["payload"] == adapter_params
        assert "components" not in captured["payload"]
        assert "bundle_price" not in captured["payload"]

    def test_missing_adapter_params_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_bundle_product"]({
            "title": "X",
        })
        assert success is False
        assert "missing_adapter_params" in result["error"]

    def test_empty_adapter_params_fails(self, loaded_dispatchers):
        success, result = _DISPATCHERS["apply_bundle_product"]({
            "adapter_params": {},
        })
        assert success is False
        assert "missing_adapter_params" in result["error"]


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


# ─── Executor records to Phase 8 (queue-path coverage) ──────────


class TestExecutorRecordsToPhase8:
    """The queue-path execution (engine enqueue -> operator
    approve -> executor dispatch) used to skip
    record_writeback entirely -- only the DIRECT-execute path
    in each applier called it. This class is the regression
    guard for the executor's recorder fan-out."""

    def _approved_action(self, queue):
        """Helper: enqueue + approve a tag_management action so
        it's ready to execute."""
        action = queue.enqueue(
            engine="tag_management",
            action_type="apply_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params={
                "product_id": "gid://shopify/Product/1",
                "merged_tags": ["promoted", "summer"],
            },
            narrative="Tag with promotion labels",
            confidence=0.9,
        )
        queue.approve(action.id, decided_by="test", reason="")
        return action

    def test_successful_execution_calls_recorder(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = self._approved_action(isolated_queue)
        # Stub the dispatcher to return success without actually
        # hitting Shopify. Patch the live registry entry.
        original = _DISPATCHERS["apply_tags"]
        try:
            _DISPATCHERS["apply_tags"] = (
                lambda params: (True, {"id": params["product_id"]})
            )
            with patch(
                "engines._writeback_recorder.record_writeback",
            ) as recorder:
                execute_action(action.id)
        finally:
            _DISPATCHERS["apply_tags"] = original
        recorder.assert_called_once()
        kwargs = recorder.call_args.kwargs
        assert kwargs["engine"] == "tag_management"
        assert kwargs["action_type"] == "apply_tags"
        assert kwargs["capability"] == "SHOPIFY_UPDATE_PRODUCT"
        assert kwargs["success"] is True
        assert kwargs["error"] is None

    def test_failed_execution_records_with_error(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = self._approved_action(isolated_queue)
        original = _DISPATCHERS["apply_tags"]
        try:
            _DISPATCHERS["apply_tags"] = (
                lambda params: (False, {"error": "shopify_5xx"})
            )
            with patch(
                "engines._writeback_recorder.record_writeback",
            ) as recorder:
                execute_action(action.id)
        finally:
            _DISPATCHERS["apply_tags"] = original
        recorder.assert_called_once()
        kwargs = recorder.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["error"] == "shopify_5xx"

    def test_dispatcher_exception_records_with_error(
        self, isolated_queue, loaded_dispatchers,
    ):
        action = self._approved_action(isolated_queue)
        original = _DISPATCHERS["apply_tags"]

        def _boom(params):
            raise RuntimeError("network down")
        try:
            _DISPATCHERS["apply_tags"] = _boom
            with patch(
                "engines._writeback_recorder.record_writeback",
            ) as recorder:
                execute_action(action.id)
        finally:
            _DISPATCHERS["apply_tags"] = original
        recorder.assert_called_once()
        kwargs = recorder.call_args.kwargs
        assert kwargs["success"] is False
        assert "dispatcher_raised" in kwargs["error"]

    def test_missing_dispatcher_records_with_error(
        self, isolated_queue,
    ):
        """An action with no registered dispatcher is a known
        failure mode (catches PR-#40-class capability-name
        bugs). The executor's recorder still fires so Phase 8
        learns 'this action_type has no dispatcher.'"""
        action = isolated_queue.enqueue(
            engine="x",
            action_type="totally_made_up",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params={},
            narrative="",
            confidence=0.5,
        )
        isolated_queue.approve(action.id, decided_by="test", reason="")
        with patch(
            "engines._writeback_recorder.record_writeback",
        ) as recorder:
            execute_action(action.id)
        recorder.assert_called_once()
        kwargs = recorder.call_args.kwargs
        assert kwargs["success"] is False
        assert "no executor registered" in kwargs["error"]

    def test_recorder_failure_doesnt_break_dispatch(
        self, isolated_queue, loaded_dispatchers,
    ):
        """The recorder is best-effort. If it raises, the queue
        entry must STILL flip to EXECUTED (the Shopify mutation
        already happened)."""
        action = self._approved_action(isolated_queue)
        original = _DISPATCHERS["apply_tags"]
        try:
            _DISPATCHERS["apply_tags"] = (
                lambda params: (True, {"ok": True})
            )
            with patch(
                "engines._writeback_recorder.record_writeback",
                side_effect=RuntimeError("recorder broken"),
            ):
                result = execute_action(action.id)
        finally:
            _DISPATCHERS["apply_tags"] = original
        # The dispatch outcome surfaces normally
        assert result is not None
        assert result.status == ApprovalStatus.EXECUTED

    def test_recorder_receives_action_params_copy(
        self, isolated_queue, loaded_dispatchers,
    ):
        """The recorder gets a COPY of action.params (not a
        reference) so a downstream consumer can't mutate the
        queue's stored params."""
        action = self._approved_action(isolated_queue)
        original = _DISPATCHERS["apply_tags"]
        try:
            _DISPATCHERS["apply_tags"] = (
                lambda params: (True, {})
            )
            with patch(
                "engines._writeback_recorder.record_writeback",
            ) as recorder:
                execute_action(action.id)
        finally:
            _DISPATCHERS["apply_tags"] = original
        kwargs = recorder.call_args.kwargs
        # Mutate the recorder's params arg; the queue's stored
        # params must be unchanged.
        kwargs["params"]["product_id"] = "MUTATED"
        re_read = isolated_queue.get(action.id)
        assert re_read.params["product_id"] == "gid://shopify/Product/1"
