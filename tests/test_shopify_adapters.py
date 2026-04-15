"""Tests for Phase 2 Shopify Native adapters.

Real GraphQL calls are forbidden — every test patches the
adapter's ``_gql`` method (or where appropriate, the underlying
``ShopifyGraphQL.query``) to return canned responses.

Coverage:

  * Each adapter's metadata (name, capabilities, category, priority)
  * Configuration gating (env vars + explicit constructor args)
  * Happy-path GraphQL → AdapterResult success for every operation
  * Vendor schema translation (GID normalisation, risk score
    map, fulfillmentOrders → fulfillmentCreate two-step dance,
    metafields camelCase translation)
  * userErrors → AdapterValidationError mapping
  * GraphQL "errors" envelope → AdapterError mapping
  * Bootstrap registers all 4 adapters
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterResult,
    AdapterValidationError,
    Capability,
    get_registry,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)
from core.adapters.errors import AdapterAuthError, AdapterError


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Wipe every singleton + Shopify env var between tests."""
    for var in ("SHOPAI_SHOPIFY_URL", "SHOPAI_SHOPIFY_KEY"):
        monkeypatch.delenv(var, raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


# ── ShopifyBaseAdapter ───────────────────────────────────────


class TestShopifyBaseAdapter:
    def test_unconfigured_without_credentials(self):
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        a = ShopifyRiskAdapter()
        assert not a.is_configured()

    def test_configured_via_constructor(self):
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        a = ShopifyRiskAdapter(
            shop_url="store.myshopify.com",
            access_token="shpat_test",
        )
        assert a.is_configured()

    def test_configured_via_env(self, monkeypatch):
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "store.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_test")
        reset_config()
        a = ShopifyRiskAdapter()
        assert a.is_configured()

    def test_constructor_overrides_env(self, monkeypatch):
        """Explicit credentials win over env vars (so multi-store
        setups can each have their own adapter instance)."""
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "env.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "env_token")
        reset_config()
        a = ShopifyRiskAdapter(
            shop_url="explicit.myshopify.com",
            access_token="explicit_token",
        )
        shop, token = a._resolve_credentials()
        assert shop == "explicit.myshopify.com"
        assert token == "explicit_token"

    def test_category_is_shopify_native(self):
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        from core.adapters.shopify.inventory import ShopifyInventoryAdapter
        from core.adapters.shopify.fulfillment import ShopifyFulfillmentAdapter
        from core.adapters.shopify.metafield import ShopifyMetafieldAdapter
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        from core.adapters.shopify.customer_mutate import ShopifyCustomerMutateAdapter
        from core.adapters.shopify.discount import ShopifyDiscountAdapter
        from core.adapters.shopify.discount_read import ShopifyDiscountReadAdapter
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        from core.adapters.shopify.segment import ShopifySegmentAdapter
        for cls in (
            ShopifyRiskAdapter,
            ShopifyInventoryAdapter,
            ShopifyFulfillmentAdapter,
            ShopifyMetafieldAdapter,
            ShopifyOrdersAdapter,
            ShopifyCustomersAdapter,
            ShopifyCustomerMutateAdapter,
            ShopifyDiscountAdapter,
            ShopifyDiscountReadAdapter,
            ShopifyRefundAdapter,
            ShopifySegmentAdapter,
        ):
            assert cls().category == AdapterCategory.SHOPIFY_NATIVE
            assert cls().priority == 100  # Native always preferred

    def test_user_errors_raise_validation_error(self):
        """Shopify mutations return userErrors next to the
        success payload — the base must raise
        AdapterValidationError so the router does NOT fall back."""
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        a = ShopifyRiskAdapter(shop_url="x", access_token="y")
        with pytest.raises(AdapterValidationError) as exc:
            a._check_user_errors(
                {
                    "fulfillmentCreate": {
                        "userErrors": [
                            {"field": ["fulfillment", "lineItems"],
                             "message": "Line items missing"}
                        ],
                    },
                },
                "fulfillmentCreate",
            )
        assert "Line items missing" in str(exc.value)

    def test_gql_envelope_errors_become_adapter_error(self, monkeypatch):
        """When Shopify returns HTTP 200 but with ``errors`` in
        the envelope, the base must raise ``AdapterError``."""
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        a = ShopifyRiskAdapter(shop_url="x", access_token="y")

        # Patch the lazily-built client method
        def fake_make_client():
            class _FakeClient:
                def query(self, q, v):
                    return {
                        "data": None,
                        "errors": [
                            {"message": "Field 'badField' doesn't exist"}
                        ],
                    }
            return _FakeClient()

        monkeypatch.setattr(a, "_make_client", fake_make_client)
        with pytest.raises(AdapterError) as exc:
            a._gql("query { x }")
        assert "GraphQL errors" in str(exc.value)


# ── ShopifyRiskAdapter ───────────────────────────────────────


class TestShopifyRiskAdapter:
    def test_metadata(self):
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        a = ShopifyRiskAdapter()
        assert a.name == "shopify_risk"
        assert Capability.SHOPIFY_ASSESS_RISK in a.capabilities
        assert a.cost_per_call == 0.0

    def test_to_gid_accepts_numeric(self):
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        assert ShopifyRiskAdapter._to_gid("12345") == "gid://shopify/Order/12345"
        assert ShopifyRiskAdapter._to_gid(12345) == "gid://shopify/Order/12345"

    def test_to_gid_passes_through_existing_gid(self):
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        gid = "gid://shopify/Order/777"
        assert ShopifyRiskAdapter._to_gid(gid) == gid

    def test_assess_risk_high(self):
        """Happy path: HIGH risk order with multiple facts."""
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        a = ShopifyRiskAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "order": {
                "id": "gid://shopify/Order/999",
                "name": "#1042",
                "risk": {
                    "recommendation": "CANCEL",
                    "assessments": [{
                        "riskLevel": "HIGH",
                        "provider": {"handle": "shopify_protect", "features": []},
                        "facts": [
                            {"description": "Address mismatch",
                             "sentiment": "NEGATIVE"},
                            {"description": "Card AVS failed",
                             "sentiment": "NEGATIVE"},
                        ],
                    }],
                },
                "shopifyProtect": {
                    "status": "ACTIVE",
                    "eligibility": {"status": "ELIGIBLE"},
                },
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_ASSESS_RISK,
                {"order_id": "999"},
            )

        assert result.ok
        assert result.data["risk_level"] == "HIGH"
        assert result.data["score"] == 0.9
        assert result.data["recommendation"] == "cancel"
        assert len(result.data["facts"]) == 2
        assert result.data["protect_eligible"] is True
        assert result.data["found"] is True

    def test_assess_risk_picks_highest_severity(self):
        """If multiple assessments are returned, the adapter
        must pick the highest-severity one — that matches
        Shopify admin behaviour."""
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        a = ShopifyRiskAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "order": {
                "id": "gid://shopify/Order/1",
                "name": "#1",
                "risk": {
                    "assessments": [
                        {"riskLevel": "LOW", "facts": []},
                        {"riskLevel": "HIGH", "facts": []},
                        {"riskLevel": "MEDIUM", "facts": []},
                    ],
                },
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_ASSESS_RISK,
                {"order_id": "1"},
            )
        assert result.data["risk_level"] == "HIGH"
        assert result.data["score"] == 0.9

    def test_assess_risk_order_not_found(self):
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        a = ShopifyRiskAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"order": None}):
            result = a.execute(
                Capability.SHOPIFY_ASSESS_RISK,
                {"order_id": "ghost"},
            )
        assert result.ok
        assert result.data["found"] is False
        assert result.data["risk_level"] == "UNKNOWN"

    def test_assess_risk_missing_order_id_raises(self):
        from core.adapters.shopify.risk import ShopifyRiskAdapter
        a = ShopifyRiskAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── ShopifyInventoryAdapter ──────────────────────────────────


