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
        for cls in (
            ShopifyRiskAdapter,
            ShopifyInventoryAdapter,
            ShopifyFulfillmentAdapter,
            ShopifyMetafieldAdapter,
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


# ── Bootstrap ────────────────────────────────────────────────


class TestShopifyBootstrap:
    def test_register_all_adds_eight_adapters(self):
        from core.adapters.shopify.bootstrap import register_all
        status = register_all()
        assert len(status) == 8
        assert set(status.keys()) == {
            "shopify_risk", "shopify_inventory",
            "shopify_fulfillment", "shopify_metafield",
            "shopify_discount", "shopify_files",
            "shopify_draft_orders", "shopify_marketing_events",
        }

    def test_register_all_idempotent(self):
        from core.adapters.shopify.bootstrap import register_all
        register_all()
        # Second call must not raise
        register_all()
        assert len(get_registry()) == 8

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
        assert router.route(Capability.SHOPIFY_CREATE_DISCOUNT).name == "shopify_discount"
        assert router.route(Capability.SHOPIFY_LIST_DISCOUNTS).name == "shopify_discount"
        assert router.route(Capability.SHOPIFY_UPLOAD_FILE).name == "shopify_files"
        assert router.route(Capability.SHOPIFY_LIST_FILES).name == "shopify_files"
        assert router.route(Capability.SHOPIFY_CREATE_DRAFT_ORDER).name == "shopify_draft_orders"
        assert router.route(Capability.SHOPIFY_COMPLETE_DRAFT_ORDER).name == "shopify_draft_orders"
        assert router.route(Capability.SHOPIFY_LIST_DRAFT_ORDERS).name == "shopify_draft_orders"
        assert router.route(Capability.SHOPIFY_CREATE_MARKETING_ACTIVITY).name == "shopify_marketing_events"
        assert router.route(Capability.SHOPIFY_UPDATE_MARKETING_ACTIVITY).name == "shopify_marketing_events"
        assert router.route(Capability.SHOPIFY_ADD_MARKETING_ENGAGEMENT).name == "shopify_marketing_events"
        assert router.route(Capability.SHOPIFY_LIST_MARKETING_ACTIVITIES).name == "shopify_marketing_events"


# ── ShopifyMarketingEventsAdapter ──────────────────────────


class TestShopifyMarketingEventsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter()
        assert a.name == "shopify_marketing_events"
        for cap in (
            Capability.SHOPIFY_CREATE_MARKETING_ACTIVITY,
            Capability.SHOPIFY_UPDATE_MARKETING_ACTIVITY,
            Capability.SHOPIFY_ADD_MARKETING_ENGAGEMENT,
            Capability.SHOPIFY_LIST_MARKETING_ACTIVITIES,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── _build_create_input validation ─────────────────────

    def test_create_input_requires_title(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyMarketingEventsAdapter._build_create_input({"channel": "social"})

    def test_create_input_requires_channel(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyMarketingEventsAdapter._build_create_input({"title": "Camp"})

    @staticmethod
    def _min_valid_create_params(**overrides) -> dict:
        """Minimal valid input for ``_build_create_input``.

        Three fields are functionally required by Shopify's external
        activity surface (caught live during smoke testing):
        ``utm`` (so sales can be attributed), ``remote_url`` (for
        click-through to the source), and ``ad_spend``-or-``budget``
        (to satisfy the non-null Budget validation). The helper
        encodes that contract so individual tests only override the
        fields they care about.
        """
        base = {
            "title": "Smoke Title",
            "channel": "social",
            "utm": {"source": "fb", "medium": "cpc", "campaign": "c"},
            "remote_url": "https://example.com/dashboard",
            "ad_spend": {"amount": 100, "currency": "USD"},
        }
        base.update(overrides)
        return base

    def test_create_input_channel_aliases_resolve(self):
        """Engines pass vendor names ('facebook', 'tiktok', 'google');
        Shopify wants the canonical SOCIAL/SEARCH/etc. enum. Aliases
        must collapse cleanly at the boundary."""
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        cases = [
            ("facebook", "SOCIAL"),
            ("Instagram", "SOCIAL"),
            ("TIKTOK", "SOCIAL"),
            ("google", "SEARCH"),
            ("google_ads", "SEARCH"),
            ("display", "DISPLAY"),
            ("email", "EMAIL"),
        ]
        for raw, expected in cases:
            out = ShopifyMarketingEventsAdapter._build_create_input(
                self._min_valid_create_params(channel=raw)
            )
            assert out["marketingChannelType"] == expected, raw

    def test_create_input_unknown_channel_rejected(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyMarketingEventsAdapter._build_create_input(
                self._min_valid_create_params(channel="carrier-pigeon")
            )

    def test_create_input_tactic_defaults_to_ad(self):
        """Shopify rejects MarketingActivityCreateExternalInput with
        a null tactic (caught live during smoke test). The adapter
        defaults to AD because that's 95% of ShopAI's launches."""
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        out = ShopifyMarketingEventsAdapter._build_create_input(
            self._min_valid_create_params()
        )
        assert out["tactic"] == "AD"

    def test_create_input_tactic_aliases_resolve(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        cases = [
            ("ad", "AD"),
            ("paid", "AD"),
            ("post", "POST"),
            ("abandoned_cart", "ABANDONED_CART"),
            ("cart_recovery", "ABANDONED_CART"),
            ("retargeting", "RETARGETING"),
            ("seo", "SEO"),
        ]
        for raw, expected in cases:
            out = ShopifyMarketingEventsAdapter._build_create_input(
                self._min_valid_create_params(tactic=raw)
            )
            assert out["tactic"] == expected, raw

    def test_create_input_unknown_tactic_rejected(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyMarketingEventsAdapter._build_create_input(
                self._min_valid_create_params(tactic="telepathy")
            )

    def test_create_input_status_alias_resolves_and_defaults_active(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        out = ShopifyMarketingEventsAdapter._build_create_input(
            self._min_valid_create_params()
        )
        assert out["status"] == "ACTIVE"
        out2 = ShopifyMarketingEventsAdapter._build_create_input(
            self._min_valid_create_params(status="paused")
        )
        assert out2["status"] == "PAUSED"

    def test_create_input_utm_required_subfields(self):
        """Shopify cannot attribute sales without source/medium/campaign;
        rejecting upfront prevents an opaque userErrors envelope."""
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        for missing in ("source", "medium", "campaign"):
            utm = {"source": "x", "medium": "y", "campaign": "z"}
            del utm[missing]
            with pytest.raises(AdapterValidationError) as exc:
                ShopifyMarketingEventsAdapter._build_create_input(
                    self._min_valid_create_params(utm=utm)
                )
            assert missing in str(exc.value)

    def test_create_input_utm_passes_optional_fields(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        out = ShopifyMarketingEventsAdapter._build_create_input(
            self._min_valid_create_params(utm={
                "source": "fb", "medium": "cpc", "campaign": "c25",
                "content": "hero", "term": "summer",
            })
        )
        assert out["utm"] == {
            "source": "fb", "medium": "cpc", "campaign": "c25",
            "content": "hero", "term": "summer",
        }

    def test_create_input_remote_url_required(self):
        """Shopify rejects activities with a null remoteUrl (caught
        live during smoke test); the merchant uses it to click through
        to the source platform."""
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        params = self._min_valid_create_params()
        del params["remote_url"]
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyMarketingEventsAdapter._build_create_input(params)
        assert "remote_url" in str(exc.value)

    def test_create_input_remote_id_url_preview_pass_through(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        out = ShopifyMarketingEventsAdapter._build_create_input(
            self._min_valid_create_params(
                remote_id="fb-camp-123",
                remote_url="https://business.facebook.com/...",
                remote_preview_image_url="https://cdn/preview.jpg",
            )
        )
        assert out["remoteId"] == "fb-camp-123"
        assert out["remoteUrl"].startswith("https://business")
        assert out["remotePreviewImageUrl"].endswith("preview.jpg")

    def test_create_input_ad_spend_money_input_normalised(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        out = ShopifyMarketingEventsAdapter._build_create_input(
            self._min_valid_create_params(
                ad_spend={"amount": 250, "currency": "usd"},
            )
        )
        assert out["adSpend"] == {"amount": "250.00", "currencyCode": "USD"}

    def test_create_input_ad_spend_bare_number_defaults_usd(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        out = ShopifyMarketingEventsAdapter._build_create_input(
            self._min_valid_create_params(ad_spend=99.5)
        )
        assert out["adSpend"] == {"amount": "99.50", "currencyCode": "USD"}

    def test_create_input_ad_spend_negative_rejected(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyMarketingEventsAdapter._build_create_input(
                self._min_valid_create_params(
                    ad_spend={"amount": -10, "currency": "USD"},
                )
            )

    def test_create_input_budget_validation(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        params = self._min_valid_create_params(
            budget={"total": 5000, "type": "DAILY"},
        )
        # Helper sets ad_spend by default; this test cares about
        # explicit budget shaping, so drop ad_spend to isolate.
        del params["ad_spend"]
        out = ShopifyMarketingEventsAdapter._build_create_input(params)
        assert out["budget"]["budgetType"] == "DAILY"
        assert out["budget"]["total"]["amount"] == "5000.00"

        bad_no_total = self._min_valid_create_params(
            budget={"type": "DAILY"},  # missing total
        )
        del bad_no_total["ad_spend"]
        with pytest.raises(AdapterValidationError):
            ShopifyMarketingEventsAdapter._build_create_input(bad_no_total)

        bad_type = self._min_valid_create_params(
            budget={"total": 5000, "type": "WHENEVER"},
        )
        del bad_type["ad_spend"]
        with pytest.raises(AdapterValidationError):
            ShopifyMarketingEventsAdapter._build_create_input(bad_type)

    def test_create_input_budget_required_or_inferred_from_ad_spend(self):
        """Shopify rejects external activities with a null budget
        (caught live during smoke test). When the caller gives
        ad_spend but no explicit budget, default budget = ad_spend
        as LIFETIME — most ShopAI engines already know the spend and
        don't care about a separate 'planned budget' field."""
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        # No budget AND no ad_spend → fail fast.
        params = self._min_valid_create_params()
        del params["ad_spend"]
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyMarketingEventsAdapter._build_create_input(params)
        assert "budget" in str(exc.value).lower()

        # ad_spend only → budget inferred as LIFETIME.
        out = ShopifyMarketingEventsAdapter._build_create_input(
            self._min_valid_create_params(
                ad_spend={"amount": 100, "currency": "USD"},
            )
        )
        assert out["budget"]["budgetType"] == "LIFETIME"
        assert out["budget"]["total"] == {"amount": "100.00",
                                          "currencyCode": "USD"}

    # ── Create — happy path ───────────────────────────────

    def test_create_activity_happy_path(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "marketingActivityCreateExternal": {
                "marketingActivity": {
                    "id": "gid://shopify/MarketingActivity/123",
                    "title": "Summer Sale FB",
                    "status": "ACTIVE",
                    "marketingChannelType": "SOCIAL",
                    "sourceAndMedium": "facebook / cpc",
                    "adSpend": {"amount": "250.00", "currencyCode": "USD"},
                    "utmParameters": {
                        "source": "facebook", "medium": "cpc",
                        "campaign": "summer25", "content": "", "term": "",
                    },
                },
                "userErrors": [],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_MARKETING_ACTIVITY,
                self._min_valid_create_params(
                    title="Summer Sale FB", channel="facebook",
                    utm={"source": "facebook", "medium": "cpc",
                         "campaign": "summer25"},
                    ad_spend={"amount": 250, "currency": "USD"},
                    remote_id="fb-1",
                    remote_url="https://business.facebook.com/...",
                ),
            )
        assert result.ok
        act = result.data["activity"]
        assert act["id"] == "gid://shopify/MarketingActivity/123"
        assert act["channel"] == "SOCIAL"
        assert act["status"] == "ACTIVE"
        assert act["ad_spend"] == 250.0
        assert act["currency"] == "USD"
        assert act["utm"]["source"] == "facebook"
        assert act["utm"]["campaign"] == "summer25"

    def test_create_activity_user_errors_propagate(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "marketingActivityCreateExternal": {
                "marketingActivity": None,
                "userErrors": [{
                    "field": ["input", "utm", "source"],
                    "message": "UTM source is required",
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_MARKETING_ACTIVITY,
                self._min_valid_create_params(),
            )
        assert not result.ok

    # ── Update activity ──────────────────────────────────

    def test_update_activity_requires_id(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_MARKETING_ACTIVITY,
                {"status": "paused"},
            )
        assert not result.ok

    def test_update_activity_needs_at_least_one_field(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_MARKETING_ACTIVITY,
                {"id": "gid://shopify/MarketingActivity/1"},
            )
        assert not result.ok

    def test_update_activity_status_alias_resolves(self):
        """Schema places ``marketingActivityId`` at the GraphQL field
        level, NOT inside MarketingActivityUpdateExternalInput — caught
        live during smoke test ('Field is not defined on
        MarketingActivityUpdateExternalInput' for both ``id`` and
        ``marketingActivityId`' inside input). The adapter splits the
        identifier out as a top-level variable."""
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"marketingActivityUpdateExternal": {
                "marketingActivity": {"id": v["marketingActivityId"]},
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_UPDATE_MARKETING_ACTIVITY, {
                "id": "gid://shopify/MarketingActivity/1",
                "status": "paused",
            })
        # Identifier sits OUTSIDE input, only update fields go inside.
        assert captured["marketingActivityId"] == "gid://shopify/MarketingActivity/1"
        assert captured["input"]["status"] == "PAUSED"
        assert "id" not in captured["input"]
        assert "marketingActivityId" not in captured["input"]

    # ── Engagement ───────────────────────────────────────

    def test_engagement_requires_activity_id_or_remote_id(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(
                Capability.SHOPIFY_ADD_MARKETING_ENGAGEMENT,
                {"occurred_on": "2026-04-25", "impressions": 100},
            )
        assert not result.ok

    def test_engagement_input_requires_at_least_one_metric(self):
        """Shopify rejects engagements with no measurable activity."""
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyMarketingEventsAdapter._build_engagement_input({
                "occurred_on": "2026-04-25",
            })
        assert "metric" in str(exc.value)

    def test_engagement_input_translates_friendly_metrics(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        out = ShopifyMarketingEventsAdapter._build_engagement_input({
            "occurred_on": "2026-04-25",
            "impressions": 12345, "clicks": 230, "sessions": 800,
            "spend": {"amount": 25.50, "currency": "USD"},
            "sales": 200,
        })
        assert out["occurredOn"] == "2026-04-25"
        assert out["impressionsCount"] == 12345
        assert out["clicksCount"] == 230
        assert out["sessionsCount"] == 800
        assert out["adSpend"]["amount"] == "25.50"
        assert out["sales"]["amount"] == "200.00"
        assert out["isCumulative"] is False
        # utcOffset is required on MarketingEngagementInput (caught
        # live as "Expected value to not be null"). Default is UTC.
        assert out["utcOffset"] == "+00:00"
        # conversionsCount is not on MarketingEngagement in the current
        # schema — caught live during smoke test; the adapter drops the
        # field rather than ship a request Shopify will reject.
        assert "conversionsCount" not in out

    def test_engagement_input_utc_offset_overridable(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        out = ShopifyMarketingEventsAdapter._build_engagement_input({
            "occurred_on": "2026-04-25", "impressions": 100,
            "utc_offset": "-05:00",
        })
        assert out["utcOffset"] == "-05:00"

    def test_engagement_input_negative_metrics_rejected(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyMarketingEventsAdapter._build_engagement_input({
                "occurred_on": "2026-04-25", "impressions": -5,
            })

    def test_add_engagement_happy_path(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"marketingEngagementCreate": {
                "marketingEngagement": {
                    "occurredOn": "2026-04-25",
                    "impressionsCount": 10000,
                    "clicksCount": 250,
                    "sessionsCount": 850,
                    "adSpend": {"amount": "50.00", "currencyCode": "USD"},
                    "sales": {"amount": "300.00", "currencyCode": "USD"},
                    "isCumulative": False,
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_ADD_MARKETING_ENGAGEMENT,
                {
                    "activity_id": "gid://shopify/MarketingActivity/1",
                    "occurred_on": "2026-04-25",
                    "impressions": 10000, "clicks": 250, "sessions": 850,
                    "spend": {"amount": 50, "currency": "USD"},
                    "sales": {"amount": 300, "currency": "USD"},
                },
            )
        assert result.ok
        eng = result.data["engagement"]
        assert eng["impressions"] == 10000
        assert eng["clicks"] == 250
        assert eng["sessions"] == 850
        assert eng["spend"] == 50.0
        assert eng["sales"] == 300.0
        assert captured["marketingActivityId"] == "gid://shopify/MarketingActivity/1"
        # Schema variable name is marketingEngagement, not engagement —
        # caught live during smoke test as a "missing required argument".
        assert "marketingEngagement" in captured

    def test_add_engagement_remote_id_path(self):
        """Schema accepts marketingActivityId OR remoteId — there is
        NO marketingChannelType arg on this mutation. Channel-name
        fallback was removed after a live smoke test rejected it as
        'argument not accepted'."""
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"marketingEngagementCreate": {
                "marketingEngagement": {"occurredOn": "2026-04-25",
                                        "impressionsCount": 10},
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_ADD_MARKETING_ENGAGEMENT, {
                "remote_id": "fb-camp-123",
                "occurred_on": "2026-04-25", "impressions": 10,
            })
        assert captured["remoteId"] == "fb-camp-123"
        assert "marketingActivityId" not in captured
        assert "marketingChannelType" not in captured

    # ── List ────────────────────────────────────────────

    def test_list_activities_happy_path(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "marketingActivities": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/MarketingActivity/1",
                        "title": "Summer Sale FB",
                        "status": "ACTIVE",
                        "marketingChannelType": "SOCIAL",
                        "adSpend": {"amount": "250.00",
                                    "currencyCode": "USD"},
                        "utmParameters": {
                            "source": "facebook", "medium": "cpc",
                            "campaign": "summer25",
                        },
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_MARKETING_ACTIVITIES,
                               {"limit": 10})
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["activities"][0]["channel"] == "SOCIAL"

    def test_list_activities_clamps_limit(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"marketingActivities": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_MARKETING_ACTIVITIES,
                      {"limit": 9999})
        assert captured["first"] == 250

    def test_list_activities_empty_page(self):
        from core.adapters.shopify.marketing_events import ShopifyMarketingEventsAdapter
        a = ShopifyMarketingEventsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "marketingActivities": {"pageInfo": {}, "edges": []},
        }):
            result = a.execute(Capability.SHOPIFY_LIST_MARKETING_ACTIVITIES, {})
        assert result.ok
        assert result.data["count"] == 0
        assert result.data["has_next_page"] is False


# ── ShopifyDraftOrdersAdapter ──────────────────────────────


class TestShopifyDraftOrdersAdapter:
    def test_metadata(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        a = ShopifyDraftOrdersAdapter()
        assert a.name == "shopify_draft_orders"
        assert Capability.SHOPIFY_CREATE_DRAFT_ORDER in a.capabilities
        assert Capability.SHOPIFY_COMPLETE_DRAFT_ORDER in a.capabilities
        assert Capability.SHOPIFY_LIST_DRAFT_ORDERS in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        a = ShopifyDraftOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── _build_draft_input validation ────────────────────────

    def test_build_input_requires_line_items(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrdersAdapter._build_draft_input({})
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrdersAdapter._build_draft_input({"line_items": []})

    def test_build_input_variant_line_item(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        out = ShopifyDraftOrdersAdapter._build_draft_input({
            "line_items": [
                {"variant_id": "gid://shopify/ProductVariant/123",
                 "quantity": 2},
            ],
        })
        assert out["lineItems"][0]["variantId"] == "gid://shopify/ProductVariant/123"
        assert out["lineItems"][0]["quantity"] == 2

    def test_build_input_custom_line_item_with_price(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        out = ShopifyDraftOrdersAdapter._build_draft_input({
            "line_items": [
                {"title": "Custom service",
                 "quantity": 1,
                 "original_unit_price": 50},
            ],
        })
        assert out["lineItems"][0]["title"] == "Custom service"
        assert out["lineItems"][0]["originalUnitPrice"] == "50.00"

    def test_build_input_custom_item_without_price_rejected(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyDraftOrdersAdapter._build_draft_input({
                "line_items": [{"title": "Custom", "quantity": 1}],
            })
        assert "original_unit_price" in str(exc.value)

    def test_build_input_line_item_without_variant_or_title_rejected(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrdersAdapter._build_draft_input({
                "line_items": [{"quantity": 1}],
            })

    def test_build_input_quantity_must_be_positive_int(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        for bad in (0, -1, "many"):
            with pytest.raises(AdapterValidationError):
                ShopifyDraftOrdersAdapter._build_draft_input({
                    "line_items": [
                        {"variant_id": "gid://x", "quantity": bad},
                    ],
                })

    def test_build_input_non_dict_line_item_rejected(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrdersAdapter._build_draft_input({
                "line_items": ["not a dict"],
            })

    def test_build_input_email_validated(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        out = ShopifyDraftOrdersAdapter._build_draft_input({
            "line_items": [{"variant_id": "gid://x", "quantity": 1}],
            "email": "buyer@example.com",
        })
        assert out["email"] == "buyer@example.com"
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrdersAdapter._build_draft_input({
                "line_items": [{"variant_id": "gid://x", "quantity": 1}],
                "email": "not-an-email",
            })

    def test_build_input_customer_id_passes_as_purchasing_entity(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        out = ShopifyDraftOrdersAdapter._build_draft_input({
            "line_items": [{"variant_id": "gid://x", "quantity": 1}],
            "customer_id": "gid://shopify/Customer/42",
        })
        assert out["purchasingEntity"]["customerId"] == "gid://shopify/Customer/42"

    def test_build_input_tags_list_form(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        out = ShopifyDraftOrdersAdapter._build_draft_input({
            "line_items": [{"variant_id": "gid://x", "quantity": 1}],
            "tags": ["recovery", "shopai", ""],
        })
        # Empty strings dropped silently to spare callers a filter step.
        assert out["tags"] == ["recovery", "shopai"]

    def test_build_input_tags_string_form(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        out = ShopifyDraftOrdersAdapter._build_draft_input({
            "line_items": [{"variant_id": "gid://x", "quantity": 1}],
            "tags": "recovery, shopai , vip",
        })
        assert out["tags"] == ["recovery", "shopai", "vip"]

    def test_build_input_tags_invalid_type_rejected(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrdersAdapter._build_draft_input({
                "line_items": [{"variant_id": "gid://x", "quantity": 1}],
                "tags": 12345,
            })

    def test_build_input_applied_discount_percentage(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        out = ShopifyDraftOrdersAdapter._build_draft_input({
            "line_items": [{"variant_id": "gid://x", "quantity": 1}],
            "applied_discount": {"value_type": "PERCENTAGE", "value": 10,
                                 "title": "Recovery"},
        })
        assert out["appliedDiscount"]["valueType"] == "PERCENTAGE"
        assert out["appliedDiscount"]["value"] == 10.0
        assert out["appliedDiscount"]["title"] == "Recovery"

    def test_build_input_applied_discount_validates_value_type(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrdersAdapter._build_draft_input({
                "line_items": [{"variant_id": "gid://x", "quantity": 1}],
                "applied_discount": {"value_type": "FREE_LUNCH", "value": 5},
            })

    def test_build_input_applied_discount_percentage_capped_at_100(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrdersAdapter._build_draft_input({
                "line_items": [{"variant_id": "gid://x", "quantity": 1}],
                "applied_discount": {"value_type": "PERCENTAGE",
                                     "value": 150},
            })

    def test_build_input_line_item_applied_discount(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        out = ShopifyDraftOrdersAdapter._build_draft_input({
            "line_items": [
                {"variant_id": "gid://x", "quantity": 1,
                 "applied_discount": {"value_type": "FIXED_AMOUNT",
                                      "value": 5}},
            ],
        })
        assert out["lineItems"][0]["appliedDiscount"]["valueType"] == "FIXED_AMOUNT"

    # ── Create — happy path ──────────────────────────────────

    def test_create_draft_happy_path(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        a = ShopifyDraftOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "draftOrderCreate": {
                "draftOrder": {
                    "id": "gid://shopify/DraftOrder/77",
                    "name": "#D77",
                    "status": "OPEN",
                    "invoiceUrl": "https://shop.myshopify.com/checkouts/c/abc",
                    "totalPriceSet": {
                        "presentmentMoney": {"amount": "55.00",
                                             "currencyCode": "USD"},
                    },
                    "subtotalPriceSet": {
                        "presentmentMoney": {"amount": "50.00",
                                             "currencyCode": "USD"},
                    },
                    "currencyCode": "USD",
                    "createdAt": "2026-04-25T12:00:00Z",
                    "updatedAt": "2026-04-25T12:00:00Z",
                    "lineItems": {"edges": [
                        {"node": {
                            "title": "Cool Mug",
                            "quantity": 2,
                            "originalUnitPriceSet": {
                                "presentmentMoney": {"amount": "25.00",
                                                     "currencyCode": "USD"},
                            },
                        }},
                    ]},
                },
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_DRAFT_ORDER, {
                "line_items": [
                    {"variant_id": "gid://shopify/ProductVariant/999",
                     "quantity": 2},
                ],
                "email": "buyer@example.com",
            })
        assert result.ok
        d = result.data["draft_order"]
        assert d["id"] == "gid://shopify/DraftOrder/77"
        assert d["status"] == "OPEN"
        assert d["invoice_url"].startswith("https://")
        assert d["total"] == 55.0
        assert d["subtotal"] == 50.0
        assert d["currency"] == "USD"
        assert len(d["line_items"]) == 1
        assert d["line_items"][0]["unit_price"] == 25.0
        assert d["line_items"][0]["quantity"] == 2

    def test_create_draft_user_errors_propagate(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        a = ShopifyDraftOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "draftOrderCreate": {
                "draftOrder": None,
                "userErrors": [{
                    "field": ["lineItems", "0", "variantId"],
                    "message": "Variant does not exist",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_DRAFT_ORDER, {
                "line_items": [
                    {"variant_id": "gid://shopify/ProductVariant/0",
                     "quantity": 1},
                ],
            })
        assert not result.ok

    # ── Complete ─────────────────────────────────────────────

    def test_complete_draft_happy_path(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        a = ShopifyDraftOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "draftOrderComplete": {
                "draftOrder": {
                    "id": "gid://shopify/DraftOrder/77",
                    "status": "COMPLETED",
                    "order": {
                        "id": "gid://shopify/Order/1234",
                        "name": "#1001",
                    },
                },
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_COMPLETE_DRAFT_ORDER, {
                "id": "gid://shopify/DraftOrder/77",
            })
        assert result.ok
        assert result.data["status"] == "COMPLETED"
        assert result.data["order_id"] == "gid://shopify/Order/1234"
        assert result.data["order_name"] == "#1001"

    def test_complete_draft_requires_id(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        a = ShopifyDraftOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_COMPLETE_DRAFT_ORDER, {})
        assert not result.ok

    def test_complete_draft_passes_payment_pending_flag(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        a = ShopifyDraftOrdersAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["paymentPending"] = v["paymentPending"]
            captured["id"] = v["id"]
            return {"draftOrderComplete": {
                "draftOrder": {"id": v["id"], "status": "OPEN", "order": None},
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_COMPLETE_DRAFT_ORDER, {
                "id": "gid://shopify/DraftOrder/77",
                "payment_pending": True,
            })
        assert captured["paymentPending"] is True
        assert captured["id"] == "gid://shopify/DraftOrder/77"

    # ── List ──────────────────────────────────────────────────

    def test_list_drafts_happy_path(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        a = ShopifyDraftOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "draftOrders": {
                "pageInfo": {"hasNextPage": True, "endCursor": "cur"},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/DraftOrder/1",
                        "name": "#D1",
                        "status": "OPEN",
                        "invoiceUrl": "https://shop/invoice/1",
                        "totalPriceSet": {
                            "presentmentMoney": {"amount": "30.00",
                                                 "currencyCode": "USD"},
                        },
                        "subtotalPriceSet": {
                            "presentmentMoney": {"amount": "30.00",
                                                 "currencyCode": "USD"},
                        },
                        "createdAt": "2026-04-25T12:00:00Z",
                        "updatedAt": "2026-04-25T12:00:00Z",
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_DRAFT_ORDERS,
                               {"limit": 10})
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["has_next_page"] is True
        assert result.data["draft_orders"][0]["status"] == "OPEN"
        assert result.data["draft_orders"][0]["total"] == 30.0

    def test_list_drafts_clamps_limit(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        a = ShopifyDraftOrdersAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"draftOrders": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_DRAFT_ORDERS, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_drafts_passes_query_filter(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        a = ShopifyDraftOrdersAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = v["query"]
            return {"draftOrders": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_DRAFT_ORDERS,
                      {"query": "status:open"})
        assert captured["query"] == "status:open"

    def test_list_drafts_handles_empty_page(self):
        from core.adapters.shopify.draft_orders import ShopifyDraftOrdersAdapter
        a = ShopifyDraftOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "draftOrders": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                            "edges": []},
        }):
            result = a.execute(Capability.SHOPIFY_LIST_DRAFT_ORDERS, {})
        assert result.ok
        assert result.data["count"] == 0
        assert result.data["end_cursor"] == ""


# ── ShopifyFilesAdapter ─────────────────────────────────────


class TestShopifyFilesAdapter:
    def test_metadata(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        a = ShopifyFilesAdapter()
        assert a.name == "shopify_files"
        assert Capability.SHOPIFY_UPLOAD_FILE in a.capabilities
        assert Capability.SHOPIFY_LIST_FILES in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        a = ShopifyFilesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── _build_file_inputs validation ────────────────────────

    def test_build_inputs_single_url_form(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        out = ShopifyFilesAdapter._build_file_inputs({
            "url": "https://cdn.example.com/hero.jpg",
            "alt": "Product hero image",
        })
        assert len(out) == 1
        assert out[0]["originalSource"] == "https://cdn.example.com/hero.jpg"
        assert out[0]["contentType"] == "IMAGE"
        assert out[0]["alt"] == "Product hero image"

    def test_build_inputs_batch_form(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        out = ShopifyFilesAdapter._build_file_inputs({
            "files": [
                {"url": "https://cdn.example.com/a.jpg", "alt": "A"},
                {"url": "https://cdn.example.com/b.png", "alt": "B"},
            ],
        })
        assert len(out) == 2
        assert out[0]["originalSource"].endswith("/a.jpg")
        assert out[1]["originalSource"].endswith("/b.png")

    def test_build_inputs_requires_url_or_files(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyFilesAdapter._build_file_inputs({"alt": "foo"})
        assert "url" in str(exc.value) or "files" in str(exc.value)

    def test_build_inputs_empty_files_list_rejected(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyFilesAdapter._build_file_inputs({"files": []})

    def test_build_inputs_non_dict_entry_rejected(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyFilesAdapter._build_file_inputs({"files": ["not a dict"]})

    def test_build_inputs_missing_url_rejected(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyFilesAdapter._build_file_inputs({"files": [{"alt": "x"}]})
        assert "url" in str(exc.value)

    def test_build_inputs_rejects_non_http_urls(self):
        """Shopify only fetches public http(s) URLs. ``data:`` URIs
        and local file:// paths fail at fetch time with an opaque
        userErrors message — better to reject them up-front."""
        from core.adapters.shopify.files import ShopifyFilesAdapter
        for bad in (
            "data:image/png;base64,abc",
            "file:///c:/Users/x/img.png",
            "ftp://files.example.com/x.jpg",
            "/local/path/img.jpg",
        ):
            with pytest.raises(AdapterValidationError) as exc:
                ShopifyFilesAdapter._build_file_inputs({"url": bad})
            assert "http" in str(exc.value).lower()

    def test_build_inputs_content_type_aliases_resolve(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        for alias, expected in (
            ("image", "IMAGE"),
            ("photo", "IMAGE"),
            ("PHOTO", "IMAGE"),
            ("video", "VIDEO"),
            ("mp4", "VIDEO"),
            ("file", "FILE"),
            ("pdf", "FILE"),
        ):
            out = ShopifyFilesAdapter._build_file_inputs({
                "url": "https://x/y.bin", "type": alias,
            })
            assert out[0]["contentType"] == expected, alias

    def test_build_inputs_default_type_is_image(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        out = ShopifyFilesAdapter._build_file_inputs({"url": "https://x/y.jpg"})
        assert out[0]["contentType"] == "IMAGE"

    def test_build_inputs_unknown_type_rejected(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyFilesAdapter._build_file_inputs({
                "url": "https://x/y", "type": "spreadsheet",
            })

    def test_build_inputs_alt_truncated_to_512(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        long_alt = "x" * 1000
        out = ShopifyFilesAdapter._build_file_inputs({
            "url": "https://x/y.jpg", "alt": long_alt,
        })
        assert len(out[0]["alt"]) == 512

    def test_build_inputs_max_files_per_call_enforced(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        too_many = [{"url": f"https://x/{i}.jpg"} for i in range(251)]
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyFilesAdapter._build_file_inputs({"files": too_many})
        assert "250" in str(exc.value)

    # ── Upload — happy path ──────────────────────────────────

    def test_upload_files_single_image_happy_path(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        a = ShopifyFilesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "fileCreate": {
                "files": [{
                    "id": "gid://shopify/MediaImage/1",
                    "fileStatus": "UPLOADED",
                    "alt": "Hero",
                    "createdAt": "2026-04-25T12:00:00Z",
                    "image": {
                        "url": "https://cdn.shopify.com/s/files/.../hero.jpg",
                        "width": 1200,
                        "height": 800,
                    },
                    "mimeType": "image/jpeg",
                }],
                "userErrors": [],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_UPLOAD_FILE,
                {"url": "https://cdn.example.com/hero.jpg", "alt": "Hero"},
            )
        assert result.ok
        assert result.data["uploaded"] == 1
        f = result.data["files"][0]
        assert f["kind"] == "image"
        assert f["url"].endswith("/hero.jpg")
        assert f["width"] == 1200
        assert f["height"] == 800
        assert f["status"] == "UPLOADED"
        assert f["mime_type"] == "image/jpeg"

    def test_upload_files_user_errors_propagate(self):
        """If Shopify returns userErrors, the call must surface as a
        failure result so the router doesn't fall back."""
        from core.adapters.shopify.files import ShopifyFilesAdapter
        a = ShopifyFilesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "fileCreate": {
                "files": [],
                "userErrors": [{
                    "field": ["files", "0", "originalSource"],
                    "message": "URL is unreachable",
                    "code": "INVALID_URL",
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_UPLOAD_FILE,
                {"url": "https://broken.example.com/missing.jpg"},
            )
        assert not result.ok

    def test_upload_files_batch_passes_all_through(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        a = ShopifyFilesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["files"] = v["files"]
            return {
                "fileCreate": {
                    "files": [
                        {"id": f"gid://m/{i}", "fileStatus": "UPLOADED",
                         "image": {"url": f"https://cdn/{i}.jpg",
                                   "width": 100, "height": 100}}
                        for i in range(3)
                    ],
                    "userErrors": [],
                },
            }

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPLOAD_FILE, {
                "files": [
                    {"url": "https://x/1.jpg", "alt": "one"},
                    {"url": "https://x/2.jpg", "alt": "two"},
                    {"url": "https://x/3.jpg", "alt": "three"},
                ],
            })
        assert result.ok
        assert result.data["uploaded"] == 3
        assert len(captured["files"]) == 3
        assert captured["files"][0]["alt"] == "one"

    # ── _normalise_file ─────────────────────────────────────

    def test_normalise_image_lifts_image_subobject(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        out = ShopifyFilesAdapter._normalise_file({
            "id": "gid://1", "fileStatus": "READY", "alt": "x",
            "image": {"url": "https://cdn/y.jpg", "width": 50, "height": 60},
            "mimeType": "image/jpeg",
            "createdAt": "2026-01-01T00:00:00Z",
        })
        assert out["kind"] == "image"
        assert out["url"] == "https://cdn/y.jpg"
        assert out["width"] == 50
        assert out["height"] == 60
        assert out["mime_type"] == "image/jpeg"

    def test_normalise_generic_file(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        out = ShopifyFilesAdapter._normalise_file({
            "id": "gid://2", "fileStatus": "READY",
            "url": "https://cdn/x.pdf",
            "originalFileSize": "12345",
            "mimeType": "application/pdf",
        })
        assert out["kind"] == "file"
        assert out["url"] == "https://cdn/x.pdf"
        assert out["size_bytes"] == 12345
        assert out["mime_type"] == "application/pdf"

    def test_normalise_video_lifts_first_source(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        out = ShopifyFilesAdapter._normalise_file({
            "id": "gid://3", "fileStatus": "READY",
            "sources": [{
                "url": "https://cdn/v.mp4",
                "mimeType": "video/mp4",
                "format": "mp4",
                "width": 1920, "height": 1080,
            }],
        })
        assert out["kind"] == "video"
        assert out["url"] == "https://cdn/v.mp4"
        assert out["mime_type"] == "video/mp4"
        assert out["width"] == 1920
        assert out["height"] == 1080

    def test_normalise_handles_non_dict(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        assert ShopifyFilesAdapter._normalise_file(None) == {}  # type: ignore[arg-type]
        assert ShopifyFilesAdapter._normalise_file("not a dict") == {}  # type: ignore[arg-type]

    # ── List ──────────────────────────────────────────────────

    def test_list_files_happy_path(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        a = ShopifyFilesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "files": {
                "pageInfo": {"hasNextPage": True, "endCursor": "cur"},
                "edges": [
                    {"node": {
                        "id": "gid://1", "fileStatus": "READY",
                        "alt": "p1",
                        "image": {"url": "https://cdn/1.jpg",
                                  "width": 100, "height": 100},
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_FILES, {"limit": 5})
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["has_next_page"] is True
        assert result.data["end_cursor"] == "cur"
        assert result.data["files"][0]["url"] == "https://cdn/1.jpg"

    def test_list_files_clamps_limit_to_max(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        a = ShopifyFilesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"files": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_FILES, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_files_passes_query_through(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        a = ShopifyFilesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = v.get("query")
            return {"files": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_FILES,
                      {"query": "media_type:IMAGE"})
        assert captured["query"] == "media_type:IMAGE"

    def test_list_files_rejects_non_string_query(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        a = ShopifyFilesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_LIST_FILES, {"query": 123})
        assert not result.ok

    def test_list_files_handles_empty_page(self):
        from core.adapters.shopify.files import ShopifyFilesAdapter
        a = ShopifyFilesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "files": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                      "edges": []},
        }):
            result = a.execute(Capability.SHOPIFY_LIST_FILES, {})
        assert result.ok
        assert result.data["count"] == 0
        assert result.data["has_next_page"] is False
        assert result.data["end_cursor"] == ""


# ── ShopifyDiscountAdapter ──────────────────────────────────


class TestShopifyDiscountAdapter:
    def test_metadata(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter()
        assert a.name == "shopify_discount"
        assert Capability.SHOPIFY_CREATE_DISCOUNT in a.capabilities
        assert Capability.SHOPIFY_LIST_DISCOUNTS in a.capabilities

    def test_unsupported_capability_rejected(self):
        """``execute()`` catches AdapterValidationError and returns a
        failure result (the router relies on that); the underlying
        ``_execute`` is what raises. Assert the failure envelope so
        the test mirrors the real call site shape."""
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        # The router asks the adapter what capabilities it supports
        # before calling execute() in production; here we exercise
        # the defensive path inside _execute itself.
        assert not result.ok

    # ── _build_basic_input validation ────────────────────────

    def test_build_input_requires_title(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyDiscountAdapter._build_basic_input({"code": "X", "percentage": 10})
        assert "title" in str(exc.value)

    def test_build_input_requires_code(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyDiscountAdapter._build_basic_input({"title": "T", "percentage": 10})
        assert "code" in str(exc.value)

    def test_build_input_requires_percentage_or_amount(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyDiscountAdapter._build_basic_input({"title": "T", "code": "X"})
        assert "percentage" in str(exc.value) or "amount" in str(exc.value)

    def test_build_input_rejects_both_percentage_and_amount(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyDiscountAdapter._build_basic_input({
                "title": "T", "code": "X", "percentage": 10, "amount": 5,
            })
        assert "mutually exclusive" in str(exc.value)

    def test_build_input_percentage_converted_to_fraction(self):
        """Shopify's DiscountPercentageValueInput.percentage is a 0-1
        fraction, not a 0-100 number. 25% input must become 0.25 in
        the GraphQL payload."""
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        out = ShopifyDiscountAdapter._build_basic_input({
            "title": "Summer", "code": "S25", "percentage": 25,
        })
        assert out["customerGets"]["value"]["percentage"] == 0.25

    def test_build_input_percentage_range_validated(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        for bad in (0, -5, 100.1, 200):
            with pytest.raises(AdapterValidationError):
                ShopifyDiscountAdapter._build_basic_input({
                    "title": "T", "code": "X", "percentage": bad,
                })

    def test_build_input_amount_uses_fixed_amount_branch(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        out = ShopifyDiscountAdapter._build_basic_input({
            "title": "FixedTen", "code": "TEN", "amount": 10,
        })
        value = out["customerGets"]["value"]
        assert "discountAmount" in value
        # Shopify expects amount as a string with 2 decimals.
        assert value["discountAmount"]["amount"] == "10.00"
        assert value["discountAmount"]["appliesOnEachItem"] is False

    def test_build_input_amount_must_be_positive(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyDiscountAdapter._build_basic_input({
                "title": "T", "code": "X", "amount": 0,
            })
        with pytest.raises(AdapterValidationError):
            ShopifyDiscountAdapter._build_basic_input({
                "title": "T", "code": "X", "amount": -5,
            })

    def test_build_input_amount_non_numeric_rejected(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyDiscountAdapter._build_basic_input({
                "title": "T", "code": "X", "amount": "free",
            })

    def test_build_input_dates_pass_through(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        out = ShopifyDiscountAdapter._build_basic_input({
            "title": "T", "code": "X", "percentage": 10,
            "starts_at": "2026-06-01T00:00:00Z",
            "ends_at": "2026-08-31T23:59:59Z",
        })
        assert out["startsAt"] == "2026-06-01T00:00:00Z"
        assert out["endsAt"] == "2026-08-31T23:59:59Z"

    def test_build_input_dates_must_be_strings(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyDiscountAdapter._build_basic_input({
                "title": "T", "code": "X", "percentage": 10,
                "starts_at": 1234567890,
            })

    def test_build_input_usage_limit_validated(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        out = ShopifyDiscountAdapter._build_basic_input({
            "title": "T", "code": "X", "percentage": 10, "usage_limit": 100,
        })
        assert out["usageLimit"] == 100

        with pytest.raises(AdapterValidationError):
            ShopifyDiscountAdapter._build_basic_input({
                "title": "T", "code": "X", "percentage": 10, "usage_limit": 0,
            })
        with pytest.raises(AdapterValidationError):
            ShopifyDiscountAdapter._build_basic_input({
                "title": "T", "code": "X", "percentage": 10, "usage_limit": "many",
            })

    def test_build_input_applies_once_per_customer_default_true(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        out = ShopifyDiscountAdapter._build_basic_input({
            "title": "T", "code": "X", "percentage": 10,
        })
        assert out["appliesOncePerCustomer"] is True

    def test_build_input_applies_once_per_customer_can_be_false(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        out = ShopifyDiscountAdapter._build_basic_input({
            "title": "T", "code": "X", "percentage": 10,
            "applies_once_per_customer": False,
        })
        assert out["appliesOncePerCustomer"] is False

    # ── Create — happy path ──────────────────────────────────

    def test_create_discount_happy_path(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "discountCodeBasicCreate": {
                "codeDiscountNode": {
                    "id": "gid://shopify/DiscountCodeNode/1",
                    "codeDiscount": {
                        "title": "Summer 25%",
                        "summary": "25% off all items",
                        "status": "ACTIVE",
                        "startsAt": "2026-06-01T00:00:00Z",
                        "endsAt": "2026-08-31T23:59:59Z",
                        "usageLimit": 500,
                        "appliesOncePerCustomer": True,
                        "codes": {"nodes": [{"code": "SUMMER25"}]},
                    },
                },
                "userErrors": [],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_DISCOUNT,
                {
                    "title": "Summer 25%",
                    "code": "SUMMER25",
                    "percentage": 25,
                    "starts_at": "2026-06-01T00:00:00Z",
                    "ends_at": "2026-08-31T23:59:59Z",
                    "usage_limit": 500,
                },
            )
        assert result.ok
        assert result.data["id"] == "gid://shopify/DiscountCodeNode/1"
        assert result.data["code"] == "SUMMER25"
        assert result.data["title"] == "Summer 25%"
        assert result.data["status"] == "ACTIVE"
        assert result.data["usage_limit"] == 500

    def test_create_discount_user_errors_fail_fast(self):
        """Shopify returns a userErrors array when the input was
        accepted by the schema but rejected by business rules
        (e.g. duplicate code). The adapter must promote that to
        AdapterValidationError so the router doesn't fall back."""
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "discountCodeBasicCreate": {
                "codeDiscountNode": None,
                "userErrors": [{
                    "field": ["basicCodeDiscount", "code"],
                    "message": "Code is already in use",
                    "code": "TAKEN",
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_DISCOUNT,
                {"title": "T", "code": "X", "percentage": 10},
            )
        assert not result.ok
        assert "TAKEN" in str(result.error or "") or "in use" in str(result.error or "")

    # ── List ──────────────────────────────────────────────────

    def test_list_discounts_happy_path(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "codeDiscountNodes": {
                "pageInfo": {"hasNextPage": True, "endCursor": "cur123"},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/DiscountCodeNode/1",
                        "codeDiscount": {
                            "title": "Summer 25%",
                            "summary": "25% off",
                            "status": "ACTIVE",
                            "startsAt": "2026-06-01T00:00:00Z",
                            "endsAt": "2026-08-31T23:59:59Z",
                            "usageLimit": 500,
                            "asyncUsageCount": 42,
                            "appliesOncePerCustomer": True,
                            "codes": {"nodes": [{"code": "SUMMER25"}]},
                        },
                    }},
                ],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_DISCOUNTS,
                {"limit": 10},
            )
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["has_next_page"] is True
        assert result.data["end_cursor"] == "cur123"
        d = result.data["discounts"][0]
        assert d["code"] == "SUMMER25"
        assert d["usage_count"] == 42

    def test_list_discounts_clamps_limit_to_max(self):
        """codeDiscountNodes accepts at most 250 per call. A caller
        asking for 9999 must be silently clamped — the request must
        succeed with what Shopify allows."""
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"codeDiscountNodes": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_DISCOUNTS, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_discounts_default_limit_when_omitted(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"codeDiscountNodes": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_DISCOUNTS, {})
        assert captured["first"] == 50

    def test_list_discounts_invalid_limit_falls_back_to_default(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"codeDiscountNodes": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_DISCOUNTS, {"limit": "many"})
        assert captured["first"] == 50

    def test_list_discounts_passes_cursor_through(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["after"] = v["after"]
            return {"codeDiscountNodes": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_DISCOUNTS,
                {"cursor": "cur123"},
            )
        assert captured["after"] == "cur123"

    def test_list_discounts_rejects_non_string_cursor(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(
                Capability.SHOPIFY_LIST_DISCOUNTS,
                {"cursor": 12345},
            )
        assert not result.ok

    def test_list_discounts_handles_empty_page(self):
        from core.adapters.shopify.discounts import ShopifyDiscountAdapter
        a = ShopifyDiscountAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "codeDiscountNodes": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_DISCOUNTS, {})
        assert result.ok
        assert result.data["count"] == 0
        assert result.data["has_next_page"] is False
        assert result.data["end_cursor"] == ""