class TestShopifyInventoryAdapter:
    def test_metadata(self):
        from core.adapters.shopify.inventory import ShopifyInventoryAdapter
        a = ShopifyInventoryAdapter()
        assert a.name == "shopify_inventory"
        assert Capability.SHOPIFY_FETCH_PRODUCTS in a.capabilities
        assert Capability.SHOPIFY_UPDATE_INVENTORY in a.capabilities

    def test_fetch_inventory_aggregates_locations(self):
        from core.adapters.shopify.inventory import ShopifyInventoryAdapter
        a = ShopifyInventoryAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "inventoryItems": {
                "edges": [{
                    "node": {
                        "id": "gid://shopify/InventoryItem/A1",
                        "sku": "ABC-123",
                        "tracked": True,
                        "inventoryLevels": {
                            "edges": [
                                {"node": {
                                    "location": {
                                        "id": "gid://shopify/Location/L1",
                                        "name": "Main",
                                    },
                                    "quantities": [
                                        {"name": "available", "quantity": 50},
                                        {"name": "on_hand", "quantity": 60},
                                    ],
                                }},
                                {"node": {
                                    "location": {
                                        "id": "gid://shopify/Location/L2",
                                        "name": "Warehouse 2",
                                    },
                                    "quantities": [
                                        {"name": "available", "quantity": 37},
                                        {"name": "on_hand", "quantity": 40},
                                    ],
                                }},
                            ],
                        },
                    },
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_FETCH_PRODUCTS,
                {"sku": "ABC-123"},
            )

        assert result.ok
        assert result.data["sku"] == "ABC-123"
        assert result.data["found"] is True
        assert result.data["tracked"] is True
        assert result.data["total"] == 87  # 50 + 37 (available)
        assert len(result.data["by_location"]) == 2
        assert result.data["by_location"][0]["available"] == 50
        assert result.data["by_location"][0]["on_hand"] == 60

    def test_fetch_inventory_sku_not_found(self):
        from core.adapters.shopify.inventory import ShopifyInventoryAdapter
        a = ShopifyInventoryAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "inventoryItems": {"edges": []},
        }):
            result = a.execute(
                Capability.SHOPIFY_FETCH_PRODUCTS,
                {"sku": "missing"},
            )
        assert result.ok
        assert result.data["found"] is False
        assert result.data["total"] == 0

    def test_fetch_inventory_missing_sku_raises(self):
        from core.adapters.shopify.inventory import ShopifyInventoryAdapter
        a = ShopifyInventoryAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_FETCH_PRODUCTS, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_set_on_hand_happy_path(self):
        from core.adapters.shopify.inventory import ShopifyInventoryAdapter
        a = ShopifyInventoryAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "inventorySetOnHandQuantities": {
                "inventoryAdjustmentGroup": {
                    "createdAt": "2026-04-08T12:00:00Z",
                    "reason": "cycle_count",
                    "changes": [
                        {"name": "on_hand", "delta": 5,
                         "quantityAfterChange": 50},
                    ],
                },
                "userErrors": [],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_INVENTORY,
                {
                    "reason": "cycle_count",
                    "set_quantities": [{
                        "inventory_item_id": "gid://shopify/InventoryItem/A1",
                        "location_id": "gid://shopify/Location/L1",
                        "quantity": 50,
                    }],
                },
            )
        assert result.ok
        assert result.data["applied"] == 1
        assert result.data["reason"] == "cycle_count"

    def test_set_on_hand_user_errors_become_validation_error(self):
        from core.adapters.shopify.inventory import ShopifyInventoryAdapter
        a = ShopifyInventoryAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "inventorySetOnHandQuantities": {
                "userErrors": [
                    {"field": ["input", "setQuantities"],
                     "message": "Inventory item not found"}
                ],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_INVENTORY,
                {
                    "set_quantities": [{
                        "inventory_item_id": "gid://shopify/InventoryItem/missing",
                        "location_id": "gid://shopify/Location/L1",
                        "quantity": 0,
                    }],
                },
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "Inventory item not found" in result.error.reason

    def test_set_on_hand_missing_fields_raises(self):
        from core.adapters.shopify.inventory import ShopifyInventoryAdapter
        a = ShopifyInventoryAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_UPDATE_INVENTORY,
            {"set_quantities": [{"inventory_item_id": "x"}]},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_set_on_hand_empty_list_raises(self):
        from core.adapters.shopify.inventory import ShopifyInventoryAdapter
        a = ShopifyInventoryAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_UPDATE_INVENTORY,
            {"set_quantities": []},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── ShopifyFulfillmentAdapter ────────────────────────────────


class TestShopifyFulfillmentAdapter:
    def test_metadata(self):
        from core.adapters.shopify.fulfillment import ShopifyFulfillmentAdapter
        a = ShopifyFulfillmentAdapter()
        assert a.name == "shopify_fulfillment"
        assert Capability.SHOPIFY_CREATE_FULFILLMENT in a.capabilities

    def test_fulfill_two_step_dance(self):
        """The adapter must do TWO GraphQL calls: first
        ``fulfillmentOrders`` to discover the FulfillmentOrders
        for the order, then ``fulfillmentCreate`` to actually
        ship them. Verify the second call uses the IDs from
        the first."""
        from core.adapters.shopify.fulfillment import ShopifyFulfillmentAdapter
        a = ShopifyFulfillmentAdapter(shop_url="s", access_token="t")

        responses = [
            # 1st call: fulfillmentOrders query
            {
                "order": {
                    "id": "gid://shopify/Order/777",
                    "name": "#777",
                    "fulfillmentOrders": {
                        "edges": [{
                            "node": {
                                "id": "gid://shopify/FulfillmentOrder/FO1",
                                "status": "OPEN",
                                "lineItems": {
                                    "edges": [
                                        {"node": {
                                            "id": "gid://shopify/FulfillmentOrderLineItem/LI1",
                                            "remainingQuantity": 2,
                                            "totalQuantity": 2,
                                            "lineItem": {
                                                "id": "x",
                                                "title": "Widget",
                                                "sku": "WID-1",
                                            },
                                        }},
                                    ],
                                },
                            },
                        }],
                    },
                },
            },
            # 2nd call: fulfillmentCreate mutation
            {
                "fulfillmentCreate": {
                    "fulfillment": {
                        "id": "gid://shopify/Fulfillment/F1",
                        "status": "SUCCESS",
                        "createdAt": "2026-04-08T12:00:00Z",
                        "trackingInfo": [{
                            "company": "USPS",
                            "number": "9400111899223197428490",
                            "url": "https://tools.usps.com/?t=9400111899223197428490",
                        }],
                    },
                    "userErrors": [],
                },
            },
        ]

        call_count = {"i": 0}
        captured_vars = []
        def fake_gql(query, variables):
            r = responses[call_count["i"]]
            captured_vars.append(variables)
            call_count["i"] += 1
            return r

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_FULFILLMENT,
                {
                    "order_id": "777",
                    "tracking": {
                        "company": "USPS",
                        "number": "9400111899223197428490",
                    },
                    "notify_customer": True,
                },
            )

        assert result.ok
        assert result.data["fulfillment_id"] == "gid://shopify/Fulfillment/F1"
        assert result.data["status"] == "SUCCESS"
        assert call_count["i"] == 2
        # First call: fulfillmentOrders query for the order GID
        assert captured_vars[0]["id"] == "gid://shopify/Order/777"
        # Second call: fulfillmentCreate uses the FO ID from the first response
        fc_input = captured_vars[1]["fulfillment"]
        assert "lineItemsByFulfillmentOrder" in fc_input
        fos = fc_input["lineItemsByFulfillmentOrder"]
        assert fos[0]["fulfillmentOrderId"] == "gid://shopify/FulfillmentOrder/FO1"
        assert fos[0]["fulfillmentOrderLineItems"][0]["quantity"] == 2

    def test_fulfill_skips_closed_fulfillment_orders(self):
        """Only OPEN fulfillment orders should be fulfilled — closed
        ones must be filtered out."""
        from core.adapters.shopify.fulfillment import ShopifyFulfillmentAdapter
        a = ShopifyFulfillmentAdapter(shop_url="s", access_token="t")

        with patch.object(a, "_gql", return_value={
            "order": {
                "id": "gid://shopify/Order/1",
                "fulfillmentOrders": {
                    "edges": [
                        {"node": {
                            "id": "fo_closed",
                            "status": "CLOSED",
                            "lineItems": {"edges": []},
                        }},
                    ],
                },
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_FULFILLMENT,
                {"order_id": "1"},
            )
        # No OPEN fulfillment orders → adapter raises
        assert not result.ok
        assert "nothing left to fulfil" in result.error.reason

    def test_fulfill_order_not_found(self):
        from core.adapters.shopify.fulfillment import ShopifyFulfillmentAdapter
        a = ShopifyFulfillmentAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"order": None}):
            result = a.execute(
                Capability.SHOPIFY_CREATE_FULFILLMENT,
                {"order_id": "ghost"},
            )
        assert not result.ok
        assert "not found" in result.error.reason

    def test_cancel_action(self):
        from core.adapters.shopify.fulfillment import ShopifyFulfillmentAdapter
        a = ShopifyFulfillmentAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "fulfillmentCancel": {
                "fulfillment": {
                    "id": "gid://shopify/Fulfillment/F1",
                    "status": "CANCELLED",
                },
                "userErrors": [],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_FULFILLMENT,
                {
                    "action": "cancel",
                    "fulfillment_id": "gid://shopify/Fulfillment/F1",
                },
            )
        assert result.ok
        assert result.data["status"] == "CANCELLED"
        assert result.data["action"] == "cancelled"

    def test_cancel_missing_id_raises(self):
        from core.adapters.shopify.fulfillment import ShopifyFulfillmentAdapter
        a = ShopifyFulfillmentAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_CREATE_FULFILLMENT,
            {"action": "cancel"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_fulfill_user_errors_propagate(self):
        from core.adapters.shopify.fulfillment import ShopifyFulfillmentAdapter
        a = ShopifyFulfillmentAdapter(shop_url="s", access_token="t")

        responses = [
            {  # fulfillmentOrders
                "order": {
                    "id": "gid://shopify/Order/1",
                    "fulfillmentOrders": {
                        "edges": [{
                            "node": {
                                "id": "fo1", "status": "OPEN",
                                "lineItems": {"edges": [
                                    {"node": {
                                        "id": "li1",
                                        "remainingQuantity": 1,
                                        "totalQuantity": 1,
                                        "lineItem": {"id": "x"},
                                    }},
                                ]},
                            },
                        }],
                    },
                },
            },
            {  # fulfillmentCreate with userErrors
                "fulfillmentCreate": {
                    "fulfillment": None,
                    "userErrors": [
                        {"field": ["fulfillment", "trackingInfo"],
                         "message": "Tracking number invalid"},
                    ],
                },
            },
        ]
        i = {"n": 0}
        def gql(q, v):
            r = responses[i["n"]]
            i["n"] += 1
            return r

        with patch.object(a, "_gql", side_effect=gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_FULFILLMENT,
                {"order_id": "1"},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "Tracking number invalid" in result.error.reason


# ── ShopifyMetafieldAdapter ──────────────────────────────────


class TestShopifyMetafieldAdapter:
    def test_metadata(self):
        from core.adapters.shopify.metafield import ShopifyMetafieldAdapter
        a = ShopifyMetafieldAdapter()
        assert a.name == "shopify_metafield"
        assert Capability.SHOPIFY_SET_METAFIELD in a.capabilities

    def test_normalise_translates_snake_to_camel(self):
        from core.adapters.shopify.metafield import ShopifyMetafieldAdapter
        out = ShopifyMetafieldAdapter._normalise([{
            "owner_id": "gid://shopify/Order/1",
            "namespace": "shopai",
            "key": "fraud_score",
            "type": "number_decimal",
            "value": 0.42,
        }])
        assert out[0]["ownerId"] == "gid://shopify/Order/1"
        assert "owner_id" not in out[0]
        # Numeric value coerced to string
        assert out[0]["value"] == "0.42"

    def test_normalise_defaults_namespace_and_type(self):
        from core.adapters.shopify.metafield import ShopifyMetafieldAdapter
        out = ShopifyMetafieldAdapter._normalise([{
            "owner_id": "gid://shopify/Order/1",
            "key": "k",
            "value": "v",
        }])
        assert out[0]["namespace"] == "shopai"
        assert out[0]["type"] == "single_line_text_field"

    def test_normalise_missing_required_raises(self):
        from core.adapters.shopify.metafield import ShopifyMetafieldAdapter
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyMetafieldAdapter._normalise([{"key": "x"}])
        assert "owner_id" in str(exc.value)

    def test_normalise_non_dict_entry_raises(self):
        from core.adapters.shopify.metafield import ShopifyMetafieldAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyMetafieldAdapter._normalise(["not a dict"])  # type: ignore[list-item]

    def test_set_metafields_single_chunk(self):
        from core.adapters.shopify.metafield import ShopifyMetafieldAdapter
        a = ShopifyMetafieldAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "metafieldsSet": {
                "metafields": [{
                    "id": "gid://shopify/Metafield/1",
                    "key": "fraud_score",
                    "namespace": "shopai",
                    "ownerType": "ORDER",
                    "type": "number_decimal",
                    "value": "0.42",
                }],
                "userErrors": [],
            },
        }) as mocked:
            result = a.execute(
                Capability.SHOPIFY_SET_METAFIELD,
                {"metafields": [{
                    "owner_id": "gid://shopify/Order/1",
                    "key": "fraud_score",
                    "type": "number_decimal",
                    "value": "0.42",
                }]},
            )

        assert result.ok
        assert result.data["written"] == 1
        assert result.data["chunks"] == 1
        assert mocked.call_count == 1

    def test_set_metafields_chunks_at_25(self):
        """Shopify caps metafieldsSet at 25 entries per call.
        Larger payloads must be split automatically."""
        from core.adapters.shopify.metafield import ShopifyMetafieldAdapter
        a = ShopifyMetafieldAdapter(shop_url="s", access_token="t")

        # Build 60 metafields → expect 3 chunks (25 + 25 + 10)
        big_payload = [{
            "owner_id": f"gid://shopify/Order/{i}",
            "key": "k",
            "value": str(i),
        } for i in range(60)]

        # Each chunk returns its own slice of metafields
        call_count = {"n": 0}
        def fake_gql(q, v):
            call_count["n"] += 1
            sent = v["metafields"]
            return {
                "metafieldsSet": {
                    "metafields": [{"id": f"m{i}"} for i in range(len(sent))],
                    "userErrors": [],
                },
            }

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_SET_METAFIELD,
                {"metafields": big_payload},
            )

        assert result.ok
        assert call_count["n"] == 3  # 25 + 25 + 10
        assert result.data["chunks"] == 3
        assert result.data["written"] == 60

    def test_set_metafields_user_errors_propagate(self):
        from core.adapters.shopify.metafield import ShopifyMetafieldAdapter
        a = ShopifyMetafieldAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "metafieldsSet": {
                "metafields": [],
                "userErrors": [{
                    "field": ["metafields", "0", "value"],
                    "message": "Value cannot be blank",
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_SET_METAFIELD,
                {"metafields": [{
                    "owner_id": "gid://shopify/Order/1",
                    "key": "k",
                    "value": "",
                }]},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "Value cannot be blank" in result.error.reason

    def test_empty_metafields_raises(self):
        from core.adapters.shopify.metafield import ShopifyMetafieldAdapter
        a = ShopifyMetafieldAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_SET_METAFIELD, {"metafields": []})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── ShopifyOrdersAdapter (Option D) ─────────────────────────


class TestShopifyOrdersAdapter:
    def test_metadata(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter()
        assert a.name == "shopify_orders"
        assert Capability.SHOPIFY_FETCH_ORDERS in a.capabilities

    def test_fetch_orders_happy_path(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        canned = {
            "orders": {
                "pageInfo": {"hasNextPage": True, "endCursor": "CUR1"},
                "edges": [{
                    "cursor": "CUR1",
                    "node": {
                        "id": "gid://shopify/Order/101",
                        "name": "#1001",
                        "createdAt": "2026-04-01T10:00:00Z",
                        "updatedAt": "2026-04-02T10:00:00Z",
                        "displayFinancialStatus": "PAID",
                        "displayFulfillmentStatus": "UNFULFILLED",
                        "currentTotalPriceSet": {
                            "shopMoney": {"amount": "99.99",
                                          "currencyCode": "USD"},
                        },
                        "customer": {
                            "id": "gid://shopify/Customer/7",
                            "displayName": "A Smith",
                            "email": "a@b.co",
                        },
                        "email": "a@b.co",
                        "tags": ["vip"],
                    },
                }],
            },
        }
        with patch.object(a, "_gql", return_value=canned) as mocked:
            result = a.execute(
                Capability.SHOPIFY_FETCH_ORDERS,
                {"status": "open", "first": 10},
            )
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["orders"][0]["id"] == "gid://shopify/Order/101"
        assert result.data["orders"][0]["financial_status"] == "paid"
        assert result.data["orders"][0]["total_amount"] == "99.99"
        assert result.data["page_info"]["has_next_page"] is True
        # Check that status filter got turned into a raw query
        args = mocked.call_args[0]
        assert args[1]["query"] == "status:open"

    def test_fetch_orders_invalid_status(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_FETCH_ORDERS, {"status": "bogus"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_fetch_orders_first_out_of_range(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_FETCH_ORDERS, {"first": 500},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_fetch_orders_combines_status_and_extra_query(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "orders": {"pageInfo": {}, "edges": []},
        }) as mocked:
            a.execute(
                Capability.SHOPIFY_FETCH_ORDERS,
                {"status": "open", "query": "tag:vip"},
            )
        assert mocked.call_args[0][1]["query"] == "status:open tag:vip"

    def test_fetch_orders_any_status_sends_extra_query_only(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "orders": {"pageInfo": {}, "edges": []},
        }) as mocked:
            a.execute(
                Capability.SHOPIFY_FETCH_ORDERS,
                {"status": "any", "query": "tag:vip"},
            )
        assert mocked.call_args[0][1]["query"] == "tag:vip"

    def test_fetch_orders_with_line_items(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        canned = {
            "orders": {
                "pageInfo": {"hasNextPage": False, "endCursor": ""},
                "edges": [{
                    "cursor": "c",
                    "node": {
                        "id": "gid://shopify/Order/1",
                        "name": "#1",
                        "currentTotalPriceSet": {
                            "shopMoney": {"amount": "10", "currencyCode": "USD"},
                        },
                        "lineItems": {
                            "edges": [{
                                "node": {
                                    "id": "gid://shopify/LineItem/9",
                                    "sku": "SKU-9",
                                    "name": "Widget",
                                    "quantity": 3,
                                    "currentQuantity": 2,
                                },
                            }],
                        },
                    },
                }],
            },
        }
        with patch.object(a, "_gql", return_value=canned):
            result = a.execute(
                Capability.SHOPIFY_FETCH_ORDERS,
                {"include_line_items": True},
            )
        assert result.ok
        li = result.data["orders"][0]["line_items"]
        assert li[0]["sku"] == "SKU-9"
        assert li[0]["quantity"] == 3
        assert li[0]["current_quantity"] == 2


# ── ShopifyCustomersAdapter (Option D) ──────────────────────


class TestShopifyCustomersAdapter:
    def test_metadata(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter()
        assert a.name == "shopify_customers"
        assert Capability.SHOPIFY_FETCH_CUSTOMERS in a.capabilities

    def test_fetch_customers_happy_path(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        canned = {
            "customers": {
                "pageInfo": {"hasNextPage": False, "endCursor": ""},
                "edges": [{
                    "cursor": "c",
                    "node": {
                        "id": "gid://shopify/Customer/1",
                        "displayName": "Jane Doe",
                        "firstName": "Jane",
                        "lastName": "Doe",
                        "email": "jane@example.com",
                        "numberOfOrders": 5,
                        "amountSpent": {"amount": "500.00", "currencyCode": "USD"},
                        "state": "ENABLED",
                        "tags": ["vip"],
                        "verifiedEmail": True,
                    },
                }],
            },
        }
        with patch.object(a, "_gql", return_value=canned):
            result = a.execute(
                Capability.SHOPIFY_FETCH_CUSTOMERS,
                {"query": "tag:vip", "first": 25},
            )
        assert result.ok
        assert result.data["count"] == 1
        c = result.data["customers"][0]
        assert c["id"] == "gid://shopify/Customer/1"
        assert c["orders_count"] == 5
        assert c["state"] == "enabled"
        assert c["tags"] == ["vip"]

    def test_fetch_customers_first_out_of_range(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_FETCH_CUSTOMERS, {"first": 0},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_fetch_customers_with_addresses(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        canned = {
            "customers": {
                "pageInfo": {},
                "edges": [{
                    "cursor": "c",
                    "node": {
                        "id": "gid://shopify/Customer/1",
                        "defaultAddress": {
                            "id": "gid://shopify/MailingAddress/2",
                            "address1": "123 Main St",
                            "city": "Seattle",
                            "countryCodeV2": "US",
                        },
                    },
                }],
            },
        }
        with patch.object(a, "_gql", return_value=canned):
            result = a.execute(
                Capability.SHOPIFY_FETCH_CUSTOMERS,
                {"include_addresses": True},
            )
        addr = result.data["customers"][0]["default_address"]
        assert addr["address1"] == "123 Main St"
        assert addr["country_code"] == "US"


# ── ShopifyDiscountAdapter (Option D) ───────────────────────


class TestShopifyDiscountAdapter:
    def test_metadata(self):
        from core.adapters.shopify.discount import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter()
        assert a.name == "shopify_discount"
        assert Capability.SHOPIFY_CREATE_DISCOUNT in a.capabilities

    def test_create_percentage_discount(self):
        from core.adapters.shopify.discount import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        canned = {
            "discountCodeBasicCreate": {
                "codeDiscountNode": {
                    "id": "gid://shopify/DiscountCodeNode/1",
                    "codeDiscount": {
                        "title": "Spring15",
                        "startsAt": "2026-04-01T00:00:00Z",
                        "endsAt": "2026-04-30T23:59:59Z",
                        "usageLimit": 100,
                        "appliesOncePerCustomer": True,
                        "codes": {
                            "edges": [{"node": {"code": "SAVE15"}}],
                        },
                    },
                },
                "userErrors": [],
            },
        }
        with patch.object(a, "_gql", return_value=canned) as mocked:
            result = a.execute(
                Capability.SHOPIFY_CREATE_DISCOUNT,
                {
                    "code": "SAVE15",
                    "title": "Spring15",
                    "kind": "percentage",
                    "value": 15,
                    "usage_limit": 100,
                    "applies_once_per_customer": True,
                },
            )
        assert result.ok
        assert result.data["discount_id"] == "gid://shopify/DiscountCodeNode/1"
        assert result.data["code"] == "SAVE15"
        # Validate that percentage was encoded as 0..1 float
        sent = mocked.call_args[0][1]["basicCodeDiscount"]
        assert sent["customerGets"]["value"]["percentage"] == 0.15

    def test_create_fixed_amount_discount(self):
        from core.adapters.shopify.discount import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        canned = {
            "discountCodeBasicCreate": {
                "codeDiscountNode": {
                    "id": "gid://shopify/DiscountCodeNode/2",
                    "codeDiscount": {
                        "title": "FIVE",
                        "codes": {"edges": [{"node": {"code": "FIVE"}}]},
                    },
                },
                "userErrors": [],
            },
        }
        with patch.object(a, "_gql", return_value=canned) as mocked:
            result = a.execute(
                Capability.SHOPIFY_CREATE_DISCOUNT,
                {
                    "code": "FIVE",
                    "kind": "fixed_amount",
                    "value": 5.0,
                    "currency": "USD",
                    "minimum_subtotal": 30.0,
                },
            )
        assert result.ok
        sent = mocked.call_args[0][1]["basicCodeDiscount"]
        assert "discountAmount" in sent["customerGets"]["value"]
        assert sent["customerGets"]["value"]["discountAmount"]["amount"] == "5.00"
        assert "minimumRequirement" in sent

    def test_create_missing_code(self):
        from core.adapters.shopify.discount import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_CREATE_DISCOUNT,
            {"kind": "percentage", "value": 10},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_create_bad_kind(self):
        from core.adapters.shopify.discount import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_CREATE_DISCOUNT,
            {"code": "X", "kind": "bogus", "value": 1},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_create_percentage_over_100(self):
        from core.adapters.shopify.discount import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_CREATE_DISCOUNT,
            {"code": "X", "kind": "percentage", "value": 150},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_create_fixed_amount_missing_currency(self):
        from core.adapters.shopify.discount import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_CREATE_DISCOUNT,
            {"code": "X", "kind": "fixed_amount", "value": 5},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_user_errors_surface(self):
        from core.adapters.shopify.discount import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "discountCodeBasicCreate": {
                "codeDiscountNode": None,
                "userErrors": [{
                    "field": ["code"],
                    "message": "Code already exists",
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_DISCOUNT,
                {"code": "DUP", "kind": "percentage", "value": 10},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "Code already exists" in result.error.reason


# ── ShopifySegmentAdapter (Option D) ────────────────────────


class TestShopifySegmentAdapter:
    def test_metadata(self):
        from core.adapters.shopify.segment import ShopifySegmentAdapter
        a = ShopifySegmentAdapter()
        assert a.name == "shopify_segment"
        assert Capability.SHOPIFY_QUERY_SEGMENT in a.capabilities

    def test_list_segments(self):
        from core.adapters.shopify.segment import ShopifySegmentAdapter
        a = ShopifySegmentAdapter(shop_url="s", access_token="t")
        canned = {
            "segments": {
                "pageInfo": {"hasNextPage": False, "endCursor": ""},
                "edges": [{
                    "cursor": "c",
                    "node": {
                        "id": "gid://shopify/Segment/1",
                        "name": "VIPs",
                        "query": "tag = 'vip'",
                        "lastEditDate": "2026-03-01T00:00:00Z",
                        "creationDate": "2026-01-01T00:00:00Z",
                    },
                }],
            },
        }
        with patch.object(a, "_gql", return_value=canned):
            result = a.execute(
                Capability.SHOPIFY_QUERY_SEGMENT,
                {"mode": "list", "first": 25},
            )
        assert result.ok
        assert result.data["mode"] == "list"
        assert result.data["count"] == 1
        assert result.data["segments"][0]["name"] == "VIPs"

    def test_preview_segment(self):
        from core.adapters.shopify.segment import ShopifySegmentAdapter
        a = ShopifySegmentAdapter(shop_url="s", access_token="t")
        canned = {
            "customerSegmentMembers": {
                "statistics": {"totalCount": 347},
            },
        }
        with patch.object(a, "_gql", return_value=canned) as mocked:
            result = a.execute(
                Capability.SHOPIFY_QUERY_SEGMENT,
                {"mode": "preview", "query": "tag = 'vip'"},
            )
        assert result.ok
        assert result.data["mode"] == "preview"
        assert result.data["count"] == 347
        assert mocked.call_args[0][1]["query"] == "tag = 'vip'"

    def test_preview_missing_query(self):
        from core.adapters.shopify.segment import ShopifySegmentAdapter
        a = ShopifySegmentAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_QUERY_SEGMENT, {"mode": "preview"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_invalid_mode(self):
        from core.adapters.shopify.segment import ShopifySegmentAdapter
        a = ShopifySegmentAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_QUERY_SEGMENT, {"mode": "bogus"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── ShopifyDiscountReadAdapter ───────────────────────────────


class TestShopifyDiscountReadAdapter:
    def test_metadata(self):
        from core.adapters.shopify.discount_read import (
            ShopifyDiscountReadAdapter,
        )
        a = ShopifyDiscountReadAdapter()
        assert a.name == "shopify_discount_read"
        assert Capability.SHOPIFY_LIST_DISCOUNTS in a.capabilities

    def test_list_basic_codes(self):
        from core.adapters.shopify.discount_read import (
            ShopifyDiscountReadAdapter,
        )
        a = ShopifyDiscountReadAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "codeDiscountNodes": {
                "pageInfo": {"hasNextPage": False, "endCursor": "cur"},
                "edges": [
                    {
                        "cursor": "c1",
                        "node": {
                            "id": "gid://shopify/DiscountCodeNode/1",
                            "codeDiscount": {
                                "__typename": "DiscountCodeBasic",
                                "title": "Spring",
                                "status": "ACTIVE",
                                "startsAt": "2026-04-01T00:00:00Z",
                                "endsAt": "2026-04-30T23:59:59Z",
                                "usageLimit": 100,
                                "appliesOncePerCustomer": True,
                                "asyncUsageCount": 5,
                                "summary": "15% off",
                                "codes": {
                                    "pageInfo": {"hasNextPage": False},
                                    "edges": [{"node": {"code": "SAVE15"}}],
                                },
                            },
                        },
                    },
                ],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_DISCOUNTS,
                {"first": 10},
            )

        assert result.ok
        assert result.data["count"] == 1
        assert result.data["page_info"]["has_next_page"] is False
        d = result.data["discounts"][0]
        assert d["code"] == "SAVE15"
        assert d["codes"] == ["SAVE15"]
        assert d["has_more_codes"] is False
        assert d["title"] == "Spring"
        assert d["type"] == "basic"
        assert d["typename"] == "DiscountCodeBasic"
        assert d["status"] == "active"
        assert d["applies_once_per_customer"] is True
        assert d["async_usage_count"] == 5
        assert d["summary"] == "15% off"

    def test_list_empty(self):
        from core.adapters.shopify.discount_read import (
            ShopifyDiscountReadAdapter,
        )
        a = ShopifyDiscountReadAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "codeDiscountNodes": {
                "pageInfo": {"hasNextPage": False, "endCursor": ""},
                "edges": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_DISCOUNTS, {})
        assert result.ok
        assert result.data["count"] == 0
        assert result.data["discounts"] == []

    def test_list_query_filter_passed_through(self):
        """'query' is a Shopify search DSL string — the adapter
        must pass it to the GraphQL variables verbatim."""
        from core.adapters.shopify.discount_read import (
            ShopifyDiscountReadAdapter,
        )
        a = ShopifyDiscountReadAdapter(shop_url="s", access_token="t")
        captured: dict = {}
        def fake_gql(query, variables):
            captured["vars"] = variables
            return {"codeDiscountNodes": {"edges": [], "pageInfo": {}}}
        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_DISCOUNTS,
                {"first": 25, "after": "cur", "query": "status:active"},
            )
        assert captured["vars"]["first"] == 25
        assert captured["vars"]["after"] == "cur"
        assert captured["vars"]["query"] == "status:active"

    def test_list_invalid_first(self):
        from core.adapters.shopify.discount_read import (
            ShopifyDiscountReadAdapter,
        )
        a = ShopifyDiscountReadAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_DISCOUNTS, {"first": 500},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_list_bulk_codes_flagged_has_more(self):
        """Bulk-code discounts can have thousands of codes —
        has_more_codes must surface when the inner connection
        is truncated."""
        from core.adapters.shopify.discount_read import (
            ShopifyDiscountReadAdapter,
        )
        a = ShopifyDiscountReadAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "codeDiscountNodes": {
                "pageInfo": {},
                "edges": [{
                    "node": {
                        "id": "gid://shopify/DiscountCodeNode/9",
                        "codeDiscount": {
                            "__typename": "DiscountCodeBasic",
                            "title": "Bulk Codes",
                            "status": "ACTIVE",
                            "codes": {
                                "pageInfo": {"hasNextPage": True},
                                "edges": [
                                    {"node": {"code": "BULK001"}},
                                    {"node": {"code": "BULK002"}},
                                ],
                            },
                        },
                    },
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_DISCOUNTS, {})
        assert result.ok
        d = result.data["discounts"][0]
        assert d["has_more_codes"] is True
        assert d["codes"] == ["BULK001", "BULK002"]

    def test_list_discount_code_app_fragment(self):
        """Shopify Function-based (app) discounts must not show
        up as blank rows — they belong to the DiscountCodeApp
        type and need their own fragment."""
        from core.adapters.shopify.discount_read import (
            ShopifyDiscountReadAdapter,
        )
        a = ShopifyDiscountReadAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "codeDiscountNodes": {
                "pageInfo": {},
                "edges": [{
                    "node": {
                        "id": "gid://shopify/DiscountCodeNode/app1",
                        "codeDiscount": {
                            "__typename": "DiscountCodeApp",
                            "title": "App-powered",
                            "status": "ACTIVE",
                            "codes": {
                                "edges": [{"node": {"code": "APPCODE"}}],
                            },
                        },
                    },
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_DISCOUNTS, {})
        assert result.ok
        d = result.data["discounts"][0]
        assert d["type"] == "app"
        assert d["code"] == "APPCODE"

    def test_list_missing_codes_edge_is_safe(self):
        """A malformed node (no codes.edges) must NOT crash
        the whole list — drop the code string gracefully."""
        from core.adapters.shopify.discount_read import (
            ShopifyDiscountReadAdapter,
        )
        a = ShopifyDiscountReadAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "codeDiscountNodes": {
                "pageInfo": {},
                "edges": [
                    {
                        "node": {
                            "id": "gid://shopify/DiscountCodeNode/7",
                            "codeDiscount": {
                                "__typename": "DiscountCodeBasic",
                                "title": "Missing Codes",
                                "status": "SCHEDULED",
                            },
                        },
                    },
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_DISCOUNTS, {})
        assert result.ok
        assert result.data["discounts"][0]["code"] == ""
        assert result.data["discounts"][0]["title"] == "Missing Codes"


# ── ShopifyCustomerMutateAdapter ─────────────────────────────


class TestShopifyCustomerMutateAdapter:
    def test_metadata(self):
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        a = ShopifyCustomerMutateAdapter()
        assert a.name == "shopify_customer_mutate"
        assert Capability.SHOPIFY_UPDATE_CUSTOMER in a.capabilities

    def test_to_gid_numeric(self):
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        assert (
            ShopifyCustomerMutateAdapter._to_gid("77")
            == "gid://shopify/Customer/77"
        )
        gid = "gid://shopify/Customer/77"
        assert ShopifyCustomerMutateAdapter._to_gid(gid) == gid

    def test_update_note_and_tags(self):
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        a = ShopifyCustomerMutateAdapter(shop_url="s", access_token="t")
        captured: dict = {}
        def fake_gql(query, variables):
            captured["vars"] = variables
            return {
                "customerUpdate": {
                    "customer": {
                        "id": "gid://shopify/Customer/1",
                        "tags": ["vip", "early-access"],
                        "note": "VIP flagged",
                        "email": "a@b.com",
                        "phone": "",
                        "firstName": "A",
                        "lastName": "B",
                        "emailMarketingConsent": {
                            "marketingState": "SUBSCRIBED",
                        },
                        "smsMarketingConsent": {
                            "marketingState": "UNSUBSCRIBED",
                        },
                    },
                    "userErrors": [],
                },
            }
        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_CUSTOMER,
                {
                    "customer_id": "1",
                    "tags": ["VIP", "vip", "early-access"],  # dedup
                    "note": "VIP flagged",
                },
            )
        assert result.ok
        assert result.data["updated_fields"] == ["tags", "note"]
        assert result.data["tags"] == ["vip", "early-access"]
        assert result.data["email_marketing_state"] == "subscribed"
        assert result.data["sms_marketing_state"] == "unsubscribed"
        # Dedupe happened in the OUTGOING payload:
        assert captured["vars"]["input"]["tags"] == ["VIP", "early-access"]
        assert captured["vars"]["input"]["note"] == "VIP flagged"
        # id is the canonical GID
        assert captured["vars"]["input"]["id"] == "gid://shopify/Customer/1"

    def test_update_add_remove_tags_uses_atomic_mutations(self):
        """add_tags/remove_tags uses Shopify's tagsAdd / tagsRemove
        mutations — atomic server-side deltas with no lost-update
        race under concurrent tagging by other agents."""
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        a = ShopifyCustomerMutateAdapter(shop_url="s", access_token="t")

        calls: list[tuple[str, dict]] = []

        def fake_gql(query, variables):
            calls.append((query, variables))
            if "tagsAdd" in query:
                return {"tagsAdd": {
                    "node": {
                        "id": "gid://shopify/Customer/2",
                        "tags": ["loyal", "inactive", "newsletter",
                                 "winback-2026"],
                    },
                    "userErrors": [],
                }}
            return {"tagsRemove": {
                "node": {
                    "id": "gid://shopify/Customer/2",
                    "tags": ["loyal", "newsletter", "winback-2026"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_CUSTOMER,
                {
                    "customer_id": "2",
                    "add_tags": ["winback-2026"],
                    "remove_tags": ["INACTIVE"],
                },
            )
        assert result.ok
        # Exactly two calls — tagsAdd + tagsRemove (no fetch,
        # no customerUpdate with only {id}).
        assert len(calls) == 2
        assert "tagsAdd" in calls[0][0]
        assert calls[0][1]["tags"] == ["winback-2026"]
        assert "tagsRemove" in calls[1][0]
        assert calls[1][1]["tags"] == ["INACTIVE"]
        # Final tags reflect the server-side state.
        assert result.data["tags"] == [
            "loyal", "newsletter", "winback-2026",
        ]

    def test_update_absolute_tags_uses_customerUpdate(self):
        """'tags' (absolute) goes through customerUpdate, NOT
        the atomic delta mutations."""
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        a = ShopifyCustomerMutateAdapter(shop_url="s", access_token="t")
        calls: list = []

        def fake_gql(query, variables):
            calls.append(query)
            return {
                "customerUpdate": {
                    "customer": {
                        "id": "gid://shopify/Customer/3",
                        "tags": ["x"],
                    },
                    "userErrors": [],
                },
            }

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_CUSTOMER,
                {
                    "customer_id": "3",
                    "tags": ["x"],
                },
            )
        assert result.ok
        assert len(calls) == 1
        assert "customerUpdate" in calls[0]

    def test_update_add_remove_overlap_rejected(self):
        """Overlapping add_tags/remove_tags is a caller bug —
        surface it instead of silently resolving one way."""
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        a = ShopifyCustomerMutateAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_UPDATE_CUSTOMER,
            {
                "customer_id": "3",
                "add_tags": ["vip"],
                "remove_tags": ["VIP"],  # case-insensitive clash
            },
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "overlap" in str(result.error).lower()

    def test_update_marketing_state(self):
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        a = ShopifyCustomerMutateAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(query, variables):
            captured["vars"] = variables
            return {
                "customerUpdate": {
                    "customer": {
                        "id": "gid://shopify/Customer/4",
                        "tags": [],
                        "emailMarketingConsent": {
                            "marketingState": "UNSUBSCRIBED",
                        },
                    },
                    "userErrors": [],
                },
            }

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_CUSTOMER,
                {
                    "customer_id": "4",
                    "email_marketing_state": "unsubscribed",
                },
            )
        assert result.ok
        consent = captured["vars"]["input"]["emailMarketingConsent"]
        assert consent["marketingState"] == "UNSUBSCRIBED"

    def test_update_invalid_marketing_state(self):
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        a = ShopifyCustomerMutateAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_UPDATE_CUSTOMER,
            {"customer_id": "4", "email_marketing_state": "maybe"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_update_missing_customer_id(self):
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        a = ShopifyCustomerMutateAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_CUSTOMER, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_update_no_mutable_fields_refused(self):
        """Sending just {customer_id} with no field changes is a
        caller bug — refuse rather than burn a quota hit."""
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        a = ShopifyCustomerMutateAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_UPDATE_CUSTOMER, {"customer_id": "5"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_update_user_errors_bubble_up(self):
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        a = ShopifyCustomerMutateAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "customerUpdate": {
                "customer": None,
                "userErrors": [
                    {"field": ["email"], "message": "Email is invalid"},
                ],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_CUSTOMER,
                {"customer_id": "9", "email": "nope"},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "Email is invalid" in str(result.error)

    def test_update_null_customer_response_raises(self):
        """Shopify returns customer=null (no userErrors) when the
        access token lacks write_customers scope — surface it
        loudly instead of returning ok=True with empty data."""
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        from core.adapters.errors import AdapterError
        a = ShopifyCustomerMutateAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "customerUpdate": {"customer": None, "userErrors": []},
        }):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_CUSTOMER,
                {"customer_id": "1", "note": "x"},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)
        assert "scope" in str(result.error).lower()

    def test_update_subscribed_requires_opt_in_level(self):
        """Email marketing SUBSCRIBED without opt-in-level used
        to round-trip and fail at Shopify; reject up front."""
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        a = ShopifyCustomerMutateAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_UPDATE_CUSTOMER,
            {"customer_id": "1", "email_marketing_state": "subscribed"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "opt_in_level" in str(result.error)

    def test_update_subscribed_with_opt_in_succeeds(self):
        from core.adapters.shopify.customer_mutate import (
            ShopifyCustomerMutateAdapter,
        )
        a = ShopifyCustomerMutateAdapter(shop_url="s", access_token="t")
        captured: dict = {}
        def fake_gql(query, variables):
            captured["vars"] = variables
            return {"customerUpdate": {
                "customer": {
                    "id": "gid://shopify/Customer/1",
                    "tags": [],
                    "emailMarketingConsent": {
                        "marketingState": "SUBSCRIBED",
                        "marketingOptInLevel": "SINGLE_OPT_IN",
                    },
                },
                "userErrors": [],
            }}
        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_CUSTOMER,
                {
                    "customer_id": "1",
                    "email_marketing_state": "subscribed",
                    "email_marketing_opt_in_level": "single_opt_in",
                },
            )
        assert result.ok
        consent = captured["vars"]["input"]["emailMarketingConsent"]
        assert consent["marketingState"] == "SUBSCRIBED"
        assert consent["marketingOptInLevel"] == "SINGLE_OPT_IN"


# ── ShopifyRefundAdapter ─────────────────────────────────────


class TestShopifyRefundAdapter:
    def test_metadata(self):
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter()
        assert a.name == "shopify_refund"
        assert Capability.SHOPIFY_CREATE_REFUND in a.capabilities

    def test_to_gid(self):
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        assert ShopifyRefundAdapter._to_gid("7", "Order") == (
            "gid://shopify/Order/7"
        )
        assert ShopifyRefundAdapter._to_gid(
            "gid://shopify/LineItem/5", "LineItem",
        ) == "gid://shopify/LineItem/5"

    def test_refund_line_items(self):
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(query, variables):
            captured["vars"] = variables
            return {
                "refundCreate": {
                    "refund": {
                        "id": "gid://shopify/Refund/100",
                        "note": "customer",
                        "createdAt": "2026-04-14T12:00:00Z",
                        "totalRefundedSet": {
                            "shopMoney": {
                                "amount": "25.00",
                                "currencyCode": "USD",
                            },
                        },
                        "refundLineItems": {
                            "edges": [{
                                "node": {
                                    "quantity": 2,
                                    "restockType": "RETURN",
                                    "lineItem": {
                                        "id": "gid://shopify/LineItem/9",
                                    },
                                },
                            }],
                        },
                    },
                    "order": {
                        "id": "gid://shopify/Order/42",
                        "name": "#1001",
                    },
                    "userErrors": [],
                },
            }

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_REFUND,
                {
                    "order_id": "42",
                    "reason": "customer",
                    "notify": True,
                    "refund_line_items": [
                        {
                            "line_item_id": "9",
                            "quantity": 2,
                            "restock_type": "return",
                            "location_id": "1",
                        },
                    ],
                },
            )

        assert result.ok
        assert result.data["refund_id"] == "gid://shopify/Refund/100"
        assert result.data["total_refunded"] == "25.00"
        assert result.data["currency"] == "USD"
        assert result.data["restocked"] is True

        payload = captured["vars"]["input"]
        assert payload["orderId"] == "gid://shopify/Order/42"
        assert payload["notify"] is True
        assert payload["note"] == "customer"
        items = payload["refundLineItems"]
        assert items[0]["lineItemId"] == "gid://shopify/LineItem/9"
        assert items[0]["quantity"] == 2
        assert items[0]["restockType"] == "RETURN"
        assert items[0]["locationId"] == "gid://shopify/Location/1"

    def test_refund_amount_uses_parent_transaction(self):
        """amount-only refund triggers a transactions fetch to
        find the capture parent; the mutation payload must carry
        the correct parentId."""
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")

        fetch_response = {
            "order": {
                "id": "gid://shopify/Order/42",
                "name": "#1001",
                "currencyCode": "USD",
                "totalOutstandingSet": {
                    "shopMoney": {"amount": "25.00", "currencyCode": "USD"},
                },
                "transactions": [
                    {
                        "id": "gid://shopify/Transaction/tx_auth",
                        "kind": "AUTHORIZATION",
                        "status": "SUCCESS",
                        "amountSet": {
                            "shopMoney": {
                                "amount": "25.00",
                                "currencyCode": "USD",
                            },
                        },
                    },
                    {
                        "id": "gid://shopify/Transaction/tx_cap",
                        "kind": "CAPTURE",
                        "status": "SUCCESS",
                        "amountSet": {
                            "shopMoney": {
                                "amount": "25.00",
                                "currencyCode": "USD",
                            },
                        },
                    },
                ],
            },
        }
        mutate_response = {
            "refundCreate": {
                "refund": {
                    "id": "gid://shopify/Refund/500",
                    "totalRefundedSet": {
                        "shopMoney": {
                            "amount": "12.50",
                            "currencyCode": "USD",
                        },
                    },
                    "refundLineItems": {"edges": []},
                    "createdAt": "2026-04-14T12:00:00Z",
                    "note": "",
                },
                "order": {"id": "gid://shopify/Order/42"},
                "userErrors": [],
            },
        }

        calls: list[tuple[str, dict]] = []

        def fake_gql(query, variables):
            calls.append((query, variables))
            if "transactions(first" in query:
                return fetch_response
            return mutate_response

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_REFUND,
                {
                    "order_id": "42",
                    "amount": 12.50,
                    "currency": "USD",
                },
            )

        assert result.ok
        assert result.data["restocked"] is False
        mutation_vars = calls[1][1]
        txns = mutation_vars["input"]["transactions"]
        assert txns[0]["parentId"] == "gid://shopify/Transaction/tx_cap"
        assert txns[0]["amount"] == "12.50"
        assert txns[0]["kind"] == "REFUND"

    def test_refund_full_infers_amount(self):
        """refund_full=True infers the amount from outstanding."""
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")

        fetch = {
            "order": {
                "id": "gid://shopify/Order/99",
                "currencyCode": "USD",
                "totalOutstandingSet": {
                    "shopMoney": {"amount": "50.00", "currencyCode": "USD"},
                },
                "transactions": [{
                    "id": "gid://shopify/Transaction/tx",
                    "kind": "SALE", "status": "SUCCESS",
                    "amountSet": {
                        "shopMoney": {
                            "amount": "50.00", "currencyCode": "USD",
                        },
                    },
                }],
            },
        }
        mutate = {
            "refundCreate": {
                "refund": {
                    "id": "gid://shopify/Refund/1",
                    "totalRefundedSet": {
                        "shopMoney": {
                            "amount": "50.00", "currencyCode": "USD",
                        },
                    },
                    "refundLineItems": {"edges": []},
                    "createdAt": "",
                    "note": "",
                },
                "order": {},
                "userErrors": [],
            },
        }
        calls: list = []

        def fake_gql(query, variables):
            calls.append((query, variables))
            return fetch if "transactions(first" in query else mutate

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_REFUND,
                {"order_id": "99", "refund_full": True},
            )
        assert result.ok
        mvars = calls[1][1]
        assert mvars["input"]["transactions"][0]["amount"] == "50.00"

    def test_refund_full_plus_amount_rejected(self):
        """refund_full and amount together is ambiguous — must
        raise rather than silently preferring one branch."""
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_CREATE_REFUND,
            {
                "order_id": "1",
                "refund_full": True,
                "amount": 5.0,
                "currency": "USD",
            },
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "mutually exclusive" in str(result.error)

    def test_refund_full_zero_outstanding_rejected(self):
        """An already-fully-refunded order has outstanding=0.00
        (a truthy string). A naive truthiness check would let
        this through and fire a zero-dollar refund."""
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "order": {
                "id": "gid://shopify/Order/1",
                "currencyCode": "USD",
                "totalOutstandingSet": {
                    "shopMoney": {"amount": "0.00", "currencyCode": "USD"},
                },
                "transactions": [{
                    "id": "gid://shopify/Transaction/cap",
                    "kind": "CAPTURE", "status": "SUCCESS",
                    "createdAt": "2026-04-14T12:00:00Z",
                    "amountSet": {
                        "shopMoney": {"amount": "10.00", "currencyCode": "USD"},
                    },
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_REFUND,
                {"order_id": "1", "refund_full": True},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "outstanding" in str(result.error).lower()

    def test_refund_uses_parent_gateway_not_hardcoded_manual(self):
        """The refund transaction must inherit the parent's
        gateway — Shopify rejects Stripe refunds tagged as
        'manual' with 'gateway must match parent'."""
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")

        fetch = {
            "order": {
                "id": "gid://shopify/Order/1",
                "currencyCode": "USD",
                "totalOutstandingSet": {
                    "shopMoney": {"amount": "10.00", "currencyCode": "USD"},
                },
                "transactions": [{
                    "id": "gid://shopify/Transaction/stripe_cap",
                    "kind": "CAPTURE", "status": "SUCCESS",
                    "gateway": "stripe",
                    "createdAt": "2026-04-14T12:00:00Z",
                    "amountSet": {
                        "shopMoney": {"amount": "10.00", "currencyCode": "USD"},
                    },
                }],
            },
        }
        mutate = {
            "refundCreate": {
                "refund": {
                    "id": "gid://shopify/Refund/1",
                    "totalRefundedSet": {
                        "shopMoney": {
                            "amount": "5.00", "currencyCode": "USD",
                        },
                    },
                    "refundLineItems": {"edges": []},
                    "createdAt": "", "note": "",
                },
                "order": {},
                "userErrors": [],
            },
        }
        calls: list = []
        def fake_gql(query, variables):
            calls.append((query, variables))
            return fetch if "transactions(first" in query else mutate
        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_REFUND,
                {"order_id": "1", "amount": 5.0, "currency": "USD"},
            )
        assert result.ok
        mvars = calls[1][1]
        assert mvars["input"]["transactions"][0]["gateway"] == "stripe"

    def test_refund_picks_most_recent_capture(self):
        """Multi-capture orders (split-shipment) must refund
        against the NEWEST capture, not the first one returned."""
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")

        fetch = {
            "order": {
                "id": "gid://shopify/Order/1",
                "currencyCode": "USD",
                "totalOutstandingSet": {
                    "shopMoney": {"amount": "20.00", "currencyCode": "USD"},
                },
                "transactions": [
                    {
                        "id": "gid://shopify/Transaction/old",
                        "kind": "CAPTURE", "status": "SUCCESS",
                        "gateway": "stripe",
                        "createdAt": "2026-04-10T00:00:00Z",
                        "amountSet": {"shopMoney": {
                            "amount": "10.00", "currencyCode": "USD",
                        }},
                    },
                    {
                        "id": "gid://shopify/Transaction/new",
                        "kind": "CAPTURE", "status": "SUCCESS",
                        "gateway": "stripe",
                        "createdAt": "2026-04-14T00:00:00Z",
                        "amountSet": {"shopMoney": {
                            "amount": "10.00", "currencyCode": "USD",
                        }},
                    },
                ],
            },
        }
        mutate = {
            "refundCreate": {
                "refund": {
                    "id": "gid://shopify/Refund/1",
                    "totalRefundedSet": {
                        "shopMoney": {
                            "amount": "5.00", "currencyCode": "USD",
                        },
                    },
                    "refundLineItems": {"edges": []},
                    "createdAt": "", "note": "",
                },
                "order": {}, "userErrors": [],
            },
        }
        calls: list = []
        def fake_gql(query, variables):
            calls.append((query, variables))
            return fetch if "transactions(first" in query else mutate
        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_CREATE_REFUND,
                {"order_id": "1", "amount": 5.0, "currency": "USD"},
            )
        mvars = calls[1][1]
        assert mvars["input"]["transactions"][0]["parentId"] == (
            "gid://shopify/Transaction/new"
        )

    def test_refund_currency_mismatch_rejected(self):
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")

        with patch.object(a, "_gql", return_value={
            "order": {
                "id": "gid://shopify/Order/1",
                "currencyCode": "USD",
                "totalOutstandingSet": {
                    "shopMoney": {"amount": "10.00", "currencyCode": "USD"},
                },
                "transactions": [{
                    "id": "gid://shopify/Transaction/cap",
                    "kind": "CAPTURE", "status": "SUCCESS",
                    "gateway": "stripe",
                    "createdAt": "2026-04-14T12:00:00Z",
                    "amountSet": {
                        "shopMoney": {"amount": "10.00", "currencyCode": "USD"},
                    },
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_REFUND,
                {"order_id": "1", "amount": 5.0, "currency": "EUR"},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "currency" in str(result.error).lower()

    def test_refund_hinted_parent_skips_fetch(self):
        """When the caller passes parent_transaction_id, the
        round-trip to fetch transactions is skipped."""
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")
        calls: list = []
        def fake_gql(query, variables):
            calls.append((query, variables))
            return {
                "refundCreate": {
                    "refund": {
                        "id": "gid://shopify/Refund/1",
                        "totalRefundedSet": {
                            "shopMoney": {
                                "amount": "5.00", "currencyCode": "USD",
                            },
                        },
                        "refundLineItems": {"edges": []},
                        "createdAt": "", "note": "",
                    },
                    "order": {}, "userErrors": [],
                },
            }
        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_REFUND,
                {
                    "order_id": "1",
                    "amount": 5.0,
                    "currency": "USD",
                    "parent_transaction_id": "999",
                    "gateway": "stripe",
                },
            )
        assert result.ok
        # Only one call — the refund mutation. No fetch.
        assert len(calls) == 1
        mvars = calls[0][1]
        assert mvars["input"]["transactions"][0]["parentId"] == (
            "gid://shopify/OrderTransaction/999"
        )
        assert mvars["input"]["transactions"][0]["gateway"] == "stripe"

    def test_refund_null_refund_raises(self):
        """refundCreate returning null (scope miss) must surface
        loudly — not return ok=True with empty data."""
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        from core.adapters.errors import AdapterError
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "refundCreate": {
                "refund": None,
                "order": None,
                "userErrors": [],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_REFUND,
                {
                    "order_id": "1",
                    "refund_line_items": [{
                        "line_item_id": "2", "quantity": 1,
                    }],
                },
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)
        assert "scope" in str(result.error).lower()

    def test_refund_shipping_no_op_rejected(self):
        """refund_shipping={} or {"amount": 0} is a caller bug."""
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_CREATE_REFUND,
            {
                "order_id": "1",
                "refund_line_items": [
                    {"line_item_id": "2", "quantity": 1},
                ],
                "refund_shipping": {"full_refund": False, "amount": 0},
            },
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_refund_fails_when_no_capture_exists(self):
        """An order with only an AUTH transaction cannot be
        refunded — the adapter must raise rather than silently
        send a malformed mutation."""
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")

        with patch.object(a, "_gql", return_value={
            "order": {
                "id": "gid://shopify/Order/1",
                "currencyCode": "USD",
                "totalOutstandingSet": {
                    "shopMoney": {"amount": "0", "currencyCode": "USD"},
                },
                "transactions": [{
                    "id": "gid://shopify/Transaction/auth",
                    "kind": "AUTHORIZATION", "status": "SUCCESS",
                    "amountSet": {
                        "shopMoney": {
                            "amount": "10.00", "currencyCode": "USD",
                        },
                    },
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_REFUND,
                {"order_id": "1", "amount": 5, "currency": "USD"},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_refund_missing_order_id(self):
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_CREATE_REFUND, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_refund_no_refund_instruction(self):
        """order_id alone with no refund items/amount/shipping is
        a caller bug — refuse."""
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_CREATE_REFUND, {"order_id": "1"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_refund_invalid_restock_type(self):
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_CREATE_REFUND,
            {
                "order_id": "1",
                "refund_line_items": [{
                    "line_item_id": "1", "quantity": 1,
                    "restock_type": "destroy",
                }],
            },
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_refund_user_errors_bubble_up(self):
        from core.adapters.shopify.refund import ShopifyRefundAdapter
        a = ShopifyRefundAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "refundCreate": {
                "refund": None,
                "order": None,
                "userErrors": [
                    {"field": ["amount"],
                     "message": "Refund exceeds refundable balance"},
                ],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_REFUND,
                {
                    "order_id": "1",
                    "refund_line_items": [{
                        "line_item_id": "2", "quantity": 1,
                    }],
                },
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "refundable balance" in str(result.error).lower()


# ── Bootstrap ────────────────────────────────────────────────


class TestShopifyBootstrap:
    def test_register_all_adds_all_adapters(self):
        from core.adapters.shopify.bootstrap import register_all
        status = register_all()
        assert len(status) == 11
        assert set(status.keys()) == {
            "shopify_risk", "shopify_inventory",
            "shopify_fulfillment", "shopify_metafield",
            "shopify_orders", "shopify_customers",
            "shopify_customer_mutate",
            "shopify_discount", "shopify_discount_read",
            "shopify_refund", "shopify_segment",
        }

    def test_register_all_idempotent(self):
        from core.adapters.shopify.bootstrap import register_all
        register_all()
        # Second call must not raise
        register_all()
        assert len(get_registry()) == 11

    def test_explicit_creds_make_adapters_configured(self):
        from core.adapters.shopify.bootstrap import register_all
        status = register_all(
            shop_url="store.myshopify.com",
            access_token="shpat_test",
        )
        assert all(status.values()), f"some adapters not configured: {status}"

    def test_env_creds_make_adapters_configured(self, monkeypatch):
        from core.adapters.shopify.bootstrap import register_all
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "store.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_test")
        reset_config()
        status = register_all()
        assert all(status.values())

    def test_router_picks_shopify_for_each_capability(self, monkeypatch):
        from core.adapters import get_router
        from core.adapters.shopify.bootstrap import register_all
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "store.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_test")
        reset_config()
        register_all()

        router = get_router()
        # Each capability resolves to exactly one Shopify adapter
        assert router.route(Capability.SHOPIFY_ASSESS_RISK).name == "shopify_risk"
        assert router.route(Capability.SHOPIFY_FETCH_PRODUCTS).name == "shopify_inventory"
        assert router.route(Capability.SHOPIFY_UPDATE_INVENTORY).name == "shopify_inventory"
        assert router.route(Capability.SHOPIFY_CREATE_FULFILLMENT).name == "shopify_fulfillment"
        assert router.route(Capability.SHOPIFY_SET_METAFIELD).name == "shopify_metafield"
        assert router.route(Capability.SHOPIFY_FETCH_ORDERS).name == "shopify_orders"
        assert router.route(Capability.SHOPIFY_FETCH_CUSTOMERS).name == "shopify_customers"
        assert router.route(Capability.SHOPIFY_CREATE_DISCOUNT).name == "shopify_discount"
        assert router.route(Capability.SHOPIFY_LIST_DISCOUNTS).name == "shopify_discount_read"
        assert router.route(Capability.SHOPIFY_UPDATE_CUSTOMER).name == "shopify_customer_mutate"
        assert router.route(Capability.SHOPIFY_CREATE_REFUND).name == "shopify_refund"
        assert router.route(Capability.SHOPIFY_QUERY_SEGMENT).name == "shopify_segment"
