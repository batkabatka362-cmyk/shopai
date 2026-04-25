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
    def test_register_all_adds_seventyone_adapters(self):
        from core.adapters.shopify.bootstrap import register_all
        status = register_all()
        assert len(status) == 71
        assert set(status.keys()) == {
            "shopify_risk", "shopify_inventory",
            "shopify_fulfillment", "shopify_metafield",
            "shopify_discount", "shopify_files",
            "shopify_draft_orders", "shopify_marketing_events",
            "shopify_returns", "shopify_metaobjects",
            "shopify_publications", "shopify_order_edits",
            "shopify_themes", "shopify_analytics",
            "shopify_translations", "shopify_customer_segments",
            "shopify_refunds",
            "shopify_payment_customizations",
            "shopify_delivery_customizations",
            "shopify_gift_cards",
            "shopify_subscription_contracts",
            "shopify_markets",
            "shopify_web_pixels",
            "shopify_companies",
            "shopify_locations",
            "shopify_inventory_shipments",
            "shopify_channels",
            "shopify_cart_transforms",
            "shopify_validations",
            "shopify_products",
            "shopify_orders",
            "shopify_customers",
            "shopify_webhooks",
            "shopify_bulk",
            "shopify_shop",
            "shopify_pages",
            "shopify_articles",
            "shopify_bulk_mutations",
            "shopify_disputes",
            "shopify_delivery_profiles",
            "shopify_draft_order_calculate",
            "shopify_selling_plan_groups",
            "shopify_customer_payment_methods",
            "shopify_apps",
            "shopify_abandoned_checkouts",
            "shopify_collections",
            "shopify_metafield_definitions",
            "shopify_price_lists",
            "shopify_carrier_services",
            "shopify_fulfillment_services",
            "shopify_discount_automatic",
            "shopify_metaobject_definitions",
            "shopify_script_tags",
            "shopify_order_transactions",
            "shopify_payment_terms",
            "shopify_market_web_presences",
            "shopify_draft_order_invoice",
            "shopify_customer_merge",
            "shopify_fulfillment_events",
            "shopify_customer_consent",
            "shopify_inventory_activation",
            "shopify_discount_code_bxgy",
            "shopify_subscription_draft",
            "shopify_catalogs",
            "shopify_fulfillment_hold",
            "shopify_payments_payouts",
            "shopify_order_invoice",
            "shopify_company_contact_roles",
            "shopify_metaobjects_upsert",
            "shopify_app_subscriptions",
            "shopify_discount_code_free_shipping",
        }

    def test_register_all_idempotent(self):
        from core.adapters.shopify.bootstrap import register_all
        register_all()
        # Second call must not raise
        register_all()
        assert len(get_registry()) == 71

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
        assert router.route(Capability.SHOPIFY_LIST_RETURNS).name == "shopify_returns"
        assert router.route(Capability.SHOPIFY_GET_RETURN).name == "shopify_returns"
        assert router.route(Capability.SHOPIFY_APPROVE_RETURN).name == "shopify_returns"
        assert router.route(Capability.SHOPIFY_DECLINE_RETURN).name == "shopify_returns"
        assert router.route(Capability.SHOPIFY_CREATE_METAOBJECT).name == "shopify_metaobjects"
        assert router.route(Capability.SHOPIFY_UPDATE_METAOBJECT).name == "shopify_metaobjects"
        assert router.route(Capability.SHOPIFY_GET_METAOBJECT).name == "shopify_metaobjects"
        assert router.route(Capability.SHOPIFY_LIST_METAOBJECTS).name == "shopify_metaobjects"
        assert router.route(Capability.SHOPIFY_LIST_PUBLICATIONS).name == "shopify_publications"
        assert router.route(Capability.SHOPIFY_PUBLISH_RESOURCE).name == "shopify_publications"
        assert router.route(Capability.SHOPIFY_UNPUBLISH_RESOURCE).name == "shopify_publications"
        assert router.route(Capability.SHOPIFY_EDIT_ORDER).name == "shopify_order_edits"
        assert router.route(Capability.SHOPIFY_LIST_THEMES).name == "shopify_themes"
        assert router.route(Capability.SHOPIFY_LIST_THEME_FILES).name == "shopify_themes"
        assert router.route(Capability.SHOPIFY_UPSERT_THEME_FILES).name == "shopify_themes"
        assert router.route(Capability.SHOPIFY_RUN_ANALYTICS_QUERY).name == "shopify_analytics"
        assert router.route(Capability.SHOPIFY_GET_TRANSLATABLE_RESOURCE).name == "shopify_translations"
        assert router.route(Capability.SHOPIFY_REGISTER_TRANSLATIONS).name == "shopify_translations"
        assert router.route(Capability.SHOPIFY_REMOVE_TRANSLATIONS).name == "shopify_translations"
        assert router.route(Capability.SHOPIFY_QUERY_SEGMENT).name == "shopify_customer_segments"
        assert router.route(Capability.SHOPIFY_GET_SEGMENT_MEMBERS).name == "shopify_customer_segments"
        assert router.route(Capability.SHOPIFY_CREATE_SEGMENT).name == "shopify_customer_segments"
        assert router.route(Capability.SHOPIFY_CREATE_REFUND).name == "shopify_refunds"
        assert router.route(Capability.SHOPIFY_LIST_ORDER_REFUNDS).name == "shopify_refunds"
        assert router.route(Capability.SHOPIFY_GET_REFUND).name == "shopify_refunds"
        assert router.route(Capability.SHOPIFY_CREATE_PAYMENT_CUSTOMIZATION).name == "shopify_payment_customizations"
        assert router.route(Capability.SHOPIFY_LIST_PAYMENT_CUSTOMIZATIONS).name == "shopify_payment_customizations"
        assert router.route(Capability.SHOPIFY_DELETE_PAYMENT_CUSTOMIZATION).name == "shopify_payment_customizations"
        assert router.route(Capability.SHOPIFY_CREATE_DELIVERY_CUSTOMIZATION).name == "shopify_delivery_customizations"
        assert router.route(Capability.SHOPIFY_LIST_DELIVERY_CUSTOMIZATIONS).name == "shopify_delivery_customizations"
        assert router.route(Capability.SHOPIFY_DELETE_DELIVERY_CUSTOMIZATION).name == "shopify_delivery_customizations"
        assert router.route(Capability.SHOPIFY_CREATE_GIFT_CARD).name == "shopify_gift_cards"
        assert router.route(Capability.SHOPIFY_LIST_GIFT_CARDS).name == "shopify_gift_cards"
        assert router.route(Capability.SHOPIFY_GET_GIFT_CARD).name == "shopify_gift_cards"
        assert router.route(Capability.SHOPIFY_DEACTIVATE_GIFT_CARD).name == "shopify_gift_cards"
        assert router.route(Capability.SHOPIFY_LIST_SUBSCRIPTION_CONTRACTS).name == "shopify_subscription_contracts"
        assert router.route(Capability.SHOPIFY_GET_SUBSCRIPTION_CONTRACT).name == "shopify_subscription_contracts"
        assert router.route(Capability.SHOPIFY_PAUSE_SUBSCRIPTION_CONTRACT).name == "shopify_subscription_contracts"
        assert router.route(Capability.SHOPIFY_RESUME_SUBSCRIPTION_CONTRACT).name == "shopify_subscription_contracts"
        assert router.route(Capability.SHOPIFY_CANCEL_SUBSCRIPTION_CONTRACT).name == "shopify_subscription_contracts"
        assert router.route(Capability.SHOPIFY_LIST_MARKETS).name == "shopify_markets"
        assert router.route(Capability.SHOPIFY_GET_MARKET).name == "shopify_markets"
        assert router.route(Capability.SHOPIFY_LIST_SHOP_LOCALES).name == "shopify_markets"
        assert router.route(Capability.SHOPIFY_CREATE_WEB_PIXEL).name == "shopify_web_pixels"
        assert router.route(Capability.SHOPIFY_UPDATE_WEB_PIXEL).name == "shopify_web_pixels"
        assert router.route(Capability.SHOPIFY_DELETE_WEB_PIXEL).name == "shopify_web_pixels"
        assert router.route(Capability.SHOPIFY_LIST_COMPANIES).name == "shopify_companies"
        assert router.route(Capability.SHOPIFY_GET_COMPANY).name == "shopify_companies"
        assert router.route(Capability.SHOPIFY_CREATE_COMPANY).name == "shopify_companies"
        assert router.route(Capability.SHOPIFY_LIST_LOCATIONS).name == "shopify_locations"
        assert router.route(Capability.SHOPIFY_GET_LOCATION).name == "shopify_locations"
        assert router.route(Capability.SHOPIFY_CREATE_LOCATION).name == "shopify_locations"
        assert router.route(Capability.SHOPIFY_UPDATE_LOCATION).name == "shopify_locations"
        assert router.route(Capability.SHOPIFY_LIST_INVENTORY_SHIPMENTS).name == "shopify_inventory_shipments"
        assert router.route(Capability.SHOPIFY_GET_INVENTORY_SHIPMENT).name == "shopify_inventory_shipments"
        assert router.route(Capability.SHOPIFY_CREATE_INVENTORY_SHIPMENT).name == "shopify_inventory_shipments"
        assert router.route(Capability.SHOPIFY_LIST_CHANNELS).name == "shopify_channels"
        assert router.route(Capability.SHOPIFY_CREATE_CART_TRANSFORM).name == "shopify_cart_transforms"
        assert router.route(Capability.SHOPIFY_LIST_CART_TRANSFORMS).name == "shopify_cart_transforms"
        assert router.route(Capability.SHOPIFY_DELETE_CART_TRANSFORM).name == "shopify_cart_transforms"
        assert router.route(Capability.SHOPIFY_CREATE_VALIDATION).name == "shopify_validations"
        assert router.route(Capability.SHOPIFY_LIST_VALIDATIONS).name == "shopify_validations"
        assert router.route(Capability.SHOPIFY_DELETE_VALIDATION).name == "shopify_validations"
        assert router.route(Capability.SHOPIFY_LIST_PRODUCTS).name == "shopify_products"
        assert router.route(Capability.SHOPIFY_GET_PRODUCT).name == "shopify_products"
        assert router.route(Capability.SHOPIFY_CREATE_PRODUCT).name == "shopify_products"
        assert router.route(Capability.SHOPIFY_UPDATE_PRODUCT).name == "shopify_products"
        assert router.route(Capability.SHOPIFY_DELETE_PRODUCT).name == "shopify_products"
        assert router.route(Capability.SHOPIFY_UPDATE_VARIANTS).name == "shopify_products"
        assert router.route(Capability.SHOPIFY_LIST_ORDERS).name == "shopify_orders"
        assert router.route(Capability.SHOPIFY_GET_ORDER).name == "shopify_orders"
        assert router.route(Capability.SHOPIFY_UPDATE_ORDER).name == "shopify_orders"
        assert router.route(Capability.SHOPIFY_TAG_ORDER).name == "shopify_orders"
        assert router.route(Capability.SHOPIFY_UNTAG_ORDER).name == "shopify_orders"
        assert router.route(Capability.SHOPIFY_CLOSE_ORDER).name == "shopify_orders"
        assert router.route(Capability.SHOPIFY_FETCH_CUSTOMERS).name == "shopify_customers"
        assert router.route(Capability.SHOPIFY_GET_CUSTOMER).name == "shopify_customers"
        assert router.route(Capability.SHOPIFY_CREATE_CUSTOMER).name == "shopify_customers"
        assert router.route(Capability.SHOPIFY_UPDATE_CUSTOMER).name == "shopify_customers"
        assert router.route(Capability.SHOPIFY_TAG_CUSTOMER).name == "shopify_customers"
        assert router.route(Capability.SHOPIFY_UNTAG_CUSTOMER).name == "shopify_customers"
        assert router.route(Capability.SHOPIFY_DELETE_CUSTOMER).name == "shopify_customers"
        assert router.route(Capability.SHOPIFY_LIST_WEBHOOKS).name == "shopify_webhooks"
        assert router.route(Capability.SHOPIFY_CREATE_WEBHOOK).name == "shopify_webhooks"
        assert router.route(Capability.SHOPIFY_UPDATE_WEBHOOK).name == "shopify_webhooks"
        assert router.route(Capability.SHOPIFY_DELETE_WEBHOOK).name == "shopify_webhooks"
        assert router.route(Capability.SHOPIFY_RUN_BULK_QUERY).name == "shopify_bulk"
        assert router.route(Capability.SHOPIFY_GET_BULK_OPERATION).name == "shopify_bulk"
        assert router.route(Capability.SHOPIFY_CANCEL_BULK_OPERATION).name == "shopify_bulk"
        assert router.route(Capability.SHOPIFY_GET_SHOP).name == "shopify_shop"
        assert router.route(Capability.SHOPIFY_GET_SHOP_POLICIES).name == "shopify_shop"
        assert router.route(Capability.SHOPIFY_LIST_CURRENCIES).name == "shopify_shop"
        assert router.route(Capability.SHOPIFY_LIST_PAGES).name == "shopify_pages"
        assert router.route(Capability.SHOPIFY_GET_PAGE).name == "shopify_pages"
        assert router.route(Capability.SHOPIFY_CREATE_PAGE).name == "shopify_pages"
        assert router.route(Capability.SHOPIFY_UPDATE_PAGE).name == "shopify_pages"
        assert router.route(Capability.SHOPIFY_DELETE_PAGE).name == "shopify_pages"
        assert router.route(Capability.SHOPIFY_LIST_BLOGS).name == "shopify_articles"
        assert router.route(Capability.SHOPIFY_LIST_ARTICLES).name == "shopify_articles"
        assert router.route(Capability.SHOPIFY_GET_ARTICLE).name == "shopify_articles"
        assert router.route(Capability.SHOPIFY_CREATE_ARTICLE).name == "shopify_articles"
        assert router.route(Capability.SHOPIFY_UPDATE_ARTICLE).name == "shopify_articles"
        assert router.route(Capability.SHOPIFY_DELETE_ARTICLE).name == "shopify_articles"
        assert router.route(Capability.SHOPIFY_STAGE_UPLOAD).name == "shopify_bulk_mutations"
        assert router.route(Capability.SHOPIFY_RUN_BULK_MUTATION).name == "shopify_bulk_mutations"
        assert router.route(Capability.SHOPIFY_LIST_DISPUTES).name == "shopify_disputes"
        assert router.route(Capability.SHOPIFY_GET_DISPUTE).name == "shopify_disputes"
        assert router.route(Capability.SHOPIFY_LIST_DELIVERY_PROFILES).name == "shopify_delivery_profiles"
        assert router.route(Capability.SHOPIFY_GET_DELIVERY_PROFILE).name == "shopify_delivery_profiles"
        assert router.route(Capability.SHOPIFY_GET_DELIVERY_SETTINGS).name == "shopify_delivery_profiles"
        assert router.route(Capability.SHOPIFY_CALCULATE_DRAFT_ORDER).name == "shopify_draft_order_calculate"
        assert router.route(Capability.SHOPIFY_LIST_SELLING_PLAN_GROUPS).name == "shopify_selling_plan_groups"
        assert router.route(Capability.SHOPIFY_GET_SELLING_PLAN_GROUP).name == "shopify_selling_plan_groups"
        assert router.route(Capability.SHOPIFY_LIST_CUSTOMER_PAYMENT_METHODS).name == "shopify_customer_payment_methods"
        assert router.route(Capability.SHOPIFY_GET_CUSTOMER_PAYMENT_METHOD).name == "shopify_customer_payment_methods"
        assert router.route(Capability.SHOPIFY_REVOKE_CUSTOMER_PAYMENT_METHOD).name == "shopify_customer_payment_methods"
        assert router.route(Capability.SHOPIFY_GET_CURRENT_APP_INSTALLATION).name == "shopify_apps"
        assert router.route(Capability.SHOPIFY_LIST_APP_INSTALLATIONS).name == "shopify_apps"
        assert router.route(Capability.SHOPIFY_LIST_ABANDONED_CHECKOUTS).name == "shopify_abandoned_checkouts"
        assert router.route(Capability.SHOPIFY_GET_ABANDONED_CHECKOUT).name == "shopify_abandoned_checkouts"
        assert router.route(Capability.SHOPIFY_LIST_COLLECTIONS).name == "shopify_collections"
        assert router.route(Capability.SHOPIFY_GET_COLLECTION).name == "shopify_collections"
        assert router.route(Capability.SHOPIFY_CREATE_COLLECTION).name == "shopify_collections"
        assert router.route(Capability.SHOPIFY_UPDATE_COLLECTION).name == "shopify_collections"
        assert router.route(Capability.SHOPIFY_DELETE_COLLECTION).name == "shopify_collections"
        assert router.route(Capability.SHOPIFY_LIST_METAFIELD_DEFINITIONS).name == "shopify_metafield_definitions"
        assert router.route(Capability.SHOPIFY_CREATE_METAFIELD_DEFINITION).name == "shopify_metafield_definitions"
        assert router.route(Capability.SHOPIFY_DELETE_METAFIELD_DEFINITION).name == "shopify_metafield_definitions"
        assert router.route(Capability.SHOPIFY_LIST_PRICE_LISTS).name == "shopify_price_lists"
        assert router.route(Capability.SHOPIFY_GET_PRICE_LIST).name == "shopify_price_lists"
        assert router.route(Capability.SHOPIFY_CREATE_PRICE_LIST).name == "shopify_price_lists"
        assert router.route(Capability.SHOPIFY_DELETE_PRICE_LIST).name == "shopify_price_lists"
        assert router.route(Capability.SHOPIFY_LIST_CARRIER_SERVICES).name == "shopify_carrier_services"
        assert router.route(Capability.SHOPIFY_CREATE_CARRIER_SERVICE).name == "shopify_carrier_services"
        assert router.route(Capability.SHOPIFY_UPDATE_CARRIER_SERVICE).name == "shopify_carrier_services"
        assert router.route(Capability.SHOPIFY_DELETE_CARRIER_SERVICE).name == "shopify_carrier_services"
        assert router.route(Capability.SHOPIFY_LIST_FULFILLMENT_SERVICES).name == "shopify_fulfillment_services"
        assert router.route(Capability.SHOPIFY_CREATE_FULFILLMENT_SERVICE).name == "shopify_fulfillment_services"
        assert router.route(Capability.SHOPIFY_UPDATE_FULFILLMENT_SERVICE).name == "shopify_fulfillment_services"
        assert router.route(Capability.SHOPIFY_DELETE_FULFILLMENT_SERVICE).name == "shopify_fulfillment_services"
        assert router.route(Capability.SHOPIFY_LIST_AUTOMATIC_DISCOUNTS).name == "shopify_discount_automatic"
        assert router.route(Capability.SHOPIFY_CREATE_AUTOMATIC_DISCOUNT).name == "shopify_discount_automatic"
        assert router.route(Capability.SHOPIFY_DELETE_AUTOMATIC_DISCOUNT).name == "shopify_discount_automatic"
        assert router.route(Capability.SHOPIFY_LIST_METAOBJECT_DEFINITIONS).name == "shopify_metaobject_definitions"
        assert router.route(Capability.SHOPIFY_GET_METAOBJECT_DEFINITION).name == "shopify_metaobject_definitions"
        assert router.route(Capability.SHOPIFY_CREATE_METAOBJECT_DEFINITION).name == "shopify_metaobject_definitions"
        assert router.route(Capability.SHOPIFY_DELETE_METAOBJECT_DEFINITION).name == "shopify_metaobject_definitions"
        assert router.route(Capability.SHOPIFY_LIST_SCRIPT_TAGS).name == "shopify_script_tags"
        assert router.route(Capability.SHOPIFY_CREATE_SCRIPT_TAG).name == "shopify_script_tags"
        assert router.route(Capability.SHOPIFY_UPDATE_SCRIPT_TAG).name == "shopify_script_tags"
        assert router.route(Capability.SHOPIFY_DELETE_SCRIPT_TAG).name == "shopify_script_tags"
        assert router.route(Capability.SHOPIFY_LIST_ORDER_TRANSACTIONS).name == "shopify_order_transactions"
        assert router.route(Capability.SHOPIFY_GET_TRANSACTION).name == "shopify_order_transactions"
        assert router.route(Capability.SHOPIFY_LIST_PAYMENT_TERMS_TEMPLATES).name == "shopify_payment_terms"
        assert router.route(Capability.SHOPIFY_CREATE_PAYMENT_TERMS).name == "shopify_payment_terms"
        assert router.route(Capability.SHOPIFY_UPDATE_PAYMENT_TERMS).name == "shopify_payment_terms"
        assert router.route(Capability.SHOPIFY_DELETE_PAYMENT_TERMS).name == "shopify_payment_terms"
        assert router.route(Capability.SHOPIFY_LIST_MARKET_WEB_PRESENCES).name == "shopify_market_web_presences"
        assert router.route(Capability.SHOPIFY_GET_MARKET_WEB_PRESENCE).name == "shopify_market_web_presences"
        assert router.route(Capability.SHOPIFY_PREVIEW_DRAFT_ORDER_INVOICE).name == "shopify_draft_order_invoice"
        assert router.route(Capability.SHOPIFY_SEND_DRAFT_ORDER_INVOICE).name == "shopify_draft_order_invoice"
        assert router.route(Capability.SHOPIFY_PREVIEW_CUSTOMER_MERGE).name == "shopify_customer_merge"
        assert router.route(Capability.SHOPIFY_MERGE_CUSTOMERS).name == "shopify_customer_merge"
        assert router.route(Capability.SHOPIFY_GET_CUSTOMER_MERGE_JOB).name == "shopify_customer_merge"
        assert router.route(Capability.SHOPIFY_LIST_FULFILLMENT_EVENTS).name == "shopify_fulfillment_events"
        assert router.route(Capability.SHOPIFY_CREATE_FULFILLMENT_EVENT).name == "shopify_fulfillment_events"
        assert router.route(Capability.SHOPIFY_UPDATE_SMS_CONSENT).name == "shopify_customer_consent"
        assert router.route(Capability.SHOPIFY_UPDATE_EMAIL_CONSENT).name == "shopify_customer_consent"
        assert router.route(Capability.SHOPIFY_ACTIVATE_INVENTORY_AT_LOCATION).name == "shopify_inventory_activation"
        assert router.route(Capability.SHOPIFY_DEACTIVATE_INVENTORY_AT_LOCATION).name == "shopify_inventory_activation"
        assert router.route(Capability.SHOPIFY_ADJUST_INVENTORY_QUANTITIES).name == "shopify_inventory_activation"
        assert router.route(Capability.SHOPIFY_CREATE_DISCOUNT_BXGY).name == "shopify_discount_code_bxgy"
        assert router.route(Capability.SHOPIFY_DELETE_DISCOUNT_BXGY).name == "shopify_discount_code_bxgy"
        assert router.route(Capability.SHOPIFY_CREATE_SUBSCRIPTION_DRAFT).name == "shopify_subscription_draft"
        assert router.route(Capability.SHOPIFY_UPDATE_SUBSCRIPTION_DRAFT).name == "shopify_subscription_draft"
        assert router.route(Capability.SHOPIFY_COMMIT_SUBSCRIPTION_DRAFT).name == "shopify_subscription_draft"
        assert router.route(Capability.SHOPIFY_LIST_CATALOGS).name == "shopify_catalogs"
        assert router.route(Capability.SHOPIFY_GET_CATALOG).name == "shopify_catalogs"
        assert router.route(Capability.SHOPIFY_HOLD_FULFILLMENT_ORDER).name == "shopify_fulfillment_hold"
        assert router.route(Capability.SHOPIFY_RELEASE_FULFILLMENT_ORDER_HOLD).name == "shopify_fulfillment_hold"
        assert router.route(Capability.SHOPIFY_LIST_PAYOUTS).name == "shopify_payments_payouts"
        assert router.route(Capability.SHOPIFY_GET_PAYOUT).name == "shopify_payments_payouts"
        assert router.route(Capability.SHOPIFY_GET_PAYMENTS_BALANCE).name == "shopify_payments_payouts"
        assert router.route(Capability.SHOPIFY_SEND_ORDER_INVOICE).name == "shopify_order_invoice"
        assert router.route(Capability.SHOPIFY_LIST_COMPANY_CONTACT_ROLES).name == "shopify_company_contact_roles"
        assert router.route(Capability.SHOPIFY_ASSIGN_COMPANY_CONTACT_ROLE).name == "shopify_company_contact_roles"
        assert router.route(Capability.SHOPIFY_REVOKE_COMPANY_CONTACT_ROLE).name == "shopify_company_contact_roles"
        assert router.route(Capability.SHOPIFY_UPSERT_METAOBJECT).name == "shopify_metaobjects_upsert"
        assert router.route(Capability.SHOPIFY_BULK_DELETE_METAOBJECTS).name == "shopify_metaobjects_upsert"
        assert router.route(Capability.SHOPIFY_LIST_APP_SUBSCRIPTIONS).name == "shopify_app_subscriptions"
        assert router.route(Capability.SHOPIFY_CREATE_APP_SUBSCRIPTION).name == "shopify_app_subscriptions"
        assert router.route(Capability.SHOPIFY_CANCEL_APP_SUBSCRIPTION).name == "shopify_app_subscriptions"
        assert router.route(Capability.SHOPIFY_CREATE_DISCOUNT_FREE_SHIPPING).name == "shopify_discount_code_free_shipping"
        assert router.route(Capability.SHOPIFY_DELETE_DISCOUNT_FREE_SHIPPING).name == "shopify_discount_code_free_shipping"


# ── ShopifyValidationsAdapter ────────────────────────────


class TestShopifyValidationsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        a = ShopifyValidationsAdapter()
        assert a.name == "shopify_validations"
        for cap in (
            Capability.SHOPIFY_CREATE_VALIDATION,
            Capability.SHOPIFY_LIST_VALIDATIONS,
            Capability.SHOPIFY_DELETE_VALIDATION,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        a = ShopifyValidationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── _build_create_input ──────────────────────

    def test_build_input_requires_function_id(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyValidationsAdapter._build_create_input({})

    def test_build_input_enabled_defaults_true(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        out = ShopifyValidationsAdapter._build_create_input({
            "function_id": "fn-1",
        })
        assert out["enable"] is True
        assert out["blockOnFailure"] is False  # default-False

    def test_build_input_block_on_failure_can_be_true(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        out = ShopifyValidationsAdapter._build_create_input({
            "function_id": "fn-1",
            "block_on_failure": True,
        })
        assert out["blockOnFailure"] is True

    def test_build_input_title_pass_through(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        out = ShopifyValidationsAdapter._build_create_input({
            "function_id": "fn-1",
            "title": "Block sub-$25 orders",
        })
        assert out["title"] == "Block sub-$25 orders"

    def test_build_input_title_must_be_string(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyValidationsAdapter._build_create_input({
                "function_id": "fn-1", "title": 12345,
            })

    def test_build_input_metafields_coerced(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        out = ShopifyValidationsAdapter._build_create_input({
            "function_id": "fn-1",
            "metafields": [
                {"key": "min_total", "value": 25},
            ],
        })
        # Numeric coerced to string per metafield convention.
        assert out["metafields"][0]["value"] == "25"

    # ── Create — happy path ─────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        a = ShopifyValidationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"validationCreate": {
                "validation": {
                    "id": "gid://shopify/Validation/9",
                    "title": v["validation"].get("title", ""),
                    "enabled": v["validation"]["enable"],
                    "blockOnFailure": v["validation"]["blockOnFailure"],
                    "shopifyFunction": {
                        "id": v["validation"]["functionId"],
                        "title": "Min Order",
                        "apiType": "validation",
                    },
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_VALIDATION, {
                "function_id": "fn-min-order",
                "title": "Block sub-$25",
                "block_on_failure": True,
            })
        assert result.ok
        v = result.data["validation"]
        assert v["function_id"] == "fn-min-order"
        assert v["block_on_failure"] is True
        assert v["title"] == "Block sub-$25"
        # Variable named after the type (Pattern A in CLAUDE.md).
        assert "validation" in captured

    def test_create_user_errors_propagate(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        a = ShopifyValidationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "validationCreate": {
                "validation": None,
                "userErrors": [{
                    "field": ["validation", "functionId"],
                    "message": "Function not found",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_VALIDATION, {
                "function_id": "missing",
            })
        assert not result.ok

    # ── List ────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        a = ShopifyValidationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "validations": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Validation/1",
                        "title": "Min Order",
                        "enabled": True,
                        "blockOnFailure": True,
                        "shopifyFunction": {
                            "id": "fn-1", "title": "Min Order Func",
                            "apiType": "validation",
                        },
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_VALIDATIONS, {
                "limit": 10,
            })
        assert result.ok
        assert result.data["count"] == 1
        v = result.data["validations"][0]
        assert v["function_api_type"] == "validation"

    def test_list_clamps_limit(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        a = ShopifyValidationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"validations": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_VALIDATIONS, {"limit": 9999})
        assert captured["first"] == 250

    # ── Delete ──────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        a = ShopifyValidationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_DELETE_VALIDATION, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        a = ShopifyValidationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "validationDelete": {
                "deletedId": "gid://shopify/Validation/1",
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_DELETE_VALIDATION, {
                "id": "gid://shopify/Validation/1",
            })
        assert result.ok
        assert result.data["deleted_id"].endswith("/1")

    # ── Normaliser ──────────────────────────────

    def test_normalise_handles_non_dict(self):
        from core.adapters.shopify.validations import ShopifyValidationsAdapter
        assert ShopifyValidationsAdapter._normalise_validation(None) == {}  # type: ignore[arg-type]


# ── ShopifyCartTransformsAdapter ────────────────────────


class TestShopifyCartTransformsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        a = ShopifyCartTransformsAdapter()
        assert a.name == "shopify_cart_transforms"
        for cap in (
            Capability.SHOPIFY_CREATE_CART_TRANSFORM,
            Capability.SHOPIFY_LIST_CART_TRANSFORMS,
            Capability.SHOPIFY_DELETE_CART_TRANSFORM,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        a = ShopifyCartTransformsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Create — validation ────────────────────────

    def test_create_requires_function_id(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        a = ShopifyCartTransformsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_CREATE_CART_TRANSFORM, {})
        assert not result.ok

    def test_create_block_on_failure_default_false(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        a = ShopifyCartTransformsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"cartTransformCreate": {
                "cartTransform": {
                    "id": "gid://shopify/CartTransform/1",
                    "functionId": v["functionId"],
                    "blockOnFailure": v["blockOnFailure"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_CREATE_CART_TRANSFORM, {
                "function_id": "fn-1",
            })
        assert captured["blockOnFailure"] is False

    def test_create_block_on_failure_can_be_true(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        a = ShopifyCartTransformsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"cartTransformCreate": {
                "cartTransform": {
                    "id": "gid://shopify/CartTransform/1",
                    "functionId": v["functionId"],
                    "blockOnFailure": v["blockOnFailure"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_CREATE_CART_TRANSFORM, {
                "function_id": "fn-1",
                "block_on_failure": True,
            })
        assert captured["blockOnFailure"] is True

    # ── Metafields validation ─────────────────────

    def test_build_metafields_dict_form(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        out = ShopifyCartTransformsAdapter._build_metafields([
            {"namespace": "$app:bundle",
             "key": "skus",
             "type": "json",
             "value": ["sku-1", "sku-2"]},
            {"key": "count", "value": 4},
        ])
        # JSON-coerced complex value.
        assert out[0]["value"] == '["sku-1", "sku-2"]'
        # Numeric coerced to string per metafield convention.
        assert out[1]["value"] == "4"
        # Default namespace.
        assert out[1]["namespace"] == "shopai"

    def test_build_metafields_none_returns_empty_list(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        assert ShopifyCartTransformsAdapter._build_metafields(None) == []

    def test_build_metafields_non_list_rejected(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyCartTransformsAdapter._build_metafields("not a list")

    def test_build_metafields_missing_key_rejected(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyCartTransformsAdapter._build_metafields([
                {"value": "v"},
            ])

    def test_build_metafields_missing_value_rejected(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyCartTransformsAdapter._build_metafields([
                {"key": "k"},
            ])

    # ── Create — happy path ─────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        a = ShopifyCartTransformsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"cartTransformCreate": {
                "cartTransform": {
                    "id": "gid://shopify/CartTransform/9",
                    "functionId": v["functionId"],
                    "blockOnFailure": v["blockOnFailure"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_CART_TRANSFORM, {
                "function_id": "fn-bundle-expand",
                "metafields": [
                    {"key": "config",
                     "value": {"expand_pattern": "BUNDLE-*"}},
                ],
            })
        assert result.ok
        assert result.data["id"].endswith("/9")
        # Metafields wired through.
        assert captured["metafields"][0]["key"] == "config"
        # Complex value JSON-coerced.
        assert "expand_pattern" in captured["metafields"][0]["value"]

    def test_create_user_errors_propagate(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        a = ShopifyCartTransformsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "cartTransformCreate": {
                "cartTransform": None,
                "userErrors": [{
                    "field": ["functionId"],
                    "message": "Function not found",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_CART_TRANSFORM, {
                "function_id": "missing",
            })
        assert not result.ok

    # ── List ────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        a = ShopifyCartTransformsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "cartTransforms": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/CartTransform/1",
                        "functionId": "fn-1",
                        "blockOnFailure": False,
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_CART_TRANSFORMS,
                               {"limit": 10})
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["cart_transforms"][0]["function_id"] == "fn-1"

    def test_list_clamps_limit(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        a = ShopifyCartTransformsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"cartTransforms": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_CART_TRANSFORMS, {"limit": 9999})
        assert captured["first"] == 250

    # ── Delete ──────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        a = ShopifyCartTransformsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_DELETE_CART_TRANSFORM, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.cart_transforms import (
            ShopifyCartTransformsAdapter,
        )
        a = ShopifyCartTransformsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "cartTransformDelete": {
                "deletedId": "gid://shopify/CartTransform/1",
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_DELETE_CART_TRANSFORM, {
                "id": "gid://shopify/CartTransform/1",
            })
        assert result.ok
        assert result.data["deleted_id"].endswith("/1")


# ── ShopifyChannelsAdapter ──────────────────────────────


class TestShopifyChannelsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.channels import ShopifyChannelsAdapter
        a = ShopifyChannelsAdapter()
        assert a.name == "shopify_channels"
        assert Capability.SHOPIFY_LIST_CHANNELS in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.channels import ShopifyChannelsAdapter
        a = ShopifyChannelsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    def test_list_happy_path(self):
        from core.adapters.shopify.channels import ShopifyChannelsAdapter
        a = ShopifyChannelsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "channels": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Channel/1",
                        "name": "Online Store",
                        "handle": "online_store",
                        "supportsFuturePublishing": True,
                    }},
                    {"node": {
                        "id": "gid://shopify/Channel/2",
                        "name": "Shop",
                        "handle": "shop",
                        "supportsFuturePublishing": False,
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_CHANNELS, {"limit": 10})
        assert result.ok
        assert result.data["count"] == 2
        names = {c["name"] for c in result.data["channels"]}
        assert names == {"Online Store", "Shop"}
        assert result.data["channels"][0]["supports_future_publishing"] is True

    def test_list_clamps_limit(self):
        from core.adapters.shopify.channels import ShopifyChannelsAdapter
        a = ShopifyChannelsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"channels": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_CHANNELS, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_default_limit(self):
        from core.adapters.shopify.channels import ShopifyChannelsAdapter
        a = ShopifyChannelsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"channels": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_CHANNELS, {})
        assert captured["first"] == 50

    def test_list_passes_cursor(self):
        from core.adapters.shopify.channels import ShopifyChannelsAdapter
        a = ShopifyChannelsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["after"] = v["after"]
            return {"channels": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_CHANNELS, {"cursor": "cur123"})
        assert captured["after"] == "cur123"

    def test_list_rejects_non_string_cursor(self):
        from core.adapters.shopify.channels import ShopifyChannelsAdapter
        a = ShopifyChannelsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_LIST_CHANNELS, {
                "cursor": 12345,
            })
        assert not result.ok

    def test_list_handles_empty(self):
        from core.adapters.shopify.channels import ShopifyChannelsAdapter
        a = ShopifyChannelsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "channels": {"pageInfo": {}, "edges": []},
        }):
            result = a.execute(Capability.SHOPIFY_LIST_CHANNELS, {})
        assert result.ok
        assert result.data["count"] == 0


# ── ShopifyInventoryShipmentsAdapter ────────────────────


class TestShopifyInventoryShipmentsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        a = ShopifyInventoryShipmentsAdapter()
        assert a.name == "shopify_inventory_shipments"
        for cap in (
            Capability.SHOPIFY_LIST_INVENTORY_SHIPMENTS,
            Capability.SHOPIFY_GET_INVENTORY_SHIPMENT,
            Capability.SHOPIFY_CREATE_INVENTORY_SHIPMENT,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        a = ShopifyInventoryShipmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── _build_create_input validation ─────────────

    def test_build_input_requires_origin_and_destination(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        # Missing origin
        with pytest.raises(AdapterValidationError):
            ShopifyInventoryShipmentsAdapter._build_create_input({
                "destination_id": "gid://shopify/Location/B",
                "line_items": [{"inventory_item_id": "gid://x", "quantity": 1}],
            })
        # Missing destination
        with pytest.raises(AdapterValidationError):
            ShopifyInventoryShipmentsAdapter._build_create_input({
                "origin_id": "gid://shopify/Location/A",
                "line_items": [{"inventory_item_id": "gid://x", "quantity": 1}],
            })

    def test_build_input_rejects_self_shipment(self):
        """Shopify rejects shipments where origin == destination —
        fail fast at the adapter rather than paying for the
        userErrors round-trip."""
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyInventoryShipmentsAdapter._build_create_input({
                "origin_id": "gid://shopify/Location/A",
                "destination_id": "gid://shopify/Location/A",
                "line_items": [{"inventory_item_id": "gid://x", "quantity": 1}],
            })
        assert "differ" in str(exc.value) or "self-shipment" in str(exc.value).lower()

    def test_build_input_requires_line_items(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyInventoryShipmentsAdapter._build_create_input({
                "origin_id": "gid://shopify/Location/A",
                "destination_id": "gid://shopify/Location/B",
            })
        with pytest.raises(AdapterValidationError):
            ShopifyInventoryShipmentsAdapter._build_create_input({
                "origin_id": "gid://shopify/Location/A",
                "destination_id": "gid://shopify/Location/B",
                "line_items": [],
            })

    def test_build_input_line_item_validation(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        base = {
            "origin_id": "gid://shopify/Location/A",
            "destination_id": "gid://shopify/Location/B",
        }
        # Missing inventory_item_id
        with pytest.raises(AdapterValidationError):
            ShopifyInventoryShipmentsAdapter._build_create_input({
                **base, "line_items": [{"quantity": 1}],
            })
        # Quantity must be positive int
        with pytest.raises(AdapterValidationError):
            ShopifyInventoryShipmentsAdapter._build_create_input({
                **base,
                "line_items": [{"inventory_item_id": "gid://x", "quantity": 0}],
            })
        with pytest.raises(AdapterValidationError):
            ShopifyInventoryShipmentsAdapter._build_create_input({
                **base,
                "line_items": [{"inventory_item_id": "gid://x",
                                "quantity": "many"}],
            })
        # Non-dict line item
        with pytest.raises(AdapterValidationError):
            ShopifyInventoryShipmentsAdapter._build_create_input({
                **base, "line_items": ["not a dict"],
            })

    def test_build_input_caps_at_250_line_items(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        too_many = [
            {"inventory_item_id": f"gid://i/{i}", "quantity": 1}
            for i in range(251)
        ]
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyInventoryShipmentsAdapter._build_create_input({
                "origin_id": "gid://shopify/Location/A",
                "destination_id": "gid://shopify/Location/B",
                "line_items": too_many,
            })
        assert "250" in str(exc.value)

    def test_build_input_optional_fields_pass_through(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        out = ShopifyInventoryShipmentsAdapter._build_create_input({
            "origin_id": "gid://shopify/Location/A",
            "destination_id": "gid://shopify/Location/B",
            "tracking_number": "1Z999AA10123456784",
            "tracking_url": "https://carrier/track/1Z999",
            "note": "Replenish from DC",
            "arrival_date": "2026-05-15",
            "line_items": [
                {"inventory_item_id": "gid://i/1", "quantity": 50},
            ],
        })
        assert out["trackingNumber"] == "1Z999AA10123456784"
        assert out["trackingUrl"].startswith("https://carrier/")
        assert out["note"] == "Replenish from DC"
        assert out["arrivalDate"] == "2026-05-15"
        # Wire-side ids use the schema's camelCase form.
        assert out["originLocationId"] == "gid://shopify/Location/A"
        assert out["destinationLocationId"] == "gid://shopify/Location/B"
        assert out["lineItems"][0] == {
            "inventoryItemId": "gid://i/1", "quantity": 50,
        }

    def test_build_input_optional_field_non_string_rejected(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyInventoryShipmentsAdapter._build_create_input({
                "origin_id": "gid://shopify/Location/A",
                "destination_id": "gid://shopify/Location/B",
                "tracking_number": 12345,   # must be string
                "line_items": [
                    {"inventory_item_id": "gid://i/1", "quantity": 1},
                ],
            })

    # ── List ────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        a = ShopifyInventoryShipmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "inventoryShipments": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/InventoryShipment/1",
                        "name": "#IS1",
                        "status": "IN_TRANSIT",
                        "trackingNumber": "1Z999",
                        "trackingUrl": "https://t/1Z999",
                        "arrivalDate": "2026-05-15",
                        "origin": {"id": "gid://shopify/Location/A",
                                   "name": "DC West"},
                        "destination": {"id": "gid://shopify/Location/B",
                                        "name": "Brooklyn"},
                        "lineItems": {"edges": [
                            {"node": {
                                "id": "gid://shopify/InvShipLine/L",
                                "quantity": 50,
                                "receivedQuantity": 0,
                                "inventoryItem": {
                                    "id": "gid://shopify/InventoryItem/X",
                                    "sku": "MUG-BLU-12",
                                },
                            }},
                        ]},
                    }},
                ],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_INVENTORY_SHIPMENTS, {"limit": 10},
            )
        assert result.ok
        s = result.data["shipments"][0]
        assert s["status"] == "IN_TRANSIT"
        assert s["origin_name"] == "DC West"
        assert s["destination_name"] == "Brooklyn"
        assert s["line_items_count"] == 1
        assert s["line_items"][0]["sku"] == "MUG-BLU-12"
        assert s["line_items"][0]["received_quantity"] == 0

    def test_list_clamps_limit(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        a = ShopifyInventoryShipmentsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"inventoryShipments": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_INVENTORY_SHIPMENTS, {
                "limit": 9999,
            })
        assert captured["first"] == 250

    def test_list_passes_query_and_sort(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        a = ShopifyInventoryShipmentsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = v["query"]
            captured["sortKey"] = v["sortKey"]
            return {"inventoryShipments": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_INVENTORY_SHIPMENTS, {
                "query": "status:IN_TRANSIT",
                "sort_key": "created_at",
            })
        assert captured["query"] == "status:IN_TRANSIT"
        assert captured["sortKey"] == "CREATED_AT"

    # ── Get ─────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        a = ShopifyInventoryShipmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(
                Capability.SHOPIFY_GET_INVENTORY_SHIPMENT, {},
            )
        assert not result.ok

    def test_get_happy_path(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        a = ShopifyInventoryShipmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "inventoryShipment": {
                "id": "gid://shopify/InventoryShipment/9",
                "name": "#IS9",
                "status": "OPEN",
                "lineItems": {"edges": []},
            },
        }):
            result = a.execute(Capability.SHOPIFY_GET_INVENTORY_SHIPMENT, {
                "id": "gid://shopify/InventoryShipment/9",
            })
        assert result.ok
        assert result.data["found"] is True
        assert result.data["shipment"]["status"] == "OPEN"

    def test_get_not_found(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        a = ShopifyInventoryShipmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "inventoryShipment": None,
        }):
            result = a.execute(Capability.SHOPIFY_GET_INVENTORY_SHIPMENT, {
                "id": "gid://shopify/InventoryShipment/missing",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Create — happy path ────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        a = ShopifyInventoryShipmentsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["input"] = v["input"]
            return {"inventoryShipmentCreate": {
                "inventoryShipment": {
                    "id": "gid://shopify/InventoryShipment/new",
                    "name": "#IS-new",
                    "status": "OPEN",
                    "origin": {"id": v["input"]["originLocationId"],
                               "name": "DC"},
                    "destination": {"id": v["input"]["destinationLocationId"],
                                    "name": "Store"},
                    "lineItems": {"edges": []},
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_INVENTORY_SHIPMENT,
                {
                    "origin_id": "gid://shopify/Location/A",
                    "destination_id": "gid://shopify/Location/B",
                    "line_items": [
                        {"inventory_item_id": "gid://i/1", "quantity": 50},
                    ],
                },
            )
        assert result.ok
        assert result.data["shipment"]["id"].endswith("/new")
        # Wire payload uses the camelCase form.
        assert "originLocationId" in captured["input"]
        assert captured["input"]["lineItems"][0]["inventoryItemId"] == "gid://i/1"

    def test_create_user_errors_propagate(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        a = ShopifyInventoryShipmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "inventoryShipmentCreate": {
                "inventoryShipment": None,
                "userErrors": [{
                    "field": ["input", "originLocationId"],
                    "message": "Origin location does not exist",
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_INVENTORY_SHIPMENT,
                {
                    "origin_id": "gid://shopify/Location/missing",
                    "destination_id": "gid://shopify/Location/B",
                    "line_items": [
                        {"inventory_item_id": "gid://i/1", "quantity": 1},
                    ],
                },
            )
        assert not result.ok

    # ── Normaliser ─────────────────────────────

    def test_normalise_handles_non_dict(self):
        from core.adapters.shopify.inventory_shipments import (
            ShopifyInventoryShipmentsAdapter,
        )
        assert ShopifyInventoryShipmentsAdapter._normalise_shipment(None) == {}  # type: ignore[arg-type]


# ── ShopifyLocationsAdapter ────────────────────────────


class TestShopifyLocationsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter()
        assert a.name == "shopify_locations"
        for cap in (
            Capability.SHOPIFY_LIST_LOCATIONS,
            Capability.SHOPIFY_GET_LOCATION,
            Capability.SHOPIFY_CREATE_LOCATION,
            Capability.SHOPIFY_UPDATE_LOCATION,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── _build_address_input ──────────────────────────

    def test_build_address_requires_country(self):
        from core.adapters.shopify.locations import _build_address_input
        with pytest.raises(AdapterValidationError):
            _build_address_input({"city": "X"}, where="address")

    def test_build_address_country_or_country_code_satisfies(self):
        from core.adapters.shopify.locations import _build_address_input
        out = _build_address_input(
            {"country": "US", "city": "Brooklyn"}, where="t",
        )
        assert out["country"] == "US"
        assert out["city"] == "Brooklyn"

    def test_build_address_camelcase_translation(self):
        from core.adapters.shopify.locations import _build_address_input
        out = _build_address_input({
            "address1": "123 Main", "city": "Brooklyn",
            "province_code": "NY", "country_code": "US",
            "zip": "11201", "phone": "+1-555-0100",
        }, where="t")
        # snake → camel for AddressInput.
        assert out["provinceCode"] == "NY"
        assert out["countryCode"] == "US"
        assert "phone" in out

    def test_build_address_non_string_field_rejected(self):
        from core.adapters.shopify.locations import _build_address_input
        with pytest.raises(AdapterValidationError):
            _build_address_input({"country": "US", "city": 123}, where="t")

    # ── List ─────────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "locations": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Location/1",
                        "name": "HQ",
                        "isActive": True,
                        "shipsInventory": True,
                        "fulfillsOnlineOrders": True,
                        "hasActiveInventory": True,
                        "address": {
                            "address1": "123 Main",
                            "city": "Brooklyn",
                            "province": "New York",
                            "country": "United States",
                            "countryCode": "US",
                            "zip": "11201",
                            "phone": "+1-555-0100",
                            "formatted": ["123 Main", "Brooklyn NY 11201"],
                        },
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_LOCATIONS, {"limit": 10})
        assert result.ok
        loc = result.data["locations"][0]
        assert loc["name"] == "HQ"
        assert loc["country_code"] == "US"
        assert loc["fulfills_online_orders"] is True

    def test_list_default_excludes_inactive(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["includeInactive"] = v["includeInactive"]
            return {"locations": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_LOCATIONS, {})
        assert captured["includeInactive"] is False

    def test_list_include_inactive_opt_in(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["includeInactive"] = v["includeInactive"]
            return {"locations": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_LOCATIONS, {
                "include_inactive": True,
            })
        assert captured["includeInactive"] is True

    def test_list_clamps_limit(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"locations": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_LOCATIONS, {"limit": 9999})
        assert captured["first"] == 250

    # ── Get ────────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_GET_LOCATION, {})
        assert not result.ok

    def test_get_happy_path(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "location": {
                "id": "gid://shopify/Location/9",
                "name": "Brooklyn DC",
                "isActive": True,
                "shipsInventory": True,
                "fulfillsOnlineOrders": True,
                "hasActiveInventory": True,
                "address": {"address1": "X", "country": "US",
                            "countryCode": "US"},
            },
        }):
            result = a.execute(Capability.SHOPIFY_GET_LOCATION, {
                "id": "gid://shopify/Location/9",
            })
        assert result.ok
        assert result.data["found"] is True
        assert result.data["location"]["name"] == "Brooklyn DC"

    def test_get_not_found(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"location": None}):
            result = a.execute(Capability.SHOPIFY_GET_LOCATION, {
                "id": "gid://shopify/Location/missing",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Create — validation ──────────────────────

    def test_create_requires_name(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_CREATE_LOCATION, {
                "address": {"country": "US"},
            })
        assert not result.ok

    def test_create_requires_address_dict(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_CREATE_LOCATION, {
                "name": "X",
            })
        assert not result.ok
        with patch.object(a, "_gql"):
            r2 = a.execute(Capability.SHOPIFY_CREATE_LOCATION, {
                "name": "X", "address": "not a dict",
            })
        assert not r2.ok

    def test_create_address_country_required(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_CREATE_LOCATION, {
                "name": "X", "address": {"city": "Y"},
            })
        assert not result.ok

    # ── Create — happy path ─────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["input"] = v["input"]
            return {"locationAdd": {
                "location": {
                    "id": "gid://shopify/Location/new",
                    "name": v["input"]["name"],
                    "isActive": True,
                    "shipsInventory": True,
                    "fulfillsOnlineOrders": True,
                    "hasActiveInventory": False,
                    "address": {
                        "address1": "123 Main", "city": "Brooklyn",
                        "country": "United States", "countryCode": "US",
                    },
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_LOCATION, {
                "name": "Brooklyn DC",
                "address": {
                    "address1": "123 Main",
                    "city": "Brooklyn",
                    "country": "US", "country_code": "US",
                    "zip": "11201",
                },
                "fulfills_online_orders": True,
            })
        assert result.ok
        assert result.data["location"]["name"] == "Brooklyn DC"
        # Wire payload uses camelCase translation.
        assert captured["input"]["address"]["countryCode"] == "US"
        assert captured["input"]["fulfillsOnlineOrders"] is True

    def test_create_user_errors_propagate(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "locationAdd": {
                "location": None,
                "userErrors": [{
                    "field": ["input", "address", "country"],
                    "message": "Country is invalid",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_LOCATION, {
                "name": "X",
                "address": {"country": "Atlantis"},
            })
        assert not result.ok

    # ── Update ────────────────────────────────────

    def test_update_requires_id(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_UPDATE_LOCATION, {
                "name": "New name",
            })
        assert not result.ok

    def test_update_needs_at_least_one_field(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_UPDATE_LOCATION, {
                "id": "gid://shopify/Location/1",
            })
        assert not result.ok

    def test_update_partial_fields_only(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        a = ShopifyLocationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["input"] = v["input"]
            return {"locationEdit": {
                "location": {
                    "id": v["id"], "name": v["input"]["name"],
                    "isActive": True, "shipsInventory": True,
                    "fulfillsOnlineOrders": True, "hasActiveInventory": True,
                    "address": {"countryCode": "US"},
                }, "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_UPDATE_LOCATION, {
                "id": "gid://shopify/Location/1",
                "name": "Brooklyn DC v2",
            })
        # Only the name changed; address must NOT be in the input.
        assert captured["input"] == {"name": "Brooklyn DC v2"}

    # ── Normalisation ────────────────────────────

    def test_normalise_handles_non_dict(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        assert ShopifyLocationsAdapter._normalise_location(None) == {}  # type: ignore[arg-type]

    def test_normalise_handles_missing_address(self):
        from core.adapters.shopify.locations import ShopifyLocationsAdapter
        out = ShopifyLocationsAdapter._normalise_location({
            "id": "gid://l/1", "name": "L", "isActive": True,
            # No address at all
        })
        assert out["country_code"] == ""
        assert out["city"] == ""


# ── ShopifyCompaniesAdapter ──────────────────────────────


class TestShopifyCompaniesAdapter:
    def test_metadata(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        a = ShopifyCompaniesAdapter()
        assert a.name == "shopify_companies"
        for cap in (
            Capability.SHOPIFY_LIST_COMPANIES,
            Capability.SHOPIFY_GET_COMPANY,
            Capability.SHOPIFY_CREATE_COMPANY,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        a = ShopifyCompaniesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── _build_create_input validation ────────────

    def test_build_create_input_requires_name(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyCompaniesAdapter._build_create_input({})
        with pytest.raises(AdapterValidationError):
            ShopifyCompaniesAdapter._build_create_input({"name": "  "})

    def test_build_create_input_minimal(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        out = ShopifyCompaniesAdapter._build_create_input({"name": "Acme"})
        assert out == {"company": {"name": "Acme"}}

    def test_build_create_input_with_external_id_and_note(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        out = ShopifyCompaniesAdapter._build_create_input({
            "name": "Acme",
            "external_id": "hubspot-12345",
            "note": "Imported from HubSpot",
        })
        assert out["company"]["externalId"] == "hubspot-12345"
        assert out["company"]["note"] == "Imported from HubSpot"

    def test_build_create_input_with_customer_seed(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        out = ShopifyCompaniesAdapter._build_create_input({
            "name": "Acme",
            "customer_id": "gid://shopify/Customer/X",
        })
        assert out["companyContact"]["customerId"] == "gid://shopify/Customer/X"

    def test_build_create_input_with_location_seed(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        out = ShopifyCompaniesAdapter._build_create_input({
            "name": "Acme",
            "location": {
                "name": "HQ",
                "address": {
                    "address1": "123 Main",
                    "city": "Springfield",
                    "country": "United States",
                    "zip": "62704",
                },
            },
        })
        loc = out["companyLocation"]
        assert loc["name"] == "HQ"
        # snake_case → camelCase translation for AddressInput.
        assert loc["shippingAddress"]["address1"] == "123 Main"
        assert loc["shippingAddress"]["city"] == "Springfield"

    def test_build_create_input_location_requires_name(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyCompaniesAdapter._build_create_input({
                "name": "Acme",
                "location": {"address": {"address1": "X"}},  # no location name
            })

    def test_build_create_input_location_must_be_dict(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyCompaniesAdapter._build_create_input({
                "name": "Acme",
                "location": "not a dict",
            })

    def test_build_create_input_address_field_must_be_string(self):
        """If a caller passes a non-string in an address field
        (typo: city as int) the adapter rejects up-front rather
        than letting Shopify barf on a generic 'invalid input'."""
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyCompaniesAdapter._build_create_input({
                "name": "Acme",
                "location": {
                    "name": "HQ",
                    "address": {"city": 12345},
                },
            })

    def test_build_create_input_invalid_external_id_type_rejected(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyCompaniesAdapter._build_create_input({
                "name": "Acme", "external_id": 12345,
            })

    # ── List ──────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        a = ShopifyCompaniesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "companies": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Company/1",
                        "name": "Acme",
                        "note": "VIP",
                        "externalId": "ext-1",
                        "ordersCount": {"count": 12},
                        "totalSpent": {
                            "amount": "5000.00",
                            "currencyCode": "USD",
                        },
                        "mainContact": {
                            "id": "gid://shopify/CompanyContact/X",
                            "customer": {
                                "id": "gid://shopify/Customer/Y",
                                "email": "buyer@acme.com",
                                "displayName": "Wile E. Buyer",
                            },
                        },
                        "locations": {"edges": [
                            {"node": {
                                "id": "gid://shopify/CompanyLocation/Z",
                                "name": "HQ",
                                "shippingAddress": {
                                    "address1": "123 Main",
                                    "city": "Springfield",
                                    "country": "United States",
                                    "zip": "62704",
                                },
                            }},
                        ]},
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_COMPANIES, {"limit": 10})
        assert result.ok
        c = result.data["companies"][0]
        assert c["name"] == "Acme"
        assert c["external_id"] == "ext-1"
        assert c["orders_count"] == 12
        assert c["total_spent"] == 5000.0
        assert c["main_contact_email"] == "buyer@acme.com"
        assert c["locations"][0]["city"] == "Springfield"

    def test_list_clamps_limit(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        a = ShopifyCompaniesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"companies": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_COMPANIES, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_passes_query_and_sort(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        a = ShopifyCompaniesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = v["query"]
            captured["sortKey"] = v["sortKey"]
            return {"companies": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_COMPANIES, {
                "query": "name:Acme",
                "sort_key": "created_at",
            })
        assert captured["query"] == "name:Acme"
        assert captured["sortKey"] == "CREATED_AT"

    def test_list_handles_empty_page(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        a = ShopifyCompaniesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "companies": {"pageInfo": {}, "edges": []},
        }):
            result = a.execute(Capability.SHOPIFY_LIST_COMPANIES, {})
        assert result.ok
        assert result.data["count"] == 0

    # ── Get ───────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        a = ShopifyCompaniesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_GET_COMPANY, {})
        assert not result.ok

    def test_get_happy_path(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        a = ShopifyCompaniesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "company": {
                "id": "gid://shopify/Company/9",
                "name": "Acme",
                "note": "",
                "externalId": "",
                "ordersCount": {"count": 0},
                "totalSpent": {"amount": "0", "currencyCode": "USD"},
                "mainContact": None,
                "locations": {"edges": []},
            },
        }):
            result = a.execute(Capability.SHOPIFY_GET_COMPANY, {
                "id": "gid://shopify/Company/9",
            })
        assert result.ok
        assert result.data["found"] is True
        assert result.data["company"]["name"] == "Acme"

    def test_get_not_found(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        a = ShopifyCompaniesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"company": None}):
            result = a.execute(Capability.SHOPIFY_GET_COMPANY, {
                "id": "gid://shopify/Company/missing",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Create — happy path ──────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        a = ShopifyCompaniesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["input"] = v["input"]
            return {"companyCreate": {
                "company": {
                    "id": "gid://shopify/Company/new",
                    "name": v["input"]["company"]["name"],
                    "note": v["input"]["company"].get("note", ""),
                    "externalId": v["input"]["company"].get("externalId", ""),
                    "ordersCount": {"count": 0},
                    "totalSpent": {"amount": "0", "currencyCode": "USD"},
                    "mainContact": None,
                    "locations": {"edges": []},
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_COMPANY, {
                "name": "Acme Corp",
                "external_id": "hubspot-99",
            })
        assert result.ok
        assert result.data["company"]["name"] == "Acme Corp"
        assert result.data["company"]["external_id"] == "hubspot-99"
        assert captured["input"]["company"]["externalId"] == "hubspot-99"

    def test_create_user_errors_propagate(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        a = ShopifyCompaniesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "companyCreate": {
                "company": None,
                "userErrors": [{
                    "field": ["input", "company", "name"],
                    "message": "Name has already been taken",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_COMPANY, {
                "name": "Acme",
            })
        assert not result.ok

    # ── Normaliser ───────────────────────────────

    def test_normalise_handles_non_dict(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        assert ShopifyCompaniesAdapter._normalise_company(None) == {}  # type: ignore[arg-type]

    def test_normalise_handles_missing_main_contact(self):
        from core.adapters.shopify.companies import ShopifyCompaniesAdapter
        out = ShopifyCompaniesAdapter._normalise_company({
            "id": "gid://c/1", "name": "C", "note": "",
            "ordersCount": 0,
            "totalSpent": {"amount": "0", "currencyCode": "USD"},
            "mainContact": None,
            "locations": {"edges": []},
        })
        assert out["main_contact_id"] == ""
        assert out["main_contact_email"] == ""
        assert out["main_contact_name"] == ""


# ── ShopifyWebPixelsAdapter ──────────────────────────────


class TestShopifyWebPixelsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        a = ShopifyWebPixelsAdapter()
        assert a.name == "shopify_web_pixels"
        for cap in (
            Capability.SHOPIFY_CREATE_WEB_PIXEL,
            Capability.SHOPIFY_UPDATE_WEB_PIXEL,
            Capability.SHOPIFY_DELETE_WEB_PIXEL,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        a = ShopifyWebPixelsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── _build_settings ─────────────────────────────

    def test_build_settings_dict_to_json_string(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        out = ShopifyWebPixelsAdapter._build_settings(
            {"settings": {"meta_pixel_id": "1234", "events": ["x"]}},
            where="t",
        )
        # Compact JSON encoding so the wire payload stays predictable.
        assert out == '{"meta_pixel_id":"1234","events":["x"]}'

    def test_build_settings_pre_serialised_string_passes_through(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        out = ShopifyWebPixelsAdapter._build_settings(
            {"settings": '{"meta_pixel_id": "abc"}'},
            where="t",
        )
        assert out == '{"meta_pixel_id": "abc"}'

    def test_build_settings_invalid_json_string_rejected(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyWebPixelsAdapter._build_settings(
                {"settings": "not valid json"}, where="t",
            )

    def test_build_settings_none_rejected(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyWebPixelsAdapter._build_settings({}, where="t")

    def test_build_settings_unsupported_type_rejected(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyWebPixelsAdapter._build_settings(
                {"settings": 12345}, where="t",
            )

    # ── Create ──────────────────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        a = ShopifyWebPixelsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["webPixel"] = v["webPixel"]
            return {"webPixelCreate": {
                "webPixel": {
                    "id": "gid://shopify/WebPixel/1",
                    "settings": v["webPixel"]["settings"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_WEB_PIXEL, {
                "settings": {
                    "meta_pixel_id": "abc",
                    "events": ["checkout_completed"],
                },
            })
        assert result.ok
        assert result.data["web_pixel"]["id"].endswith("/1")
        # Returned settings parsed back into a dict for ergonomic
        # caller access.
        assert result.data["web_pixel"]["settings"] == {
            "meta_pixel_id": "abc",
            "events": ["checkout_completed"],
        }
        # Wire payload is the JSON string form.
        assert isinstance(captured["webPixel"]["settings"], str)

    def test_create_user_errors_propagate(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        a = ShopifyWebPixelsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "webPixelCreate": {
                "webPixel": None,
                "userErrors": [{
                    "field": ["webPixel", "settings"],
                    "message": "Schema mismatch",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_WEB_PIXEL, {
                "settings": {"x": "y"},
            })
        assert not result.ok

    def test_create_settings_required(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        a = ShopifyWebPixelsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_CREATE_WEB_PIXEL, {})
        assert not result.ok

    # ── Update ──────────────────────────────────────

    def test_update_requires_id(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        a = ShopifyWebPixelsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_UPDATE_WEB_PIXEL, {
                "settings": {"x": "y"},
            })
        assert not result.ok

    def test_update_requires_settings(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        a = ShopifyWebPixelsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_UPDATE_WEB_PIXEL, {
                "id": "gid://shopify/WebPixel/1",
            })
        assert not result.ok

    def test_update_happy_path(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        a = ShopifyWebPixelsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["id"] = v["id"]
            captured["webPixel"] = v["webPixel"]
            return {"webPixelUpdate": {
                "webPixel": {
                    "id": v["id"],
                    "settings": v["webPixel"]["settings"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_WEB_PIXEL, {
                "id": "gid://shopify/WebPixel/1",
                "settings": {"new_key": "new_value"},
            })
        assert result.ok
        assert captured["id"] == "gid://shopify/WebPixel/1"
        assert result.data["web_pixel"]["settings"] == {
            "new_key": "new_value",
        }

    # ── Delete ──────────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        a = ShopifyWebPixelsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_DELETE_WEB_PIXEL, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        a = ShopifyWebPixelsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "webPixelDelete": {
                "deletedWebPixelId": "gid://shopify/WebPixel/1",
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_DELETE_WEB_PIXEL, {
                "id": "gid://shopify/WebPixel/1",
            })
        assert result.ok
        assert result.data["deleted_id"].endswith("/1")

    def test_delete_user_errors_propagate(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        a = ShopifyWebPixelsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "webPixelDelete": {
                "deletedWebPixelId": None,
                "userErrors": [{
                    "field": ["id"],
                    "message": "Web pixel not found",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_DELETE_WEB_PIXEL, {
                "id": "gid://shopify/WebPixel/missing",
            })
        assert not result.ok

    # ── Normalisation ──────────────────────────────

    def test_normalise_handles_non_dict(self):
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        assert ShopifyWebPixelsAdapter._normalise_pixel(None) == {}  # type: ignore[arg-type]

    def test_normalise_malformed_settings_string_passes_through(self):
        """If settings comes back as malformed JSON (shouldn't happen
        from Shopify, but...), surface the raw string rather than
        crashing the read path."""
        from core.adapters.shopify.web_pixels import ShopifyWebPixelsAdapter
        out = ShopifyWebPixelsAdapter._normalise_pixel({
            "id": "gid://x", "settings": "not json",
        })
        assert out["settings"] == "not json"


# ── ShopifyMarketsAdapter ──────────────────────────────


class TestShopifyMarketsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.markets import ShopifyMarketsAdapter
        a = ShopifyMarketsAdapter()
        assert a.name == "shopify_markets"
        for cap in (
            Capability.SHOPIFY_LIST_MARKETS,
            Capability.SHOPIFY_GET_MARKET,
            Capability.SHOPIFY_LIST_SHOP_LOCALES,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.markets import ShopifyMarketsAdapter
        a = ShopifyMarketsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List markets ─────────────────────────────

    def test_list_markets_happy_path(self):
        from core.adapters.shopify.markets import ShopifyMarketsAdapter
        a = ShopifyMarketsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "markets": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Market/1",
                        "name": "United States",
                        "handle": "us",
                        "enabled": True,
                        "primary": True,
                        "currencySettings": {
                            "baseCurrency": {
                                "currencyCode": "USD",
                                "currencyName": "US Dollar",
                            },
                        },
                        "regions": {"edges": [
                            {"node": {
                                "id": "gid://shopify/MarketRegion/A",
                                "name": "United States",
                                "code": "US",
                            }},
                        ]},
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_MARKETS, {"limit": 10})
        assert result.ok
        assert result.data["count"] == 1
        m = result.data["markets"][0]
        assert m["primary"] is True
        assert m["currency_code"] == "USD"
        assert m["currency_name"] == "US Dollar"
        assert m["regions"][0]["country_code"] == "US"

    def test_list_markets_clamps_limit(self):
        from core.adapters.shopify.markets import ShopifyMarketsAdapter
        a = ShopifyMarketsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"markets": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_MARKETS, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_markets_empty(self):
        from core.adapters.shopify.markets import ShopifyMarketsAdapter
        a = ShopifyMarketsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "markets": {"pageInfo": {}, "edges": []},
        }):
            result = a.execute(Capability.SHOPIFY_LIST_MARKETS, {})
        assert result.ok
        assert result.data["count"] == 0

    # ── Get market ───────────────────────────────

    def test_get_market_requires_id(self):
        from core.adapters.shopify.markets import ShopifyMarketsAdapter
        a = ShopifyMarketsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_GET_MARKET, {})
        assert not result.ok

    def test_get_market_happy_path(self):
        from core.adapters.shopify.markets import ShopifyMarketsAdapter
        a = ShopifyMarketsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "market": {
                "id": "gid://shopify/Market/1",
                "name": "Europe",
                "handle": "eu",
                "enabled": True,
                "primary": False,
                "currencySettings": {
                    "baseCurrency": {"currencyCode": "EUR",
                                     "currencyName": "Euro"},
                },
                "regions": {"edges": []},
            },
        }):
            result = a.execute(Capability.SHOPIFY_GET_MARKET, {
                "id": "gid://shopify/Market/1",
            })
        assert result.ok
        assert result.data["found"] is True
        assert result.data["market"]["currency_code"] == "EUR"

    def test_get_market_not_found(self):
        from core.adapters.shopify.markets import ShopifyMarketsAdapter
        a = ShopifyMarketsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"market": None}):
            result = a.execute(Capability.SHOPIFY_GET_MARKET, {
                "id": "gid://shopify/Market/missing",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── List shop locales ───────────────────────

    def test_list_shop_locales_happy_path(self):
        """``shopLocales`` is a top-level non-paginated list — every
        call returns the full set. The adapter just normalises."""
        from core.adapters.shopify.markets import ShopifyMarketsAdapter
        a = ShopifyMarketsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "shopLocales": [
                {"locale": "en", "name": "English",
                 "primary": True, "published": True},
                {"locale": "fr", "name": "French",
                 "primary": False, "published": True},
                {"locale": "es", "name": "Spanish",
                 "primary": False, "published": False},
            ],
        }):
            result = a.execute(Capability.SHOPIFY_LIST_SHOP_LOCALES, {})
        assert result.ok
        assert result.data["count"] == 3
        primary = [l for l in result.data["locales"] if l["primary"]]
        assert len(primary) == 1
        assert primary[0]["locale"] == "en"

    def test_list_shop_locales_handles_non_list(self):
        from core.adapters.shopify.markets import ShopifyMarketsAdapter
        a = ShopifyMarketsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"shopLocales": None}):
            result = a.execute(Capability.SHOPIFY_LIST_SHOP_LOCALES, {})
        assert result.ok
        assert result.data["count"] == 0
        assert result.data["locales"] == []

    # ── Normaliser ──────────────────────────────

    def test_normalise_handles_non_dict(self):
        from core.adapters.shopify.markets import ShopifyMarketsAdapter
        assert ShopifyMarketsAdapter._normalise_market(None) == {}  # type: ignore[arg-type]

    def test_normalise_handles_missing_currency_settings(self):
        from core.adapters.shopify.markets import ShopifyMarketsAdapter
        out = ShopifyMarketsAdapter._normalise_market({
            "id": "gid://m/1", "name": "M", "handle": "m",
            "enabled": True, "primary": False,
            # No currencySettings at all
            "regions": {"edges": []},
        })
        assert out["currency_code"] == ""
        assert out["currency_name"] == ""


# ── ShopifySubscriptionContractsAdapter ───────────────────


class TestShopifySubscriptionContractsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter()
        assert a.name == "shopify_subscription_contracts"
        for cap in (
            Capability.SHOPIFY_LIST_SUBSCRIPTION_CONTRACTS,
            Capability.SHOPIFY_GET_SUBSCRIPTION_CONTRACT,
            Capability.SHOPIFY_PAUSE_SUBSCRIPTION_CONTRACT,
            Capability.SHOPIFY_RESUME_SUBSCRIPTION_CONTRACT,
            Capability.SHOPIFY_CANCEL_SUBSCRIPTION_CONTRACT,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ───────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "subscriptionContracts": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/SubscriptionContract/1",
                        "status": "ACTIVE",
                        "currencyCode": "USD",
                        "nextBillingDate": "2026-05-01T00:00:00Z",
                        "customer": {
                            "id": "gid://shopify/Customer/X",
                            "email": "ada@example.com",
                            "displayName": "Ada Lovelace",
                        },
                        "lines": {"edges": [
                            {"node": {
                                "id": "gid://shopify/SubscriptionLine/L",
                                "title": "Monthly Coffee",
                                "variantTitle": "12oz",
                                "sku": "COFFEE-12",
                                "quantity": 1,
                                "currentPrice": {"amount": "29.99",
                                                 "currencyCode": "USD"},
                            }},
                        ]},
                    }},
                ],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_SUBSCRIPTION_CONTRACTS, {"limit": 10},
            )
        assert result.ok
        assert result.data["count"] == 1
        c = result.data["contracts"][0]
        assert c["status"] == "ACTIVE"
        assert c["customer_email"] == "ada@example.com"
        assert c["lines"][0]["current_price"] == 29.99
        assert c["lines"][0]["quantity"] == 1

    def test_list_clamps_limit(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"subscriptionContracts": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_SUBSCRIPTION_CONTRACTS,
                {"limit": 9999},
            )
        assert captured["first"] == 250

    def test_list_passes_sort_key_uppercased(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["sortKey"] = v["sortKey"]
            captured["reverse"] = v["reverse"]
            return {"subscriptionContracts": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_SUBSCRIPTION_CONTRACTS, {
                "sort_key": "created_at", "reverse": True,
            })
        assert captured["sortKey"] == "CREATED_AT"
        assert captured["reverse"] is True

    def test_list_empty(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "subscriptionContracts": {"pageInfo": {}, "edges": []},
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_SUBSCRIPTION_CONTRACTS, {},
            )
        assert result.ok
        assert result.data["count"] == 0

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(
                Capability.SHOPIFY_GET_SUBSCRIPTION_CONTRACT, {},
            )
        assert not result.ok

    def test_get_happy_path(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "subscriptionContract": {
                "id": "gid://shopify/SubscriptionContract/9",
                "status": "PAUSED",
                "lines": {"edges": []},
            },
        }):
            result = a.execute(Capability.SHOPIFY_GET_SUBSCRIPTION_CONTRACT, {
                "id": "gid://shopify/SubscriptionContract/9",
            })
        assert result.ok
        assert result.data["found"] is True
        assert result.data["contract"]["status"] == "PAUSED"

    def test_get_not_found(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "subscriptionContract": None,
        }):
            result = a.execute(Capability.SHOPIFY_GET_SUBSCRIPTION_CONTRACT, {
                "id": "gid://shopify/SubscriptionContract/missing",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Lifecycle (pause / resume / cancel) ─────

    def test_pause_requires_id(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(
                Capability.SHOPIFY_PAUSE_SUBSCRIPTION_CONTRACT, {},
            )
        assert not result.ok

    def test_pause_happy_path(self):
        """Pause uses ``subscriptionContractPause`` with id at the
        field level (Pattern A — identifier outside the input)."""
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = q
            captured["id"] = v["id"]
            return {"subscriptionContractPause": {
                "contract": {"id": v["id"], "status": "PAUSED"},
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_PAUSE_SUBSCRIPTION_CONTRACT,
                {"id": "gid://shopify/SubscriptionContract/1"},
            )
        assert result.ok
        assert result.data["status"] == "PAUSED"
        assert "subscriptionContractPause" in captured["query"]

    def test_pause_user_errors_propagate(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "subscriptionContractPause": {
                "contract": None,
                "userErrors": [{
                    "field": ["subscriptionContractId"],
                    "message": "Contract already paused",
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_PAUSE_SUBSCRIPTION_CONTRACT,
                {"id": "gid://shopify/SubscriptionContract/1"},
            )
        assert not result.ok

    def test_resume_uses_activate_mutation(self):
        """Capability is named ``RESUME`` because that's what engines
        actually do — but Shopify's mutation is ``...Activate``. The
        adapter normalises across the name mismatch."""
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = q
            return {"subscriptionContractActivate": {
                "contract": {"id": v["id"], "status": "ACTIVE"},
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_RESUME_SUBSCRIPTION_CONTRACT,
                {"id": "gid://shopify/SubscriptionContract/1"},
            )
        assert result.ok
        assert result.data["status"] == "ACTIVE"
        # Wire-side mutation is Activate even though our cap is RESUME.
        assert "subscriptionContractActivate" in captured["query"]

    def test_cancel_happy_path(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "subscriptionContractCancel": {
                "contract": {
                    "id": "gid://shopify/SubscriptionContract/1",
                    "status": "CANCELLED",
                },
                "userErrors": [],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CANCEL_SUBSCRIPTION_CONTRACT,
                {"id": "gid://shopify/SubscriptionContract/1"},
            )
        assert result.ok
        assert result.data["status"] == "CANCELLED"

    def test_cancel_user_errors_propagate(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        a = ShopifySubscriptionContractsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "subscriptionContractCancel": {
                "contract": None,
                "userErrors": [{
                    "field": ["subscriptionContractId"],
                    "message": "Contract already cancelled",
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CANCEL_SUBSCRIPTION_CONTRACT,
                {"id": "gid://shopify/SubscriptionContract/cancelled"},
            )
        assert not result.ok

    # ── Normaliser ─────────────────────────────

    def test_normalise_handles_non_dict(self):
        from core.adapters.shopify.subscriptions import (
            ShopifySubscriptionContractsAdapter,
        )
        assert ShopifySubscriptionContractsAdapter._normalise_contract(None) == {}  # type: ignore[arg-type]


# ── ShopifyGiftCardsAdapter ───────────────────────────────


class TestShopifyGiftCardsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter()
        assert a.name == "shopify_gift_cards"
        for cap in (
            Capability.SHOPIFY_CREATE_GIFT_CARD,
            Capability.SHOPIFY_LIST_GIFT_CARDS,
            Capability.SHOPIFY_GET_GIFT_CARD,
            Capability.SHOPIFY_DEACTIVATE_GIFT_CARD,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Build create input validation ───────────────

    def test_build_create_input_requires_initial_value(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyGiftCardsAdapter._build_create_input({})

    def test_build_create_input_initial_value_must_be_positive(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyGiftCardsAdapter._build_create_input({"initial_value": 0})
        with pytest.raises(AdapterValidationError):
            ShopifyGiftCardsAdapter._build_create_input({"initial_value": -10})
        with pytest.raises(AdapterValidationError):
            ShopifyGiftCardsAdapter._build_create_input({"initial_value": "free"})

    def test_build_create_input_initial_value_coerced_to_decimal(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        out = ShopifyGiftCardsAdapter._build_create_input({"initial_value": 25})
        # Decimal scalar — Shopify wants a 2-decimal string.
        assert out["initialValue"] == "25.00"

    def test_build_create_input_currency_silently_dropped(self):
        """``GiftCardCreateInput`` does NOT accept a currencyCode field
        (caught live as 'Field is not defined on GiftCardCreateInput').
        Gift card currency is inherited from the shop's primary
        currency. The friendly call shape accepts ``currency`` for
        forward compatibility / caller intent but the adapter drops
        it on the wire."""
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        out = ShopifyGiftCardsAdapter._build_create_input({
            "initial_value": 10, "currency": "usd",
        })
        assert "currencyCode" not in out
        assert "currency" not in out

    def test_build_create_input_currency_non_string_rejected(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyGiftCardsAdapter._build_create_input({
                "initial_value": 10, "currency": 123,
            })

    def test_build_create_input_optional_fields_pass_through(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        out = ShopifyGiftCardsAdapter._build_create_input({
            "initial_value": 50,
            "code": "WELCOME50",
            "customer_id": "gid://shopify/Customer/X",
            "expires_on": "2026-12-31",
            "note": "Goodwill",
            "template_suffix": "default",
            "recipient_email": "ada@example.com",
            "recipient_name": "Ada Lovelace",
        })
        assert out["code"] == "WELCOME50"
        assert out["customerId"] == "gid://shopify/Customer/X"
        assert out["expiresOn"] == "2026-12-31"
        assert out["note"] == "Goodwill"
        assert out["templateSuffix"] == "default"
        assert out["recipientAttributes"] == {
            "email": "ada@example.com", "name": "Ada Lovelace",
        }

    def test_build_create_input_invalid_email_rejected(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyGiftCardsAdapter._build_create_input({
                "initial_value": 10,
                "recipient_email": "not-an-email",
            })

    def test_build_create_input_empty_code_rejected(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyGiftCardsAdapter._build_create_input({
                "initial_value": 10, "code": "",
            })

    # ── Create — happy path ─────────────────────────

    def test_create_gift_card_happy_path(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "giftCardCreate": {
                "giftCard": {
                    "id": "gid://shopify/GiftCard/1",
                    "maskedCode": "•••• •••• •••• 1234",
                    "lastCharacters": "1234",
                    "balance": {"amount": "25.00",
                                "currencyCode": "USD"},
                    "initialValue": {"amount": "25.00",
                                     "currencyCode": "USD"},
                    "enabled": True,
                    "expiresOn": None,
                    "note": "Goodwill",
                    "customer": None,
                },
                "giftCardCode": "ABCD1234EFGH5678",
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_GIFT_CARD, {
                "initial_value": 25, "note": "Goodwill",
            })
        assert result.ok
        gc = result.data["gift_card"]
        assert gc["id"].endswith("/1")
        assert gc["balance"] == 25.0
        assert gc["initial_value"] == 25.0
        assert gc["currency"] == "USD"
        assert gc["enabled"] is True
        # Plaintext code surfaced ONLY at creation — engines that
        # want to email it must capture from this response.
        assert result.data["code"] == "ABCD1234EFGH5678"

    def test_create_gift_card_user_errors_propagate(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "giftCardCreate": {
                "giftCard": None,
                "giftCardCode": None,
                "userErrors": [{
                    "field": ["input", "code"],
                    "message": "Code already in use",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_GIFT_CARD, {
                "initial_value": 10, "code": "TAKEN",
            })
        assert not result.ok

    # ── Get ─────────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_GET_GIFT_CARD, {})
        assert not result.ok

    def test_get_happy_path(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "giftCard": {
                "id": "gid://shopify/GiftCard/9",
                "maskedCode": "•••• •••• •••• 9999",
                "lastCharacters": "9999",
                "balance": {"amount": "10.00",
                            "currencyCode": "USD"},
                "initialValue": {"amount": "25.00",
                                 "currencyCode": "USD"},
                "enabled": True,
                "customer": {"id": "gid://shopify/Customer/X",
                             "email": "ada@example.com",
                             "displayName": "Ada"},
            },
        }):
            result = a.execute(Capability.SHOPIFY_GET_GIFT_CARD, {
                "id": "gid://shopify/GiftCard/9",
            })
        assert result.ok
        assert result.data["found"] is True
        gc = result.data["gift_card"]
        # Partial spend reflected — balance < initial_value.
        assert gc["balance"] == 10.0
        assert gc["initial_value"] == 25.0
        assert gc["customer_email"] == "ada@example.com"

    def test_get_not_found(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"giftCard": None}):
            result = a.execute(Capability.SHOPIFY_GET_GIFT_CARD, {
                "id": "gid://shopify/GiftCard/missing",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── List ────────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "giftCards": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/GiftCard/1",
                        "maskedCode": "•••• 1234",
                        "lastCharacters": "1234",
                        "balance": {"amount": "25.00",
                                    "currencyCode": "USD"},
                        "initialValue": {"amount": "25.00",
                                         "currencyCode": "USD"},
                        "enabled": True,
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_GIFT_CARDS, {})
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["gift_cards"][0]["balance"] == 25.0

    def test_list_clamps_limit(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"giftCards": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_GIFT_CARDS, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_passes_query_filter(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = v["query"]
            captured["sortKey"] = v["sortKey"]
            return {"giftCards": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_GIFT_CARDS, {
                "query": "status:enabled",
                "sort_key": "amount_spent",
            })
        assert captured["query"] == "status:enabled"
        assert captured["sortKey"] == "AMOUNT_SPENT"

    # ── Deactivate ─────────────────────────────────

    def test_deactivate_requires_id(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_DEACTIVATE_GIFT_CARD, {})
        assert not result.ok

    def test_deactivate_happy_path(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "giftCardDeactivate": {
                "giftCard": {
                    "id": "gid://shopify/GiftCard/1",
                    "maskedCode": "•••• 1234",
                    "lastCharacters": "1234",
                    "balance": {"amount": "0.00",
                                "currencyCode": "USD"},
                    "initialValue": {"amount": "25.00",
                                     "currencyCode": "USD"},
                    "enabled": False,
                },
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_DEACTIVATE_GIFT_CARD, {
                "id": "gid://shopify/GiftCard/1",
            })
        assert result.ok
        # enabled flipped to False post-deactivate.
        assert result.data["gift_card"]["enabled"] is False

    def test_deactivate_user_errors_propagate(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        a = ShopifyGiftCardsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "giftCardDeactivate": {
                "giftCard": None,
                "userErrors": [{
                    "field": ["id"],
                    "message": "Gift card already deactivated",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_DEACTIVATE_GIFT_CARD, {
                "id": "gid://shopify/GiftCard/already-dead",
            })
        assert not result.ok

    def test_normalise_handles_non_dict(self):
        from core.adapters.shopify.gift_cards import ShopifyGiftCardsAdapter
        assert ShopifyGiftCardsAdapter._normalise_gift_card(None) == {}  # type: ignore[arg-type]


# ── ShopifyPayment / DeliveryCustomizationsAdapter ─────────


class TestShopifyCustomizationsAdapters:
    """Both adapters share a common base; this test class exercises
    both prefixes (payment + delivery) with the same scenarios."""

    def test_metadata(self):
        from core.adapters.shopify.customizations import (
            ShopifyDeliveryCustomizationsAdapter,
            ShopifyPaymentCustomizationsAdapter,
        )
        pay = ShopifyPaymentCustomizationsAdapter()
        delv = ShopifyDeliveryCustomizationsAdapter()
        assert pay.name == "shopify_payment_customizations"
        assert delv.name == "shopify_delivery_customizations"
        assert pay._prefix == "payment"
        assert delv._prefix == "delivery"
        # Each adapter exposes 3 capabilities.
        assert len(pay.capabilities) == 3
        assert len(delv.capabilities) == 3

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.customizations import (
            ShopifyPaymentCustomizationsAdapter,
        )
        a = ShopifyPaymentCustomizationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Build input validation (shared by both adapters) ──────

    def test_create_requires_title(self):
        from core.adapters.shopify.customizations import (
            ShopifyPaymentCustomizationsAdapter,
        )
        a = ShopifyPaymentCustomizationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_CREATE_PAYMENT_CUSTOMIZATION, {
                "function_id": "fn-1",
            })
        assert not result.ok

    def test_create_requires_function_id(self):
        from core.adapters.shopify.customizations import (
            ShopifyDeliveryCustomizationsAdapter,
        )
        a = ShopifyDeliveryCustomizationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_CREATE_DELIVERY_CUSTOMIZATION, {
                "title": "Hide express",
            })
        assert not result.ok

    def test_build_input_metafields_validation(self):
        from core.adapters.shopify.customizations import (
            ShopifyPaymentCustomizationsAdapter,
        )
        a = ShopifyPaymentCustomizationsAdapter(shop_url="s", access_token="t")
        # Happy path with metafields
        out = a._build_input({
            "title": "Hide AmEx",
            "function_id": "fn-1",
            "metafields": [
                {"namespace": "$app:cfg", "key": "threshold",
                 "type": "number_decimal", "value": 1000},
            ],
        })
        # Numeric value coerced to string per Shopify metafield convention.
        assert out["metafields"][0]["value"] == "1000"
        assert out["metafields"][0]["namespace"] == "$app:cfg"

        # Non-list metafields rejected
        with pytest.raises(AdapterValidationError):
            a._build_input({
                "title": "T", "function_id": "f",
                "metafields": "not a list",
            })
        # Missing key
        with pytest.raises(AdapterValidationError):
            a._build_input({
                "title": "T", "function_id": "f",
                "metafields": [{"value": "v"}],
            })
        # Missing value
        with pytest.raises(AdapterValidationError):
            a._build_input({
                "title": "T", "function_id": "f",
                "metafields": [{"key": "k"}],
            })

    def test_build_input_enabled_defaults_true(self):
        from core.adapters.shopify.customizations import (
            ShopifyPaymentCustomizationsAdapter,
        )
        a = ShopifyPaymentCustomizationsAdapter(shop_url="s", access_token="t")
        out = a._build_input({"title": "T", "function_id": "f"})
        assert out["enabled"] is True
        out2 = a._build_input({"title": "T", "function_id": "f",
                               "enabled": False})
        assert out2["enabled"] is False

    # ── Create — happy path (both prefixes) ─────────────────

    def test_create_payment_customization_happy_path(self):
        from core.adapters.shopify.customizations import (
            ShopifyPaymentCustomizationsAdapter,
        )
        a = ShopifyPaymentCustomizationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = q
            # Variable name follows the "input named after the type"
            # convention (Pattern caught live).
            captured["input"] = v["paymentCustomization"]
            return {"paymentCustomizationCreate": {
                "paymentCustomization": {
                    "id": "gid://shopify/PaymentCustomization/1",
                    "title": v["paymentCustomization"]["title"],
                    "enabled": True,
                    "functionId": v["paymentCustomization"]["functionId"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_PAYMENT_CUSTOMIZATION,
                {
                    "title": "Hide AmEx > $1000",
                    "function_id": "fn-12345",
                },
            )
        assert result.ok
        assert result.data["id"].endswith("/1")
        # The mutation name correctly used the ``payment`` prefix.
        assert "paymentCustomizationCreate" in captured["query"]
        assert captured["input"]["functionId"] == "fn-12345"

    def test_create_delivery_customization_happy_path(self):
        """Same code path, different prefix — verifying the shared
        base routes correctly to the delivery mutation."""
        from core.adapters.shopify.customizations import (
            ShopifyDeliveryCustomizationsAdapter,
        )
        a = ShopifyDeliveryCustomizationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = q
            return {"deliveryCustomizationCreate": {
                "deliveryCustomization": {
                    "id": "gid://shopify/DeliveryCustomization/1",
                    "title": v["deliveryCustomization"]["title"],
                    "enabled": True,
                    "functionId": v["deliveryCustomization"]["functionId"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_DELIVERY_CUSTOMIZATION,
                {
                    "title": "Hide express for heavy orders",
                    "function_id": "fn-67890",
                },
            )
        assert result.ok
        # Mutation name uses ``delivery`` prefix even though the
        # adapter logic is shared.
        assert "deliveryCustomizationCreate" in captured["query"]

    def test_create_user_errors_propagate(self):
        from core.adapters.shopify.customizations import (
            ShopifyPaymentCustomizationsAdapter,
        )
        a = ShopifyPaymentCustomizationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "paymentCustomizationCreate": {
                "paymentCustomization": None,
                "userErrors": [{
                    "field": ["input", "functionId"],
                    "message": "Function not found",
                }],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_PAYMENT_CUSTOMIZATION,
                {"title": "T", "function_id": "missing"},
            )
        assert not result.ok

    # ── List ───────────────────────────────────────────────

    def test_list_payment_customizations_happy_path(self):
        from core.adapters.shopify.customizations import (
            ShopifyPaymentCustomizationsAdapter,
        )
        a = ShopifyPaymentCustomizationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "paymentCustomizations": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/PaymentCustomization/1",
                        "title": "Hide AmEx",
                        "enabled": True,
                        "functionId": "fn-1",
                    }},
                ],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_PAYMENT_CUSTOMIZATIONS,
                {"limit": 10},
            )
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["customizations"][0]["function_id"] == "fn-1"

    def test_list_clamps_limit(self):
        from core.adapters.shopify.customizations import (
            ShopifyPaymentCustomizationsAdapter,
        )
        a = ShopifyPaymentCustomizationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"paymentCustomizations": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_PAYMENT_CUSTOMIZATIONS, {
                "limit": 9999,
            })
        assert captured["first"] == 250

    # ── Delete ─────────────────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.customizations import (
            ShopifyPaymentCustomizationsAdapter,
        )
        a = ShopifyPaymentCustomizationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(
                Capability.SHOPIFY_DELETE_PAYMENT_CUSTOMIZATION, {},
            )
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.customizations import (
            ShopifyDeliveryCustomizationsAdapter,
        )
        a = ShopifyDeliveryCustomizationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "deliveryCustomizationDelete": {
                "deletedId": "gid://shopify/DeliveryCustomization/1",
                "userErrors": [],
            },
        }):
            result = a.execute(
                Capability.SHOPIFY_DELETE_DELIVERY_CUSTOMIZATION,
                {"id": "gid://shopify/DeliveryCustomization/1"},
            )
        assert result.ok
        assert result.data["deleted_id"].endswith("/1")


# ── ShopifyRefundsAdapter ─────────────────────────────────


class TestShopifyRefundsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        a = ShopifyRefundsAdapter()
        assert a.name == "shopify_refunds"
        for cap in (
            Capability.SHOPIFY_CREATE_REFUND,
            Capability.SHOPIFY_LIST_ORDER_REFUNDS,
            Capability.SHOPIFY_GET_REFUND,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        a = ShopifyRefundsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Build refund input validation ────────────────

    def test_build_refund_input_requires_order_id(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyRefundsAdapter._build_refund_input({
                "transactions": [{"parent_id": "x", "amount": 5}],
            })

    def test_build_refund_input_requires_some_money_movement(self):
        """A refund with no transactions / line items / shipping is a
        no-op and Shopify rejects it. Fail fast."""
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyRefundsAdapter._build_refund_input({
                "order_id": "gid://shopify/Order/1",
                "note": "just a note",
            })
        assert "transactions" in str(exc.value) or "line_items" in str(exc.value)

    def test_build_refund_input_passes_optional_fields(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        out = ShopifyRefundsAdapter._build_refund_input({
            "order_id": "gid://shopify/Order/1",
            "note": "Damaged",
            "notify": True,
            "currency": "usd",
            "transactions": [
                {"parent_id": "gid://shopify/OrderTransaction/X",
                 "amount": "25.50", "gateway": "manual"},
            ],
        })
        assert out["orderId"] == "gid://shopify/Order/1"
        assert out["note"] == "Damaged"
        assert out["notify"] is True
        # Currency normalised to upper-case.
        assert out["currency"] == "USD"
        # Amount coerced to 2-decimal string.
        assert out["transactions"][0]["amount"] == "25.50"
        # Default kind = REFUND.
        assert out["transactions"][0]["kind"] == "REFUND"

    def test_build_refund_input_transactions_validation(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        # Missing parent_id
        with pytest.raises(AdapterValidationError):
            ShopifyRefundsAdapter._build_refund_input({
                "order_id": "gid://x",
                "transactions": [{"amount": 5, "gateway": "manual"}],
            })
        # Non-numeric amount
        with pytest.raises(AdapterValidationError):
            ShopifyRefundsAdapter._build_refund_input({
                "order_id": "gid://x",
                "transactions": [{"parent_id": "y", "amount": "much"}],
            })
        # Zero amount
        with pytest.raises(AdapterValidationError):
            ShopifyRefundsAdapter._build_refund_input({
                "order_id": "gid://x",
                "transactions": [{"parent_id": "y", "amount": 0}],
            })
        # Bad kind
        with pytest.raises(AdapterValidationError):
            ShopifyRefundsAdapter._build_refund_input({
                "order_id": "gid://x",
                "transactions": [{"parent_id": "y", "amount": 5,
                                  "kind": "WHATEVER"}],
            })

    def test_build_refund_input_refund_line_items_validation(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        # Happy
        out = ShopifyRefundsAdapter._build_refund_input({
            "order_id": "gid://x",
            "refund_line_items": [
                {"line_item_id": "gid://l/1", "quantity": 2,
                 "restock_type": "no_restock"},
            ],
        })
        assert out["refundLineItems"][0]["lineItemId"] == "gid://l/1"
        assert out["refundLineItems"][0]["quantity"] == 2
        # Alias resolves.
        assert out["refundLineItems"][0]["restockType"] == "NO_RESTOCK"

        # Missing line_item_id
        with pytest.raises(AdapterValidationError):
            ShopifyRefundsAdapter._build_refund_input({
                "order_id": "gid://x",
                "refund_line_items": [{"quantity": 1}],
            })
        # Non-positive quantity
        with pytest.raises(AdapterValidationError):
            ShopifyRefundsAdapter._build_refund_input({
                "order_id": "gid://x",
                "refund_line_items": [
                    {"line_item_id": "gid://l/1", "quantity": 0},
                ],
            })
        # Bad restock_type
        with pytest.raises(AdapterValidationError):
            ShopifyRefundsAdapter._build_refund_input({
                "order_id": "gid://x",
                "refund_line_items": [
                    {"line_item_id": "gid://l/1", "quantity": 1,
                     "restock_type": "throw_in_trash"},
                ],
            })

    def test_build_refund_input_shipping_full_refund(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        out = ShopifyRefundsAdapter._build_refund_input({
            "order_id": "gid://x",
            "shipping": {"full_refund": True},
        })
        assert out["shipping"] == {"fullRefund": True}

    def test_build_refund_input_shipping_amount(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        out = ShopifyRefundsAdapter._build_refund_input({
            "order_id": "gid://x",
            "shipping": {"amount": 10},
        })
        assert out["shipping"]["amount"] == "10.00"

    def test_build_refund_input_shipping_neither_rejected(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyRefundsAdapter._build_refund_input({
                "order_id": "gid://x",
                "shipping": {},
            })

    # ── Create — happy path ─────────────────────────

    def test_create_refund_happy_path(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        a = ShopifyRefundsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "refundCreate": {
                "refund": {
                    "id": "gid://shopify/Refund/77",
                    "note": "Damaged",
                    "totalRefundedSet": {
                        "presentmentMoney": {"amount": "25.50",
                                             "currencyCode": "USD"},
                    },
                    "order": {"id": "gid://shopify/Order/100",
                              "name": "#1001"},
                    "refundLineItems": {"edges": []},
                    "transactions": {"edges": [
                        {"node": {
                            "id": "gid://shopify/OrderTransaction/T",
                            "kind": "REFUND",
                            "status": "SUCCESS",
                            "gateway": "manual",
                            "amountSet": {
                                "presentmentMoney": {
                                    "amount": "25.50",
                                    "currencyCode": "USD",
                                },
                            },
                        }},
                    ]},
                    "createdAt": "2026-04-25T12:00:00Z",
                    "updatedAt": "2026-04-25T12:00:00Z",
                },
                "order": {
                    "id": "gid://shopify/Order/100",
                    "name": "#1001",
                    "displayFinancialStatus": "REFUNDED",
                },
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_REFUND, {
                "order_id": "gid://shopify/Order/100",
                "note": "Damaged",
                "transactions": [
                    {"parent_id": "gid://shopify/OrderTransaction/Y",
                     "amount": "25.50", "gateway": "manual"},
                ],
            })
        assert result.ok
        assert result.data["order_financial_status"] == "REFUNDED"
        r = result.data["refund"]
        assert r["total"] == 25.50
        assert r["currency"] == "USD"
        assert len(r["transactions"]) == 1
        assert r["transactions"][0]["amount"] == 25.50

    def test_create_refund_user_errors_propagate(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        a = ShopifyRefundsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "refundCreate": {
                "refund": None,
                "order": None,
                "userErrors": [{
                    "field": ["input", "transactions", "0", "amount"],
                    "message": "Refund amount exceeds order total",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_REFUND, {
                "order_id": "gid://x",
                "transactions": [
                    {"parent_id": "gid://t/1", "amount": 9999},
                ],
            })
        assert not result.ok

    # ── List order refunds ──────────────────────────

    def test_list_order_refunds_requires_order_id(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        a = ShopifyRefundsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_LIST_ORDER_REFUNDS, {})
        assert not result.ok

    def test_list_order_refunds_happy_path(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        a = ShopifyRefundsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "order": {
                "id": "gid://shopify/Order/100",
                "name": "#1001",
                "refunds": [
                    {
                        "id": "gid://shopify/Refund/1",
                        "note": "Damaged",
                        "totalRefundedSet": {
                            "presentmentMoney": {"amount": "25.50",
                                                 "currencyCode": "USD"},
                        },
                        "order": {"id": "gid://shopify/Order/100",
                                  "name": "#1001"},
                        "refundLineItems": {"edges": []},
                        "transactions": {"edges": []},
                    },
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_ORDER_REFUNDS, {
                "order_id": "gid://shopify/Order/100",
            })
        assert result.ok
        assert result.data["found"] is True
        assert result.data["count"] == 1
        assert result.data["refunds"][0]["total"] == 25.50

    def test_list_order_refunds_not_found(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        a = ShopifyRefundsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"order": None}):
            result = a.execute(Capability.SHOPIFY_LIST_ORDER_REFUNDS, {
                "order_id": "gid://shopify/Order/missing",
            })
        assert result.ok
        assert result.data["found"] is False
        assert result.data["count"] == 0

    # ── Get refund ──────────────────────────────────

    def test_get_refund_requires_id(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        a = ShopifyRefundsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_GET_REFUND, {})
        assert not result.ok

    def test_get_refund_happy_path(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        a = ShopifyRefundsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "refund": {
                "id": "gid://shopify/Refund/1",
                "note": "",
                "totalRefundedSet": {
                    "presentmentMoney": {"amount": "10.00",
                                         "currencyCode": "USD"},
                },
                "order": {"id": "gid://shopify/Order/1", "name": "#1"},
                "refundLineItems": {"edges": []},
                "transactions": {"edges": []},
            },
        }):
            result = a.execute(Capability.SHOPIFY_GET_REFUND, {
                "id": "gid://shopify/Refund/1",
            })
        assert result.ok
        assert result.data["found"] is True
        assert result.data["refund"]["total"] == 10.0

    def test_get_refund_not_found(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        a = ShopifyRefundsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"refund": None}):
            result = a.execute(Capability.SHOPIFY_GET_REFUND, {
                "id": "gid://shopify/Refund/missing",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Normalisation ──────────────────────────────

    def test_normalise_handles_non_dict(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        assert ShopifyRefundsAdapter._normalise_refund(None) == {}  # type: ignore[arg-type]

    def test_normalise_lifts_line_items_and_transactions(self):
        from core.adapters.shopify.refunds import ShopifyRefundsAdapter
        out = ShopifyRefundsAdapter._normalise_refund({
            "id": "gid://r/1", "note": "n",
            "totalRefundedSet": {
                "presentmentMoney": {"amount": "5.00",
                                     "currencyCode": "USD"},
            },
            "refundLineItems": {"edges": [
                {"node": {
                    "id": "gid://rli/1", "quantity": 2,
                    "restockType": "RETURN",
                    "lineItem": {
                        "id": "gid://l/1", "title": "Cool Mug",
                        "sku": "MUG-001",
                    },
                    "subtotalSet": {
                        "presentmentMoney": {
                            "amount": "5.00", "currencyCode": "USD",
                        },
                    },
                }},
            ]},
            "transactions": {"edges": [
                {"node": {
                    "id": "gid://t/1", "kind": "REFUND",
                    "status": "SUCCESS", "gateway": "stripe",
                    "amountSet": {
                        "presentmentMoney": {
                            "amount": "5.00", "currencyCode": "USD",
                        },
                    },
                }},
            ]},
        })
        assert out["total"] == 5.0
        assert len(out["line_items"]) == 1
        assert out["line_items"][0]["product_title"] == "Cool Mug"
        assert out["line_items"][0]["sku"] == "MUG-001"
        assert out["line_items"][0]["restock_type"] == "RETURN"
        assert len(out["transactions"]) == 1
        assert out["transactions"][0]["gateway"] == "stripe"


# ── ShopifyCustomerSegmentsAdapter ────────────────────────


class TestShopifyCustomerSegmentsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter()
        assert a.name == "shopify_customer_segments"
        for cap in (
            Capability.SHOPIFY_QUERY_SEGMENT,
            Capability.SHOPIFY_GET_SEGMENT_MEMBERS,
            Capability.SHOPIFY_CREATE_SEGMENT,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Query segments ───────────────────────────────

    def test_query_segments_happy_path(self):
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "segments": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Segment/1",
                        "name": "VIPs",
                        "query": "amount_spent > 500",
                        "creationDate": "2026-01-01T00:00:00Z",
                        "lastEditDate": "2026-04-01T00:00:00Z",
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_QUERY_SEGMENT, {"limit": 10})
        assert result.ok
        assert result.data["count"] == 1
        seg = result.data["segments"][0]
        assert seg["name"] == "VIPs"
        assert seg["query"] == "amount_spent > 500"

    def test_query_segments_clamps_limit(self):
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"segments": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_QUERY_SEGMENT, {"limit": 9999})
        assert captured["first"] == 250

    def test_query_segments_passes_filter_and_sort(self):
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = v["query"]
            captured["sortKey"] = v["sortKey"]
            captured["reverse"] = v["reverse"]
            return {"segments": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_QUERY_SEGMENT, {
                "query": "name:VIP",
                "sort_key": "creation_date",
                "reverse": True,
            })
        assert captured["query"] == "name:VIP"
        assert captured["sortKey"] == "CREATION_DATE"
        assert captured["reverse"] is True

    def test_query_segments_handles_empty(self):
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "segments": {"pageInfo": {}, "edges": []},
        }):
            result = a.execute(Capability.SHOPIFY_QUERY_SEGMENT, {})
        assert result.ok
        assert result.data["count"] == 0

    # ── Get segment members ─────────────────────────

    def test_get_members_requires_segment_id(self):
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_GET_SEGMENT_MEMBERS, {})
        assert not result.ok

    def test_get_members_happy_path(self):
        """SegmentStatistics has no totalCount in the current schema
        (caught live). The adapter relies on pageInfo as the
        has-more signal; engines that need an exact total scan the
        connection."""
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "customerSegmentMembers": {
                "pageInfo": {"hasNextPage": True, "endCursor": "cur"},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Customer/1",
                        "firstName": "Ada",
                        "lastName": "Lovelace",
                        "displayName": "Ada Lovelace",
                        "defaultEmailAddress": {"emailAddress": "ada@example.com"},
                        "defaultPhoneNumber": {"phoneNumber": "+15551234"},
                        "amountSpent": {"amount": "1234.50",
                                        "currencyCode": "USD"},
                        "numberOfOrders": 5,
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_GET_SEGMENT_MEMBERS, {
                "segment_id": "gid://shopify/Segment/1",
                "limit": 10,
            })
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["has_next_page"] is True
        m = result.data["members"][0]
        assert m["first_name"] == "Ada"
        assert m["email"] == "ada@example.com"
        assert m["amount_spent"] == 1234.50
        assert m["currency"] == "USD"
        assert m["orders_count"] == 5

    def test_get_members_clamps_limit(self):
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"customerSegmentMembers": {
                "pageInfo": {}, "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_GET_SEGMENT_MEMBERS, {
                "segment_id": "gid://x", "limit": 9999,
            })
        assert captured["first"] == 250

    def test_get_members_handles_missing_optional_fields(self):
        """Customer.defaultEmailAddress / defaultPhoneNumber can be
        null when the customer hasn't given those details. The
        normaliser must surface empty strings rather than crash."""
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "customerSegmentMembers": {
                "pageInfo": {},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Customer/x",
                        "firstName": "", "lastName": "",
                        "displayName": "Anonymous",
                        "defaultEmailAddress": None,
                        "defaultPhoneNumber": None,
                        "amountSpent": {"amount": "0",
                                        "currencyCode": "USD"},
                        "numberOfOrders": 0,
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_GET_SEGMENT_MEMBERS, {
                "segment_id": "gid://shopify/Segment/1",
            })
        assert result.ok
        assert result.data["members"][0]["email"] == ""
        assert result.data["members"][0]["phone"] == ""

    # ── Create segment ───────────────────────────────

    def test_create_segment_requires_name(self):
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_CREATE_SEGMENT, {
                "query": "amount_spent > 500",
            })
        assert not result.ok

    def test_create_segment_requires_query(self):
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_CREATE_SEGMENT, {
                "name": "VIPs",
            })
        assert not result.ok

    def test_create_segment_happy_path(self):
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"segmentCreate": {
                "segment": {
                    "id": "gid://shopify/Segment/99",
                    "name": v["name"],
                    "query": v["query"],
                    "creationDate": "2026-04-25T12:00:00Z",
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_SEGMENT, {
                "name": "At-risk customers",
                "query": "last_order_date < -60d AND amount_spent > 200",
            })
        assert result.ok
        assert result.data["segment"]["id"] == "gid://shopify/Segment/99"
        assert result.data["segment"]["name"] == "At-risk customers"
        assert captured["name"] == "At-risk customers"
        assert "amount_spent" in captured["query"]

    def test_create_segment_user_errors_propagate(self):
        from core.adapters.shopify.segments import ShopifyCustomerSegmentsAdapter
        a = ShopifyCustomerSegmentsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "segmentCreate": {
                "segment": None,
                "userErrors": [{
                    "field": ["query"],
                    "message": "Invalid segment query syntax",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_SEGMENT, {
                "name": "Bad",
                "query": "this is not valid",
            })
        assert not result.ok


# ── ShopifyTranslationsAdapter ────────────────────────────


class TestShopifyTranslationsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter()
        assert a.name == "shopify_translations"
        for cap in (
            Capability.SHOPIFY_GET_TRANSLATABLE_RESOURCE,
            Capability.SHOPIFY_REGISTER_TRANSLATIONS,
            Capability.SHOPIFY_REMOVE_TRANSLATIONS,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Get translatable resource ───────────────────────

    def test_get_translatable_requires_resource_id(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_GET_TRANSLATABLE_RESOURCE, {})
        assert not result.ok

    def test_get_translatable_happy_path(self):
        """Schema requires ``locale`` argument on TranslatableResource.
        translations (caught live)."""
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"translatableResource": {
                "resourceId": "gid://shopify/Product/1",
                "translatableContent": [
                    {"key": "title", "value": "Cool Mug",
                     "digest": "abc123", "locale": "en"},
                    {"key": "body_html", "value": "<p>The mug.</p>",
                     "digest": "def456", "locale": "en"},
                ],
                "translations": [
                    {"key": "title", "value": "Tasse Cool",
                     "locale": "fr", "outdated": False, "market": None},
                ],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_GET_TRANSLATABLE_RESOURCE, {
                "resource_id": "gid://shopify/Product/1",
                "locale": "fr",
            })
        assert result.ok
        assert result.data["found"] is True
        assert result.data["locale"] == "fr"
        # Locale was passed as a required GraphQL variable.
        assert captured["locale"] == "fr"
        # Translatable content surfaces digest — engines need it to
        # register a non-stale translation.
        assert len(result.data["translatable_content"]) == 2
        assert result.data["translatable_content"][0] == {
            "key": "title", "value": "Cool Mug",
            "digest": "abc123", "source_locale": "en",
        }
        assert result.data["translations"][0]["locale"] == "fr"

    def test_get_translatable_requires_locale(self):
        """Without a locale the GraphQL request would be rejected with
        'missing required arguments: locale'. Fail fast at the
        adapter to avoid the round-trip."""
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_GET_TRANSLATABLE_RESOURCE, {
                "resource_id": "gid://shopify/Product/1",
            })
        assert not result.ok

    def test_get_translatable_invalid_locale_type(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_GET_TRANSLATABLE_RESOURCE, {
                "resource_id": "gid://x", "locale": 12345,
            })
        assert not result.ok

    def test_get_translatable_not_found(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "translatableResource": None,
        }):
            result = a.execute(Capability.SHOPIFY_GET_TRANSLATABLE_RESOURCE, {
                "resource_id": "gid://shopify/Product/missing",
                "locale": "fr",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Register — dict form ────────────────────────────

    def test_register_dict_form_requires_locale(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://x",
                "translations": {
                    "title": {"value": "T", "digest": "abc"},
                },
            })
        assert not result.ok

    def test_register_dict_form_happy_path(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"translationsRegister": {
                "translations": [
                    {"key": "title", "value": "Tasse",
                     "locale": "fr", "outdated": False},
                    {"key": "body_html", "value": "<p>La tasse.</p>",
                     "locale": "fr", "outdated": False},
                ],
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://shopify/Product/1",
                "locale": "fr",
                "translations": {
                    "title": {"value": "Tasse", "digest": "abc"},
                    "body_html": {"value": "<p>La tasse.</p>",
                                  "digest": "def"},
                },
            })
        assert result.ok
        assert result.data["registered_count"] == 2
        # Wire format: each entry has key/value/locale + digest field
        # named the GraphQL way.
        sent = captured["translations"]
        assert len(sent) == 2
        keys = {t["key"] for t in sent}
        assert keys == {"title", "body_html"}
        for t in sent:
            assert t["locale"] == "fr"
            assert "translatableContentDigest" in t

    def test_register_dict_form_missing_digest_rejected(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://x",
                "locale": "fr",
                "translations": {
                    "title": {"value": "Tasse"},  # no digest
                },
            })
        assert not result.ok

    def test_register_dict_form_non_string_value_rejected(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://x", "locale": "fr",
                "translations": {"title": {"value": 12, "digest": "x"}},
            })
        assert not result.ok

    def test_register_dict_form_bare_string_entry_rejected(self):
        """Friendly form requires {value, digest}; a bare string would
        leave the digest implicit — which Shopify silently treats as
        outdated. Fail loudly instead."""
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://x", "locale": "fr",
                "translations": {"title": "Tasse"},
            })
        assert not result.ok

    def test_register_empty_translations_rejected(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://x", "locale": "fr",
                "translations": {},
            })
        assert not result.ok

    def test_register_caps_at_100_per_call(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            big = {f"k{i}": {"value": "v", "digest": "d"} for i in range(101)}
            result = a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://x", "locale": "fr",
                "translations": big,
            })
        assert not result.ok

    # ── Register — list form ────────────────────────────

    def test_register_list_form_happy_path(self):
        """List form is for callers that need per-translation locale
        (e.g. pushing fr + es in one call)."""
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"translationsRegister": {
                "translations": [
                    {"key": "title", "value": "Tasse", "locale": "fr"},
                    {"key": "title", "value": "Taza", "locale": "es"},
                ],
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://shopify/Product/1",
                "translations": [
                    {"key": "title", "value": "Tasse",
                     "locale": "fr", "digest": "abc"},
                    {"key": "title", "value": "Taza",
                     "locale": "es", "digest": "def"},
                ],
            })
        assert result.ok
        assert result.data["registered_count"] == 2
        # Per-entry locales preserved in the GraphQL payload.
        locales = {t["locale"] for t in captured["translations"]}
        assert locales == {"fr", "es"}

    def test_register_list_form_missing_locale_rejected(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://x",
                "translations": [
                    {"key": "title", "value": "T", "digest": "x"},
                ],
            })
        assert not result.ok

    def test_register_list_form_missing_digest_rejected(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://x",
                "translations": [
                    {"key": "title", "value": "T", "locale": "fr"},
                ],
            })
        assert not result.ok

    def test_register_list_form_locale_falls_back_to_top_level(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"translationsRegister": {
                "translations": [], "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://x",
                "locale": "fr",   # top-level fallback
                "translations": [
                    {"key": "title", "value": "T", "digest": "x"},
                ],
            })
        assert captured["translations"][0]["locale"] == "fr"

    def test_register_unsupported_translations_shape_rejected(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://x",
                "translations": "string",
            })
        assert not result.ok

    def test_register_user_errors_propagate(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "translationsRegister": {
                "translations": [],
                "userErrors": [{
                    "field": ["translations", "0", "locale"],
                    "message": "Locale not enabled",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_REGISTER_TRANSLATIONS, {
                "resource_id": "gid://x", "locale": "klingon",
                "translations": {"title": {"value": "Tasse", "digest": "x"}},
            })
        assert not result.ok

    # ── Remove translations ─────────────────────────────

    def test_remove_requires_resource_id(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REMOVE_TRANSLATIONS, {
                "keys": ["title"], "locales": ["fr"],
            })
        assert not result.ok

    def test_remove_requires_keys(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REMOVE_TRANSLATIONS, {
                "resource_id": "gid://x", "locales": ["fr"],
            })
        assert not result.ok
        with patch.object(a, "_gql"):
            r2 = a.execute(Capability.SHOPIFY_REMOVE_TRANSLATIONS, {
                "resource_id": "gid://x", "keys": [], "locales": ["fr"],
            })
        assert not r2.ok

    def test_remove_requires_locales(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REMOVE_TRANSLATIONS, {
                "resource_id": "gid://x", "keys": ["title"],
            })
        assert not result.ok

    def test_remove_singular_keys_locales_auto_wrap(self):
        """Engines often want to remove ONE key in ONE locale; the
        singular form should auto-wrap to a list-of-one."""
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"translationsRemove": {
                "translations": [
                    {"key": "title", "locale": "fr"},
                ],
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_REMOVE_TRANSLATIONS, {
                "resource_id": "gid://shopify/Product/1",
                "keys": "title",      # single key
                "locale": "fr",       # single locale
            })
        assert result.ok
        assert captured["translationKeys"] == ["title"]
        assert captured["locales"] == ["fr"]

    def test_remove_happy_path_multi(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "translationsRemove": {
                "translations": [
                    {"key": "title", "locale": "fr"},
                    {"key": "title", "locale": "es"},
                ],
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_REMOVE_TRANSLATIONS, {
                "resource_id": "gid://shopify/Product/1",
                "keys": ["title"],
                "locales": ["fr", "es"],
            })
        assert result.ok
        assert result.data["removed_count"] == 2

    def test_remove_user_errors_propagate(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "translationsRemove": {
                "translations": [],
                "userErrors": [{
                    "field": ["resourceId"],
                    "message": "Resource not found",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_REMOVE_TRANSLATIONS, {
                "resource_id": "gid://shopify/Product/missing",
                "keys": ["title"], "locales": ["fr"],
            })
        assert not result.ok

    def test_remove_non_string_key_rejected(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REMOVE_TRANSLATIONS, {
                "resource_id": "gid://x", "keys": [123], "locales": ["fr"],
            })
        assert not result.ok

    def test_remove_non_string_locale_rejected(self):
        from core.adapters.shopify.translations import ShopifyTranslationsAdapter
        a = ShopifyTranslationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_REMOVE_TRANSLATIONS, {
                "resource_id": "gid://x", "keys": ["title"], "locales": [123],
            })
        assert not result.ok


# ── ShopifyAnalyticsAdapter ────────────────────────────────


class TestShopifyAnalyticsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.analytics import ShopifyAnalyticsAdapter
        a = ShopifyAnalyticsAdapter()
        assert a.name == "shopify_analytics"
        assert Capability.SHOPIFY_RUN_ANALYTICS_QUERY in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.analytics import ShopifyAnalyticsAdapter
        a = ShopifyAnalyticsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    def test_requires_query_string(self):
        from core.adapters.shopify.analytics import ShopifyAnalyticsAdapter
        a = ShopifyAnalyticsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_RUN_ANALYTICS_QUERY, {})
        assert not result.ok
        with patch.object(a, "_gql"):
            r2 = a.execute(Capability.SHOPIFY_RUN_ANALYTICS_QUERY, {
                "query": "",
            })
        assert not r2.ok

    def test_query_alias_shopifyql_accepted(self):
        from core.adapters.shopify.analytics import ShopifyAnalyticsAdapter
        a = ShopifyAnalyticsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = v["query"]
            return {"shopifyqlQuery": {
                "__typename": "TableResponse",
                "tableData": {"columns": [], "rowData": []},
                "parseErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_RUN_ANALYTICS_QUERY, {
                "shopifyql": "FROM products SHOW total_sales",
            })
        assert captured["query"] == "FROM products SHOW total_sales"

    def test_run_query_happy_path_with_numeric_coercion(self):
        """ShopifyQL returns numeric column values as decimal-formatted
        strings. Engines do arithmetic on revenue / count fields, so
        the adapter coerces numeric columns to native float/int based
        on the GraphQL dataType so callers don't have to re-cast."""
        from core.adapters.shopify.analytics import ShopifyAnalyticsAdapter
        a = ShopifyAnalyticsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "shopifyqlQuery": {
                "tableData": {
                    "columns": [
                        {"name": "date", "dataType": "STRING",
                         "displayName": "Date"},
                        {"name": "orders", "dataType": "COUNT",
                         "displayName": "Orders"},
                        {"name": "revenue", "dataType": "DECIMAL",
                         "displayName": "Revenue"},
                    ],
                    "rows": [
                        ["2026-04-19", "12", "980.50"],
                        ["2026-04-20", "8.0", "612.40"],
                    ],
                },
                "parseErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_RUN_ANALYTICS_QUERY, {
                "query": "FROM orders SINCE -7d GROUP BY date",
            })
        assert result.ok
        assert result.data["row_count"] == 2
        first = result.data["rows"][0]
        assert first == {"date": "2026-04-19",
                         "orders": 12,
                         "revenue": 980.50}
        # Decimal-formatted COUNT ("8.0") still becomes int.
        assert result.data["rows"][1]["orders"] == 8
        # Column metadata preserved with snake_case keys, including
        # the human-readable displayName.
        assert result.data["columns"][2] == {
            "name": "revenue", "data_type": "DECIMAL",
            "display_name": "Revenue",
        }

    def test_run_query_falls_back_to_legacy_rowData_field(self):
        """Older API versions exposed ``rowData`` instead of ``rows``;
        the adapter tolerates both so it doesn't break on a schema
        flip mid-rollout."""
        from core.adapters.shopify.analytics import ShopifyAnalyticsAdapter
        a = ShopifyAnalyticsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "shopifyqlQuery": {
                "tableData": {
                    "columns": [
                        {"name": "x", "dataType": "STRING"},
                    ],
                    "rowData": [["A"]],   # legacy field name
                },
                "parseErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_RUN_ANALYTICS_QUERY, {
                "query": "FROM x SHOW x",
            })
        assert result.ok
        assert result.data["rows"] == [{"x": "A"}]

    def test_run_query_parse_errors_become_validation_failure(self):
        """ShopifyQL parse errors are caller bugs (bad DSL syntax),
        not vendor outages — surface them as AdapterValidationError so
        the router doesn't fall back to a different adapter."""
        from core.adapters.shopify.analytics import ShopifyAnalyticsAdapter
        a = ShopifyAnalyticsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "shopifyqlQuery": {
                "tableData": None,
                "parseErrors": [
                    {"code": "SYNTAX_ERROR",
                     "message": "Unexpected token 'FROOM'"},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_RUN_ANALYTICS_QUERY, {
                "query": "FROOM orders",
            })
        assert not result.ok

    def test_run_query_handles_empty_result(self):
        from core.adapters.shopify.analytics import ShopifyAnalyticsAdapter
        a = ShopifyAnalyticsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "shopifyqlQuery": {
                "tableData": {
                    "columns": [{"name": "date", "dataType": "STRING"}],
                    "rows": [],
                },
                "parseErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_RUN_ANALYTICS_QUERY, {
                "query": "FROM orders SINCE -1d",
            })
        assert result.ok
        assert result.data["row_count"] == 0
        assert result.data["columns"][0]["name"] == "date"

    def test_rows_to_dicts_skips_non_list_rows(self):
        from core.adapters.shopify.analytics import ShopifyAnalyticsAdapter
        out = ShopifyAnalyticsAdapter._rows_to_dicts(
            [{"name": "x", "data_type": "STRING"}],
            [["A"], "not a list", ["B"]],
        )
        assert out == [{"x": "A"}, {"x": "B"}]

    def test_rows_to_dicts_truncates_overlong_rows(self):
        """If a row has more columns than the schema declares (Shopify
        sometimes does this for joined queries), the extra cells are
        silently dropped rather than crashing the parse."""
        from core.adapters.shopify.analytics import ShopifyAnalyticsAdapter
        out = ShopifyAnalyticsAdapter._rows_to_dicts(
            [{"name": "x", "data_type": "STRING"}],
            [["A", "extra1", "extra2"]],
        )
        assert out == [{"x": "A"}]

    def test_normalise_columns_skips_non_dict_entries(self):
        from core.adapters.shopify.analytics import ShopifyAnalyticsAdapter
        out = ShopifyAnalyticsAdapter._normalise_columns([
            {"name": "ok", "dataType": "STRING"},
            "garbage",
            {"name": "also_ok", "dataType": "DECIMAL"},
        ])
        assert len(out) == 2
        assert out[0]["name"] == "ok"
        assert out[1]["data_type"] == "DECIMAL"

    def test_coerce_value_handles_all_branches(self):
        from core.adapters.shopify.analytics import _coerce_value
        # Numeric coercion
        assert _coerce_value("12.5", "decimal") == 12.5
        assert _coerce_value("100", "currency") == 100.0
        assert _coerce_value("42", "int") == 42
        # Decimal-formatted int tolerated
        assert _coerce_value("8.0", "count") == 8
        # Non-numeric strings in numeric columns left alone
        assert _coerce_value("not a number", "decimal") == "not a number"
        # JSON columns parsed
        assert _coerce_value('{"a": 1}', "json") == {"a": 1}
        # Malformed JSON in a JSON column passes through as the string
        # rather than raising — engines may want to log and continue.
        assert _coerce_value("not json", "json") == "not json"
        # None passes through
        assert _coerce_value(None, "decimal") is None
        # Plain strings in plain string columns untouched (callers may
        # be doing exact-match on order ids that look numeric).
        assert _coerce_value("12345", "string") == "12345"


# ── ShopifyThemesAdapter ───────────────────────────────────


class TestShopifyThemesAdapter:
    def test_metadata(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter()
        assert a.name == "shopify_themes"
        for cap in (
            Capability.SHOPIFY_LIST_THEMES,
            Capability.SHOPIFY_LIST_THEME_FILES,
            Capability.SHOPIFY_UPSERT_THEME_FILES,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List themes ──────────────────────────────────────

    def test_list_themes_happy_path(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "themes": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/OnlineStoreTheme/1",
                        "name": "Dawn",
                        "role": "MAIN",
                        "processing": False,
                        "createdAt": "2026-01-01T00:00:00Z",
                        "updatedAt": "2026-04-01T00:00:00Z",
                    }},
                    {"node": {
                        "id": "gid://shopify/OnlineStoreTheme/2",
                        "name": "Backup",
                        "role": "UNPUBLISHED",
                        "processing": False,
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_THEMES, {"limit": 10})
        assert result.ok
        assert result.data["count"] == 2
        roles = {t["role"] for t in result.data["themes"]}
        assert roles == {"MAIN", "UNPUBLISHED"}

    def test_list_themes_role_aliases_resolve(self):
        """Engines pass natural words ('live', 'dev'); the adapter
        maps them to the canonical UPPER_SNAKE Shopify enum values."""
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["roles"] = v["roles"]
            return {"themes": {"pageInfo": {}, "edges": []}}

        for friendly, expected in (
            ("live", "MAIN"),
            ("published", "MAIN"),
            ("dev", "DEVELOPMENT"),
            ("development", "DEVELOPMENT"),
            ("MAIN", "MAIN"),
        ):
            captured.clear()
            with patch.object(a, "_gql", side_effect=fake_gql):
                a.execute(Capability.SHOPIFY_LIST_THEMES, {
                    "role": friendly,
                })
            assert captured["roles"] == [expected], friendly

    def test_list_themes_role_filter_string_or_list(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["roles"] = v["roles"]
            return {"themes": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_THEMES, {
                "roles": ["main", "demo"],
            })
        assert captured["roles"] == ["MAIN", "DEMO"]

    def test_list_themes_invalid_role_type_rejected(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_LIST_THEMES, {
                "roles": 12345,
            })
        assert not result.ok

    def test_list_themes_clamps_limit(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"themes": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_THEMES, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_themes_empty(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "themes": {"pageInfo": {}, "edges": []},
        }):
            result = a.execute(Capability.SHOPIFY_LIST_THEMES, {})
        assert result.ok
        assert result.data["count"] == 0

    # ── List theme files ─────────────────────────────────

    def test_list_theme_files_requires_theme_id(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_LIST_THEME_FILES, {})
        assert not result.ok

    def test_list_theme_files_happy_path(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "theme": {
                "id": "gid://shopify/OnlineStoreTheme/1",
                "name": "Dawn",
                "files": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "cur"},
                    "edges": [
                        {"node": {
                            "filename": "snippets/foo.liquid",
                            "size": "123",
                            "contentType": "LIQUID",
                            "checksumMd5": "abc",
                        }},
                    ],
                },
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_THEME_FILES, {
                "theme_id": "gid://shopify/OnlineStoreTheme/1",
            })
        assert result.ok
        assert result.data["found"] is True
        assert result.data["theme_name"] == "Dawn"
        assert result.data["count"] == 1
        f = result.data["files"][0]
        assert f["filename"] == "snippets/foo.liquid"
        # Size string from GraphQL coerced to int.
        assert f["size"] == 123

    def test_list_theme_files_filenames_string_to_list(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["filenames"] = v["filenames"]
            return {"theme": {"id": "gid://x", "files": {
                "pageInfo": {}, "edges": [],
            }}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_THEME_FILES, {
                "theme_id": "gid://x",
                "filenames": "snippets/foo.liquid",
            })
        assert captured["filenames"] == ["snippets/foo.liquid"]

    def test_list_theme_files_not_found_returns_found_false(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"theme": None}):
            result = a.execute(Capability.SHOPIFY_LIST_THEME_FILES, {
                "theme_id": "gid://shopify/OnlineStoreTheme/missing",
            })
        assert result.ok
        assert result.data["found"] is False
        assert result.data["count"] == 0

    def test_list_theme_files_filenames_non_list_rejected(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_LIST_THEME_FILES, {
                "theme_id": "gid://x",
                "filenames": 12345,
            })
        assert not result.ok

    # ── Upsert theme files ──────────────────────────────

    def test_upsert_requires_theme_id(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_UPSERT_THEME_FILES, {
                "filename": "snippets/foo.liquid", "body": "{% comment %}{% endcomment %}",
            })
        assert not result.ok

    def test_build_files_input_single_form(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        out = ShopifyThemesAdapter._build_files_input({
            "filename": "snippets/foo.liquid",
            "body": "{% comment %}hi{% endcomment %}",
        })
        assert len(out) == 1
        assert out[0]["filename"] == "snippets/foo.liquid"
        assert out[0]["body"] == {
            "type": "TEXT",
            "value": "{% comment %}hi{% endcomment %}",
        }

    def test_build_files_input_batch_form(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        out = ShopifyThemesAdapter._build_files_input({"files": [
            {"filename": "snippets/a.liquid", "body": "A"},
            {"filename": "sections/b.liquid", "body": "B"},
        ]})
        assert len(out) == 2
        assert out[1]["filename"] == "sections/b.liquid"
        assert out[1]["body"]["value"] == "B"

    def test_build_files_input_url_form(self):
        """Caller can fetch from a URL instead of inline-pasting bytes
        — useful for the creative pipeline pushing a generated CSS
        asset hosted on the CDN."""
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        out = ShopifyThemesAdapter._build_files_input({"files": [
            {"filename": "assets/hero.jpg",
             "url": "https://cdn.example.com/hero.jpg"},
        ]})
        assert out[0]["body"] == {
            "type": "URL",
            "value": "https://cdn.example.com/hero.jpg",
        }

    def test_build_files_input_body_and_url_mutually_exclusive(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyThemesAdapter._build_files_input({"files": [
                {"filename": "a.liquid", "body": "x",
                 "url": "https://x"},
            ]})

    def test_build_files_input_neither_body_nor_url_rejected(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyThemesAdapter._build_files_input({"files": [
                {"filename": "a.liquid"},
            ]})

    def test_build_files_input_url_must_be_http(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        for bad in ("/local/path", "ftp://x", "data:image/png;base64,..."):
            with pytest.raises(AdapterValidationError):
                ShopifyThemesAdapter._build_files_input({"files": [
                    {"filename": "x.liquid", "url": bad},
                ]})

    def test_build_files_input_caps_at_50(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        too_many = [
            {"filename": f"snippets/x{i}.liquid", "body": "x"}
            for i in range(51)
        ]
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyThemesAdapter._build_files_input({"files": too_many})
        assert "50" in str(exc.value)

    def test_build_files_input_missing_filename(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyThemesAdapter._build_files_input({"files": [
                {"body": "x"},
            ]})

    def test_upsert_happy_path(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "themeFilesUpsert": {
                "upsertedThemeFiles": [
                    {"filename": "snippets/foo.liquid"},
                    {"filename": "sections/bar.liquid"},
                ],
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_UPSERT_THEME_FILES, {
                "theme_id": "gid://shopify/OnlineStoreTheme/1",
                "files": [
                    {"filename": "snippets/foo.liquid", "body": "x"},
                    {"filename": "sections/bar.liquid", "body": "y"},
                ],
            })
        assert result.ok
        assert result.data["upserted_count"] == 2
        assert "snippets/foo.liquid" in result.data["filenames"]

    def test_upsert_user_errors_propagate(self):
        from core.adapters.shopify.themes import ShopifyThemesAdapter
        a = ShopifyThemesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "themeFilesUpsert": {
                "upsertedThemeFiles": [],
                "userErrors": [{
                    "field": ["files", "0", "filename"],
                    "message": "Filename invalid",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_UPSERT_THEME_FILES, {
                "theme_id": "gid://x",
                "filename": "INVALID/PATH",
                "body": "x",
            })
        assert not result.ok


# ── ShopifyOrderEditsAdapter ───────────────────────────────


class TestShopifyOrderEditsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        a = ShopifyOrderEditsAdapter()
        assert a.name == "shopify_order_edits"
        assert Capability.SHOPIFY_EDIT_ORDER in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        a = ShopifyOrderEditsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Top-level validation ──────────────────────────────

    def test_requires_order_id(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        a = ShopifyOrderEditsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_EDIT_ORDER, {
                "changes": [{"op": "add_variant",
                             "variant_id": "gid://x", "quantity": 1}],
            })
        assert not result.ok

    def test_requires_changes_list(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        a = ShopifyOrderEditsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_EDIT_ORDER, {
                "order_id": "gid://shopify/Order/1",
            })
        assert not result.ok

    def test_rejects_empty_changes_list(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        a = ShopifyOrderEditsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_EDIT_ORDER, {
                "order_id": "gid://shopify/Order/1", "changes": [],
            })
        assert not result.ok

    def test_rejects_unknown_op(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        with pytest.raises(AdapterValidationError) as exc:
            ShopifyOrderEditsAdapter._build_change(
                {"op": "fly_to_moon"}, 0,
            )
        assert "fly_to_moon" in str(exc.value)

    def test_rejects_non_dict_change(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyOrderEditsAdapter._build_change("not a dict", 0)

    # ── _build_change validation per op ───────────────────

    def test_build_add_variant_validates(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        # Happy path
        out = ShopifyOrderEditsAdapter._build_change({
            "op": "add_variant",
            "variant_id": "gid://shopify/ProductVariant/1",
            "quantity": 3,
        }, 0)
        assert out["mutation_name"] == "orderEditAddVariant"
        assert out["variables"]["variantId"].endswith("/1")
        assert out["variables"]["quantity"] == 3

        # Missing variant_id
        with pytest.raises(AdapterValidationError):
            ShopifyOrderEditsAdapter._build_change({
                "op": "add_variant", "quantity": 1,
            }, 0)
        # Quantity < 1 rejected (add_variant must add at least one)
        with pytest.raises(AdapterValidationError):
            ShopifyOrderEditsAdapter._build_change({
                "op": "add_variant", "variant_id": "gid://x", "quantity": 0,
            }, 0)
        # Non-numeric quantity rejected
        with pytest.raises(AdapterValidationError):
            ShopifyOrderEditsAdapter._build_change({
                "op": "add_variant", "variant_id": "gid://x",
                "quantity": "many",
            }, 0)

    def test_build_add_custom_item_validates(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        out = ShopifyOrderEditsAdapter._build_change({
            "op": "add_custom_item", "title": "Make-good",
            "price": 0, "quantity": 1, "taxable": False,
            "requires_shipping": False,
        }, 0)
        assert out["mutation_name"] == "orderEditAddCustomItem"
        assert out["variables"]["title"] == "Make-good"
        assert out["variables"]["price"] == {
            "amount": "0.00", "currencyCode": "USD",
        }
        assert out["variables"]["taxable"] is False
        assert out["variables"]["requiresShipping"] is False

        # Missing title
        with pytest.raises(AdapterValidationError):
            ShopifyOrderEditsAdapter._build_change({
                "op": "add_custom_item", "price": 5, "quantity": 1,
            }, 0)
        # Missing price
        with pytest.raises(AdapterValidationError):
            ShopifyOrderEditsAdapter._build_change({
                "op": "add_custom_item", "title": "x", "quantity": 1,
            }, 0)

    def test_build_set_quantity_validates(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        # quantity=0 is the canonical "remove the line item" form,
        # which is why set_quantity allows 0 but add_variant doesn't.
        out = ShopifyOrderEditsAdapter._build_change({
            "op": "set_quantity",
            "line_item_id": "gid://shopify/CalculatedLineItem/1",
            "quantity": 0,
        }, 0)
        assert out["variables"]["quantity"] == 0
        assert out["variables"]["restock"] is True   # default-True

        # quantity negative rejected
        with pytest.raises(AdapterValidationError):
            ShopifyOrderEditsAdapter._build_change({
                "op": "set_quantity",
                "line_item_id": "gid://x", "quantity": -1,
            }, 0)
        # Missing line_item_id
        with pytest.raises(AdapterValidationError):
            ShopifyOrderEditsAdapter._build_change({
                "op": "set_quantity", "quantity": 1,
            }, 0)
        # Missing quantity (None != 0)
        with pytest.raises(AdapterValidationError):
            ShopifyOrderEditsAdapter._build_change({
                "op": "set_quantity", "line_item_id": "gid://x",
            }, 0)

    def test_build_add_line_item_discount_validates(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        out = ShopifyOrderEditsAdapter._build_change({
            "op": "add_line_item_discount",
            "line_item_id": "gid://x",
            "value_type": "PERCENTAGE", "value": 15,
            "description": "Sorry",
        }, 0)
        assert out["variables"]["discount"]["value"] == 15.0
        assert out["variables"]["discount"]["valueType"] == "PERCENTAGE"
        assert out["variables"]["discount"]["description"] == "Sorry"

        # Default value_type is PERCENTAGE
        out2 = ShopifyOrderEditsAdapter._build_change({
            "op": "add_line_item_discount",
            "line_item_id": "gid://x", "value": 5,
        }, 0)
        assert out2["variables"]["discount"]["valueType"] == "PERCENTAGE"

        # PERCENTAGE > 100 rejected
        with pytest.raises(AdapterValidationError):
            ShopifyOrderEditsAdapter._build_change({
                "op": "add_line_item_discount",
                "line_item_id": "gid://x",
                "value_type": "PERCENTAGE", "value": 150,
            }, 0)
        # FIXED_AMOUNT > 100 OK
        out3 = ShopifyOrderEditsAdapter._build_change({
            "op": "add_line_item_discount",
            "line_item_id": "gid://x",
            "value_type": "FIXED_AMOUNT", "value": 250,
        }, 0)
        assert out3["variables"]["discount"]["value"] == 250.0

        # Bad value_type
        with pytest.raises(AdapterValidationError):
            ShopifyOrderEditsAdapter._build_change({
                "op": "add_line_item_discount",
                "line_item_id": "gid://x",
                "value_type": "FREE_LUNCH", "value": 5,
            }, 0)

    # ── Full flow happy path ──────────────────────────────

    def test_edit_order_runs_begin_apply_commit(self):
        """The adapter folds Shopify's stateful 3-stage edit flow
        (begin → mutations → commit) into a single call. Each call
        must be made in order and the calculated_order_id must be
        passed through every mutation."""
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        a = ShopifyOrderEditsAdapter(shop_url="s", access_token="t")
        calls: list[str] = []

        def fake_gql(q, v):
            # Detect which mutation by name in the GraphQL document.
            if "orderEditBegin" in q:
                calls.append("begin")
                return {"orderEditBegin": {
                    "calculatedOrder": {"id": "gid://shopify/CalculatedOrder/CC"},
                    "userErrors": [],
                }}
            if "orderEditAddVariant" in q:
                calls.append("add_variant")
                # Variable id MUST be the calculated order, not the
                # original order id.
                assert v["id"] == "gid://shopify/CalculatedOrder/CC"
                return {"orderEditAddVariant": {
                    "calculatedOrder": {"id": v["id"]}, "userErrors": [],
                }}
            if "orderEditSetQuantity" in q:
                calls.append("set_quantity")
                assert v["id"] == "gid://shopify/CalculatedOrder/CC"
                return {"orderEditSetQuantity": {
                    "calculatedOrder": {"id": v["id"]}, "userErrors": [],
                }}
            if "orderEditCommit" in q:
                calls.append("commit")
                assert v["id"] == "gid://shopify/CalculatedOrder/CC"
                return {"orderEditCommit": {
                    "order": {
                        "id": "gid://shopify/Order/777",
                        "name": "#1001",
                        "totalPriceSet": {
                            "presentmentMoney": {
                                "amount": "120.00", "currencyCode": "USD",
                            },
                        },
                    },
                    "userErrors": [],
                }}
            raise AssertionError(f"unexpected mutation: {q}")

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_EDIT_ORDER, {
                "order_id": "gid://shopify/Order/777",
                "changes": [
                    {"op": "add_variant",
                     "variant_id": "gid://shopify/ProductVariant/X",
                     "quantity": 1},
                    {"op": "set_quantity",
                     "line_item_id": "gid://shopify/CalculatedLineItem/Y",
                     "quantity": 0},
                ],
                "notify_customer": True,
                "staff_note": "Customer requested swap.",
            })
        assert result.ok
        # Sequence: begin first, mutations in caller-supplied order,
        # commit last. The adapter MUST NOT commit until every change
        # succeeded.
        assert calls == ["begin", "add_variant", "set_quantity", "commit"]
        assert result.data["order_id"] == "gid://shopify/Order/777"
        assert result.data["calculated_order_id"] == "gid://shopify/CalculatedOrder/CC"
        assert result.data["change_count"] == 2
        assert result.data["new_total"] == 120.0
        assert result.data["currency"] == "USD"
        assert result.data["notified_customer"] is True

    def test_edit_order_skips_commit_on_intermediate_failure(self):
        """If any change fails the adapter must surface the error
        WITHOUT committing — Shopify discards the calculated order
        on session end so there's no half-applied state to clean up.
        Pre-commit failure with no visible side effects is the
        contract callers rely on."""
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        a = ShopifyOrderEditsAdapter(shop_url="s", access_token="t")
        calls: list[str] = []

        def fake_gql(q, v):
            if "orderEditBegin" in q:
                calls.append("begin")
                return {"orderEditBegin": {
                    "calculatedOrder": {"id": "gid://shopify/CalculatedOrder/CC"},
                    "userErrors": [],
                }}
            if "orderEditAddVariant" in q:
                calls.append("add_variant")
                # First mutation fails with a userError.
                return {"orderEditAddVariant": {
                    "calculatedOrder": None,
                    "userErrors": [{
                        "field": ["variantId"],
                        "message": "Variant not found",
                    }],
                }}
            if "orderEditCommit" in q:
                calls.append("commit")  # MUST NOT happen
                return {"orderEditCommit": {
                    "order": None, "userErrors": [],
                }}
            raise AssertionError(f"unexpected mutation: {q}")

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_EDIT_ORDER, {
                "order_id": "gid://shopify/Order/777",
                "changes": [
                    {"op": "add_variant",
                     "variant_id": "gid://shopify/ProductVariant/missing",
                     "quantity": 1},
                ],
            })
        assert not result.ok
        # commit was not called — the contract that prevents
        # half-applied edits.
        assert "commit" not in calls

    def test_edit_order_begin_failure_short_circuits(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        a = ShopifyOrderEditsAdapter(shop_url="s", access_token="t")
        calls: list[str] = []

        def fake_gql(q, v):
            if "orderEditBegin" in q:
                calls.append("begin")
                return {"orderEditBegin": {
                    "calculatedOrder": None,
                    "userErrors": [{
                        "field": ["id"], "message": "Order not found",
                    }],
                }}
            calls.append("other")
            raise AssertionError("nothing should run after begin failed")

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_EDIT_ORDER, {
                "order_id": "gid://shopify/Order/missing",
                "changes": [
                    {"op": "add_variant",
                     "variant_id": "gid://x", "quantity": 1},
                ],
            })
        assert not result.ok
        assert calls == ["begin"]

    def test_edit_order_validates_all_changes_before_calling_begin(self):
        """If a later change is malformed we must reject BEFORE
        calling begin — otherwise the begin side-effect happens for
        nothing. (The calculated order is auto-discarded but it's
        still a wasted GraphQL hop and a real audit-log entry.)"""
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        a = ShopifyOrderEditsAdapter(shop_url="s", access_token="t")
        calls: list[str] = []

        def fake_gql(q, v):
            calls.append(q[:30])
            return {}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_EDIT_ORDER, {
                "order_id": "gid://shopify/Order/1",
                "changes": [
                    {"op": "add_variant",
                     "variant_id": "gid://x", "quantity": 1},
                    {"op": "set_quantity"},  # malformed (no line_item_id)
                ],
            })
        assert not result.ok
        assert calls == []  # begin was NOT called

    def test_edit_order_passes_staff_note_only_when_set(self):
        from core.adapters.shopify.order_edits import ShopifyOrderEditsAdapter
        a = ShopifyOrderEditsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            if "orderEditBegin" in q:
                return {"orderEditBegin": {
                    "calculatedOrder": {"id": "gid://shopify/CalculatedOrder/CC"},
                    "userErrors": [],
                }}
            if "orderEditAddVariant" in q:
                return {"orderEditAddVariant": {
                    "calculatedOrder": {"id": v["id"]}, "userErrors": [],
                }}
            if "orderEditCommit" in q:
                captured.update(v)
                return {"orderEditCommit": {
                    "order": {"id": "gid://shopify/Order/1", "name": "#1"},
                    "userErrors": [],
                }}
            return {}

        # No staff_note → key absent from commit variables.
        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_EDIT_ORDER, {
                "order_id": "gid://shopify/Order/1",
                "changes": [
                    {"op": "add_variant",
                     "variant_id": "gid://x", "quantity": 1},
                ],
            })
        assert "staffNote" not in captured

        # With staff_note → key present.
        captured.clear()
        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_EDIT_ORDER, {
                "order_id": "gid://shopify/Order/1",
                "changes": [
                    {"op": "add_variant",
                     "variant_id": "gid://x", "quantity": 1},
                ],
                "staff_note": "Goodwill discount",
            })
        assert captured["staffNote"] == "Goodwill discount"


# ── ShopifyPublicationsAdapter ─────────────────────────────


class TestShopifyPublicationsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter()
        assert a.name == "shopify_publications"
        for cap in (
            Capability.SHOPIFY_LIST_PUBLICATIONS,
            Capability.SHOPIFY_PUBLISH_RESOURCE,
            Capability.SHOPIFY_UNPUBLISH_RESOURCE,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────────────

    def test_list_publications_happy_path(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "publications": {
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Publication/1",
                        "name": "Online Store",
                        "supportsFuturePublishing": True,
                    }},
                    {"node": {
                        "id": "gid://shopify/Publication/2",
                        "name": "Shop Channel",
                        "supportsFuturePublishing": False,
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_PUBLICATIONS,
                               {"limit": 10})
        assert result.ok
        assert result.data["count"] == 2
        names = {p["name"] for p in result.data["publications"]}
        assert names == {"Online Store", "Shop Channel"}
        # supports_future_publishing flag is preserved per-channel.
        sfp = {p["name"]: p["supports_future_publishing"]
               for p in result.data["publications"]}
        assert sfp == {"Online Store": True, "Shop Channel": False}

    def test_list_publications_clamps_limit(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"publications": {"edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_PUBLICATIONS, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_publications_default_limit(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"publications": {"edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_PUBLICATIONS, {})
        assert captured["first"] == 50

    def test_list_publications_handles_empty(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "publications": {"edges": []},
        }):
            result = a.execute(Capability.SHOPIFY_LIST_PUBLICATIONS, {})
        assert result.ok
        assert result.data["count"] == 0

    # ── Publish — validation ─────────────────────────────

    def test_publish_requires_resource_id(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_PUBLISH_RESOURCE, {
                "publication_ids": ["gid://shopify/Publication/1"],
            })
        assert not result.ok

    def test_publish_requires_publication_ids(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_PUBLISH_RESOURCE, {
                "id": "gid://shopify/Product/1",
            })
        assert not result.ok

    def test_publish_rejects_empty_publication_list(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_PUBLISH_RESOURCE, {
                "id": "gid://shopify/Product/1",
                "publication_ids": [],
            })
        assert not result.ok

    def test_publish_rejects_non_string_publication_id(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_PUBLISH_RESOURCE, {
                "id": "gid://shopify/Product/1",
                "publication_ids": [12345],
            })
        assert not result.ok

    def test_publish_accepts_singular_publication_id(self):
        """Engines often want to push to ONE channel; the singular
        form should auto-wrap into a list-of-one so callers don't have
        to remember which form the API wants."""
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["input"] = v["input"]
            captured["id"] = v["id"]
            return {"publishablePublish": {
                "publishable": {
                    "__typename": "Product",
                    "id": v["id"], "title": "Cool Mug",
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_PUBLISH_RESOURCE, {
                "id": "gid://shopify/Product/1",
                "publication_id": "gid://shopify/Publication/x",
            })
        assert result.ok
        assert len(captured["input"]) == 1
        assert captured["input"][0] == {
            "publicationId": "gid://shopify/Publication/x",
        }

    # ── Publish — happy path ─────────────────────────────

    def test_publish_resource_to_multiple_channels(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["id"] = v["id"]
            captured["input"] = v["input"]
            return {"publishablePublish": {
                "publishable": {
                    "__typename": "Product",
                    "id": v["id"],
                    "title": "Winning Product",
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_PUBLISH_RESOURCE, {
                "id": "gid://shopify/Product/1",
                "publication_ids": [
                    "gid://shopify/Publication/online",
                    "gid://shopify/Publication/shop",
                    "gid://shopify/Publication/fb",
                ],
            })
        assert result.ok
        assert result.data["id"] == "gid://shopify/Product/1"
        assert result.data["title"] == "Winning Product"
        assert result.data["kind"] == "product"
        assert result.data["publication_count"] == 3
        assert len(captured["input"]) == 3
        assert captured["input"][0]["publicationId"] == "gid://shopify/Publication/online"

    def test_publish_user_errors_propagate(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "publishablePublish": {
                "publishable": None,
                "userErrors": [{
                    "field": ["id"],
                    "message": "Resource not found",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_PUBLISH_RESOURCE, {
                "id": "gid://shopify/Product/missing",
                "publication_ids": ["gid://shopify/Publication/1"],
            })
        assert not result.ok

    # ── Unpublish — happy path ────────────────────────────

    def test_unpublish_resource_happy_path(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "publishableUnpublish": {
                "publishable": {
                    "__typename": "Product",
                    "id": "gid://shopify/Product/1",
                    "title": "Underperformer",
                },
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_UNPUBLISH_RESOURCE, {
                "id": "gid://shopify/Product/1",
                "publication_ids": ["gid://shopify/Publication/fb"],
            })
        assert result.ok
        assert result.data["title"] == "Underperformer"
        assert result.data["kind"] == "product"
        assert result.data["publication_count"] == 1

    def test_unpublish_collection_kind_collection(self):
        """Publishable is a union over Product / Collection — the
        normaliser must surface __typename so callers know which kind
        they just operated on."""
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "publishableUnpublish": {
                "publishable": {
                    "__typename": "Collection",
                    "id": "gid://shopify/Collection/1",
                    "title": "Summer 2026",
                },
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_UNPUBLISH_RESOURCE, {
                "id": "gid://shopify/Collection/1",
                "publication_ids": ["gid://shopify/Publication/x"],
            })
        assert result.ok
        assert result.data["kind"] == "collection"

    def test_unpublish_user_errors_propagate(self):
        from core.adapters.shopify.publications import ShopifyPublicationsAdapter
        a = ShopifyPublicationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "publishableUnpublish": {
                "publishable": None,
                "userErrors": [{
                    "field": ["id"],
                    "message": "Already unpublished",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_UNPUBLISH_RESOURCE, {
                "id": "gid://shopify/Product/1",
                "publication_ids": ["gid://shopify/Publication/fb"],
            })
        assert not result.ok


# ── ShopifyMetaobjectsAdapter ──────────────────────────────


class TestShopifyMetaobjectsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter()
        assert a.name == "shopify_metaobjects"
        for cap in (
            Capability.SHOPIFY_CREATE_METAOBJECT,
            Capability.SHOPIFY_UPDATE_METAOBJECT,
            Capability.SHOPIFY_GET_METAOBJECT,
            Capability.SHOPIFY_LIST_METAOBJECTS,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── _normalise_fields (dict and list shapes) ─────────────

    def test_normalise_fields_dict_form_coerces_primitives(self):
        from core.adapters.shopify.metaobjects import _normalise_fields
        out = _normalise_fields({
            "question": "When does it ship?",
            "priority": 5,
            "active": True,
            "missing": None,
        }, where="t")
        # Convert to a dict for easier assertions; field order preserved
        # in source but we don't depend on it for primitives.
        flat = {f["key"]: f["value"] for f in out}
        assert flat["question"] == "When does it ship?"
        assert flat["priority"] == "5"
        assert flat["active"] == "true"
        assert flat["missing"] == ""

    def test_normalise_fields_dict_serialises_complex_values(self):
        from core.adapters.shopify.metaobjects import _normalise_fields
        out = _normalise_fields({
            "tags": ["sale", "summer"],
            "config": {"a": 1, "b": 2},
        }, where="t")
        flat = {f["key"]: f["value"] for f in out}
        assert "sale" in flat["tags"]
        assert flat["config"].startswith("{") and flat["config"].endswith("}")

    def test_normalise_fields_list_form_passes_through(self):
        from core.adapters.shopify.metaobjects import _normalise_fields
        out = _normalise_fields([
            {"key": "title", "value": "Hello"},
            {"key": "count", "value": 42},
        ], where="t")
        assert out == [
            {"key": "title", "value": "Hello"},
            {"key": "count", "value": "42"},
        ]

    def test_normalise_fields_list_rejects_missing_key(self):
        from core.adapters.shopify.metaobjects import _normalise_fields
        with pytest.raises(AdapterValidationError):
            _normalise_fields([{"value": "no key here"}], where="t")

    def test_normalise_fields_list_rejects_non_dict(self):
        from core.adapters.shopify.metaobjects import _normalise_fields
        with pytest.raises(AdapterValidationError):
            _normalise_fields(["not a dict"], where="t")

    def test_normalise_fields_dict_rejects_empty_key(self):
        from core.adapters.shopify.metaobjects import _normalise_fields
        with pytest.raises(AdapterValidationError):
            _normalise_fields({"": "value"}, where="t")

    def test_normalise_fields_unsupported_shape_rejected(self):
        from core.adapters.shopify.metaobjects import _normalise_fields
        with pytest.raises(AdapterValidationError):
            _normalise_fields("just a string", where="t")  # type: ignore[arg-type]

    # ── _build_create_input ───────────────────────────────

    def test_build_create_input_requires_type(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyMetaobjectsAdapter._build_create_input({
                "fields": {"x": "y"},
            })

    def test_build_create_input_requires_fields(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        with pytest.raises(AdapterValidationError):
            ShopifyMetaobjectsAdapter._build_create_input({"type": "faq"})
        with pytest.raises(AdapterValidationError):
            ShopifyMetaobjectsAdapter._build_create_input({
                "type": "faq", "fields": {},
            })

    def test_build_create_input_handle_passes_through(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        out = ShopifyMetaobjectsAdapter._build_create_input({
            "type": "faq",
            "handle": "shipping-faq",
            "fields": {"q": "When?", "a": "Now."},
        })
        assert out["type"] == "faq"
        assert out["handle"] == "shipping-faq"
        keys = {f["key"] for f in out["fields"]}
        assert keys == {"q", "a"}

    # ── Create — happy path ──────────────────────────────

    def test_create_metaobject_happy_path(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "metaobjectCreate": {
                "metaobject": {
                    "id": "gid://shopify/Metaobject/1",
                    "handle": "shipping-faq",
                    "type": "faq",
                    "displayName": "Shipping FAQ",
                    "updatedAt": "2026-04-25T12:00:00Z",
                    "fields": [
                        {"key": "question", "value": "When?", "type": "single_line_text_field"},
                        {"key": "answer", "value": "Now.", "type": "rich_text_field"},
                    ],
                },
                "userErrors": [],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_METAOBJECT, {
                "type": "faq",
                "handle": "shipping-faq",
                "fields": {"question": "When?", "answer": "Now."},
            })
        assert result.ok
        m = result.data["metaobject"]
        assert m["id"] == "gid://shopify/Metaobject/1"
        assert m["handle"] == "shipping-faq"
        assert m["type"] == "faq"
        # Fields are flattened to a dict for ergonomic access.
        assert m["fields"]["question"] == "When?"
        assert m["fields"]["answer"] == "Now."
        assert m["field_meta"]["question"]["type"] == "single_line_text_field"

    def test_create_metaobject_user_errors_propagate(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "metaobjectCreate": {
                "metaobject": None,
                "userErrors": [{
                    "field": ["metaobject", "type"],
                    "message": "Type does not exist",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_CREATE_METAOBJECT, {
                "type": "nonexistent",
                "fields": {"x": "y"},
            })
        assert not result.ok

    # ── Update ───────────────────────────────────────────

    def test_update_metaobject_requires_id(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_UPDATE_METAOBJECT, {
                "fields": {"x": "y"},
            })
        assert not result.ok

    def test_update_metaobject_needs_at_least_one_change(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_UPDATE_METAOBJECT, {
                "id": "gid://shopify/Metaobject/1",
            })
        assert not result.ok

    def test_update_metaobject_partial_fields_change(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["id"] = v["id"]
            captured["meta"] = v["metaobject"]
            return {"metaobjectUpdate": {
                "metaobject": {
                    "id": v["id"], "handle": "h", "type": "faq",
                    "fields": [{"key": "q", "value": "Updated"}],
                }, "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_UPDATE_METAOBJECT, {
                "id": "gid://shopify/Metaobject/1",
                "fields": {"q": "Updated"},
            })
        assert captured["id"] == "gid://shopify/Metaobject/1"
        assert captured["meta"]["fields"][0] == {"key": "q", "value": "Updated"}
        assert "handle" not in captured["meta"]  # nothing else changed

    # ── Get ──────────────────────────────────────────────

    def test_get_metaobject_by_id(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"metaobject": {
                "id": v["id"], "handle": "h", "type": "faq", "fields": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_GET_METAOBJECT, {
                "id": "gid://shopify/Metaobject/1",
            })
        assert result.ok
        assert result.data["found"] is True
        assert captured["id"] == "gid://shopify/Metaobject/1"

    def test_get_metaobject_by_handle(self):
        """Engines that only know the human handle ('today-bundle')
        can still fetch without round-tripping through list."""
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"metaobjectByHandle": {
                "id": "gid://shopify/Metaobject/1",
                "handle": v["handle"]["handle"],
                "type": v["handle"]["type"],
                "fields": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_GET_METAOBJECT, {
                "type": "faq",
                "handle": "shipping-faq",
            })
        assert result.ok
        assert captured["handle"] == {"handle": "shipping-faq", "type": "faq"}
        assert result.data["metaobject"]["handle"] == "shipping-faq"

    def test_get_metaobject_not_found_returns_found_false(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"metaobject": None}):
            result = a.execute(Capability.SHOPIFY_GET_METAOBJECT, {
                "id": "gid://shopify/Metaobject/missing",
            })
        assert result.ok
        assert result.data["found"] is False

    def test_get_metaobject_needs_id_or_handle_pair(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_GET_METAOBJECT, {
                "handle": "shipping-faq",  # type missing
            })
        assert not result.ok

    # ── List ─────────────────────────────────────────────

    def test_list_metaobjects_requires_type(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_LIST_METAOBJECTS, {})
        assert not result.ok

    def test_list_metaobjects_happy_path(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "metaobjects": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Metaobject/1",
                        "handle": "shipping-faq",
                        "type": "faq",
                        "displayName": "Shipping",
                        "fields": [{"key": "q", "value": "When?", "type": "text"}],
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_METAOBJECTS, {
                "type": "faq",
            })
        assert result.ok
        assert result.data["count"] == 1
        m = result.data["metaobjects"][0]
        assert m["handle"] == "shipping-faq"
        assert m["fields"]["q"] == "When?"

    def test_list_metaobjects_clamps_limit(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"metaobjects": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_METAOBJECTS, {
                "type": "faq", "limit": 9999,
            })
        assert captured["first"] == 250

    def test_list_metaobjects_passes_cursor(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        a = ShopifyMetaobjectsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["after"] = v["after"]
            return {"metaobjects": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_METAOBJECTS, {
                "type": "faq", "cursor": "cur123",
            })
        assert captured["after"] == "cur123"

    # ── _normalise_metaobject ────────────────────────────

    def test_normalise_handles_non_dict(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        assert ShopifyMetaobjectsAdapter._normalise_metaobject(None) == {}  # type: ignore[arg-type]
        assert ShopifyMetaobjectsAdapter._normalise_metaobject("foo") == {}  # type: ignore[arg-type]

    def test_normalise_skips_non_dict_field_entries(self):
        from core.adapters.shopify.metaobjects import ShopifyMetaobjectsAdapter
        out = ShopifyMetaobjectsAdapter._normalise_metaobject({
            "id": "gid://x", "handle": "h", "type": "faq",
            "fields": [
                {"key": "ok", "value": "v"},
                "not a dict",   # tolerated
                {"value": "no key"},  # also tolerated (no key)
            ],
        })
        assert out["fields"] == {"ok": "v"}


# ── ShopifyReturnsAdapter ──────────────────────────────────


class TestShopifyReturnsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter()
        assert a.name == "shopify_returns"
        for cap in (
            Capability.SHOPIFY_LIST_RETURNS,
            Capability.SHOPIFY_GET_RETURN,
            Capability.SHOPIFY_APPROVE_RETURN,
            Capability.SHOPIFY_DECLINE_RETURN,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────────────

    def test_list_returns_happy_path_traverses_orders(self):
        """Schema has no top-level ``returns`` connection (caught live
        as 'Field returns doesn't exist on QueryRoot'). The adapter
        paginates ORDERS filtered by return status and flattens the
        per-order returns into a single list. Callers see a flat
        list, but the wire shape is orders → returns → edges → node."""
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "orders": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "returns": {"edges": [
                            {"node": {
                                "id": "gid://shopify/Return/1",
                                "name": "#R1",
                                "status": "OPEN",
                                "totalQuantity": 2,
                                "order": {"id": "gid://shopify/Order/100",
                                          "name": "#1001"},
                                "returnLineItems": {"edges": [
                                    {"node": {
                                        "id": "gid://shopify/ReturnLineItem/x",
                                        "quantity": 2,
                                        "returnReason": "DEFECTIVE",
                                        "returnReasonNote": "Stitching loose",
                                        "fulfillmentLineItem": {
                                            "lineItem": {
                                                "id": "gid://l/1",
                                                "title": "Cool Mug",
                                                "variantTitle": "Blue / 12oz",
                                                "sku": "MUG-BLU-12",
                                            },
                                        },
                                    }},
                                ]},
                            }},
                        ]},
                    }},
                ],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_RETURNS, {"limit": 10})
        assert result.ok
        assert result.data["count"] == 1
        ret = result.data["returns"][0]
        assert ret["status"] == "OPEN"
        assert ret["order_name"] == "#1001"
        assert ret["total_quantity"] == 2
        li = ret["line_items"][0]
        assert li["product_title"] == "Cool Mug"
        assert li["sku"] == "MUG-BLU-12"
        assert li["reason"] == "DEFECTIVE"

    def test_list_returns_default_query_filters_by_return_status(self):
        """Without a default order-side filter we'd page through every
        order in the shop to find the few with returns. The adapter
        inserts a sensible default unless the caller overrides."""
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = v["query"]
            return {"orders": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_RETURNS, {})
        assert "return_status" in captured["query"]

    def test_list_returns_clamps_limit(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["first"] = v["first"]
            return {"orders": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_RETURNS, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_returns_caller_query_overrides_default(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["query"] = v["query"]
            return {"orders": {"pageInfo": {}, "edges": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_RETURNS, {
                "query": "name:#1234",
            })
        assert captured["query"] == "name:#1234"

    def test_list_returns_handles_empty_page(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "orders": {"pageInfo": {"hasNextPage": False,
                                    "endCursor": None}, "edges": []},
        }):
            result = a.execute(Capability.SHOPIFY_LIST_RETURNS, {})
        assert result.ok
        assert result.data["count"] == 0

    # ── Get ─────────────────────────────────────────────

    def test_get_return_requires_id(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_GET_RETURN, {})
        assert not result.ok

    def test_get_return_happy_path(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "return": {
                "id": "gid://shopify/Return/9",
                "name": "#R9",
                "status": "OPEN",
                "totalQuantity": 1,
                "order": {"id": "gid://shopify/Order/100", "name": "#1001"},
                "returnLineItems": {"edges": []},
            },
        }):
            result = a.execute(Capability.SHOPIFY_GET_RETURN, {
                "id": "gid://shopify/Return/9",
            })
        assert result.ok
        assert result.data["found"] is True
        assert result.data["return"]["id"].endswith("/9")

    def test_get_return_not_found_yields_found_false(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"return": None}):
            result = a.execute(Capability.SHOPIFY_GET_RETURN, {
                "id": "gid://shopify/Return/missing",
            })
        assert result.ok
        assert result.data["found"] is False
        assert result.data["return"] is None

    # ── Approve ─────────────────────────────────────────

    def test_approve_return_happy_path(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["input"] = v["input"]
            return {"returnApproveRequest": {
                "return": {"id": v["input"]["id"], "status": "OPEN"},
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_APPROVE_RETURN, {
                "id": "gid://shopify/Return/1",
            })
        assert result.ok
        assert result.data["status"] == "OPEN"
        # notifyCustomer defaults to True (the friendly default —
        # auto-approval should email the customer their return is in
        # progress).
        assert captured["input"]["notifyCustomer"] is True

    def test_approve_return_notify_can_be_silenced(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["input"] = v["input"]
            return {"returnApproveRequest": {
                "return": {"id": v["input"]["id"]}, "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_APPROVE_RETURN, {
                "id": "gid://shopify/Return/1",
                "notify_customer": False,
            })
        assert captured["input"]["notifyCustomer"] is False

    def test_approve_return_requires_id(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_APPROVE_RETURN, {})
        assert not result.ok

    def test_approve_return_user_errors_propagate(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "returnApproveRequest": {
                "return": None,
                "userErrors": [{
                    "field": ["input", "id"],
                    "message": "Return cannot be approved in current state",
                }],
            },
        }):
            result = a.execute(Capability.SHOPIFY_APPROVE_RETURN, {
                "id": "gid://shopify/Return/closed",
            })
        assert not result.ok

    # ── Decline ─────────────────────────────────────────

    def test_decline_return_happy_path(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["input"] = v["input"]
            return {"returnDeclineRequest": {
                "return": {
                    "id": v["input"]["id"],
                    "status": "DECLINED",
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_DECLINE_RETURN, {
                "id": "gid://shopify/Return/1",
                "decline_reason": "final_sale",
            })
        assert result.ok
        assert result.data["status"] == "DECLINED"
        # The schema doesn't surface declineReason on the return
        # object, but the adapter echoes the canonical value the
        # caller's mutation actually sent so callers don't have to
        # re-derive it.
        assert result.data["decline_reason"] == "FINAL_SALE"
        assert captured["input"]["declineReason"] == "FINAL_SALE"

    def test_decline_return_aliases_resolve(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["reason"] = v["input"]["declineReason"]
            return {"returnDeclineRequest": {
                "return": {"id": v["input"]["id"]}, "userErrors": [],
            }}

        for friendly, expected in (
            ("expired", "RETURN_PERIOD_ENDED"),
            ("return_period_ended", "RETURN_PERIOD_ENDED"),
            ("FINAL_SALE", "FINAL_SALE"),
            ("other", "OTHER"),
        ):
            captured.clear()
            with patch.object(a, "_gql", side_effect=fake_gql):
                a.execute(Capability.SHOPIFY_DECLINE_RETURN, {
                    "id": "gid://shopify/Return/1",
                    "decline_reason": friendly,
                })
            assert captured["reason"] == expected, friendly

    def test_decline_return_unknown_reason_rejected(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_DECLINE_RETURN, {
                "id": "gid://shopify/Return/1",
                "decline_reason": "vibes",
            })
        assert not result.ok

    def test_decline_return_defaults_to_other(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        a = ShopifyReturnsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured["reason"] = v["input"]["declineReason"]
            return {"returnDeclineRequest": {
                "return": {"id": v["input"]["id"]}, "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_DECLINE_RETURN, {
                "id": "gid://shopify/Return/1",
            })
        assert captured["reason"] == "OTHER"

    # ── _normalise_return ───────────────────────────────

    def test_normalise_handles_missing_fulfillment_line_item(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        out = ShopifyReturnsAdapter._normalise_return({
            "id": "gid://shopify/Return/1",
            "returnLineItems": {"edges": [
                {"node": {
                    "id": "gid://x", "quantity": 1,
                    "returnReason": "WRONG_ITEM",
                    # No fulfillmentLineItem at all — the schema
                    # allows this when the line was removed.
                }},
            ]},
        })
        assert out["line_items"][0]["product_title"] == ""
        assert out["line_items"][0]["sku"] == ""
        assert out["line_items"][0]["reason"] == "WRONG_ITEM"

    def test_normalise_handles_non_dict(self):
        from core.adapters.shopify.returns import ShopifyReturnsAdapter
        assert ShopifyReturnsAdapter._normalise_return(None) == {}  # type: ignore[arg-type]
        assert ShopifyReturnsAdapter._normalise_return("foo") == {}  # type: ignore[arg-type]


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


# ── ShopifyProductsAdapter ────────────────────────────────


class TestShopifyProductsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter()
        assert a.name == "shopify_products"
        for cap in (
            Capability.SHOPIFY_LIST_PRODUCTS,
            Capability.SHOPIFY_GET_PRODUCT,
            Capability.SHOPIFY_CREATE_PRODUCT,
            Capability.SHOPIFY_UPDATE_PRODUCT,
            Capability.SHOPIFY_DELETE_PRODUCT,
            Capability.SHOPIFY_UPDATE_VARIANTS,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── _build_product_input ─────────────────────

    def test_create_requires_title(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_product_input({}, for_update=False)

    def test_update_requires_id(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_product_input({"title": "x"}, for_update=True)

    def test_create_input_status_validated(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_product_input(
                {"title": "x", "status": "INVALID"}, for_update=False,
            )

    def test_create_input_status_normalised_uppercase(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        out = a._build_product_input(
            {"title": "x", "status": "active"}, for_update=False,
        )
        assert out["status"] == "ACTIVE"

    def test_create_input_tags_string_split(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        out = a._build_product_input(
            {"title": "x", "tags": "a, b ,c"}, for_update=False,
        )
        assert out["tags"] == ["a", "b", "c"]

    def test_create_input_tags_list_pass_through(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        out = a._build_product_input(
            {"title": "x", "tags": ["a", "b"]}, for_update=False,
        )
        assert out["tags"] == ["a", "b"]

    def test_create_input_description_maps_to_html(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        out = a._build_product_input(
            {"title": "x", "description": "<p>hi</p>"},
            for_update=False,
        )
        assert out["descriptionHtml"] == "<p>hi</p>"

    def test_create_input_product_type_camelcased(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        out = a._build_product_input(
            {"title": "x", "product_type": "Lighting"}, for_update=False,
        )
        assert out["productType"] == "Lighting"

    # ── _build_variant_input ─────────────────────

    def test_variant_requires_id(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_variant_input({"price": "9.99"}, 0)

    def test_variant_price_coerced_to_string(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        out = a._build_variant_input(
            {"id": "gid://shopify/ProductVariant/1", "price": 19.99}, 0,
        )
        assert out["price"] == "19.99"

    def test_variant_compare_at_price_camelcased(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        out = a._build_variant_input(
            {"id": "gid://shopify/ProductVariant/1",
             "compare_at_price": "29.99"}, 0,
        )
        assert out["compareAtPrice"] == "29.99"

    def test_variant_price_non_numeric_string_rejected(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_variant_input(
                {"id": "gid://shopify/ProductVariant/1",
                 "price": "expensive"}, 0,
            )

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "products": {
                "pageInfo": {"hasNextPage": True, "endCursor": "abc"},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Product/1",
                        "title": "Lantern",
                        "handle": "lantern",
                        "status": "ACTIVE",
                        "vendor": "ShopAI",
                        "productType": "Lighting",
                        "tags": ["camping"],
                        "totalInventory": 42,
                        "priceRangeV2": {
                            "minVariantPrice": {
                                "amount": "9.99", "currencyCode": "USD",
                            },
                            "maxVariantPrice": {
                                "amount": "19.99", "currencyCode": "USD",
                            },
                        },
                    }}
                ],
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_PRODUCTS, {})
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["has_next_page"] is True
        assert result.data["end_cursor"] == "abc"
        p = result.data["products"][0]
        assert p["title"] == "Lantern"
        assert p["price_min"] == "9.99"
        assert p["currency_code"] == "USD"

    def test_list_clamps_limit_to_max(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"products": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_PRODUCTS, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_invalid_sort_key_rejected(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_PRODUCTS, {"sort_key": "BAD"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_list_passes_query_filter(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"products": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_PRODUCTS, {
                "query": "tag:camping", "sort_key": "TITLE", "reverse": True,
            })
        assert captured["query"] == "tag:camping"
        assert captured["sortKey"] == "TITLE"
        assert captured["reverse"] is True

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_PRODUCT, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_get_happy_path_with_variants_and_images(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "product": {
                "id": "gid://shopify/Product/1",
                "title": "Lantern",
                "handle": "lantern",
                "status": "ACTIVE",
                "tags": [],
                "totalInventory": 5,
                "priceRangeV2": {
                    "minVariantPrice": {"amount": "9.99", "currencyCode": "USD"},
                    "maxVariantPrice": {"amount": "9.99", "currencyCode": "USD"},
                },
                "variants": {
                    "edges": [{"node": {
                        "id": "gid://shopify/ProductVariant/v1",
                        "title": "Default",
                        "sku": "LANT-1",
                        "price": "9.99",
                        "compareAtPrice": "14.99",
                        "inventoryQuantity": 5,
                        "inventoryPolicy": "DENY",
                    }}],
                },
                "images": {
                    "edges": [{"node": {
                        "id": "gid://shopify/MediaImage/i1",
                        "url": "https://cdn.shopify.com/lantern.jpg",
                        "altText": "Lantern photo",
                    }}],
                },
            }
        }):
            result = a.execute(Capability.SHOPIFY_GET_PRODUCT, {
                "id": "gid://shopify/Product/1",
            })
        assert result.ok
        assert result.data["found"] is True
        p = result.data["product"]
        assert len(p["variants"]) == 1
        assert p["variants"][0]["sku"] == "LANT-1"
        assert len(p["images"]) == 1
        assert p["images"][0]["alt_text"] == "Lantern photo"

    def test_get_missing_product_returns_empty(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"product": None}):
            result = a.execute(Capability.SHOPIFY_GET_PRODUCT, {
                "id": "gid://shopify/Product/999",
            })
        assert result.ok
        assert result.data["found"] is False
        assert result.data["product"] == {}

    # ── Create ───────────────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"productCreate": {
                "product": {
                    "id": "gid://shopify/Product/new",
                    "title": v["input"]["title"],
                    "handle": "new",
                    "status": v["input"].get("status", "ACTIVE"),
                    "tags": v["input"].get("tags", []),
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_PRODUCT, {
                "title": "Lantern",
                "status": "draft",
                "tags": ["camping"],
            })
        assert result.ok
        assert result.data["product"]["id"] == "gid://shopify/Product/new"
        assert captured["input"]["status"] == "DRAFT"

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"productCreate": {
            "product": None,
            "userErrors": [
                {"field": ["title"], "message": "is taken", "code": "TAKEN"},
            ],
        }}):
            result = a.execute(Capability.SHOPIFY_CREATE_PRODUCT, {
                "title": "Lantern",
            })
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    # ── Update ───────────────────────────────────

    def test_update_happy_path(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"productUpdate": {
                "product": {
                    "id": v["input"]["id"],
                    "title": v["input"].get("title", "old"),
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_PRODUCT, {
                "id": "gid://shopify/Product/1",
                "title": "Renamed",
            })
        assert result.ok
        assert result.data["product"]["title"] == "Renamed"
        assert captured["input"]["id"] == "gid://shopify/Product/1"

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_PRODUCT, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_delete_happy_path(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"productDelete": {
            "deletedProductId": "gid://shopify/Product/1",
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_DELETE_PRODUCT, {
                "id": "gid://shopify/Product/1",
            })
        assert result.ok
        assert result.data["deleted_id"] == "gid://shopify/Product/1"

    # ── Variants bulk update ─────────────────────

    def test_variants_update_requires_product_id(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_VARIANTS, {
            "variants": [{"id": "v1", "price": "1"}],
        })
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_variants_update_requires_non_empty_list(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_VARIANTS, {
            "product_id": "gid://shopify/Product/1",
            "variants": [],
        })
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_variants_update_happy_path(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        a = ShopifyProductsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"productVariantsBulkUpdate": {
                "productVariants": [
                    {"id": "gid://shopify/ProductVariant/v1",
                     "title": "Default",
                     "sku": "LANT-1",
                     "price": "19.99",
                     "compareAtPrice": "29.99",
                     "inventoryQuantity": 5},
                ],
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_VARIANTS, {
                "product_id": "gid://shopify/Product/1",
                "variants": [
                    {"id": "gid://shopify/ProductVariant/v1",
                     "price": 19.99,
                     "compare_at_price": "29.99"},
                ],
            })
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["variants"][0]["price"] == "19.99"
        # Pattern A — productId at field level, not inside an input dict.
        assert captured["productId"] == "gid://shopify/Product/1"
        assert captured["variants"][0]["price"] == "19.99"
        assert captured["variants"][0]["compareAtPrice"] == "29.99"

    # ── Normaliser edge cases ────────────────────

    def test_normalise_handles_empty_node(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        assert ShopifyProductsAdapter._normalise_product({}) == {}
        assert ShopifyProductsAdapter._normalise_product(None) == {}

    def test_normalise_variant_handles_non_dict(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        assert ShopifyProductsAdapter._normalise_variant(None) == {}


# ── ShopifyOrdersAdapter ──────────────────────────────────


class TestShopifyOrdersAdapter:
    def test_metadata(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter()
        assert a.name == "shopify_orders"
        for cap in (
            Capability.SHOPIFY_LIST_ORDERS,
            Capability.SHOPIFY_GET_ORDER,
            Capability.SHOPIFY_UPDATE_ORDER,
            Capability.SHOPIFY_TAG_ORDER,
            Capability.SHOPIFY_UNTAG_ORDER,
            Capability.SHOPIFY_CLOSE_ORDER,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "orders": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Order/1",
                        "name": "#1001",
                        "email": "x@y.com",
                        "tags": ["vip"],
                        "displayFinancialStatus": "PAID",
                        "displayFulfillmentStatus": "UNFULFILLED",
                        "currencyCode": "USD",
                        "totalPriceSet": {
                            "shopMoney": {"amount": "99.00", "currencyCode": "USD"},
                        },
                        "subtotalPriceSet": {
                            "shopMoney": {"amount": "90.00", "currencyCode": "USD"},
                        },
                        "customer": {
                            "id": "gid://shopify/Customer/c1",
                            "email": "x@y.com",
                            "firstName": "X",
                            "lastName": "Y",
                            "numberOfOrders": 5,
                        },
                    }}
                ],
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_ORDERS, {})
        assert result.ok
        assert result.data["count"] == 1
        o = result.data["orders"][0]
        assert o["name"] == "#1001"
        assert o["financial_status"] == "PAID"
        assert o["total_price"] == "99.00"
        assert o["customer_id"] == "gid://shopify/Customer/c1"
        assert o["customer_orders_count"] == 5

    def test_list_clamps_limit(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"orders": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_ORDERS, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_invalid_sort_key_rejected(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_ORDERS, {"sort_key": "BAD"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_list_passes_query_filter(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"orders": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_ORDERS, {
                "query": "financial_status:paid",
                "sort_key": "PROCESSED_AT",
                "reverse": True,
            })
        assert captured["query"] == "financial_status:paid"
        assert captured["sortKey"] == "PROCESSED_AT"
        assert captured["reverse"] is True

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_ORDER, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_get_happy_path_with_line_items(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "order": {
                "id": "gid://shopify/Order/1",
                "name": "#1001",
                "tags": [],
                "totalPriceSet": {
                    "shopMoney": {"amount": "10.00", "currencyCode": "USD"},
                },
                "lineItems": {
                    "edges": [{"node": {
                        "id": "gid://shopify/LineItem/li1",
                        "title": "Lantern",
                        "quantity": 2,
                        "sku": "LANT-1",
                        "variant": {"id": "gid://shopify/ProductVariant/v1",
                                    "title": "Default"},
                        "product": {"id": "gid://shopify/Product/p1",
                                    "title": "Lantern"},
                        "originalUnitPriceSet": {
                            "shopMoney": {"amount": "5.00", "currencyCode": "USD"},
                        },
                    }}],
                },
                "shippingAddress": {
                    "address1": "1 Main",
                    "city": "MN",
                    "country": "US",
                    "zip": "12345",
                    "name": "Test",
                },
            }
        }):
            result = a.execute(Capability.SHOPIFY_GET_ORDER, {
                "id": "gid://shopify/Order/1",
            })
        assert result.ok
        assert result.data["found"] is True
        o = result.data["order"]
        assert len(o["line_items"]) == 1
        assert o["line_items"][0]["sku"] == "LANT-1"
        assert o["line_items"][0]["quantity"] == 2
        assert o["shipping_address"]["city"] == "MN"

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"order": None}):
            result = a.execute(Capability.SHOPIFY_GET_ORDER, {
                "id": "gid://shopify/Order/999",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Update ───────────────────────────────────

    def test_update_requires_id(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_ORDER, {"note": "x"})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_update_no_fields_rejected(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_ORDER, {
            "id": "gid://shopify/Order/1",
        })
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_update_happy_path(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"orderUpdate": {
                "order": {"id": v["input"]["id"], "note": v["input"].get("note")},
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_ORDER, {
                "id": "gid://shopify/Order/1",
                "note": "AI: high-fraud-risk",
                "tags": "fraud, review",
                "custom_attributes": [{"key": "ai_score", "value": 0.9}],
            })
        assert result.ok
        inp = captured["input"]
        assert inp["id"] == "gid://shopify/Order/1"
        assert inp["note"] == "AI: high-fraud-risk"
        assert inp["tags"] == ["fraud", "review"]
        assert inp["customAttributes"] == [{"key": "ai_score", "value": "0.9"}]

    # ── Tag / Untag ──────────────────────────────

    def test_tag_requires_tags(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_TAG_ORDER, {
            "id": "gid://shopify/Order/1",
        })
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_tag_happy_path(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"tagsAdd": {
                "node": {"id": v["id"], "tags": v["tags"]},
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_TAG_ORDER, {
                "id": "gid://shopify/Order/1",
                "tags": ["vip", "ai-flagged"],
            })
        assert result.ok
        assert captured["tags"] == ["vip", "ai-flagged"]
        assert result.data["tags"] == ["vip", "ai-flagged"]

    def test_untag_happy_path(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"tagsRemove": {
            "node": {"id": "gid://shopify/Order/1", "tags": []},
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_UNTAG_ORDER, {
                "id": "gid://shopify/Order/1",
                "tags": "vip,ai-flagged",
            })
        assert result.ok
        assert result.data["tags"] == []

    # ── Close ────────────────────────────────────

    def test_close_requires_id(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_CLOSE_ORDER, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_close_happy_path(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        a = ShopifyOrdersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"orderClose": {
            "order": {
                "id": "gid://shopify/Order/1",
                "closed": True,
                "closedAt": "2026-04-25T10:00:00Z",
            },
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_CLOSE_ORDER, {
                "id": "gid://shopify/Order/1",
            })
        assert result.ok
        assert result.data["closed"] is True
        assert result.data["closed_at"] == "2026-04-25T10:00:00Z"

    # ── Normaliser ───────────────────────────────

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        assert ShopifyOrdersAdapter._normalise_order({}) == {}
        assert ShopifyOrdersAdapter._normalise_line_item(None) == {}


# ── ShopifyCustomersAdapter ───────────────────────────────


class TestShopifyCustomersAdapter:
    def test_metadata(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter()
        assert a.name == "shopify_customers"
        for cap in (
            Capability.SHOPIFY_FETCH_CUSTOMERS,
            Capability.SHOPIFY_GET_CUSTOMER,
            Capability.SHOPIFY_CREATE_CUSTOMER,
            Capability.SHOPIFY_UPDATE_CUSTOMER,
            Capability.SHOPIFY_TAG_CUSTOMER,
            Capability.SHOPIFY_UNTAG_CUSTOMER,
            Capability.SHOPIFY_DELETE_CUSTOMER,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_create_requires_email_or_phone(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_customer_input({"first_name": "X"}, for_update=False)

    def test_create_with_email_ok(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        out = a._build_customer_input(
            {"email": "x@y.com", "first_name": "X"}, for_update=False,
        )
        assert out["email"] == "x@y.com"
        assert out["firstName"] == "X"

    def test_create_with_phone_only_ok(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        out = a._build_customer_input(
            {"phone": "+15551234567"}, for_update=False,
        )
        assert out["phone"] == "+15551234567"

    def test_update_requires_id(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_customer_input({"email": "x@y.com"}, for_update=True)

    def test_input_tags_string_split(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        out = a._build_customer_input(
            {"email": "x@y.com", "tags": "vip, ai-flagged ,review"},
            for_update=False,
        )
        assert out["tags"] == ["vip", "ai-flagged", "review"]

    def test_input_marketing_consent_subscribed(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        out = a._build_customer_input(
            {"email": "x@y.com", "accepts_email_marketing": True},
            for_update=False,
        )
        assert out["emailMarketingConsent"]["marketingState"] == "SUBSCRIBED"

    def test_input_marketing_consent_unsubscribed(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        out = a._build_customer_input(
            {"email": "x@y.com", "accepts_email_marketing": False},
            for_update=False,
        )
        assert out["emailMarketingConsent"]["marketingState"] == "UNSUBSCRIBED"

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "customers": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Customer/c1",
                        "firstName": "X",
                        "lastName": "Y",
                        "email": "x@y.com",
                        "tags": ["vip"],
                        "numberOfOrders": 3,
                        "amountSpent": {"amount": "150.00", "currencyCode": "USD"},
                        "verifiedEmail": True,
                    }}
                ],
            }
        }):
            result = a.execute(Capability.SHOPIFY_FETCH_CUSTOMERS, {})
        assert result.ok
        c = result.data["customers"][0]
        assert c["email"] == "x@y.com"
        assert c["orders_count"] == 3
        assert c["total_spent"] == "150.00"
        assert c["currency_code"] == "USD"
        assert c["verified_email"] is True

    def test_list_invalid_sort_key_rejected(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_FETCH_CUSTOMERS, {"sort_key": "BAD"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_list_passes_query_filter(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"customers": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_FETCH_CUSTOMERS, {
                "query": "tag:vip",
                "sort_key": "TOTAL_SPENT",
                "reverse": True,
            })
        assert captured["query"] == "tag:vip"
        assert captured["sortKey"] == "TOTAL_SPENT"

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_CUSTOMER, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_get_happy_path_with_addresses(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "customer": {
                "id": "gid://shopify/Customer/c1",
                "email": "x@y.com",
                "tags": [],
                "addresses": [
                    {"id": "gid://shopify/MailingAddress/a1",
                     "address1": "1 Main", "city": "MN",
                     "country": "US", "zip": "12345"},
                    {"id": "gid://shopify/MailingAddress/a2",
                     "address1": "2 Side", "city": "MN",
                     "country": "US", "zip": "12345"},
                ],
            }
        }):
            result = a.execute(Capability.SHOPIFY_GET_CUSTOMER, {
                "id": "gid://shopify/Customer/c1",
            })
        assert result.ok
        assert result.data["found"] is True
        assert len(result.data["customer"]["addresses"]) == 2

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"customer": None}):
            result = a.execute(Capability.SHOPIFY_GET_CUSTOMER, {
                "id": "gid://shopify/Customer/999",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Create / Update ──────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"customerCreate": {
                "customer": {
                    "id": "gid://shopify/Customer/new",
                    "email": v["input"]["email"],
                    "tags": [],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_CUSTOMER, {
                "email": "new@example.com",
                "first_name": "New",
                "tags": ["welcome"],
            })
        assert result.ok
        assert captured["input"]["email"] == "new@example.com"

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"customerCreate": {
            "customer": None,
            "userErrors": [
                {"field": ["email"], "message": "is taken", "code": "TAKEN"},
            ],
        }}):
            result = a.execute(Capability.SHOPIFY_CREATE_CUSTOMER, {
                "email": "x@y.com",
            })
        assert not result.ok

    def test_update_happy_path(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"customerUpdate": {
                "customer": {"id": v["input"]["id"], "tags": v["input"].get("tags", [])},
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_CUSTOMER, {
                "id": "gid://shopify/Customer/c1",
                "tags": "vip,ai-flagged",
            })
        assert result.ok
        assert captured["input"]["tags"] == ["vip", "ai-flagged"]

    # ── Tag / Untag ──────────────────────────────

    def test_tag_requires_tags(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_TAG_CUSTOMER, {
            "id": "gid://shopify/Customer/c1",
        })
        assert not result.ok

    def test_tag_happy_path(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"tagsAdd": {
            "node": {"id": "gid://shopify/Customer/c1",
                     "tags": ["vip"]},
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_TAG_CUSTOMER, {
                "id": "gid://shopify/Customer/c1",
                "tags": ["vip"],
            })
        assert result.ok
        assert result.data["tags"] == ["vip"]

    def test_untag_happy_path(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"tagsRemove": {
            "node": {"id": "gid://shopify/Customer/c1", "tags": []},
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_UNTAG_CUSTOMER, {
                "id": "gid://shopify/Customer/c1",
                "tags": "vip",
            })
        assert result.ok

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_CUSTOMER, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        a = ShopifyCustomersAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"customerDelete": {
            "deletedCustomerId": "gid://shopify/Customer/c1",
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_DELETE_CUSTOMER, {
                "id": "gid://shopify/Customer/c1",
            })
        assert result.ok
        assert result.data["deleted_id"] == "gid://shopify/Customer/c1"

    # ── Normaliser ───────────────────────────────

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.customers import ShopifyCustomersAdapter
        assert ShopifyCustomersAdapter._normalise_customer({}) == {}


# ── ShopifyWebhooksAdapter ────────────────────────────────


class TestShopifyWebhooksAdapter:
    def test_metadata(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter()
        assert a.name == "shopify_webhooks"
        for cap in (
            Capability.SHOPIFY_LIST_WEBHOOKS,
            Capability.SHOPIFY_CREATE_WEBHOOK,
            Capability.SHOPIFY_UPDATE_WEBHOOK,
            Capability.SHOPIFY_DELETE_WEBHOOK,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Topic normalisation ──────────────────────

    def test_topic_slash_form_normalised(self):
        from core.adapters.shopify.webhooks import _normalise_topic
        assert _normalise_topic("orders/paid") == "ORDERS_PAID"

    def test_topic_underscore_form_pass_through(self):
        from core.adapters.shopify.webhooks import _normalise_topic
        assert _normalise_topic("ORDERS_PAID") == "ORDERS_PAID"

    def test_topic_required(self):
        from core.adapters.shopify.webhooks import _normalise_topic
        with pytest.raises(AdapterValidationError):
            _normalise_topic("")
        with pytest.raises(AdapterValidationError):
            _normalise_topic(None)

    # ── Input builder ────────────────────────────

    def test_create_requires_callback_url(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_subscription_input({}, callback_required=True)

    def test_callback_url_must_be_http(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_subscription_input({
                "callback_url": "ftp://example.com/hook",
            })

    def test_format_validated(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_subscription_input({
                "callback_url": "https://x.com",
                "format": "yaml",
            })

    def test_input_normalises_format_to_uppercase(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        out = a._build_subscription_input({
            "callback_url": "https://x.com/hook",
            "format": "json",
            "include_fields": ["id", "tags"],
        })
        assert out["callbackUrl"] == "https://x.com/hook"
        assert out["format"] == "JSON"
        assert out["includeFields"] == ["id", "tags"]

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "webhookSubscriptions": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/WebhookSubscription/w1",
                    "topic": "ORDERS_PAID",
                    "format": "JSON",
                    "endpoint": {
                        "__typename": "WebhookHttpEndpoint",
                        "callbackUrl": "https://ingest.shopai.dev/orders",
                    },
                    "includeFields": ["id", "name"],
                }}],
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_WEBHOOKS, {})
        assert result.ok
        w = result.data["webhooks"][0]
        assert w["topic"] == "ORDERS_PAID"
        assert w["callback_url"] == "https://ingest.shopai.dev/orders"
        assert w["endpoint_kind"] == "WebhookHttpEndpoint"

    # ── Create ───────────────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"webhookSubscriptionCreate": {
                "webhookSubscription": {
                    "id": "gid://shopify/WebhookSubscription/new",
                    "topic": v["topic"],
                    "format": v["webhookSubscription"].get("format", "JSON"),
                    "endpoint": {
                        "__typename": "WebhookHttpEndpoint",
                        "callbackUrl": v["webhookSubscription"]["callbackUrl"],
                    },
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_WEBHOOK, {
                "topic": "orders/paid",
                "callback_url": "https://ingest.shopai.dev/hook",
                "format": "JSON",
            })
        assert result.ok
        # Pattern A — topic at top-level field, not inside the input.
        assert captured["topic"] == "ORDERS_PAID"
        assert captured["webhookSubscription"]["callbackUrl"] == "https://ingest.shopai.dev/hook"
        assert result.data["webhook"]["topic"] == "ORDERS_PAID"

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"webhookSubscriptionCreate": {
            "webhookSubscription": None,
            "userErrors": [{"field": ["address"], "message": "duplicate"}],
        }}):
            result = a.execute(Capability.SHOPIFY_CREATE_WEBHOOK, {
                "topic": "ORDERS_PAID",
                "callback_url": "https://x.com",
            })
        assert not result.ok

    # ── Update ───────────────────────────────────

    def test_update_requires_id(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_WEBHOOK, {
            "callback_url": "https://x.com",
        })
        assert not result.ok

    def test_update_no_fields_rejected(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_WEBHOOK, {
            "id": "gid://shopify/WebhookSubscription/w1",
        })
        assert not result.ok

    def test_update_happy_path(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"webhookSubscriptionUpdate": {
                "webhookSubscription": {
                    "id": v["id"],
                    "topic": "ORDERS_PAID",
                    "format": "JSON",
                    "endpoint": {
                        "__typename": "WebhookHttpEndpoint",
                        "callbackUrl": v["webhookSubscription"]["callbackUrl"],
                    },
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_WEBHOOK, {
                "id": "gid://shopify/WebhookSubscription/w1",
                "callback_url": "https://x.com/v2",
            })
        assert result.ok
        assert captured["id"] == "gid://shopify/WebhookSubscription/w1"
        assert captured["webhookSubscription"]["callbackUrl"] == "https://x.com/v2"

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_WEBHOOK, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        a = ShopifyWebhooksAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"webhookSubscriptionDelete": {
            "deletedWebhookSubscriptionId": "gid://shopify/WebhookSubscription/w1",
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_DELETE_WEBHOOK, {
                "id": "gid://shopify/WebhookSubscription/w1",
            })
        assert result.ok
        assert result.data["deleted_id"] == "gid://shopify/WebhookSubscription/w1"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.webhooks import ShopifyWebhooksAdapter
        assert ShopifyWebhooksAdapter._normalise_webhook({}) == {}


# ── ShopifyBulkOperationsAdapter ──────────────────────────


class TestShopifyBulkOperationsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.bulk import ShopifyBulkOperationsAdapter
        a = ShopifyBulkOperationsAdapter()
        assert a.name == "shopify_bulk"
        for cap in (
            Capability.SHOPIFY_RUN_BULK_QUERY,
            Capability.SHOPIFY_GET_BULK_OPERATION,
            Capability.SHOPIFY_CANCEL_BULK_OPERATION,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.bulk import ShopifyBulkOperationsAdapter
        a = ShopifyBulkOperationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Run query ────────────────────────────────

    def test_run_query_requires_query(self):
        from core.adapters.shopify.bulk import ShopifyBulkOperationsAdapter
        a = ShopifyBulkOperationsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_RUN_BULK_QUERY, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_run_query_happy_path(self):
        from core.adapters.shopify.bulk import ShopifyBulkOperationsAdapter
        a = ShopifyBulkOperationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"bulkOperationRunQuery": {
                "bulkOperation": {
                    "id": "gid://shopify/BulkOperation/b1",
                    "status": "CREATED",
                    "type": "QUERY",
                    "query": v["query"],
                    "objectCount": "0",
                    "fileSize": "0",
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_RUN_BULK_QUERY, {
                "query": "{ products { edges { node { id } } } }",
            })
        assert result.ok
        op = result.data["bulk_operation"]
        assert op["id"] == "gid://shopify/BulkOperation/b1"
        assert op["status"] == "CREATED"
        assert op["object_count"] == 0
        assert captured["query"].startswith("{ products")

    def test_run_query_user_errors_fail_fast(self):
        from core.adapters.shopify.bulk import ShopifyBulkOperationsAdapter
        a = ShopifyBulkOperationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"bulkOperationRunQuery": {
            "bulkOperation": None,
            "userErrors": [
                {"field": ["query"],
                 "message": "A bulk query operation for this app and "
                            "shop is already in progress."},
            ],
        }}):
            result = a.execute(Capability.SHOPIFY_RUN_BULK_QUERY, {
                "query": "{ products { edges { node { id } } } }",
            })
        assert not result.ok

    # ── Get current ──────────────────────────────

    def test_get_current_when_none_exists(self):
        from core.adapters.shopify.bulk import ShopifyBulkOperationsAdapter
        a = ShopifyBulkOperationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"currentBulkOperation": None}):
            result = a.execute(Capability.SHOPIFY_GET_BULK_OPERATION, {})
        assert result.ok
        assert result.data["found"] is False
        assert result.data["bulk_operation"] == {}
        assert result.data["is_terminal"] is False

    def test_get_current_completed_is_terminal(self):
        from core.adapters.shopify.bulk import ShopifyBulkOperationsAdapter
        a = ShopifyBulkOperationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"currentBulkOperation": {
            "id": "gid://shopify/BulkOperation/b1",
            "status": "COMPLETED",
            "type": "QUERY",
            "objectCount": "100",
            "fileSize": "5000",
            "url": "https://storage.googleapis.com/shopify-tiers/.../out.jsonl",
        }}):
            result = a.execute(Capability.SHOPIFY_GET_BULK_OPERATION, {})
        assert result.ok
        assert result.data["found"] is True
        assert result.data["is_terminal"] is True
        op = result.data["bulk_operation"]
        assert op["status"] == "COMPLETED"
        assert op["object_count"] == 100
        assert op["file_size"] == 5000
        assert op["url"].endswith(".jsonl")

    def test_get_current_running_is_not_terminal(self):
        from core.adapters.shopify.bulk import ShopifyBulkOperationsAdapter
        a = ShopifyBulkOperationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"currentBulkOperation": {
            "id": "gid://shopify/BulkOperation/b1",
            "status": "RUNNING",
            "type": "QUERY",
        }}):
            result = a.execute(Capability.SHOPIFY_GET_BULK_OPERATION, {})
        assert result.ok
        assert result.data["is_terminal"] is False

    # ── Cancel ───────────────────────────────────

    def test_cancel_requires_id(self):
        from core.adapters.shopify.bulk import ShopifyBulkOperationsAdapter
        a = ShopifyBulkOperationsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_CANCEL_BULK_OPERATION, {})
        assert not result.ok

    def test_cancel_happy_path(self):
        from core.adapters.shopify.bulk import ShopifyBulkOperationsAdapter
        a = ShopifyBulkOperationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"bulkOperationCancel": {
            "bulkOperation": {
                "id": "gid://shopify/BulkOperation/b1",
                "status": "CANCELING",
                "type": "QUERY",
            },
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_CANCEL_BULK_OPERATION, {
                "id": "gid://shopify/BulkOperation/b1",
            })
        assert result.ok
        assert result.data["bulk_operation"]["status"] == "CANCELING"

    # ── Normaliser ───────────────────────────────

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.bulk import ShopifyBulkOperationsAdapter
        assert ShopifyBulkOperationsAdapter._normalise_op({}) == {}
        assert ShopifyBulkOperationsAdapter._normalise_op(None) == {}


# ── ShopifyShopAdapter ────────────────────────────────────


class TestShopifyShopAdapter:
    def test_metadata(self):
        from core.adapters.shopify.shop import ShopifyShopAdapter
        a = ShopifyShopAdapter()
        assert a.name == "shopify_shop"
        for cap in (
            Capability.SHOPIFY_GET_SHOP,
            Capability.SHOPIFY_GET_SHOP_POLICIES,
            Capability.SHOPIFY_LIST_CURRENCIES,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.shop import ShopifyShopAdapter
        a = ShopifyShopAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Get shop ─────────────────────────────────

    def test_get_shop_happy_path(self):
        from core.adapters.shopify.shop import ShopifyShopAdapter
        a = ShopifyShopAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"shop": {
            "id": "gid://shopify/Shop/1",
            "name": "ShopAI Test",
            "email": "owner@shopai.dev",
            "myshopifyDomain": "ts0efe-ih.myshopify.com",
            "primaryDomain": {
                "url": "https://ts0efe-ih.myshopify.com",
                "host": "ts0efe-ih.myshopify.com",
                "sslEnabled": True,
            },
            "ianaTimezone": "America/Chicago",
            "currencyCode": "USD",
            "enabledPresentmentCurrencies": ["USD", "EUR"],
            "plan": {
                "displayName": "Developer Preview",
                "partnerDevelopment": True,
                "shopifyPlus": False,
            },
            "billingAddress": {
                "city": "Minneapolis", "countryCodeV2": "US",
            },
            "features": {
                "giftCards": True, "reports": True,
            },
        }}):
            result = a.execute(Capability.SHOPIFY_GET_SHOP, {})
        assert result.ok
        s = result.data["shop"]
        assert s["myshopify_domain"] == "ts0efe-ih.myshopify.com"
        assert s["currency_code"] == "USD"
        assert s["presentment_currencies"] == ["USD", "EUR"]
        assert s["plan_is_partner_dev"] is True
        assert s["plan_is_shopify_plus"] is False
        assert s["features"]["giftCards"] is True
        assert s["billing_country"] == "US"
        assert s["ssl_enabled"] is True

    def test_get_shop_missing_returns_empty(self):
        from core.adapters.shopify.shop import ShopifyShopAdapter
        a = ShopifyShopAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"shop": None}):
            result = a.execute(Capability.SHOPIFY_GET_SHOP, {})
        assert result.ok
        assert result.data["found"] is False
        assert result.data["shop"] == {}

    # ── Policies ─────────────────────────────────

    def test_get_policies_happy_path(self):
        from core.adapters.shopify.shop import ShopifyShopAdapter
        a = ShopifyShopAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"shop": {
            "shopPolicies": [
                {"id": "gid://shopify/ShopPolicy/1",
                 "type": "REFUND_POLICY",
                 "title": "Refund policy",
                 "url": "https://store/policies/refund",
                 "body": "All sales final."},
                {"id": "gid://shopify/ShopPolicy/2",
                 "type": "PRIVACY_POLICY",
                 "title": "Privacy policy",
                 "url": "https://store/policies/privacy",
                 "body": "We do not sell your data."},
            ],
        }}):
            result = a.execute(Capability.SHOPIFY_GET_SHOP_POLICIES, {})
        assert result.ok
        assert result.data["count"] == 2
        types = {p["type"] for p in result.data["policies"]}
        assert types == {"REFUND_POLICY", "PRIVACY_POLICY"}

    def test_get_policies_empty_when_none(self):
        from core.adapters.shopify.shop import ShopifyShopAdapter
        a = ShopifyShopAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"shop": {"shopPolicies": []}}):
            result = a.execute(Capability.SHOPIFY_GET_SHOP_POLICIES, {})
        assert result.ok
        assert result.data["count"] == 0

    # ── Currencies ───────────────────────────────

    def test_list_currencies_happy_path(self):
        from core.adapters.shopify.shop import ShopifyShopAdapter
        a = ShopifyShopAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"shop": {
            "currencyCode": "USD",
            "enabledPresentmentCurrencies": ["USD", "EUR", "GBP"],
            "currencyFormats": {
                "moneyFormat": "${{amount}}",
                "moneyInEmailsFormat": "${{amount}}",
                "moneyWithCurrencyFormat": "${{amount}} USD",
            },
        }}):
            result = a.execute(Capability.SHOPIFY_LIST_CURRENCIES, {})
        assert result.ok
        assert result.data["primary_currency"] == "USD"
        assert result.data["presentment_currencies"] == ["USD", "EUR", "GBP"]
        assert result.data["money_format"] == "${{amount}}"

    # ── Normaliser ───────────────────────────────

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.shop import ShopifyShopAdapter
        assert ShopifyShopAdapter._normalise_shop({}) == {}
        assert ShopifyShopAdapter._normalise_shop(None) == {}


# ── ShopifyPagesAdapter ───────────────────────────────────


class TestShopifyPagesAdapter:
    def test_metadata(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter()
        assert a.name == "shopify_pages"
        for cap in (
            Capability.SHOPIFY_LIST_PAGES,
            Capability.SHOPIFY_GET_PAGE,
            Capability.SHOPIFY_CREATE_PAGE,
            Capability.SHOPIFY_UPDATE_PAGE,
            Capability.SHOPIFY_DELETE_PAGE,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_create_requires_title(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_page_input({}, for_update=False)

    def test_create_input_body_html_alias(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        out = a._build_page_input(
            {"title": "x", "body_html": "<p>hi</p>"}, for_update=False,
        )
        assert out["body"] == "<p>hi</p>"

    def test_input_is_published_default_unset(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        out = a._build_page_input({"title": "x"}, for_update=False)
        assert "isPublished" not in out

    def test_input_is_published_true(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        out = a._build_page_input(
            {"title": "x", "is_published": True}, for_update=False,
        )
        assert out["isPublished"] is True

    def test_input_template_suffix_camelcased(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        out = a._build_page_input(
            {"title": "x", "template_suffix": "contact"}, for_update=False,
        )
        assert out["templateSuffix"] == "contact"

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "pages": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/Page/1",
                    "title": "About Us",
                    "handle": "about-us",
                    "body": "<p>About</p>",
                    "isPublished": True,
                }}],
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_PAGES, {})
        assert result.ok
        p = result.data["pages"][0]
        assert p["title"] == "About Us"
        assert p["handle"] == "about-us"
        assert p["body_html"] == "<p>About</p>"
        assert p["is_published"] is True

    def test_list_invalid_sort_key_rejected(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_PAGES, {"sort_key": "BAD"},
        )
        assert not result.ok

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_PAGE, {})
        assert not result.ok

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"page": None}):
            result = a.execute(Capability.SHOPIFY_GET_PAGE, {
                "id": "gid://shopify/Page/999",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Create / Update ──────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"pageCreate": {
                "page": {
                    "id": "gid://shopify/Page/new",
                    "title": v["page"]["title"],
                    "handle": v["page"].get("handle", ""),
                    "body": v["page"].get("body", ""),
                    "isPublished": v["page"].get("isPublished", False),
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_PAGE, {
                "title": "Holiday Returns",
                "body_html": "<p>Extended through Jan 31.</p>",
                "handle": "holiday-returns",
                "is_published": True,
            })
        assert result.ok
        assert captured["page"]["title"] == "Holiday Returns"
        assert captured["page"]["body"] == "<p>Extended through Jan 31.</p>"
        assert captured["page"]["isPublished"] is True

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"pageCreate": {
            "page": None,
            "userErrors": [{"field": ["handle"],
                            "message": "is taken", "code": "TAKEN"}],
        }}):
            result = a.execute(Capability.SHOPIFY_CREATE_PAGE, {
                "title": "Dup", "handle": "duplicate-page",
            })
        assert not result.ok

    def test_update_requires_id(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_PAGE, {"title": "x"})
        assert not result.ok

    def test_update_no_fields_rejected(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_PAGE, {
            "id": "gid://shopify/Page/1",
        })
        assert not result.ok

    def test_update_happy_path(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"pageUpdate": {
                "page": {"id": v["id"], "title": v["page"].get("title", "old")},
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_PAGE, {
                "id": "gid://shopify/Page/1",
                "title": "Renamed",
            })
        assert result.ok
        assert captured["id"] == "gid://shopify/Page/1"
        assert captured["page"]["title"] == "Renamed"

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_PAGE, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        a = ShopifyPagesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"pageDelete": {
            "deletedPageId": "gid://shopify/Page/1",
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_DELETE_PAGE, {
                "id": "gid://shopify/Page/1",
            })
        assert result.ok
        assert result.data["deleted_id"] == "gid://shopify/Page/1"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.pages import ShopifyPagesAdapter
        assert ShopifyPagesAdapter._normalise_page({}) == {}


# ── ShopifyArticlesAdapter ────────────────────────────────


class TestShopifyArticlesAdapter:
    def test_metadata(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter()
        assert a.name == "shopify_articles"
        for cap in (
            Capability.SHOPIFY_LIST_BLOGS,
            Capability.SHOPIFY_LIST_ARTICLES,
            Capability.SHOPIFY_GET_ARTICLE,
            Capability.SHOPIFY_CREATE_ARTICLE,
            Capability.SHOPIFY_UPDATE_ARTICLE,
            Capability.SHOPIFY_DELETE_ARTICLE,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_create_requires_blog_id(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_article_input(
                {"title": "x", "body_html": "<p>hi</p>"},
                for_update=False,
            )

    def test_create_requires_title(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_article_input(
                {"blog_id": "gid://shopify/Blog/1"}, for_update=False,
            )

    def test_create_input_body_html_alias(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        out = a._build_article_input({
            "blog_id": "gid://shopify/Blog/1",
            "title": "x",
            "body_html": "<p>hi</p>",
        }, for_update=False)
        assert out["blogId"] == "gid://shopify/Blog/1"
        assert out["body"] == "<p>hi</p>"

    def test_input_author_name_wrapped(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        out = a._build_article_input({
            "blog_id": "gid://shopify/Blog/1",
            "title": "x",
            "author_name": "ShopAI Editorial",
        }, for_update=False)
        assert out["author"] == {"name": "ShopAI Editorial"}

    def test_input_image_url_wrapped(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        out = a._build_article_input({
            "blog_id": "gid://shopify/Blog/1",
            "title": "x",
            "image_url": "https://cdn/img.jpg",
            "image_alt": "Hero shot",
        }, for_update=False)
        assert out["image"] == {
            "src": "https://cdn/img.jpg",
            "altText": "Hero shot",
        }

    def test_input_tags_string_split(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        out = a._build_article_input({
            "blog_id": "gid://shopify/Blog/1",
            "title": "x",
            "tags": "seo, launch ,product",
        }, for_update=False)
        assert out["tags"] == ["seo", "launch", "product"]

    # ── List blogs ───────────────────────────────

    def test_list_blogs_happy_path(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "blogs": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/Blog/1",
                    "title": "News",
                    "handle": "news",
                    "commentPolicy": "MODERATED",
                }}],
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_BLOGS, {})
        assert result.ok
        b = result.data["blogs"][0]
        assert b["title"] == "News"
        assert b["comment_policy"] == "MODERATED"

    def test_list_blogs_invalid_sort_key_rejected(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_BLOGS, {"sort_key": "BAD"},
        )
        assert not result.ok

    # ── List articles ────────────────────────────

    def test_list_articles_happy_path(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "articles": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/Article/1",
                    "title": "Top 10 levitation hacks",
                    "handle": "top-10",
                    "body": "<p>...</p>",
                    "tags": ["seo"],
                    "author": {"name": "ShopAI"},
                    "image": {"url": "https://cdn/img.jpg",
                              "altText": "Hero"},
                    "blog": {"id": "gid://shopify/Blog/1",
                             "title": "News", "handle": "news"},
                }}],
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_ARTICLES, {})
        assert result.ok
        ar = result.data["articles"][0]
        assert ar["title"] == "Top 10 levitation hacks"
        assert ar["author_name"] == "ShopAI"
        assert ar["image_url"] == "https://cdn/img.jpg"
        assert ar["blog_handle"] == "news"

    def test_list_articles_blog_id_filter_emits_query(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"articles": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_ARTICLES, {
                "blog_id": "gid://shopify/Blog/1",
            })
        assert "blog_id:gid://shopify/Blog/1" in captured["query"]

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_ARTICLE, {})
        assert not result.ok

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"article": None}):
            result = a.execute(Capability.SHOPIFY_GET_ARTICLE, {
                "id": "gid://shopify/Article/999",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Create / Update / Delete ─────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"articleCreate": {
                "article": {
                    "id": "gid://shopify/Article/new",
                    "title": v["article"]["title"],
                    "blog": {"id": v["article"]["blogId"]},
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_ARTICLE, {
                "blog_id": "gid://shopify/Blog/1",
                "title": "Why Levitation Matters",
                "body_html": "<p>...</p>",
                "is_published": True,
                "tags": ["seo"],
            })
        assert result.ok
        assert captured["article"]["blogId"] == "gid://shopify/Blog/1"
        assert captured["article"]["isPublished"] is True

    def test_update_requires_id(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_ARTICLE, {"title": "x"})
        assert not result.ok

    def test_update_no_fields_rejected(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_ARTICLE, {
            "id": "gid://shopify/Article/1",
        })
        assert not result.ok

    def test_update_happy_path(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"articleUpdate": {
                "article": {"id": v["id"]},
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_ARTICLE, {
                "id": "gid://shopify/Article/1",
                "title": "Renamed",
            })
        assert result.ok
        assert captured["id"] == "gid://shopify/Article/1"
        assert captured["article"]["title"] == "Renamed"

    def test_delete_requires_id(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_ARTICLE, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        a = ShopifyArticlesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"articleDelete": {
            "deletedArticleId": "gid://shopify/Article/1",
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_DELETE_ARTICLE, {
                "id": "gid://shopify/Article/1",
            })
        assert result.ok
        assert result.data["deleted_id"] == "gid://shopify/Article/1"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.articles import ShopifyArticlesAdapter
        assert ShopifyArticlesAdapter._normalise_blog({}) == {}
        assert ShopifyArticlesAdapter._normalise_article({}) == {}


# ── ShopifyBulkMutationsAdapter ───────────────────────────


class TestShopifyBulkMutationsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        a = ShopifyBulkMutationsAdapter()
        assert a.name == "shopify_bulk_mutations"
        for cap in (
            Capability.SHOPIFY_STAGE_UPLOAD,
            Capability.SHOPIFY_RUN_BULK_MUTATION,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        a = ShopifyBulkMutationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Stage upload input ───────────────────────

    def test_stage_invalid_resource_rejected(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyBulkMutationsAdapter._build_staged_input({
                "resource": "BAD",
                "filename": "x.jsonl",
                "mime_type": "text/jsonl",
            })

    def test_stage_requires_filename(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyBulkMutationsAdapter._build_staged_input({
                "resource": "BULK_MUTATION_VARIABLES",
                "mime_type": "text/jsonl",
            })

    def test_stage_size_coerced_to_string(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        out = ShopifyBulkMutationsAdapter._build_staged_input({
            "resource": "BULK_MUTATION_VARIABLES",
            "filename": "x.jsonl",
            "mime_type": "text/jsonl",
            "size": 12345,
        })
        assert out["fileSize"] == "12345"

    def test_stage_invalid_http_method_rejected(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyBulkMutationsAdapter._build_staged_input({
                "resource": "BULK_MUTATION_VARIABLES",
                "filename": "x.jsonl",
                "mime_type": "text/jsonl",
                "http_method": "DELETE",
            })

    def test_stage_http_method_normalised_uppercase(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        out = ShopifyBulkMutationsAdapter._build_staged_input({
            "resource": "BULK_MUTATION_VARIABLES",
            "filename": "x.jsonl",
            "mime_type": "text/jsonl",
            "http_method": "post",
        })
        assert out["httpMethod"] == "POST"

    # ── Stage upload — happy path ────────────────

    def test_stage_happy_path(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        a = ShopifyBulkMutationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"stagedUploadsCreate": {
                "stagedTargets": [{
                    "url": "https://upload.shopify.com/abc",
                    "resourceUrl": "tmp/abc/x.jsonl",
                    "parameters": [
                        {"name": "key", "value": "tmp/abc/x.jsonl"},
                        {"name": "policy", "value": "..."},
                    ],
                }],
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_STAGE_UPLOAD, {
                "resource": "BULK_MUTATION_VARIABLES",
                "filename": "products.jsonl",
                "mime_type": "text/jsonl",
                "size": "1024",
                "http_method": "POST",
            })
        assert result.ok
        # Shopify wraps a single input in a list per the
        # [StagedUploadInput!]! signature.
        assert isinstance(captured["input"], list)
        assert captured["input"][0]["resource"] == "BULK_MUTATION_VARIABLES"
        assert captured["input"][0]["fileSize"] == "1024"
        assert result.data["url"] == "https://upload.shopify.com/abc"
        assert result.data["resource_url"] == "tmp/abc/x.jsonl"
        assert {p["name"] for p in result.data["parameters"]} == {"key", "policy"}

    def test_stage_no_targets_fails(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        a = ShopifyBulkMutationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"stagedUploadsCreate": {
            "stagedTargets": [],
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_STAGE_UPLOAD, {
                "resource": "BULK_MUTATION_VARIABLES",
                "filename": "x.jsonl",
                "mime_type": "text/jsonl",
            })
        assert not result.ok

    def test_stage_user_errors_fail_fast(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        a = ShopifyBulkMutationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"stagedUploadsCreate": {
            "stagedTargets": [],
            "userErrors": [{"field": ["resource"], "message": "invalid"}],
        }}):
            result = a.execute(Capability.SHOPIFY_STAGE_UPLOAD, {
                "resource": "BULK_MUTATION_VARIABLES",
                "filename": "x.jsonl",
                "mime_type": "text/jsonl",
            })
        assert not result.ok

    # ── Run mutation ─────────────────────────────

    def test_run_mutation_requires_mutation(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        a = ShopifyBulkMutationsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_RUN_BULK_MUTATION, {
            "staged_upload_path": "tmp/abc/x.jsonl",
        })
        assert not result.ok

    def test_run_mutation_requires_staged_path(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        a = ShopifyBulkMutationsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_RUN_BULK_MUTATION, {
            "mutation": "mutation x { ... }",
        })
        assert not result.ok

    def test_run_mutation_happy_path(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        a = ShopifyBulkMutationsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"bulkOperationRunMutation": {
                "bulkOperation": {
                    "id": "gid://shopify/BulkOperation/b1",
                    "status": "CREATED",
                    "type": "MUTATION",
                    "query": v["mutation"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_RUN_BULK_MUTATION, {
                "mutation": "mutation call($input: ProductInput!) { ... }",
                "staged_upload_path": "tmp/abc/x.jsonl",
            })
        assert result.ok
        assert captured["stagedUploadPath"] == "tmp/abc/x.jsonl"
        assert result.data["bulk_operation"]["status"] == "CREATED"
        assert result.data["bulk_operation"]["type"] == "MUTATION"

    def test_run_mutation_user_errors_fail_fast(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        a = ShopifyBulkMutationsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "bulkOperationRunMutation": {
                "bulkOperation": None,
                "userErrors": [{
                    "field": ["mutation"],
                    "message": "must be a single mutation",
                    "code": "INVALID",
                }],
            }
        }):
            result = a.execute(Capability.SHOPIFY_RUN_BULK_MUTATION, {
                "mutation": "{ broken }",
                "staged_upload_path": "tmp/abc/x.jsonl",
            })
        assert not result.ok

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.bulk_mutations import (
            ShopifyBulkMutationsAdapter,
        )
        assert ShopifyBulkMutationsAdapter._normalise_op({}) == {}


# ── ShopifyDisputesAdapter ────────────────────────────────


class TestShopifyDisputesAdapter:
    def test_metadata(self):
        from core.adapters.shopify.disputes import ShopifyDisputesAdapter
        a = ShopifyDisputesAdapter()
        assert a.name == "shopify_disputes"
        for cap in (
            Capability.SHOPIFY_LIST_DISPUTES,
            Capability.SHOPIFY_GET_DISPUTE,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.disputes import ShopifyDisputesAdapter
        a = ShopifyDisputesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_happy_path_with_payments(self):
        from core.adapters.shopify.disputes import ShopifyDisputesAdapter
        a = ShopifyDisputesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "shopifyPaymentsAccount": {
                "disputes": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [{"node": {
                        "id": "gid://shopify/ShopifyPaymentsDispute/d1",
                        "status": "NEEDS_RESPONSE",
                        "type": "CHARGEBACK",
                        "reasonDetails": {
                            "reason": "FRAUDULENT",
                            "networkReasonCode": "10.4",
                        },
                        "amount": {"amount": "150.00", "currencyCode": "USD"},
                        "initiatedAt": "2026-04-01T10:00:00Z",
                        "evidenceDueBy": "2026-04-15T10:00:00Z",
                        "order": {
                            "id": "gid://shopify/Order/100",
                            "name": "#1100",
                        },
                    }}],
                },
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_DISPUTES, {})
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["shop_uses_shopify_payments"] is True
        d = result.data["disputes"][0]
        assert d["status"] == "NEEDS_RESPONSE"
        assert d["reason"] == "FRAUDULENT"
        assert d["network_reason_code"] == "10.4"
        assert d["amount"] == "150.00"
        assert d["order_name"] == "#1100"

    def test_list_handles_no_shopify_payments(self):
        from core.adapters.shopify.disputes import ShopifyDisputesAdapter
        a = ShopifyDisputesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "shopifyPaymentsAccount": None,
        }):
            result = a.execute(Capability.SHOPIFY_LIST_DISPUTES, {})
        assert result.ok
        assert result.data["count"] == 0
        assert result.data["shop_uses_shopify_payments"] is False

    def test_list_clamps_limit(self):
        from core.adapters.shopify.disputes import ShopifyDisputesAdapter
        a = ShopifyDisputesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"shopifyPaymentsAccount": None}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_DISPUTES, {"limit": 9999})
        assert captured["first"] == 250

    def test_list_ignores_sort_key_and_query(self):
        # Pattern D: the disputes connection rejects sortKey/query/reverse
        # (unlike most other connections). The adapter silently drops
        # them rather than failing — engines that pass these for
        # consistency with other list calls don't get spurious errors.
        from core.adapters.shopify.disputes import ShopifyDisputesAdapter
        a = ShopifyDisputesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"shopifyPaymentsAccount": None}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_DISPUTES, {
                "query": "status:NEEDS_RESPONSE",
                "sort_key": "INITIATED_AT",
                "reverse": True,
            })
        assert "query" not in captured
        assert "sortKey" not in captured
        assert "reverse" not in captured

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.disputes import ShopifyDisputesAdapter
        a = ShopifyDisputesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_DISPUTE, {})
        assert not result.ok

    def test_get_happy_path(self):
        from core.adapters.shopify.disputes import ShopifyDisputesAdapter
        a = ShopifyDisputesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"node": {
            "id": "gid://shopify/ShopifyPaymentsDispute/d1",
            "status": "WON",
            "type": "INQUIRY",
            "reasonDetails": {
                "reason": "PRODUCT_NOT_RECEIVED",
                "networkReasonCode": "30",
            },
            "amount": {"amount": "75.00", "currencyCode": "USD"},
            "order": {"id": "gid://shopify/Order/2", "name": "#2002"},
        }}):
            result = a.execute(Capability.SHOPIFY_GET_DISPUTE, {
                "id": "gid://shopify/ShopifyPaymentsDispute/d1",
            })
        assert result.ok
        assert result.data["found"] is True
        d = result.data["dispute"]
        assert d["status"] == "WON"
        assert d["type"] == "INQUIRY"
        assert d["amount"] == "75.00"

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.disputes import ShopifyDisputesAdapter
        a = ShopifyDisputesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"node": None}):
            result = a.execute(Capability.SHOPIFY_GET_DISPUTE, {
                "id": "gid://shopify/ShopifyPaymentsDispute/999",
            })
        assert result.ok
        assert result.data["found"] is False

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.disputes import ShopifyDisputesAdapter
        assert ShopifyDisputesAdapter._normalise_dispute({}) == {}
        assert ShopifyDisputesAdapter._normalise_dispute(None) == {}


# ── ShopifyDeliveryProfilesAdapter ────────────────────────


class TestShopifyDeliveryProfilesAdapter:
    def test_metadata(self):
        from core.adapters.shopify.delivery_profiles import (
            ShopifyDeliveryProfilesAdapter,
        )
        a = ShopifyDeliveryProfilesAdapter()
        assert a.name == "shopify_delivery_profiles"
        for cap in (
            Capability.SHOPIFY_LIST_DELIVERY_PROFILES,
            Capability.SHOPIFY_GET_DELIVERY_PROFILE,
            Capability.SHOPIFY_GET_DELIVERY_SETTINGS,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.delivery_profiles import (
            ShopifyDeliveryProfilesAdapter,
        )
        a = ShopifyDeliveryProfilesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.delivery_profiles import (
            ShopifyDeliveryProfilesAdapter,
        )
        a = ShopifyDeliveryProfilesAdapter(shop_url="s", access_token="t")
        zone_node = {
            "zone": {
                "id": "gid://shopify/DeliveryZone/1",
                "name": "Domestic",
                "countries": [{
                    "id": "gid://shopify/DeliveryCountry/1",
                    "code": {"countryCode": "US"},
                    "provinces": [{"id": "p1", "code": "CA"}],
                }],
            },
            "methodDefinitionCounts": {
                "rateDefinitionsCount": 2,
                "participantDefinitionsCount": 0,
            },
        }
        location_node = {
            "id": "gid://shopify/Location/1",
            "name": "Shop location",
        }
        profile_node = {
            "id": "gid://shopify/DeliveryProfile/1",
            "name": "General Profile",
            "default": True,
            "legacyMode": False,
            "profileLocationGroups": [{
                "locationGroup": {
                    "id": "gid://shopify/DeliveryLocationGroup/1",
                    "locations": {"edges": [{"node": location_node}]},
                },
                "locationGroupZones": {
                    "edges": [{"node": zone_node}],
                },
            }],
        }
        with patch.object(a, "_gql", return_value={
            "deliveryProfiles": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": profile_node}],
            },
        }):
            result = a.execute(Capability.SHOPIFY_LIST_DELIVERY_PROFILES, {})
        assert result.ok
        assert result.data["count"] == 1
        p = result.data["profiles"][0]
        assert p["name"] == "General Profile"
        assert p["default"] is True
        lg = p["location_groups"][0]
        assert lg["locations"][0]["name"] == "Shop location"
        zone = lg["zones"][0]
        assert zone["zone_name"] == "Domestic"
        assert zone["countries"][0]["country_code"] == "US"
        assert zone["rate_count"] == 2

    def test_list_clamps_limit(self):
        from core.adapters.shopify.delivery_profiles import (
            ShopifyDeliveryProfilesAdapter,
        )
        a = ShopifyDeliveryProfilesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"deliveryProfiles": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_DELIVERY_PROFILES, {"limit": 9999})
        assert captured["first"] == 100  # max for this connection

    # ── Get single profile (with rates) ──────────

    def test_get_requires_id(self):
        from core.adapters.shopify.delivery_profiles import (
            ShopifyDeliveryProfilesAdapter,
        )
        a = ShopifyDeliveryProfilesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_DELIVERY_PROFILE, {})
        assert not result.ok

    def test_get_happy_path_with_flat_rate_method(self):
        from core.adapters.shopify.delivery_profiles import (
            ShopifyDeliveryProfilesAdapter,
        )
        a = ShopifyDeliveryProfilesAdapter(shop_url="s", access_token="t")
        method_node = {
            "id": "gid://shopify/DeliveryMethodDefinition/m1",
            "name": "Standard",
            "active": True,
            "description": "5-7 days",
            "rateProvider": {
                "__typename": "DeliveryRateDefinition",
                "id": "gid://shopify/DeliveryRateDefinition/r1",
                "price": {"amount": "5.99", "currencyCode": "USD"},
            },
        }
        zone_node = {
            "zone": {"id": "z1", "name": "US", "countries": []},
            "methodDefinitions": {"edges": [{"node": method_node}]},
        }
        profile = {
            "id": "gid://shopify/DeliveryProfile/1",
            "name": "Default",
            "default": True,
            "legacyMode": False,
            "profileLocationGroups": [{
                "locationGroup": {
                    "id": "gid://shopify/DeliveryLocationGroup/1",
                    "locations": {"edges": []},
                },
                "locationGroupZones": {"edges": [{"node": zone_node}]},
            }],
        }
        with patch.object(a, "_gql", return_value={"deliveryProfile": profile}):
            result = a.execute(Capability.SHOPIFY_GET_DELIVERY_PROFILE, {
                "id": "gid://shopify/DeliveryProfile/1",
            })
        assert result.ok
        zone = result.data["profile"]["location_groups"][0]["zones"][0]
        method = zone["methods"][0]
        assert method["name"] == "Standard"
        assert method["kind"] == "DeliveryRateDefinition"
        assert method["price"] == "5.99"
        assert method["currency_code"] == "USD"

    def test_get_happy_path_with_carrier_participant(self):
        from core.adapters.shopify.delivery_profiles import (
            ShopifyDeliveryProfilesAdapter,
        )
        a = ShopifyDeliveryProfilesAdapter(shop_url="s", access_token="t")
        method_node = {
            "id": "m1", "name": "UPS Ground",
            "active": True, "description": "",
            "rateProvider": {
                "__typename": "DeliveryParticipant",
                "id": "part1",
                "carrierService": {"id": "cs1", "name": "UPS"},
                "fixedFee": {"amount": "2.00", "currencyCode": "USD"},
                "percentageOfRateFee": "0.10",
            },
        }
        zone_node = {
            "zone": {"id": "z1", "name": "US", "countries": []},
            "methodDefinitions": {"edges": [{"node": method_node}]},
        }
        profile = {
            "id": "p1", "name": "x", "default": False, "legacyMode": False,
            "profileLocationGroups": [{
                "locationGroup": {"id": "lg1", "locations": {"edges": []}},
                "locationGroupZones": {"edges": [{"node": zone_node}]},
            }],
        }
        with patch.object(a, "_gql", return_value={"deliveryProfile": profile}):
            result = a.execute(Capability.SHOPIFY_GET_DELIVERY_PROFILE, {
                "id": "gid://shopify/DeliveryProfile/p1",
            })
        method = result.data["profile"]["location_groups"][0]["zones"][0]["methods"][0]
        assert method["kind"] == "DeliveryParticipant"
        assert method["carrier_name"] == "UPS"
        assert method["fixed_fee"] == "2.00"
        assert method["percentage_fee"] == 0.10

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.delivery_profiles import (
            ShopifyDeliveryProfilesAdapter,
        )
        a = ShopifyDeliveryProfilesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"deliveryProfile": None}):
            result = a.execute(Capability.SHOPIFY_GET_DELIVERY_PROFILE, {
                "id": "gid://shopify/DeliveryProfile/999",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Settings ─────────────────────────────────

    def test_get_settings_happy_path(self):
        from core.adapters.shopify.delivery_profiles import (
            ShopifyDeliveryProfilesAdapter,
        )
        a = ShopifyDeliveryProfilesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"deliverySettings": {
            "legacyModeBlocked": {
                "blocked": True,
                "reasons": ["LEGACY_MODE_PROFILES_NOT_ALLOWED"],
            },
            "legacyModeProfiles": False,
        }}):
            result = a.execute(Capability.SHOPIFY_GET_DELIVERY_SETTINGS, {})
        assert result.ok
        assert result.data["legacy_mode_blocked"] is True
        assert result.data["legacy_blocked_reasons"] == [
            "LEGACY_MODE_PROFILES_NOT_ALLOWED",
        ]
        assert result.data["legacy_mode_profiles"] is False

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.delivery_profiles import (
            ShopifyDeliveryProfilesAdapter,
        )
        assert ShopifyDeliveryProfilesAdapter._normalise_profile(
            {}, with_rates=True,
        ) == {}
        assert ShopifyDeliveryProfilesAdapter._normalise_zone(
            {}, with_rates=True,
        )["zone_id"] == ""


# ── ShopifyDraftOrderCalculateAdapter ─────────────────────


class TestShopifyDraftOrderCalculateAdapter:
    def test_metadata(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        a = ShopifyDraftOrderCalculateAdapter()
        assert a.name == "shopify_draft_order_calculate"
        assert Capability.SHOPIFY_CALCULATE_DRAFT_ORDER in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        a = ShopifyDraftOrderCalculateAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_requires_line_items(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrderCalculateAdapter._build_input({})

    def test_requires_non_empty_line_items(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrderCalculateAdapter._build_input({"line_items": []})

    def test_line_item_requires_variant_or_title(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrderCalculateAdapter._build_line_item({}, 0)

    def test_line_item_quantity_default_1(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        out = ShopifyDraftOrderCalculateAdapter._build_line_item(
            {"variant_id": "gid://shopify/ProductVariant/1"}, 0,
        )
        assert out["quantity"] == 1

    def test_line_item_quantity_validated_positive(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrderCalculateAdapter._build_line_item(
                {"variant_id": "gid://shopify/ProductVariant/1",
                 "quantity": 0}, 0,
            )

    def test_input_full_shape(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        out = ShopifyDraftOrderCalculateAdapter._build_input({
            "line_items": [
                {"variant_id": "gid://shopify/ProductVariant/v1",
                 "quantity": 2},
            ],
            "customer_id": "gid://shopify/Customer/c1",
            "shipping_address": {
                "address1": "1 Main St", "city": "Seattle",
                "province_code": "WA", "country_code": "US",
                "zip": "98101",
            },
            "currency_code": "usd",
            "tags": "preview, abandoned",
            "applied_discount": {
                "value": 10, "value_type": "percentage",
                "title": "VIP -10%",
            },
        })
        assert out["lineItems"][0]["variantId"] == "gid://shopify/ProductVariant/v1"
        assert out["purchasingEntity"]["customerId"] == "gid://shopify/Customer/c1"
        assert out["shippingAddress"]["countryCode"] == "US"
        assert out["shippingAddress"]["provinceCode"] == "WA"
        assert out["presentmentCurrencyCode"] == "USD"
        assert out["tags"] == ["preview", "abandoned"]
        assert out["appliedDiscount"]["value"] == 10.0
        assert out["appliedDiscount"]["valueType"] == "PERCENTAGE"

    def test_invalid_discount_value_type_rejected(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrderCalculateAdapter._build_discount(
                {"value": 10, "value_type": "BOGOF"}, "applied_discount",
            )

    def test_address_non_string_rejected(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        with pytest.raises(AdapterValidationError):
            ShopifyDraftOrderCalculateAdapter._build_address(
                {"city": 123}, "shipping_address",
            )

    # ── Calculate — happy path ───────────────────

    def test_calculate_happy_path(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        a = ShopifyDraftOrderCalculateAdapter(shop_url="s", access_token="t")
        captured: dict = {}
        calculation = {
            "subtotalPriceSet": {
                "shopMoney": {"amount": "20.00", "currencyCode": "USD"},
            },
            "totalPriceSet": {
                "shopMoney": {"amount": "23.40", "currencyCode": "USD"},
            },
            "totalShippingPriceSet": {
                "shopMoney": {"amount": "5.00", "currencyCode": "USD"},
            },
            "totalTaxSet": {
                "shopMoney": {"amount": "1.40", "currencyCode": "USD"},
            },
            "currencyCode": "USD",
            "shippingLine": {
                "title": "Standard",
                "shippingRateHandle": "standard-rate",
                "price": "5.00",
                "custom": False,
            },
            "taxLines": [{"title": "WA Tax", "rate": 0.07, "price": "1.40"}],
            "appliedDiscount": {
                "title": "VIP",
                "description": "10% off",
                "value": "10.0",
                "valueType": "PERCENTAGE",
                "amountV2": {"amount": "2.00", "currencyCode": "USD"},
            },
            "lineItems": [{
                "variant": {"id": "v1", "title": "Default"},
                "product": {"id": "p1", "title": "Lantern"},
                "quantity": 2,
                "sku": "LANT-1",
                "title": "Lantern",
                "originalUnitPriceSet": {
                    "shopMoney": {"amount": "10.00", "currencyCode": "USD"},
                },
                "discountedUnitPriceSet": {
                    "shopMoney": {"amount": "9.00", "currencyCode": "USD"},
                },
                "totalDiscountSet": {
                    "shopMoney": {"amount": "2.00", "currencyCode": "USD"},
                },
            }],
        }

        def fake_gql(q, v):
            captured.update(v)
            return {"draftOrderCalculate": {
                "calculatedDraftOrder": calculation,
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CALCULATE_DRAFT_ORDER, {
                "line_items": [
                    {"variant_id": "gid://shopify/ProductVariant/v1",
                     "quantity": 2},
                ],
            })
        assert result.ok
        c = result.data["calculation"]
        assert c["subtotal_price"] == "20.00"
        assert c["total_price"] == "23.40"
        assert c["total_shipping"] == "5.00"
        assert c["total_tax"] == "1.40"
        assert c["currency_code"] == "USD"
        assert c["shipping_title"] == "Standard"
        assert c["shipping_rate_handle"] == "standard-rate"
        assert c["applied_discount_title"] == "VIP"
        assert c["applied_discount_amount"] == "2.00"
        assert len(c["tax_lines"]) == 1
        assert c["tax_lines"][0]["rate"] == 0.07
        assert len(c["line_items"]) == 1
        li = c["line_items"][0]
        assert li["product_title"] == "Lantern"
        assert li["original_unit_price"] == "10.00"
        assert li["discounted_unit_price"] == "9.00"
        # Confirm the wire input was assembled correctly.
        assert captured["input"]["lineItems"][0]["variantId"] == \
            "gid://shopify/ProductVariant/v1"

    def test_calculate_user_errors_fail_fast(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        a = ShopifyDraftOrderCalculateAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"draftOrderCalculate": {
            "calculatedDraftOrder": None,
            "userErrors": [{"field": ["lineItems"],
                            "message": "Variant not found"}],
        }}):
            result = a.execute(Capability.SHOPIFY_CALCULATE_DRAFT_ORDER, {
                "line_items": [
                    {"variant_id": "gid://shopify/ProductVariant/missing",
                     "quantity": 1},
                ],
            })
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    # ── Normaliser ───────────────────────────────

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.draft_order_calculate import (
            ShopifyDraftOrderCalculateAdapter,
        )
        assert ShopifyDraftOrderCalculateAdapter._normalise_calculation(
            {},
        ) == {}


# ── ShopifySellingPlanGroupsAdapter ───────────────────────


class TestShopifySellingPlanGroupsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.selling_plan_groups import (
            ShopifySellingPlanGroupsAdapter,
        )
        a = ShopifySellingPlanGroupsAdapter()
        assert a.name == "shopify_selling_plan_groups"
        for cap in (
            Capability.SHOPIFY_LIST_SELLING_PLAN_GROUPS,
            Capability.SHOPIFY_GET_SELLING_PLAN_GROUP,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.selling_plan_groups import (
            ShopifySellingPlanGroupsAdapter,
        )
        a = ShopifySellingPlanGroupsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_happy_path_compact(self):
        from core.adapters.shopify.selling_plan_groups import (
            ShopifySellingPlanGroupsAdapter,
        )
        a = ShopifySellingPlanGroupsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "sellingPlanGroups": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/SellingPlanGroup/g1",
                    "name": "Subscribe & Save",
                    "merchantCode": "subscribe-save",
                    "options": ["Delivery every"],
                    "position": 1,
                    "description": "",
                    "appId": "",
                    "sellingPlans": {"edges": [{"node": {"id": "p1"}}]},
                    "products": {"edges": [{"node": {"id": "prod1"}}]},
                }}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_SELLING_PLAN_GROUPS, {},
            )
        assert result.ok
        g = result.data["groups"][0]
        assert g["name"] == "Subscribe & Save"
        assert g["merchant_code"] == "subscribe-save"
        assert g["has_plans"] is True
        assert g["has_products"] is True

    def test_list_clamps_limit(self):
        from core.adapters.shopify.selling_plan_groups import (
            ShopifySellingPlanGroupsAdapter,
        )
        a = ShopifySellingPlanGroupsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"sellingPlanGroups": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_SELLING_PLAN_GROUPS,
                {"limit": 9999},
            )
        assert captured["first"] == 100

    def test_list_passes_query_filter(self):
        from core.adapters.shopify.selling_plan_groups import (
            ShopifySellingPlanGroupsAdapter,
        )
        a = ShopifySellingPlanGroupsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"sellingPlanGroups": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_SELLING_PLAN_GROUPS,
                {"query": "name:Coffee"},
            )
        assert captured["query"] == "name:Coffee"

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.selling_plan_groups import (
            ShopifySellingPlanGroupsAdapter,
        )
        a = ShopifySellingPlanGroupsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_SELLING_PLAN_GROUP, {})
        assert not result.ok

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.selling_plan_groups import (
            ShopifySellingPlanGroupsAdapter,
        )
        a = ShopifySellingPlanGroupsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"sellingPlanGroup": None}):
            result = a.execute(Capability.SHOPIFY_GET_SELLING_PLAN_GROUP, {
                "id": "gid://shopify/SellingPlanGroup/999",
            })
        assert result.ok
        assert result.data["found"] is False

    def test_get_full_with_recurring_billing_and_percentage_pricing(self):
        from core.adapters.shopify.selling_plan_groups import (
            ShopifySellingPlanGroupsAdapter,
        )
        a = ShopifySellingPlanGroupsAdapter(shop_url="s", access_token="t")
        plan_node = {
            "id": "gid://shopify/SellingPlan/p1",
            "name": "Every 30 days, 10% off",
            "description": "",
            "options": ["30 days"],
            "position": 1,
            "category": "SUBSCRIPTION",
            "billingPolicy": {
                "__typename": "SellingPlanRecurringBillingPolicy",
                "interval": "DAY",
                "intervalCount": 30,
                "minCycles": 1,
                "maxCycles": 0,
                "anchors": [],
            },
            "deliveryPolicy": {
                "__typename": "SellingPlanRecurringDeliveryPolicy",
                "interval": "DAY",
                "intervalCount": 30,
                "preAnchorBehavior": "NEXT",
                "cutoff": 0,
                "intent": "ON_FULFILLMENT",
            },
            "pricingPolicies": [{
                "__typename": "SellingPlanFixedPricingPolicy",
                "adjustmentType": "PERCENTAGE",
                "adjustmentValue": {
                    "__typename": "SellingPlanPricingPolicyPercentageValue",
                    "percentage": 10.0,
                },
            }],
        }
        group = {
            "id": "gid://shopify/SellingPlanGroup/g1",
            "name": "Subscribe & Save",
            "merchantCode": "subscribe-save",
            "options": ["Delivery every"],
            "position": 1,
            "description": "",
            "summary": "",
            "appId": "",
            "createdAt": "2026-01-01T00:00:00Z",
            "sellingPlans": {"edges": [{"node": plan_node}]},
            "products": {"edges": [{"node": {
                "id": "gid://shopify/Product/1",
                "title": "Coffee",
                "handle": "coffee",
            }}]},
        }
        with patch.object(a, "_gql", return_value={"sellingPlanGroup": group}):
            result = a.execute(
                Capability.SHOPIFY_GET_SELLING_PLAN_GROUP,
                {"id": "gid://shopify/SellingPlanGroup/g1"},
            )
        assert result.ok
        g = result.data["group"]
        plan = g["selling_plans"][0]
        assert plan["billing"]["kind"] == "RECURRING"
        assert plan["billing"]["interval"] == "DAY"
        assert plan["billing"]["interval_count"] == 30
        assert plan["delivery"]["intent"] == "ON_FULFILLMENT"
        assert plan["pricing"][0]["kind"] == "FIXED"
        assert plan["pricing"][0]["adjustment_type"] == "PERCENTAGE"
        assert plan["pricing"][0]["adjustment_percentage"] == 10.0
        assert g["products"][0]["handle"] == "coffee"

    def test_get_full_with_money_pricing(self):
        from core.adapters.shopify.selling_plan_groups import (
            ShopifySellingPlanGroupsAdapter,
        )
        a = ShopifySellingPlanGroupsAdapter(shop_url="s", access_token="t")
        plan_node = {
            "id": "gid://shopify/SellingPlan/p1",
            "name": "x", "description": "", "options": [],
            "position": 1, "category": "SUBSCRIPTION",
            "billingPolicy": {},
            "deliveryPolicy": {},
            "pricingPolicies": [{
                "__typename": "SellingPlanRecurringPricingPolicy",
                "afterCycle": 3,
                "adjustmentType": "FIXED_AMOUNT",
                "adjustmentValue": {
                    "__typename": "MoneyV2",
                    "amount": "5.00",
                    "currencyCode": "USD",
                },
            }],
        }
        group = {
            "id": "g1", "name": "x", "merchantCode": "",
            "options": [], "position": 1, "description": "",
            "summary": "", "appId": "", "createdAt": "",
            "sellingPlans": {"edges": [{"node": plan_node}]},
            "products": {"edges": []},
        }
        with patch.object(a, "_gql", return_value={"sellingPlanGroup": group}):
            result = a.execute(
                Capability.SHOPIFY_GET_SELLING_PLAN_GROUP,
                {"id": "gid://shopify/SellingPlanGroup/g1"},
            )
        plan = result.data["group"]["selling_plans"][0]
        assert plan["pricing"][0]["kind"] == "RECURRING"
        assert plan["pricing"][0]["after_cycle"] == 3
        assert plan["pricing"][0]["adjustment_money_amount"] == "5.00"
        assert plan["pricing"][0]["adjustment_money_currency"] == "USD"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.selling_plan_groups import (
            ShopifySellingPlanGroupsAdapter,
        )
        assert ShopifySellingPlanGroupsAdapter._normalise_group_compact({}) == {}
        assert ShopifySellingPlanGroupsAdapter._normalise_group_full({}) == {}
        assert ShopifySellingPlanGroupsAdapter._normalise_plan(None) == {}


# ── ShopifyCustomerPaymentMethodsAdapter ──────────────────


class TestShopifyCustomerPaymentMethodsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter()
        assert a.name == "shopify_customer_payment_methods"
        for cap in (
            Capability.SHOPIFY_LIST_CUSTOMER_PAYMENT_METHODS,
            Capability.SHOPIFY_GET_CUSTOMER_PAYMENT_METHOD,
            Capability.SHOPIFY_REVOKE_CUSTOMER_PAYMENT_METHOD,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_requires_customer_id(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        result = a.execute(
            Capability.SHOPIFY_LIST_CUSTOMER_PAYMENT_METHODS, {},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_list_happy_path_credit_card(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql", return_value={
            "customer": {
                "id": "gid://shopify/Customer/c1",
                "paymentMethods": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [{"node": {
                        "id": "gid://shopify/CustomerPaymentMethod/m1",
                        "revokedAt": None,
                        "revokedReason": None,
                        "instrument": {
                            "__typename": "CustomerCreditCard",
                            "brand": "VISA",
                            "expiresSoon": False,
                            "expiryMonth": 12,
                            "expiryYear": 2030,
                            "firstDigits": "4111",
                            "lastDigits": "1111",
                            "maskedNumber": "•••• 1111",
                            "name": "Test Holder",
                            "source": "shopify_payments",
                            "virtualLastDigits": "",
                        },
                    }}],
                },
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_CUSTOMER_PAYMENT_METHODS,
                {"customer_id": "gid://shopify/Customer/c1"},
            )
        assert result.ok
        m = result.data["payment_methods"][0]
        assert m["instrument_kind"] == "CustomerCreditCard"
        assert m["brand"] == "VISA"
        assert m["last_digits"] == "1111"
        assert m["expiry_month"] == 12
        assert m["is_active"] is True

    def test_list_happy_path_paypal(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql", return_value={
            "customer": {
                "id": "gid://shopify/Customer/c1",
                "paymentMethods": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [{"node": {
                        "id": "gid://shopify/CustomerPaymentMethod/m2",
                        "revokedAt": None,
                        "instrument": {
                            "__typename": "CustomerPaypalBillingAgreement",
                            "paypalAccountEmail": "x@y.com",
                            "inactive": False,
                        },
                    }}],
                },
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_CUSTOMER_PAYMENT_METHODS,
                {"customer_id": "gid://shopify/Customer/c1"},
            )
        m = result.data["payment_methods"][0]
        assert m["instrument_kind"] == "CustomerPaypalBillingAgreement"
        assert m["paypal_account_email"] == "x@y.com"
        assert m["inactive"] is False

    def test_list_revoked_marked_inactive(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql", return_value={
            "customer": {
                "id": "gid://shopify/Customer/c1",
                "paymentMethods": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [{"node": {
                        "id": "gid://shopify/CustomerPaymentMethod/m3",
                        "revokedAt": "2026-04-01T00:00:00Z",
                        "revokedReason": "MERCHANT_REQUESTED",
                        "instrument": {
                            "__typename": "CustomerCreditCard",
                            "brand": "VISA",
                        },
                    }}],
                },
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_CUSTOMER_PAYMENT_METHODS,
                {"customer_id": "gid://shopify/Customer/c1"},
            )
        m = result.data["payment_methods"][0]
        assert m["is_active"] is False
        assert m["revoked_reason"] == "MERCHANT_REQUESTED"

    def test_list_clamps_limit(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"customer": None}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_CUSTOMER_PAYMENT_METHODS,
                {"customer_id": "gid://shopify/Customer/c1", "limit": 9999},
            )
        assert captured["first"] == 250

    def test_list_handles_missing_customer(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql", return_value={"customer": None}):
            result = a.execute(
                Capability.SHOPIFY_LIST_CUSTOMER_PAYMENT_METHODS,
                {"customer_id": "gid://shopify/Customer/missing"},
            )
        assert result.ok
        assert result.data["customer_found"] is False
        assert result.data["count"] == 0

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        result = a.execute(
            Capability.SHOPIFY_GET_CUSTOMER_PAYMENT_METHOD, {},
        )
        assert not result.ok

    def test_get_happy_path_shop_pay(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql", return_value={
            "customerPaymentMethod": {
                "id": "gid://shopify/CustomerPaymentMethod/m1",
                "revokedAt": None,
                "instrument": {
                    "__typename": "CustomerShopPayAgreement",
                    "expiresSoon": True,
                    "expiryMonth": 5,
                    "expiryYear": 2026,
                    "inactive": False,
                    "lastDigits": "4242",
                    "maskedNumber": "•••• 4242",
                },
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_GET_CUSTOMER_PAYMENT_METHOD,
                {"id": "gid://shopify/CustomerPaymentMethod/m1"},
            )
        assert result.ok
        m = result.data["payment_method"]
        assert m["instrument_kind"] == "CustomerShopPayAgreement"
        assert m["expires_soon"] is True
        assert m["last_digits"] == "4242"

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql", return_value={
            "customerPaymentMethod": None,
        }):
            result = a.execute(
                Capability.SHOPIFY_GET_CUSTOMER_PAYMENT_METHOD,
                {"id": "gid://shopify/CustomerPaymentMethod/999"},
            )
        assert result.ok
        assert result.data["found"] is False

    # ── Revoke ───────────────────────────────────

    def test_revoke_requires_id(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        result = a.execute(
            Capability.SHOPIFY_REVOKE_CUSTOMER_PAYMENT_METHOD, {},
        )
        assert not result.ok

    def test_revoke_happy_path(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql", return_value={
            "customerPaymentMethodRevoke": {
                "revokedCustomerPaymentMethodId": (
                    "gid://shopify/CustomerPaymentMethod/m1"
                ),
                "userErrors": [],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_REVOKE_CUSTOMER_PAYMENT_METHOD,
                {"id": "gid://shopify/CustomerPaymentMethod/m1"},
            )
        assert result.ok
        assert result.data["revoked_id"] == \
            "gid://shopify/CustomerPaymentMethod/m1"

    def test_revoke_user_errors_fail_fast(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        a = ShopifyCustomerPaymentMethodsAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql", return_value={
            "customerPaymentMethodRevoke": {
                "revokedCustomerPaymentMethodId": "",
                "userErrors": [{"field": ["customerPaymentMethodId"],
                                "message": "Already revoked"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_REVOKE_CUSTOMER_PAYMENT_METHOD,
                {"id": "gid://shopify/CustomerPaymentMethod/already"},
            )
        assert not result.ok

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.customer_payment_methods import (
            ShopifyCustomerPaymentMethodsAdapter,
        )
        assert ShopifyCustomerPaymentMethodsAdapter._normalise_method({}) == {}
        assert ShopifyCustomerPaymentMethodsAdapter._normalise_method(None) == {}


# ── ShopifyAppsAdapter ────────────────────────────────────


class TestShopifyAppsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.apps import ShopifyAppsAdapter
        a = ShopifyAppsAdapter()
        assert a.name == "shopify_apps"
        for cap in (
            Capability.SHOPIFY_GET_CURRENT_APP_INSTALLATION,
            Capability.SHOPIFY_LIST_APP_INSTALLATIONS,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.apps import ShopifyAppsAdapter
        a = ShopifyAppsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Get current app installation ─────────────

    def test_get_current_happy_path(self):
        from core.adapters.shopify.apps import ShopifyAppsAdapter
        a = ShopifyAppsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "currentAppInstallation": {
                "id": "gid://shopify/AppInstallation/1",
                "launchUrl": "https://shopai.dev/launch",
                "uninstallUrl": "https://shopai.dev/uninstall",
                "accessScopes": [
                    {"handle": "read_products"},
                    {"handle": "write_orders"},
                    {"handle": "read_customers"},
                ],
                "app": {
                    "id": "gid://shopify/App/100",
                    "title": "ShopAI",
                    "handle": "shopai",
                    "apiKey": "abc123",
                    "developerName": "ShopAI Inc",
                    "embedded": True,
                },
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_GET_CURRENT_APP_INSTALLATION, {},
            )
        assert result.ok
        assert result.data["found"] is True
        inst = result.data["installation"]
        assert inst["app_title"] == "ShopAI"
        assert inst["embedded"] is True
        assert "read_products" in inst["access_scopes"]
        assert "write_orders" in inst["access_scopes"]

    def test_get_current_missing_returns_not_found(self):
        from core.adapters.shopify.apps import ShopifyAppsAdapter
        a = ShopifyAppsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "currentAppInstallation": None,
        }):
            result = a.execute(
                Capability.SHOPIFY_GET_CURRENT_APP_INSTALLATION, {},
            )
        assert result.ok
        assert result.data["found"] is False
        assert result.data["installation"] == {}

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.apps import ShopifyAppsAdapter
        a = ShopifyAppsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "appInstallations": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/AppInstallation/1",
                    "accessScopes": [{"handle": "read_orders"}],
                    "app": {
                        "id": "gid://shopify/App/100",
                        "title": "Klaviyo",
                        "handle": "klaviyo",
                        "developerName": "Klaviyo Inc",
                    },
                }}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_APP_INSTALLATIONS, {},
            )
        assert result.ok
        assert result.data["count"] == 1
        i = result.data["installations"][0]
        assert i["app_title"] == "Klaviyo"
        assert i["developer_name"] == "Klaviyo Inc"

    def test_list_clamps_limit(self):
        from core.adapters.shopify.apps import ShopifyAppsAdapter
        a = ShopifyAppsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"appInstallations": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_APP_INSTALLATIONS, {"limit": 9999},
            )
        assert captured["first"] == 250

    def test_list_invalid_category_rejected(self):
        from core.adapters.shopify.apps import ShopifyAppsAdapter
        a = ShopifyAppsAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_APP_INSTALLATIONS,
            {"category": "BAD"},
        )
        assert not result.ok

    def test_list_invalid_privacy_rejected(self):
        from core.adapters.shopify.apps import ShopifyAppsAdapter
        a = ShopifyAppsAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_APP_INSTALLATIONS,
            {"privacy": "SECRET"},
        )
        assert not result.ok

    def test_list_passes_filters(self):
        from core.adapters.shopify.apps import ShopifyAppsAdapter
        a = ShopifyAppsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"appInstallations": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_APP_INSTALLATIONS, {
                "category": "CHANNEL",
                "privacy": "PUBLIC",
            })
        assert captured["category"] == "CHANNEL"
        assert captured["privacy"] == "PUBLIC"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.apps import ShopifyAppsAdapter
        assert ShopifyAppsAdapter._normalise_installation({}) == {}
        assert ShopifyAppsAdapter._normalise_installation(None) == {}


# ── ShopifyAbandonedCheckoutsAdapter ──────────────────────


class TestShopifyAbandonedCheckoutsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.abandoned_checkouts import (
            ShopifyAbandonedCheckoutsAdapter,
        )
        a = ShopifyAbandonedCheckoutsAdapter()
        assert a.name == "shopify_abandoned_checkouts"
        for cap in (
            Capability.SHOPIFY_LIST_ABANDONED_CHECKOUTS,
            Capability.SHOPIFY_GET_ABANDONED_CHECKOUT,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.abandoned_checkouts import (
            ShopifyAbandonedCheckoutsAdapter,
        )
        a = ShopifyAbandonedCheckoutsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.abandoned_checkouts import (
            ShopifyAbandonedCheckoutsAdapter,
        )
        a = ShopifyAbandonedCheckoutsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "abandonedCheckouts": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/AbandonedCheckout/1",
                    "name": "#C1",
                    "abandonedCheckoutUrl": "https://store/recovery/abc",
                    "createdAt": "2026-04-25T10:00:00Z",
                    "completedAt": None,
                    "totalPriceSet": {
                        "shopMoney": {"amount": "100.00", "currencyCode": "USD"},
                    },
                    "subtotalPriceSet": {
                        "shopMoney": {"amount": "90.00", "currencyCode": "USD"},
                    },
                    "customer": {
                        "id": "gid://shopify/Customer/c1",
                        "email": "x@y.com",
                        "firstName": "X",
                        "numberOfOrders": 0,
                    },
                }}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_ABANDONED_CHECKOUTS, {},
            )
        assert result.ok
        c = result.data["checkouts"][0]
        assert c["name"] == "#C1"
        assert c["customer_email"] == "x@y.com"
        assert c["is_completed"] is False
        assert c["total_price"] == "100.00"
        assert c["abandoned_url"].endswith("/abc")

    def test_list_clamps_limit(self):
        from core.adapters.shopify.abandoned_checkouts import (
            ShopifyAbandonedCheckoutsAdapter,
        )
        a = ShopifyAbandonedCheckoutsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"abandonedCheckouts": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_ABANDONED_CHECKOUTS,
                {"limit": 9999},
            )
        assert captured["first"] == 250

    def test_list_invalid_sort_key_rejected(self):
        from core.adapters.shopify.abandoned_checkouts import (
            ShopifyAbandonedCheckoutsAdapter,
        )
        a = ShopifyAbandonedCheckoutsAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_ABANDONED_CHECKOUTS,
            {"sort_key": "BAD"},
        )
        assert not result.ok

    def test_list_passes_query_filter(self):
        from core.adapters.shopify.abandoned_checkouts import (
            ShopifyAbandonedCheckoutsAdapter,
        )
        a = ShopifyAbandonedCheckoutsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"abandonedCheckouts": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_ABANDONED_CHECKOUTS, {
                "query": "created_at:>2026-04-01",
                "sort_key": "CREATED_AT",
                "reverse": True,
            })
        assert captured["query"] == "created_at:>2026-04-01"
        assert captured["sortKey"] == "CREATED_AT"

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.abandoned_checkouts import (
            ShopifyAbandonedCheckoutsAdapter,
        )
        a = ShopifyAbandonedCheckoutsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_ABANDONED_CHECKOUT, {})
        assert not result.ok

    def test_get_happy_path_with_line_items(self):
        from core.adapters.shopify.abandoned_checkouts import (
            ShopifyAbandonedCheckoutsAdapter,
        )
        a = ShopifyAbandonedCheckoutsAdapter(shop_url="s", access_token="t")
        line_node = {
            "id": "gid://shopify/AbandonedCheckoutLineItem/1",
            "title": "Lantern",
            "quantity": 2,
            "sku": "LANT-1",
            "variantTitle": "Default",
            "variant": {"id": "v1", "title": "Default"},
            "product": {"id": "p1", "title": "Lantern"},
            "originalUnitPriceSet": {
                "shopMoney": {"amount": "10.00", "currencyCode": "USD"},
            },
            "discountedTotalPriceSet": {
                "shopMoney": {"amount": "20.00", "currencyCode": "USD"},
            },
        }
        checkout_node = {
            "id": "gid://shopify/AbandonedCheckout/1",
            "name": "#C1",
            "totalPriceSet": {
                "shopMoney": {"amount": "20.00", "currencyCode": "USD"},
            },
            "lineItems": {"edges": [{"node": line_node}]},
            "shippingAddress": {
                "address1": "1 Main", "city": "Seattle",
                "country": "US", "zip": "98101", "name": "X",
            },
        }
        with patch.object(a, "_gql", return_value={
            "abandonedCheckout": checkout_node,
        }):
            result = a.execute(Capability.SHOPIFY_GET_ABANDONED_CHECKOUT, {
                "id": "gid://shopify/AbandonedCheckout/1",
            })
        assert result.ok
        assert result.data["found"] is True
        c = result.data["checkout"]
        assert len(c["line_items"]) == 1
        assert c["line_items"][0]["sku"] == "LANT-1"
        assert c["line_items"][0]["quantity"] == 2
        assert c["shipping_address"]["city"] == "Seattle"

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.abandoned_checkouts import (
            ShopifyAbandonedCheckoutsAdapter,
        )
        a = ShopifyAbandonedCheckoutsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"abandonedCheckout": None}):
            result = a.execute(Capability.SHOPIFY_GET_ABANDONED_CHECKOUT, {
                "id": "gid://shopify/AbandonedCheckout/999",
            })
        assert result.ok
        assert result.data["found"] is False

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.abandoned_checkouts import (
            ShopifyAbandonedCheckoutsAdapter,
        )
        assert ShopifyAbandonedCheckoutsAdapter._normalise_checkout({}) == {}
        assert ShopifyAbandonedCheckoutsAdapter._normalise_line_item(None) == {}


# ── ShopifyCollectionsAdapter ─────────────────────────────


class TestShopifyCollectionsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter()
        assert a.name == "shopify_collections"
        for cap in (
            Capability.SHOPIFY_LIST_COLLECTIONS,
            Capability.SHOPIFY_GET_COLLECTION,
            Capability.SHOPIFY_CREATE_COLLECTION,
            Capability.SHOPIFY_UPDATE_COLLECTION,
            Capability.SHOPIFY_DELETE_COLLECTION,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_create_requires_title(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_collection_input({}, for_update=False)

    def test_update_requires_id(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_collection_input({"title": "x"}, for_update=True)

    def test_input_description_html_alias(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        out = a._build_collection_input(
            {"title": "x", "description_html": "<p>hi</p>"}, for_update=False,
        )
        assert out["descriptionHtml"] == "<p>hi</p>"

    def test_input_invalid_sort_order_rejected(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_collection_input(
                {"title": "x", "sort_order": "RANDOM"}, for_update=False,
            )

    def test_input_sort_order_uppercased(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        out = a._build_collection_input(
            {"title": "x", "sort_order": "best_selling"}, for_update=False,
        )
        assert out["sortOrder"] == "BEST_SELLING"

    def test_input_products_validated(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_collection_input(
                {"title": "x", "products": [123]}, for_update=False,
            )

    def test_input_products_pass_through(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        out = a._build_collection_input(
            {"title": "x", "products": [
                "gid://shopify/Product/1",
                "gid://shopify/Product/2",
            ]}, for_update=False,
        )
        assert out["products"] == [
            "gid://shopify/Product/1", "gid://shopify/Product/2",
        ]

    # ── Rule set ─────────────────────────────────

    def test_rule_set_requires_rules(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_rule_set({"applied_disjunctively": False})

    def test_rule_set_rejects_invalid_column(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_rule_set({"rules": [
                {"column": "BAD_COLUMN", "relation": "EQUALS",
                 "condition": "x"},
            ]})

    def test_rule_set_rejects_invalid_relation(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_rule_set({"rules": [
                {"column": "TAG", "relation": "FUZZY", "condition": "x"},
            ]})

    def test_rule_set_happy_path_smart_collection(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        out = a._build_rule_set({
            "applied_disjunctively": False,
            "rules": [
                {"column": "TAG", "relation": "EQUALS", "condition": "sale"},
                {"column": "VARIANT_PRICE", "relation": "GREATER_THAN",
                 "condition": 10},
            ],
        })
        assert out["appliedDisjunctively"] is False
        assert len(out["rules"]) == 2
        assert out["rules"][0]["column"] == "TAG"
        assert out["rules"][1]["condition"] == "10"

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "collections": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/Collection/1",
                    "title": "Summer Sale",
                    "handle": "summer-sale",
                    "sortOrder": "MANUAL",
                    "productsCount": {"count": 12},
                    "ruleSet": None,
                }}],
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_COLLECTIONS, {})
        assert result.ok
        c = result.data["collections"][0]
        assert c["title"] == "Summer Sale"
        assert c["products_count"] == 12
        assert c["is_smart"] is False

    def test_list_smart_collection_flagged(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "collections": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/Collection/2",
                    "title": "Sale Items",
                    "ruleSet": {
                        "appliedDisjunctively": False,
                        "rules": [{
                            "column": "TAG",
                            "relation": "EQUALS",
                            "condition": "sale",
                        }],
                    },
                }}],
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_COLLECTIONS, {})
        c = result.data["collections"][0]
        assert c["is_smart"] is True
        assert len(c["rule_set"]["rules"]) == 1

    def test_list_invalid_sort_key_rejected(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_COLLECTIONS, {"sort_key": "BAD"},
        )
        assert not result.ok

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_COLLECTION, {})
        assert not result.ok

    def test_get_happy_path_with_products(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "collection": {
                "id": "gid://shopify/Collection/1",
                "title": "Summer Sale",
                "products": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [{"node": {
                        "id": "gid://shopify/Product/1",
                        "title": "Lantern",
                        "handle": "lantern",
                        "status": "ACTIVE",
                    }}],
                },
            }
        }):
            result = a.execute(Capability.SHOPIFY_GET_COLLECTION, {
                "id": "gid://shopify/Collection/1",
            })
        assert result.ok
        c = result.data["collection"]
        assert len(c["products"]) == 1
        assert c["products"][0]["title"] == "Lantern"

    # ── Create / Update / Delete ─────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"collectionCreate": {
                "collection": {
                    "id": "gid://shopify/Collection/new",
                    "title": v["input"]["title"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_COLLECTION, {
                "title": "Summer Sale",
                "products": ["gid://shopify/Product/1"],
            })
        assert result.ok
        assert captured["input"]["title"] == "Summer Sale"
        assert captured["input"]["products"] == ["gid://shopify/Product/1"]

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"collectionCreate": {
            "collection": None,
            "userErrors": [{"field": ["handle"], "message": "is taken",
                            "code": "TAKEN"}],
        }}):
            result = a.execute(Capability.SHOPIFY_CREATE_COLLECTION, {
                "title": "Dup", "handle": "dup",
            })
        assert not result.ok

    def test_update_happy_path(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"collectionUpdate": {
                "collection": {"id": v["input"]["id"]},
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_COLLECTION, {
                "id": "gid://shopify/Collection/1",
                "title": "Renamed",
            })
        assert result.ok
        assert captured["input"]["id"] == "gid://shopify/Collection/1"
        assert captured["input"]["title"] == "Renamed"

    def test_delete_requires_id(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_COLLECTION, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        a = ShopifyCollectionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"collectionDelete": {
            "deletedCollectionId": "gid://shopify/Collection/1",
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_DELETE_COLLECTION, {
                "id": "gid://shopify/Collection/1",
            })
        assert result.ok
        assert result.data["deleted_id"] == "gid://shopify/Collection/1"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.collections import ShopifyCollectionsAdapter
        assert ShopifyCollectionsAdapter._normalise_collection({}) == {}
        assert ShopifyCollectionsAdapter._normalise_rule_set(None) == {}


# ── ShopifyMetafieldDefinitionsAdapter ────────────────────


class TestShopifyMetafieldDefinitionsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter()
        assert a.name == "shopify_metafield_definitions"
        for cap in (
            Capability.SHOPIFY_LIST_METAFIELD_DEFINITIONS,
            Capability.SHOPIFY_CREATE_METAFIELD_DEFINITION,
            Capability.SHOPIFY_DELETE_METAFIELD_DEFINITION,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_create_requires_namespace(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_definition_input({"key": "x", "type": "json",
                                       "owner_type": "PRODUCT"})

    def test_create_requires_key(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_definition_input({"namespace": "shopai", "type": "json",
                                       "owner_type": "PRODUCT"})

    def test_create_requires_type(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_definition_input({"namespace": "shopai", "key": "x",
                                       "owner_type": "PRODUCT"})

    def test_create_invalid_owner_type_rejected(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_definition_input({
                "namespace": "shopai", "key": "x", "type": "json",
                "owner_type": "WIDGET",
            })

    def test_create_owner_type_normalised_uppercase(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        out = a._build_definition_input({
            "namespace": "shopai", "key": "x", "type": "json",
            "owner_type": "product",
        })
        assert out["ownerType"] == "PRODUCT"

    def test_create_full_shape(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        out = a._build_definition_input({
            "namespace": "shopai",
            "key": "fraud_score",
            "type": "number_decimal",
            "name": "AI Fraud Score",
            "description": "0-1 risk",
            "owner_type": "ORDER",
            "pin": True,
            "validations": [
                {"name": "min", "value": 0},
                {"name": "max", "value": "1.0"},
            ],
        })
        assert out["namespace"] == "shopai"
        assert out["key"] == "fraud_score"
        assert out["type"] == "number_decimal"
        assert out["name"] == "AI Fraud Score"
        assert out["ownerType"] == "ORDER"
        assert out["pin"] is True
        assert len(out["validations"]) == 2
        assert out["validations"][0]["value"] == "0"

    def test_validation_missing_value_rejected(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_definition_input({
                "namespace": "shopai", "key": "x", "type": "json",
                "owner_type": "PRODUCT",
                "validations": [{"name": "min"}],
            })

    # ── List ─────────────────────────────────────

    def test_list_requires_owner_type(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_LIST_METAFIELD_DEFINITIONS, {})
        assert not result.ok

    def test_list_invalid_owner_type_rejected(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_METAFIELD_DEFINITIONS,
            {"owner_type": "INVALID"},
        )
        assert not result.ok

    def test_list_happy_path(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "metafieldDefinitions": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/MetafieldDefinition/1",
                    "namespace": "shopai",
                    "key": "fraud_score",
                    "name": "AI Fraud Score",
                    "type": {"name": "number_decimal", "category": "NUMBER"},
                    "ownerType": "ORDER",
                    "pinnedPosition": 1,
                    "metafieldsCount": {"count": 42},
                    "validations": [
                        {"name": "max", "type": "number_decimal", "value": "1.0"},
                    ],
                }}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_METAFIELD_DEFINITIONS,
                {"owner_type": "ORDER"},
            )
        assert result.ok
        d = result.data["definitions"][0]
        assert d["namespace"] == "shopai"
        assert d["key"] == "fraud_score"
        assert d["type"] == "number_decimal"
        assert d["type_category"] == "NUMBER"
        assert d["owner_type"] == "ORDER"
        assert d["is_pinned"] is True
        assert d["metafields_count"] == 42
        assert d["validations"][0]["value"] == "1.0"

    def test_list_passes_namespace_filter(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"metafieldDefinitions": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_METAFIELD_DEFINITIONS, {
                "owner_type": "PRODUCT",
                "namespace": "shopai",
            })
        assert captured["ownerType"] == "PRODUCT"
        assert captured["namespace"] == "shopai"

    # ── Create ───────────────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"metafieldDefinitionCreate": {
                "createdDefinition": {
                    "id": "gid://shopify/MetafieldDefinition/new",
                    "namespace": v["definition"]["namespace"],
                    "key": v["definition"]["key"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_METAFIELD_DEFINITION,
                {
                    "namespace": "shopai",
                    "key": "fraud_score",
                    "type": "number_decimal",
                    "owner_type": "ORDER",
                    "name": "AI Fraud Score",
                    "pin": True,
                },
            )
        assert result.ok
        # Pattern A: variable name matches the input type ("definition").
        assert captured["definition"]["namespace"] == "shopai"
        assert captured["definition"]["pin"] is True

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "metafieldDefinitionCreate": {
                "createdDefinition": None,
                "userErrors": [{"field": ["key"], "message": "is taken",
                                "code": "TAKEN"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_METAFIELD_DEFINITION,
                {"namespace": "shopai", "key": "dup", "type": "json",
                 "owner_type": "PRODUCT"},
            )
        assert not result.ok

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_DELETE_METAFIELD_DEFINITION, {},
        )
        assert not result.ok

    def test_delete_happy_path_keeps_metafields_by_default(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"metafieldDefinitionDelete": {
                "deletedDefinitionId": (
                    "gid://shopify/MetafieldDefinition/1"
                ),
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_DELETE_METAFIELD_DEFINITION,
                {"id": "gid://shopify/MetafieldDefinition/1"},
            )
        assert result.ok
        # Default is False — values survive the schema deletion.
        assert captured["deleteAllAssociatedMetafields"] is False

    def test_delete_with_value_purge(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        a = ShopifyMetafieldDefinitionsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"metafieldDefinitionDelete": {
                "deletedDefinitionId": "gid://shopify/MetafieldDefinition/1",
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_DELETE_METAFIELD_DEFINITION,
                {
                    "id": "gid://shopify/MetafieldDefinition/1",
                    "delete_all_associated_metafields": True,
                },
            )
        assert captured["deleteAllAssociatedMetafields"] is True

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.metafield_definitions import (
            ShopifyMetafieldDefinitionsAdapter,
        )
        assert ShopifyMetafieldDefinitionsAdapter._normalise_definition({}) == {}
        assert ShopifyMetafieldDefinitionsAdapter._normalise_definition(None) == {}


# ── ShopifyPriceListAdapter ───────────────────────────────


class TestShopifyPriceListAdapter:
    def test_metadata(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter()
        assert a.name == "shopify_price_lists"
        for cap in (
            Capability.SHOPIFY_LIST_PRICE_LISTS,
            Capability.SHOPIFY_GET_PRICE_LIST,
            Capability.SHOPIFY_CREATE_PRICE_LIST,
            Capability.SHOPIFY_DELETE_PRICE_LIST,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_create_requires_name(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_create_input({
                "currency_code": "USD",
                "parent": {"adjustment": {"type": "PERCENTAGE_DECREASE",
                                          "value": 10}},
            })

    def test_create_requires_currency(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_create_input({
                "name": "Wholesale",
                "parent": {"adjustment": {"type": "PERCENTAGE_DECREASE",
                                          "value": 10}},
            })

    def test_create_requires_parent(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_create_input({
                "name": "Wholesale", "currency_code": "USD",
            })

    def test_create_invalid_adjustment_type_rejected(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_create_input({
                "name": "Wholesale", "currency_code": "USD",
                "parent": {"adjustment": {"type": "FLAT", "value": 10}},
            })

    def test_create_adjustment_value_non_numeric_rejected(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_create_input({
                "name": "Wholesale", "currency_code": "USD",
                "parent": {"adjustment": {"type": "PERCENTAGE_DECREASE",
                                          "value": "ten"}},
            })

    def test_create_currency_uppercased(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        out = a._build_create_input({
            "name": "Wholesale", "currency_code": "usd",
            "parent": {"adjustment": {"type": "percentage_decrease",
                                      "value": 10}},
        })
        assert out["currency"] == "USD"
        assert out["parent"]["adjustment"]["type"] == "PERCENTAGE_DECREASE"
        assert out["parent"]["adjustment"]["value"] == 10.0

    def test_create_with_settings_and_catalog(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        out = a._build_create_input({
            "name": "Wholesale Tier 1",
            "currency_code": "USD",
            "catalog_id": "gid://shopify/CompanyLocationCatalog/1",
            "parent": {
                "adjustment": {"type": "PERCENTAGE_DECREASE",
                               "value": 30.5},
                "settings": {"compare_at_mode": "ADJUSTED"},
            },
        })
        assert out["catalogId"] == "gid://shopify/CompanyLocationCatalog/1"
        assert out["parent"]["settings"]["compareAtMode"] == "ADJUSTED"

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "priceLists": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/PriceList/1",
                    "name": "Wholesale Tier 1",
                    "currency": "USD",
                    "parent": {
                        "adjustment": {
                            "type": "PERCENTAGE_DECREASE",
                            "value": 30,
                        },
                        "settings": {"compareAtMode": "ADJUSTED"},
                    },
                    "catalog": {
                        "id": "gid://shopify/CompanyLocationCatalog/100",
                        "title": "B2B Tier 1 Catalog",
                        "status": "ACTIVE",
                    },
                    "fixedPricesCount": {"count": 42},
                }}],
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_PRICE_LISTS, {})
        assert result.ok
        p = result.data["price_lists"][0]
        assert p["name"] == "Wholesale Tier 1"
        assert p["currency_code"] == "USD"
        assert p["adjustment_type"] == "PERCENTAGE_DECREASE"
        assert p["adjustment_value"] == 30.0
        assert p["compare_at_mode"] == "ADJUSTED"
        assert p["catalog_title"] == "B2B Tier 1 Catalog"
        assert p["fixed_prices_count"] == 42

    def test_list_clamps_limit(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"priceLists": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_PRICE_LISTS, {"limit": 9999})
        assert captured["first"] == 250

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_PRICE_LIST, {})
        assert not result.ok

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"priceList": None}):
            result = a.execute(Capability.SHOPIFY_GET_PRICE_LIST, {
                "id": "gid://shopify/PriceList/999",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Create ───────────────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"priceListCreate": {
                "priceList": {
                    "id": "gid://shopify/PriceList/new",
                    "name": v["input"]["name"],
                    "currency": v["input"]["currency"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_PRICE_LIST, {
                "name": "Wholesale Tier 1",
                "currency_code": "USD",
                "parent": {
                    "adjustment": {"type": "PERCENTAGE_DECREASE",
                                   "value": 30},
                },
            })
        assert result.ok
        assert captured["input"]["name"] == "Wholesale Tier 1"
        assert captured["input"]["parent"]["adjustment"]["value"] == 30.0

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"priceListCreate": {
            "priceList": None,
            "userErrors": [{"field": ["name"], "message": "is taken",
                            "code": "TAKEN"}],
        }}):
            result = a.execute(Capability.SHOPIFY_CREATE_PRICE_LIST, {
                "name": "dup", "currency_code": "USD",
                "parent": {
                    "adjustment": {"type": "PERCENTAGE_DECREASE",
                                   "value": 10},
                },
            })
        assert not result.ok

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_PRICE_LIST, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        a = ShopifyPriceListAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"priceListDelete": {
            "deletedId": "gid://shopify/PriceList/1",
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_DELETE_PRICE_LIST, {
                "id": "gid://shopify/PriceList/1",
            })
        assert result.ok
        assert result.data["deleted_id"] == "gid://shopify/PriceList/1"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.price_lists import ShopifyPriceListAdapter
        assert ShopifyPriceListAdapter._normalise_price_list({}) == {}


# ── ShopifyCarrierServicesAdapter ─────────────────────────


class TestShopifyCarrierServicesAdapter:
    def test_metadata(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter()
        assert a.name == "shopify_carrier_services"
        for cap in (
            Capability.SHOPIFY_LIST_CARRIER_SERVICES,
            Capability.SHOPIFY_CREATE_CARRIER_SERVICE,
            Capability.SHOPIFY_UPDATE_CARRIER_SERVICE,
            Capability.SHOPIFY_DELETE_CARRIER_SERVICE,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_create_requires_name(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input({"callback_url": "https://x.com/q"},
                           for_update=False)

    def test_create_requires_callback_url(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input({"name": "ShopAI"}, for_update=False)

    def test_callback_url_must_be_http(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input({
                "name": "ShopAI",
                "callback_url": "ftp://x.com/q",
            }, for_update=False)

    def test_create_full_shape(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        out = a._build_input({
            "name": "ShopAI Smart Rates",
            "callback_url": "https://rates.shopai.dev/quote",
            "supports_service_discovery": True,
            "active": True,
        }, for_update=False)
        assert out["name"] == "ShopAI Smart Rates"
        assert out["callbackUrl"] == "https://rates.shopai.dev/quote"
        assert out["supportsServiceDiscovery"] is True
        assert out["active"] is True

    def test_update_requires_id(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input({"name": "ShopAI"}, for_update=True)

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "carrierServices": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/DeliveryCarrierService/1",
                    "name": "ShopAI Smart Rates",
                    "callbackUrl": "https://rates.shopai.dev/quote",
                    "active": True,
                    "supportsServiceDiscovery": True,
                }}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_CARRIER_SERVICES, {},
            )
        assert result.ok
        s = result.data["carrier_services"][0]
        assert s["name"] == "ShopAI Smart Rates"
        assert s["callback_url"] == "https://rates.shopai.dev/quote"
        assert s["active"] is True
        assert s["supports_service_discovery"] is True

    def test_list_clamps_limit(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"carrierServices": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_CARRIER_SERVICES,
                      {"limit": 9999})
        assert captured["first"] == 250

    # ── Create ───────────────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"carrierServiceCreate": {
                "carrierService": {
                    "id": "gid://shopify/DeliveryCarrierService/new",
                    "name": v["input"]["name"],
                    "callbackUrl": v["input"]["callbackUrl"],
                    "active": True,
                    "supportsServiceDiscovery": True,
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_CARRIER_SERVICE,
                {
                    "name": "ShopAI",
                    "callback_url": "https://rates.shopai.dev/q",
                    "supports_service_discovery": True,
                },
            )
        assert result.ok
        assert captured["input"]["callbackUrl"] == "https://rates.shopai.dev/q"
        assert captured["input"]["supportsServiceDiscovery"] is True

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"carrierServiceCreate": {
            "carrierService": None,
            "userErrors": [{"field": ["callbackUrl"],
                            "message": "Endpoint failed discovery"}],
        }}):
            result = a.execute(Capability.SHOPIFY_CREATE_CARRIER_SERVICE, {
                "name": "Bad", "callback_url": "https://broken.example",
            })
        assert not result.ok

    # ── Update ───────────────────────────────────

    def test_update_happy_path(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"carrierServiceUpdate": {
                "carrierService": {
                    "id": v["input"]["id"],
                    "name": v["input"].get("name", "old"),
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_CARRIER_SERVICE, {
                "id": "gid://shopify/DeliveryCarrierService/1",
                "name": "Renamed",
                "active": False,
            })
        assert result.ok
        assert captured["input"]["id"] == \
            "gid://shopify/DeliveryCarrierService/1"
        assert captured["input"]["active"] is False

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_CARRIER_SERVICE, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        a = ShopifyCarrierServicesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"carrierServiceDelete": {
            "deletedId": "gid://shopify/DeliveryCarrierService/1",
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_DELETE_CARRIER_SERVICE, {
                "id": "gid://shopify/DeliveryCarrierService/1",
            })
        assert result.ok
        assert result.data["deleted_id"] == \
            "gid://shopify/DeliveryCarrierService/1"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.carrier_services import (
            ShopifyCarrierServicesAdapter,
        )
        assert ShopifyCarrierServicesAdapter._normalise_service({}) == {}


# ── ShopifyFulfillmentServicesAdapter ─────────────────────


class TestShopifyFulfillmentServicesAdapter:
    def test_metadata(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter()
        assert a.name == "shopify_fulfillment_services"
        for cap in (
            Capability.SHOPIFY_LIST_FULFILLMENT_SERVICES,
            Capability.SHOPIFY_CREATE_FULFILLMENT_SERVICE,
            Capability.SHOPIFY_UPDATE_FULFILLMENT_SERVICE,
            Capability.SHOPIFY_DELETE_FULFILLMENT_SERVICE,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_create_requires_name(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_create_variables({"callback_url": "https://x.com/q"})

    def test_create_requires_callback_url(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_create_variables({"name": "ShopAI"})

    def test_callback_url_must_be_http(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_create_variables({
                "name": "ShopAI", "callback_url": "ftp://x.com/q",
            })

    def test_create_defaults_fulfillment_orders_opt_in_true(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        out = a._build_create_variables({
            "name": "ShopAI", "callback_url": "https://x.com/q",
        })
        assert out["fulfillmentOrdersOptIn"] is True

    def test_create_full_shape(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        out = a._build_create_variables({
            "name": "ShopAI Routing",
            "callback_url": "https://fulfill.shopai.dev/cb",
            "tracks_inventory": True,
            "permits_sku_sharing": True,
            "tracking_support": True,
            "fulfillment_orders_opt_in": True,
        })
        assert out["name"] == "ShopAI Routing"
        assert out["callbackUrl"] == "https://fulfill.shopai.dev/cb"
        assert out["inventoryManagement"] is True
        assert out["permitsSkuSharing"] is True
        assert out["trackingSupport"] is True
        assert out["fulfillmentOrdersOptIn"] is True

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "shop": {
                "fulfillmentServices": [
                    {
                        "id": "gid://shopify/FulfillmentService/1",
                        "serviceName": "Manual",
                        "callbackUrl": "",
                        "inventoryManagement": False,
                        "permitsSkuSharing": False,
                        "trackingSupport": False,
                        "type": "MANUAL",
                        "fulfillmentOrdersOptIn": True,
                        "location": {
                            "id": "gid://shopify/Location/100",
                            "name": "Shop location",
                        },
                    },
                    {
                        "id": "gid://shopify/FulfillmentService/2",
                        "serviceName": "ShopAI Routing",
                        "callbackUrl": "https://fulfill.shopai.dev/cb",
                        "inventoryManagement": True,
                        "permitsSkuSharing": True,
                        "trackingSupport": True,
                        "type": "THIRD_PARTY",
                        "fulfillmentOrdersOptIn": True,
                        "location": None,
                    },
                ],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_FULFILLMENT_SERVICES, {},
            )
        assert result.ok
        assert result.data["count"] == 2
        names = {s["name"] for s in result.data["fulfillment_services"]}
        assert names == {"Manual", "ShopAI Routing"}
        third_party = [
            s for s in result.data["fulfillment_services"]
            if s["type"] == "THIRD_PARTY"
        ][0]
        assert third_party["inventory_management"] is True

    def test_list_handles_missing_shop(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"shop": None}):
            result = a.execute(
                Capability.SHOPIFY_LIST_FULFILLMENT_SERVICES, {},
            )
        assert result.ok
        assert result.data["count"] == 0

    # ── Create ───────────────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"fulfillmentServiceCreate": {
                "fulfillmentService": {
                    "id": "gid://shopify/FulfillmentService/new",
                    "serviceName": v["name"],
                    "callbackUrl": v["callbackUrl"],
                    "fulfillmentOrdersOptIn": v["fulfillmentOrdersOptIn"],
                    "type": "THIRD_PARTY",
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_FULFILLMENT_SERVICE,
                {
                    "name": "ShopAI",
                    "callback_url": "https://fulfill.shopai.dev/cb",
                    "tracks_inventory": True,
                },
            )
        assert result.ok
        assert captured["name"] == "ShopAI"
        assert captured["fulfillmentOrdersOptIn"] is True
        assert captured["inventoryManagement"] is True

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "fulfillmentServiceCreate": {
                "fulfillmentService": None,
                "userErrors": [{"field": ["name"],
                                "message": "is taken"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_FULFILLMENT_SERVICE,
                {"name": "dup", "callback_url": "https://x.com/q"},
            )
        assert not result.ok

    # ── Update ───────────────────────────────────

    def test_update_requires_id(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_FULFILLMENT_SERVICE, {
            "name": "x",
        })
        assert not result.ok

    def test_update_no_fields_rejected(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_FULFILLMENT_SERVICE, {
            "id": "gid://shopify/FulfillmentService/1",
        })
        assert not result.ok

    def test_update_happy_path(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"fulfillmentServiceUpdate": {
                "fulfillmentService": {
                    "id": v["id"],
                    "serviceName": v.get("name", "old"),
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_FULFILLMENT_SERVICE,
                {
                    "id": "gid://shopify/FulfillmentService/1",
                    "name": "Renamed",
                    "tracking_support": True,
                },
            )
        assert result.ok
        assert captured["id"] == "gid://shopify/FulfillmentService/1"
        assert captured["name"] == "Renamed"
        assert captured["trackingSupport"] is True

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_FULFILLMENT_SERVICE, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        a = ShopifyFulfillmentServicesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "fulfillmentServiceDelete": {
                "deletedId": "gid://shopify/FulfillmentService/1",
                "userErrors": [],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_DELETE_FULFILLMENT_SERVICE,
                {"id": "gid://shopify/FulfillmentService/1"},
            )
        assert result.ok
        assert result.data["deleted_id"] == \
            "gid://shopify/FulfillmentService/1"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.fulfillment_services import (
            ShopifyFulfillmentServicesAdapter,
        )
        assert ShopifyFulfillmentServicesAdapter._normalise_service({}) == {}


# ── ShopifyDiscountAutomaticAdapter ───────────────────────


class TestShopifyDiscountAutomaticAdapter:
    def test_metadata(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter()
        assert a.name == "shopify_discount_automatic"
        for cap in (
            Capability.SHOPIFY_LIST_AUTOMATIC_DISCOUNTS,
            Capability.SHOPIFY_CREATE_AUTOMATIC_DISCOUNT,
            Capability.SHOPIFY_DELETE_AUTOMATIC_DISCOUNT,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_create_requires_title(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_basic_input({
                "starts_at": "2026-04-26T00:00:00Z",
                "percentage": 15,
            })

    def test_create_requires_starts_at(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_basic_input({"title": "x", "percentage": 15})

    def test_create_requires_percentage_or_amount(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_basic_input({
                "title": "x", "starts_at": "2026-04-26T00:00:00Z",
            })

    def test_create_percentage_range_enforced(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_basic_input({
                "title": "x", "starts_at": "2026-04-26T00:00:00Z",
                "percentage": 150,
            })

    def test_create_percentage_converted_to_fraction(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        out = a._build_basic_input({
            "title": "Site-wide 15%",
            "starts_at": "2026-04-26T00:00:00Z",
            "percentage": 15,
        })
        # ShopAI takes 0-100, Shopify wants 0-1.
        assert out["customerGets"]["value"]["percentage"] == 0.15
        assert out["customerGets"]["items"]["all"] is True

    def test_create_amount_off(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        out = a._build_basic_input({
            "title": "$10 off",
            "starts_at": "2026-04-26T00:00:00Z",
            "amount_off": 10,
        })
        amount = out["customerGets"]["value"]["discountAmount"]
        assert amount["amount"] == 10.0
        assert amount["appliesOnEachItem"] is False

    def test_create_amount_must_be_positive(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_basic_input({
                "title": "x", "starts_at": "2026-04-26T00:00:00Z",
                "amount_off": 0,
            })

    def test_create_minimum_subtotal_passed(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        out = a._build_basic_input({
            "title": "x", "starts_at": "2026-04-26T00:00:00Z",
            "percentage": 10,
            "minimum_subtotal": 50,
        })
        sub = out["minimumRequirement"]["subtotal"]
        assert sub["greaterThanOrEqualToSubtotal"] == 50.0

    def test_create_minimum_quantity_passed(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        out = a._build_basic_input({
            "title": "x", "starts_at": "2026-04-26T00:00:00Z",
            "percentage": 10,
            "minimum_quantity": 3,
        })
        # Shopify wants the quantity as a STRING — coerced.
        qty = out["minimumRequirement"]["quantity"]
        assert qty["greaterThanOrEqualToQuantity"] == "3"

    def test_create_both_minimums_rejected(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_basic_input({
                "title": "x", "starts_at": "2026-04-26T00:00:00Z",
                "percentage": 10,
                "minimum_subtotal": 50, "minimum_quantity": 3,
            })

    def test_create_invalid_applies_to_rejected(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_basic_input({
                "title": "x", "starts_at": "2026-04-26T00:00:00Z",
                "percentage": 10, "applies_to": "PRODUCTS",
            })

    # ── List ─────────────────────────────────────

    def test_list_happy_path_basic(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "automaticDiscountNodes": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/DiscountAutomaticNode/1",
                    "automaticDiscount": {
                        "__typename": "DiscountAutomaticBasic",
                        "title": "15% off everything",
                        "summary": "15% off",
                        "status": "ACTIVE",
                        "startsAt": "2026-04-26T00:00:00Z",
                        "endsAt": "2026-04-30T23:59:59Z",
                        "asyncUsageCount": 42,
                        "minimumRequirement": {
                            "__typename": "DiscountMinimumSubtotal",
                            "greaterThanOrEqualToSubtotal": {
                                "amount": "50.00",
                                "currencyCode": "USD",
                            },
                        },
                        "customerGets": {
                            "value": {
                                "__typename": "DiscountPercentage",
                                "percentage": 0.15,
                            },
                            "items": {
                                "__typename": "AllDiscountItems",
                                "allItems": True,
                            },
                        },
                    },
                }}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_AUTOMATIC_DISCOUNTS, {},
            )
        assert result.ok
        d = result.data["discounts"][0]
        assert d["kind"] == "DiscountAutomaticBasic"
        assert d["title"] == "15% off everything"
        assert d["status"] == "ACTIVE"
        assert d["percentage"] == 15.0
        assert d["minimum_subtotal"] == "50.00"
        assert d["usage_count"] == 42

    def test_list_handles_bxgy_kind(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "automaticDiscountNodes": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/DiscountAutomaticNode/2",
                    "automaticDiscount": {
                        "__typename": "DiscountAutomaticBxgy",
                        "title": "Buy 3 get 1 free",
                        "status": "ACTIVE",
                        "startsAt": "2026-04-26T00:00:00Z",
                    },
                }}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_AUTOMATIC_DISCOUNTS, {},
            )
        assert result.ok
        d = result.data["discounts"][0]
        assert d["kind"] == "DiscountAutomaticBxgy"
        # Bxgy doesn't carry a flat percentage / amount; the keys
        # default to absent.
        assert "percentage" not in d
        assert "amount_off" not in d

    def test_list_invalid_sort_key_rejected(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_AUTOMATIC_DISCOUNTS, {"sort_key": "BAD"},
        )
        assert not result.ok

    # ── Create ───────────────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"discountAutomaticBasicCreate": {
                "automaticDiscountNode": {
                    "id": "gid://shopify/DiscountAutomaticNode/new",
                    "automaticDiscount": {
                        "__typename": "DiscountAutomaticBasic",
                        "title": v["automaticBasicDiscount"]["title"],
                        "status": "ACTIVE",
                        "startsAt": v["automaticBasicDiscount"]["startsAt"],
                    },
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_AUTOMATIC_DISCOUNT,
                {
                    "title": "Site-wide 15%",
                    "starts_at": "2026-04-26T00:00:00Z",
                    "ends_at": "2026-04-30T23:59:59Z",
                    "percentage": 15,
                    "minimum_subtotal": 50,
                },
            )
        assert result.ok
        # Pattern A: variable name "automaticBasicDiscount" matches input type.
        inp = captured["automaticBasicDiscount"]
        assert inp["title"] == "Site-wide 15%"
        assert inp["startsAt"] == "2026-04-26T00:00:00Z"
        assert inp["customerGets"]["value"]["percentage"] == 0.15
        assert result.data["discount"]["id"].endswith("/new")

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "discountAutomaticBasicCreate": {
                "automaticDiscountNode": None,
                "userErrors": [{"field": ["title"], "message": "is taken",
                                "code": "TAKEN"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_AUTOMATIC_DISCOUNT,
                {"title": "dup", "starts_at": "2026-04-26T00:00:00Z",
                 "percentage": 10},
            )
        assert not result.ok

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_AUTOMATIC_DISCOUNT, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        a = ShopifyDiscountAutomaticAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "discountAutomaticDelete": {
                "deletedAutomaticDiscountId": (
                    "gid://shopify/DiscountAutomaticNode/1"
                ),
                "userErrors": [],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_DELETE_AUTOMATIC_DISCOUNT,
                {"id": "gid://shopify/DiscountAutomaticNode/1"},
            )
        assert result.ok
        assert result.data["deleted_id"] == \
            "gid://shopify/DiscountAutomaticNode/1"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.discount_automatic import (
            ShopifyDiscountAutomaticAdapter,
        )
        assert ShopifyDiscountAutomaticAdapter._normalise_discount({}) == {}
        assert ShopifyDiscountAutomaticAdapter._normalise_discount(None) == {}


# ── ShopifyMetaobjectDefinitionsAdapter ───────────────────


class TestShopifyMetaobjectDefinitionsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter()
        assert a.name == "shopify_metaobject_definitions"
        for cap in (
            Capability.SHOPIFY_LIST_METAOBJECT_DEFINITIONS,
            Capability.SHOPIFY_GET_METAOBJECT_DEFINITION,
            Capability.SHOPIFY_CREATE_METAOBJECT_DEFINITION,
            Capability.SHOPIFY_DELETE_METAOBJECT_DEFINITION,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_create_requires_type(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_create_input({
                "name": "Recipe",
                "field_definitions": [
                    {"key": "title", "type": "single_line_text_field"},
                ],
            })

    def test_create_requires_field_definitions(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_create_input({"type": "recipe", "name": "Recipe"})

    def test_field_definition_requires_key(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_field_definition(
                {"type": "single_line_text_field"}, 0,
            )

    def test_field_definition_requires_type(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_field_definition({"key": "title"}, 0)

    def test_create_full_shape(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        out = a._build_create_input({
            "type": "recipe",
            "name": "Recipe",
            "description": "Cookable recipes",
            "display_name_key": "title",
            "field_definitions": [
                {"key": "title", "name": "Title",
                 "type": "single_line_text_field", "required": True},
                {"key": "ingredients", "name": "Ingredients",
                 "type": "list.single_line_text_field"},
                {"key": "cook_time_minutes", "name": "Cook time",
                 "type": "number_integer",
                 "validations": [
                    {"name": "min", "value": 0},
                 ]},
            ],
        })
        assert out["type"] == "recipe"
        assert out["name"] == "Recipe"
        assert out["displayNameKey"] == "title"
        assert len(out["fieldDefinitions"]) == 3
        assert out["fieldDefinitions"][0]["required"] is True
        assert out["fieldDefinitions"][2]["validations"][0]["value"] == "0"

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "metaobjectDefinitions": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/MetaobjectDefinition/1",
                    "name": "Recipe",
                    "type": "recipe",
                    "description": "Cookable recipes",
                    "displayNameKey": "title",
                    "fieldDefinitions": [
                        {
                            "key": "title", "name": "Title",
                            "required": True,
                            "type": {"name": "single_line_text_field",
                                     "category": "TEXT"},
                            "validations": [],
                        },
                    ],
                    "metaobjectsCount": {"count": 12},
                }}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_METAOBJECT_DEFINITIONS, {},
            )
        assert result.ok
        d = result.data["definitions"][0]
        assert d["type"] == "recipe"
        assert d["name"] == "Recipe"
        assert len(d["field_definitions"]) == 1
        assert d["field_definitions"][0]["required"] is True
        assert d["field_definitions"][0]["type"] == "single_line_text_field"
        assert d["metaobjects_count"] == 12

    def test_list_clamps_limit(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"metaobjectDefinitions": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_METAOBJECT_DEFINITIONS,
                {"limit": 9999},
            )
        assert captured["first"] == 250

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_METAOBJECT_DEFINITION, {})
        assert not result.ok

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "metaobjectDefinition": None,
        }):
            result = a.execute(Capability.SHOPIFY_GET_METAOBJECT_DEFINITION, {
                "id": "gid://shopify/MetaobjectDefinition/999",
            })
        assert result.ok
        assert result.data["found"] is False

    # ── Create ───────────────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"metaobjectDefinitionCreate": {
                "metaobjectDefinition": {
                    "id": "gid://shopify/MetaobjectDefinition/new",
                    "name": v["definition"].get("name", ""),
                    "type": v["definition"]["type"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_METAOBJECT_DEFINITION,
                {
                    "type": "recipe",
                    "name": "Recipe",
                    "field_definitions": [
                        {"key": "title", "name": "Title",
                         "type": "single_line_text_field"},
                    ],
                },
            )
        assert result.ok
        assert captured["definition"]["type"] == "recipe"
        assert captured["definition"]["fieldDefinitions"][0]["key"] == "title"

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "metaobjectDefinitionCreate": {
                "metaobjectDefinition": None,
                "userErrors": [{"field": ["type"], "message": "is taken",
                                "code": "TAKEN"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_METAOBJECT_DEFINITION,
                {
                    "type": "dup", "name": "Dup",
                    "field_definitions": [
                        {"key": "x", "type": "single_line_text_field"},
                    ],
                },
            )
        assert not result.ok

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_DELETE_METAOBJECT_DEFINITION, {},
        )
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        a = ShopifyMetaobjectDefinitionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "metaobjectDefinitionDelete": {
                "deletedId": "gid://shopify/MetaobjectDefinition/1",
                "userErrors": [],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_DELETE_METAOBJECT_DEFINITION,
                {"id": "gid://shopify/MetaobjectDefinition/1"},
            )
        assert result.ok
        assert result.data["deleted_id"] == \
            "gid://shopify/MetaobjectDefinition/1"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.metaobject_definitions import (
            ShopifyMetaobjectDefinitionsAdapter,
        )
        assert ShopifyMetaobjectDefinitionsAdapter._normalise_definition({}) == {}


# ── ShopifyScriptTagsAdapter ──────────────────────────────


class TestShopifyScriptTagsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter()
        assert a.name == "shopify_script_tags"
        for cap in (
            Capability.SHOPIFY_LIST_SCRIPT_TAGS,
            Capability.SHOPIFY_CREATE_SCRIPT_TAG,
            Capability.SHOPIFY_UPDATE_SCRIPT_TAG,
            Capability.SHOPIFY_DELETE_SCRIPT_TAG,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_create_requires_src(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input({}, for_update=False)

    def test_create_src_must_be_https(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input(
                {"src": "http://insecure.example/x.js"}, for_update=False,
            )

    def test_create_invalid_display_scope_rejected(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input(
                {"src": "https://x.com/a.js", "display_scope": "ADMIN"},
                for_update=False,
            )

    def test_create_full_shape(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        out = a._build_input({
            "src": "https://cdn.shopai.dev/exit-intent.js",
            "display_scope": "online_store",
            "cache": True,
        }, for_update=False)
        assert out["src"] == "https://cdn.shopai.dev/exit-intent.js"
        assert out["displayScope"] == "ONLINE_STORE"
        assert out["cache"] is True

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "scriptTags": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/ScriptTag/1",
                    "src": "https://cdn.shopai.dev/x.js",
                    "displayScope": "ONLINE_STORE",
                    "cache": True,
                }}],
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_SCRIPT_TAGS, {})
        assert result.ok
        t = result.data["script_tags"][0]
        assert t["src"] == "https://cdn.shopai.dev/x.js"
        assert t["display_scope"] == "ONLINE_STORE"
        assert t["cache"] is True

    def test_list_passes_src_filter(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"scriptTags": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_SCRIPT_TAGS, {
                "src": "https://cdn.shopai.dev/x.js",
            })
        assert captured["src"] == "https://cdn.shopai.dev/x.js"

    # ── Create ───────────────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"scriptTagCreate": {
                "scriptTag": {
                    "id": "gid://shopify/ScriptTag/new",
                    "src": v["input"]["src"],
                    "displayScope": v["input"].get("displayScope", "ONLINE_STORE"),
                    "cache": v["input"].get("cache", False),
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_SCRIPT_TAG, {
                "src": "https://cdn.shopai.dev/x.js",
                "display_scope": "ALL",
            })
        assert result.ok
        assert captured["input"]["displayScope"] == "ALL"
        assert result.data["script_tag"]["src"] == \
            "https://cdn.shopai.dev/x.js"

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"scriptTagCreate": {
            "scriptTag": None,
            "userErrors": [{"field": ["src"], "message": "is taken"}],
        }}):
            result = a.execute(Capability.SHOPIFY_CREATE_SCRIPT_TAG, {
                "src": "https://cdn.shopai.dev/x.js",
            })
        assert not result.ok

    # ── Update ───────────────────────────────────

    def test_update_requires_id(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_SCRIPT_TAG, {
            "src": "https://x.com/a.js",
        })
        assert not result.ok

    def test_update_no_fields_rejected(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_SCRIPT_TAG, {
            "id": "gid://shopify/ScriptTag/1",
        })
        assert not result.ok

    def test_update_happy_path(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"scriptTagUpdate": {
                "scriptTag": {
                    "id": v["id"],
                    "src": v["input"].get("src", "old"),
                    "displayScope": v["input"].get("displayScope", "ONLINE_STORE"),
                    "cache": False,
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_SCRIPT_TAG, {
                "id": "gid://shopify/ScriptTag/1",
                "src": "https://cdn.shopai.dev/v2.js",
            })
        assert result.ok
        assert captured["id"] == "gid://shopify/ScriptTag/1"
        assert captured["input"]["src"] == "https://cdn.shopai.dev/v2.js"

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_SCRIPT_TAG, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        a = ShopifyScriptTagsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"scriptTagDelete": {
            "deletedScriptTagId": "gid://shopify/ScriptTag/1",
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_DELETE_SCRIPT_TAG, {
                "id": "gid://shopify/ScriptTag/1",
            })
        assert result.ok
        assert result.data["deleted_id"] == "gid://shopify/ScriptTag/1"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.script_tags import ShopifyScriptTagsAdapter
        assert ShopifyScriptTagsAdapter._normalise_tag({}) == {}


# ── ShopifyOrderTransactionsAdapter ───────────────────────


class TestShopifyOrderTransactionsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.order_transactions import (
            ShopifyOrderTransactionsAdapter,
        )
        a = ShopifyOrderTransactionsAdapter()
        assert a.name == "shopify_order_transactions"
        for cap in (
            Capability.SHOPIFY_LIST_ORDER_TRANSACTIONS,
            Capability.SHOPIFY_GET_TRANSACTION,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.order_transactions import (
            ShopifyOrderTransactionsAdapter,
        )
        a = ShopifyOrderTransactionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_requires_order_id(self):
        from core.adapters.shopify.order_transactions import (
            ShopifyOrderTransactionsAdapter,
        )
        a = ShopifyOrderTransactionsAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_ORDER_TRANSACTIONS, {},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_list_happy_path(self):
        from core.adapters.shopify.order_transactions import (
            ShopifyOrderTransactionsAdapter,
        )
        a = ShopifyOrderTransactionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "order": {
                "id": "gid://shopify/Order/1",
                "name": "#1001",
                "transactions": [
                    {
                        "id": "gid://shopify/OrderTransaction/t1",
                        "kind": "AUTHORIZATION",
                        "status": "SUCCESS",
                        "gateway": "stripe",
                        "test": False,
                        "authorizationCode": "auth-abc-123",
                        "processedAt": "2026-04-25T10:00:00Z",
                        "amountSet": {
                            "shopMoney": {"amount": "100.00",
                                           "currencyCode": "USD"},
                        },
                        "fees": [],
                    },
                    {
                        "id": "gid://shopify/OrderTransaction/t2",
                        "kind": "CAPTURE",
                        "status": "SUCCESS",
                        "gateway": "stripe",
                        "parentTransaction": {
                            "id": "gid://shopify/OrderTransaction/t1",
                        },
                        "amountSet": {
                            "shopMoney": {"amount": "100.00",
                                           "currencyCode": "USD"},
                        },
                        "fees": [{
                            "type": "PROCESSING",
                            "amount": {"amount": "3.20",
                                       "currencyCode": "USD"},
                            "rate": "0.029",
                            "rateName": "stripe-online",
                            "flatFee": {"amount": "0.30",
                                        "currencyCode": "USD"},
                            "flatFeeName": "stripe-flat",
                        }],
                    },
                ],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_ORDER_TRANSACTIONS,
                {"order_id": "gid://shopify/Order/1"},
            )
        assert result.ok
        assert result.data["count"] == 2
        kinds = [t["kind"] for t in result.data["transactions"]]
        assert kinds == ["AUTHORIZATION", "CAPTURE"]
        capture = result.data["transactions"][1]
        assert capture["amount"] == "100.00"
        assert capture["currency_code"] == "USD"
        assert capture["parent_transaction_id"] == \
            "gid://shopify/OrderTransaction/t1"
        assert len(capture["fees"]) == 1
        assert capture["fees"][0]["amount"] == "3.20"
        assert capture["fees"][0]["rate"] == 0.029

    def test_list_clamps_limit(self):
        from core.adapters.shopify.order_transactions import (
            ShopifyOrderTransactionsAdapter,
        )
        a = ShopifyOrderTransactionsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"order": None}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_ORDER_TRANSACTIONS,
                {"order_id": "gid://shopify/Order/1", "limit": 9999},
            )
        assert captured["first"] == 250

    def test_list_passes_capturable_filter(self):
        from core.adapters.shopify.order_transactions import (
            ShopifyOrderTransactionsAdapter,
        )
        a = ShopifyOrderTransactionsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"order": None}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_ORDER_TRANSACTIONS,
                {
                    "order_id": "gid://shopify/Order/1",
                    "capturable": True,
                },
            )
        assert captured["capturable"] is True

    def test_list_handles_missing_order(self):
        from core.adapters.shopify.order_transactions import (
            ShopifyOrderTransactionsAdapter,
        )
        a = ShopifyOrderTransactionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"order": None}):
            result = a.execute(
                Capability.SHOPIFY_LIST_ORDER_TRANSACTIONS,
                {"order_id": "gid://shopify/Order/missing"},
            )
        assert result.ok
        assert result.data["order_found"] is False
        assert result.data["count"] == 0

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.order_transactions import (
            ShopifyOrderTransactionsAdapter,
        )
        a = ShopifyOrderTransactionsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_TRANSACTION, {})
        assert not result.ok

    def test_get_happy_path_with_receipt(self):
        from core.adapters.shopify.order_transactions import (
            ShopifyOrderTransactionsAdapter,
        )
        a = ShopifyOrderTransactionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "node": {
                "id": "gid://shopify/OrderTransaction/t1",
                "kind": "REFUND",
                "status": "SUCCESS",
                "gateway": "stripe",
                "amountSet": {
                    "shopMoney": {"amount": "20.00",
                                   "currencyCode": "USD"},
                },
                "receiptJson": '{"id":"re_xyz","object":"refund"}',
                "fees": [],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_GET_TRANSACTION,
                {"id": "gid://shopify/OrderTransaction/t1"},
            )
        assert result.ok
        t = result.data["transaction"]
        assert t["kind"] == "REFUND"
        assert t["amount"] == "20.00"
        # receipt_json passed through verbatim — analytics consumers
        # parse it themselves rather than the adapter making schema calls.
        assert t["receipt_json"] == '{"id":"re_xyz","object":"refund"}'

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.order_transactions import (
            ShopifyOrderTransactionsAdapter,
        )
        a = ShopifyOrderTransactionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"node": None}):
            result = a.execute(
                Capability.SHOPIFY_GET_TRANSACTION,
                {"id": "gid://shopify/OrderTransaction/999"},
            )
        assert result.ok
        assert result.data["found"] is False

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.order_transactions import (
            ShopifyOrderTransactionsAdapter,
        )
        assert ShopifyOrderTransactionsAdapter._normalise_transaction(
            {},
        ) == {}
        assert ShopifyOrderTransactionsAdapter._normalise_fee(None) == {}


# ── ShopifyPaymentTermsAdapter ────────────────────────────


class TestShopifyPaymentTermsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter()
        assert a.name == "shopify_payment_terms"
        for cap in (
            Capability.SHOPIFY_LIST_PAYMENT_TERMS_TEMPLATES,
            Capability.SHOPIFY_CREATE_PAYMENT_TERMS,
            Capability.SHOPIFY_UPDATE_PAYMENT_TERMS,
            Capability.SHOPIFY_DELETE_PAYMENT_TERMS,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List templates ───────────────────────────

    def test_list_templates_happy_path(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "paymentTermsTemplates": [
                {
                    "id": "gid://shopify/PaymentTermsTemplate/1",
                    "name": "Net 30",
                    "translatedName": "Net 30",
                    "description": "Pay in 30 days",
                    "paymentTermsType": "NET",
                    "dueInDays": 30,
                },
                {
                    "id": "gid://shopify/PaymentTermsTemplate/2",
                    "name": "Due on receipt",
                    "translatedName": "Due on receipt",
                    "paymentTermsType": "RECEIPT",
                    "dueInDays": 0,
                },
            ]
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_PAYMENT_TERMS_TEMPLATES, {},
            )
        assert result.ok
        assert result.data["count"] == 2
        names = {t["name"] for t in result.data["templates"]}
        assert names == {"Net 30", "Due on receipt"}

    def test_list_templates_handles_empty(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "paymentTermsTemplates": [],
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_PAYMENT_TERMS_TEMPLATES, {},
            )
        assert result.ok
        assert result.data["count"] == 0

    # ── Input builder ────────────────────────────

    def test_create_requires_reference_id(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_CREATE_PAYMENT_TERMS, {
            "payment_terms_template_id": "gid://shopify/PaymentTermsTemplate/1",
        })
        assert not result.ok

    def test_create_attributes_require_template_id(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_create_attributes({})

    def test_schedules_must_be_list(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_schedules("not-a-list")

    def test_schedules_entry_needs_due_or_issued(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_schedules([{}])

    def test_schedules_happy_path(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        out = a._build_schedules([
            {"due_at": "2026-05-30T00:00:00Z"},
            {"issued_at": "2026-04-26T00:00:00Z",
             "due_at": "2026-06-26T00:00:00Z"},
        ])
        assert out[0]["dueAt"] == "2026-05-30T00:00:00Z"
        assert out[1]["issuedAt"] == "2026-04-26T00:00:00Z"

    # ── Create ───────────────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"paymentTermsCreate": {
                "paymentTerms": {
                    "id": "gid://shopify/PaymentTerms/new",
                    "paymentTermsName": "Net 30",
                    "paymentTermsType": "NET",
                    "dueInDays": 30,
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_CREATE_PAYMENT_TERMS, {
                "reference_id": "gid://shopify/Order/1",
                "payment_terms_template_id": (
                    "gid://shopify/PaymentTermsTemplate/1"
                ),
                "schedules": [{"due_at": "2026-05-30T00:00:00Z"}],
            })
        assert result.ok
        assert captured["referenceId"] == "gid://shopify/Order/1"
        attrs = captured["paymentTermsAttributes"]
        assert attrs["paymentTermsTemplateId"] == \
            "gid://shopify/PaymentTermsTemplate/1"
        assert attrs["paymentSchedules"][0]["dueAt"] == \
            "2026-05-30T00:00:00Z"

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"paymentTermsCreate": {
            "paymentTerms": None,
            "userErrors": [{"field": ["paymentTermsTemplateId"],
                            "message": "not found", "code": "INVALID"}],
        }}):
            result = a.execute(Capability.SHOPIFY_CREATE_PAYMENT_TERMS, {
                "reference_id": "gid://shopify/Order/1",
                "payment_terms_template_id": (
                    "gid://shopify/PaymentTermsTemplate/missing"
                ),
            })
        assert not result.ok

    # ── Update ───────────────────────────────────

    def test_update_requires_id(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_PAYMENT_TERMS, {
            "payment_terms_template_id": (
                "gid://shopify/PaymentTermsTemplate/1"
            ),
        })
        assert not result.ok

    def test_update_no_fields_rejected(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPDATE_PAYMENT_TERMS, {
            "id": "gid://shopify/PaymentTerms/1",
        })
        assert not result.ok

    def test_update_happy_path(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"paymentTermsUpdate": {
                "paymentTerms": {
                    "id": v["input"]["paymentTermsId"],
                    "paymentTermsName": "Updated",
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_PAYMENT_TERMS, {
                "id": "gid://shopify/PaymentTerms/1",
                "payment_terms_template_id": (
                    "gid://shopify/PaymentTermsTemplate/2"
                ),
            })
        assert result.ok
        inp = captured["input"]
        assert inp["paymentTermsId"] == "gid://shopify/PaymentTerms/1"
        assert inp["paymentTermsTemplateId"] == \
            "gid://shopify/PaymentTermsTemplate/2"

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_PAYMENT_TERMS, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        a = ShopifyPaymentTermsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"paymentTermsDelete": {
            "deletedId": "gid://shopify/PaymentTerms/1",
            "userErrors": [],
        }}):
            result = a.execute(Capability.SHOPIFY_DELETE_PAYMENT_TERMS, {
                "id": "gid://shopify/PaymentTerms/1",
            })
        assert result.ok
        assert result.data["deleted_id"] == "gid://shopify/PaymentTerms/1"

    # ── Normaliser ───────────────────────────────

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.payment_terms import (
            ShopifyPaymentTermsAdapter,
        )
        assert ShopifyPaymentTermsAdapter._normalise_template({}) == {}
        assert ShopifyPaymentTermsAdapter._normalise_payment_terms({}) == {}
        assert ShopifyPaymentTermsAdapter._normalise_schedule(None) == {}


# ── ShopifyMarketWebPresencesAdapter ──────────────────────


class TestShopifyMarketWebPresencesAdapter:
    def test_metadata(self):
        from core.adapters.shopify.market_web_presences import (
            ShopifyMarketWebPresencesAdapter,
        )
        a = ShopifyMarketWebPresencesAdapter()
        assert a.name == "shopify_market_web_presences"
        for cap in (
            Capability.SHOPIFY_LIST_MARKET_WEB_PRESENCES,
            Capability.SHOPIFY_GET_MARKET_WEB_PRESENCE,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.market_web_presences import (
            ShopifyMarketWebPresencesAdapter,
        )
        a = ShopifyMarketWebPresencesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_happy_path_with_presence(self):
        from core.adapters.shopify.market_web_presences import (
            ShopifyMarketWebPresencesAdapter,
        )
        a = ShopifyMarketWebPresencesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "markets": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/Market/1",
                    "name": "Primary Market",
                    "primary": True,
                    "enabled": True,
                    "webPresence": {
                        "id": "gid://shopify/MarketWebPresence/1",
                        "defaultLocale": {"locale": "en", "name": "English",
                                          "primary": True, "published": True},
                        "alternateLocales": [
                            {"locale": "fr", "name": "French",
                             "primary": False, "published": True},
                            {"locale": "de", "name": "German",
                             "primary": False, "published": True},
                        ],
                        "subfolderSuffix": "",
                        "domain": {
                            "id": "gid://shopify/Domain/1",
                            "host": "deguar.myshopify.com",
                            "url": "https://deguar.myshopify.com",
                            "sslEnabled": True,
                        },
                        "rootUrls": [
                            {"locale": "en",
                             "url": "https://deguar.myshopify.com/"},
                            {"locale": "fr",
                             "url": "https://deguar.myshopify.com/fr"},
                        ],
                    },
                }}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_MARKET_WEB_PRESENCES, {},
            )
        assert result.ok
        p = result.data["presences"][0]
        assert p["has_presence"] is True
        assert p["market_name"] == "Primary Market"
        assert p["market_primary"] is True
        assert p["default_locale"] == "en"
        assert p["alternate_locales"] == ["fr", "de"]
        assert p["domain_host"] == "deguar.myshopify.com"
        assert len(p["root_urls"]) == 2

    def test_list_marks_market_without_presence(self):
        from core.adapters.shopify.market_web_presences import (
            ShopifyMarketWebPresencesAdapter,
        )
        a = ShopifyMarketWebPresencesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "markets": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "id": "gid://shopify/Market/2",
                    "name": "Future France",
                    "primary": False,
                    "enabled": True,
                    "webPresence": None,
                }}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_MARKET_WEB_PRESENCES, {},
            )
        assert result.ok
        p = result.data["presences"][0]
        assert p["has_presence"] is False
        assert p["market_name"] == "Future France"

    def test_list_clamps_limit(self):
        from core.adapters.shopify.market_web_presences import (
            ShopifyMarketWebPresencesAdapter,
        )
        a = ShopifyMarketWebPresencesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"markets": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_MARKET_WEB_PRESENCES,
                {"limit": 9999},
            )
        assert captured["first"] == 250

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.market_web_presences import (
            ShopifyMarketWebPresencesAdapter,
        )
        a = ShopifyMarketWebPresencesAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_MARKET_WEB_PRESENCE, {})
        assert not result.ok

    def test_get_happy_path(self):
        from core.adapters.shopify.market_web_presences import (
            ShopifyMarketWebPresencesAdapter,
        )
        a = ShopifyMarketWebPresencesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"node": {
            "id": "gid://shopify/MarketWebPresence/1",
            "defaultLocale": {"locale": "en"},
            "alternateLocales": [],
            "subfolderSuffix": "",
            "domain": {
                "host": "shop.example",
                "url": "https://shop.example",
                "sslEnabled": True,
            },
            "rootUrls": [],
            "market": {
                "id": "gid://shopify/Market/1",
                "name": "Primary",
                "primary": True,
                "enabled": True,
            },
        }}):
            result = a.execute(
                Capability.SHOPIFY_GET_MARKET_WEB_PRESENCE,
                {"id": "gid://shopify/MarketWebPresence/1"},
            )
        assert result.ok
        p = result.data["presence"]
        assert p["domain_host"] == "shop.example"
        assert p["market_primary"] is True

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.market_web_presences import (
            ShopifyMarketWebPresencesAdapter,
        )
        a = ShopifyMarketWebPresencesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"node": None}):
            result = a.execute(
                Capability.SHOPIFY_GET_MARKET_WEB_PRESENCE,
                {"id": "gid://shopify/MarketWebPresence/999"},
            )
        assert result.ok
        assert result.data["found"] is False

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.market_web_presences import (
            ShopifyMarketWebPresencesAdapter,
        )
        assert ShopifyMarketWebPresencesAdapter._normalise_presence({}) == {}
        assert ShopifyMarketWebPresencesAdapter._normalise_presence(None) == {}


# ── ShopifyDraftOrderInvoiceSendAdapter ───────────────────


class TestShopifyDraftOrderInvoiceSendAdapter:
    def test_metadata(self):
        from core.adapters.shopify.draft_order_invoice import (
            ShopifyDraftOrderInvoiceSendAdapter,
        )
        a = ShopifyDraftOrderInvoiceSendAdapter()
        assert a.name == "shopify_draft_order_invoice"
        for cap in (
            Capability.SHOPIFY_PREVIEW_DRAFT_ORDER_INVOICE,
            Capability.SHOPIFY_SEND_DRAFT_ORDER_INVOICE,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.draft_order_invoice import (
            ShopifyDraftOrderInvoiceSendAdapter,
        )
        a = ShopifyDraftOrderInvoiceSendAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input ────────────────────────────────────

    def test_preview_requires_draft_order_id(self):
        from core.adapters.shopify.draft_order_invoice import (
            ShopifyDraftOrderInvoiceSendAdapter,
        )
        a = ShopifyDraftOrderInvoiceSendAdapter(
            shop_url="s", access_token="t",
        )
        result = a.execute(
            Capability.SHOPIFY_PREVIEW_DRAFT_ORDER_INVOICE, {},
        )
        assert not result.ok

    def test_send_requires_draft_order_id(self):
        from core.adapters.shopify.draft_order_invoice import (
            ShopifyDraftOrderInvoiceSendAdapter,
        )
        a = ShopifyDraftOrderInvoiceSendAdapter(
            shop_url="s", access_token="t",
        )
        result = a.execute(
            Capability.SHOPIFY_SEND_DRAFT_ORDER_INVOICE, {"to": "x@y.com"},
        )
        assert not result.ok

    def test_email_input_bcc_string_split(self):
        from core.adapters.shopify.draft_order_invoice import (
            ShopifyDraftOrderInvoiceSendAdapter,
        )
        a = ShopifyDraftOrderInvoiceSendAdapter(
            shop_url="s", access_token="t",
        )
        out = a._build_email_input({
            "to": "buyer@example.com",
            "from": "sales@example.com",
            "bcc": "x@y.com, z@y.com",
            "subject": "Quote",
            "custom_message": "Reply with questions.",
        })
        assert out["to"] == "buyer@example.com"
        assert out["from"] == "sales@example.com"
        assert out["bcc"] == ["x@y.com", "z@y.com"]
        assert out["customMessage"] == "Reply with questions."

    def test_email_input_to_must_be_string(self):
        from core.adapters.shopify.draft_order_invoice import (
            ShopifyDraftOrderInvoiceSendAdapter,
        )
        a = ShopifyDraftOrderInvoiceSendAdapter(
            shop_url="s", access_token="t",
        )
        with pytest.raises(AdapterValidationError):
            a._build_email_input({"to": 123})

    # ── Preview ──────────────────────────────────

    def test_preview_happy_path(self):
        from core.adapters.shopify.draft_order_invoice import (
            ShopifyDraftOrderInvoiceSendAdapter,
        )
        a = ShopifyDraftOrderInvoiceSendAdapter(
            shop_url="s", access_token="t",
        )
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"draftOrderInvoicePreview": {
                "previewSubject": "Your quote from ShopAI",
                "previewHtml": "<html><body>Quote</body></html>",
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_PREVIEW_DRAFT_ORDER_INVOICE,
                {
                    "draft_order_id": "gid://shopify/DraftOrder/123",
                    "to": "buyer@example.com",
                    "subject": "Your quote from ShopAI",
                },
            )
        assert result.ok
        assert result.data["subject"] == "Your quote from ShopAI"
        assert "<html>" in result.data["html"]
        # Pattern A: id is at the field level, not inside email input.
        assert captured["id"] == "gid://shopify/DraftOrder/123"
        assert captured["email"]["to"] == "buyer@example.com"
        assert captured["email"]["subject"] == "Your quote from ShopAI"

    def test_preview_works_without_email_input(self):
        from core.adapters.shopify.draft_order_invoice import (
            ShopifyDraftOrderInvoiceSendAdapter,
        )
        a = ShopifyDraftOrderInvoiceSendAdapter(
            shop_url="s", access_token="t",
        )
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"draftOrderInvoicePreview": {
                "previewSubject": "Default subject",
                "previewHtml": "<html></html>",
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_PREVIEW_DRAFT_ORDER_INVOICE,
                {"draft_order_id": "gid://shopify/DraftOrder/1"},
            )
        assert result.ok
        # Email input omitted entirely when caller didn't supply any.
        assert "email" not in captured

    def test_preview_user_errors_fail_fast(self):
        from core.adapters.shopify.draft_order_invoice import (
            ShopifyDraftOrderInvoiceSendAdapter,
        )
        a = ShopifyDraftOrderInvoiceSendAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql", return_value={
            "draftOrderInvoicePreview": {
                "previewSubject": "",
                "previewHtml": "",
                "userErrors": [{"field": ["id"], "message": "not found"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_PREVIEW_DRAFT_ORDER_INVOICE,
                {"draft_order_id": "gid://shopify/DraftOrder/missing"},
            )
        assert not result.ok

    # ── Send ─────────────────────────────────────

    def test_send_happy_path(self):
        from core.adapters.shopify.draft_order_invoice import (
            ShopifyDraftOrderInvoiceSendAdapter,
        )
        a = ShopifyDraftOrderInvoiceSendAdapter(
            shop_url="s", access_token="t",
        )
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"draftOrderInvoiceSend": {
                "draftOrder": {
                    "id": v["id"],
                    "name": "#D1",
                    "status": "OPEN",
                    "invoiceSentAt": "2026-04-26T10:00:00Z",
                    "invoiceUrl": "https://store/invoices/abc",
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_SEND_DRAFT_ORDER_INVOICE,
                {
                    "draft_order_id": "gid://shopify/DraftOrder/123",
                    "to": "buyer@example.com",
                    "bcc": ["sales@example.com"],
                },
            )
        assert result.ok
        assert result.data["draft_order_name"] == "#D1"
        assert result.data["invoice_url"] == "https://store/invoices/abc"
        assert result.data["invoice_sent_at"] == "2026-04-26T10:00:00Z"
        assert captured["email"]["bcc"] == ["sales@example.com"]

    def test_send_user_errors_fail_fast(self):
        from core.adapters.shopify.draft_order_invoice import (
            ShopifyDraftOrderInvoiceSendAdapter,
        )
        a = ShopifyDraftOrderInvoiceSendAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql", return_value={
            "draftOrderInvoiceSend": {
                "draftOrder": None,
                "userErrors": [{"field": ["email", "to"],
                                "message": "Invalid email"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_SEND_DRAFT_ORDER_INVOICE,
                {
                    "draft_order_id": "gid://shopify/DraftOrder/123",
                    "to": "not-an-email",
                },
            )
        assert not result.ok


# ── ShopifyCustomerMergeAdapter ───────────────────────────


class TestShopifyCustomerMergeAdapter:
    def test_metadata(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter()
        assert a.name == "shopify_customer_merge"
        for cap in (
            Capability.SHOPIFY_PREVIEW_CUSTOMER_MERGE,
            Capability.SHOPIFY_MERGE_CUSTOMERS,
            Capability.SHOPIFY_GET_CUSTOMER_MERGE_JOB,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input ────────────────────────────────────

    def test_preview_requires_both_customer_ids(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_PREVIEW_CUSTOMER_MERGE, {
            "customer_one_id": "gid://shopify/Customer/c1",
        })
        assert not result.ok

    def test_preview_rejects_same_customer_twice(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_PREVIEW_CUSTOMER_MERGE, {
            "customer_one_id": "gid://shopify/Customer/c1",
            "customer_two_id": "gid://shopify/Customer/c1",
        })
        assert not result.ok

    def test_override_fields_must_be_dict(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_override_fields({"override_fields": "not-a-dict"})

    def test_override_fields_camel_mapping(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        out = a._build_override_fields({"override_fields": {
            "customer_id_of_default_address": "gid://shopify/Customer/c1",
            "customer_id_of_email": "gid://shopify/Customer/c2",
            "customer_id_of_first_name": "gid://shopify/Customer/c1",
            "note": "Combined CRM dup",
            "tags": "merged-2026-q2,vip",
        }})
        assert out["customerIdOfDefaultAddress"] == \
            "gid://shopify/Customer/c1"
        assert out["customerIdOfEmail"] == "gid://shopify/Customer/c2"
        assert out["note"] == "Combined CRM dup"
        assert out["tags"] == ["merged-2026-q2", "vip"]

    def test_override_field_value_must_be_string(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_override_fields({"override_fields": {
                "customer_id_of_email": 123,
            }})

    # ── Preview ──────────────────────────────────

    def test_preview_happy_path_no_conflicts(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"customerMergePreview": {
                "customerMergeErrors": [],
                "blockingFields": None,
                "alternateFields": None,
                "defaultFields": None,
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_PREVIEW_CUSTOMER_MERGE,
                {
                    "customer_one_id": "gid://shopify/Customer/c1",
                    "customer_two_id": "gid://shopify/Customer/c2",
                },
            )
        assert result.ok
        assert captured["customerOneId"] == "gid://shopify/Customer/c1"
        assert captured["customerTwoId"] == "gid://shopify/Customer/c2"
        assert result.data["is_blocked"] is False
        assert result.data["has_merge_errors"] is False

    def test_preview_blocking_fields_set_is_blocked(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "customerMergePreview": {
                "customerMergeErrors": [],
                "blockingFields": {"__typename":
                                   "CustomerMergePreviewBlockingFields"},
                "alternateFields": None,
                "defaultFields": None,
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_PREVIEW_CUSTOMER_MERGE,
                {
                    "customer_one_id": "gid://shopify/Customer/c1",
                    "customer_two_id": "gid://shopify/Customer/c2",
                },
            )
        assert result.ok
        assert result.data["is_blocked"] is True
        assert result.data["has_blocking_fields"] is True

    def test_preview_merge_errors_set_is_blocked(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "customerMergePreview": {
                "customerMergeErrors": [
                    {"__typename": "CustomerMergeError"},
                ],
                "blockingFields": None,
                "alternateFields": None,
                "defaultFields": None,
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_PREVIEW_CUSTOMER_MERGE,
                {
                    "customer_one_id": "gid://shopify/Customer/c1",
                    "customer_two_id": "gid://shopify/Customer/c2",
                },
            )
        assert result.ok
        assert result.data["is_blocked"] is True
        assert result.data["has_merge_errors"] is True
        assert result.data["merge_error_count"] == 1

    # ── Merge ────────────────────────────────────

    def test_merge_happy_path(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"customerMerge": {
                "job": {"id": "gid://shopify/Job/j1", "done": False},
                "resultingCustomerId": "gid://shopify/Customer/c1",
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_MERGE_CUSTOMERS,
                {
                    "customer_one_id": "gid://shopify/Customer/c1",
                    "customer_two_id": "gid://shopify/Customer/c2",
                    "override_fields": {
                        "customer_id_of_email": "gid://shopify/Customer/c1",
                    },
                },
            )
        assert result.ok
        assert result.data["job_id"] == "gid://shopify/Job/j1"
        assert result.data["job_done"] is False
        assert result.data["resulting_customer_id"] == \
            "gid://shopify/Customer/c1"
        assert captured["overrideFields"]["customerIdOfEmail"] == \
            "gid://shopify/Customer/c1"

    def test_merge_user_errors_fail_fast(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"customerMerge": {
            "job": None,
            "resultingCustomerId": None,
            "userErrors": [{"field": ["customerOneId"],
                            "message": "Customer not found",
                            "code": "INVALID"}],
        }}):
            result = a.execute(
                Capability.SHOPIFY_MERGE_CUSTOMERS,
                {
                    "customer_one_id": "gid://shopify/Customer/missing",
                    "customer_two_id": "gid://shopify/Customer/c2",
                },
            )
        assert not result.ok

    # ── Get job ──────────────────────────────────

    def test_get_job_requires_id(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_CUSTOMER_MERGE_JOB, {})
        assert not result.ok

    def test_get_job_completed_is_terminal(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "customerMergeJobStatus": {
                "job": {"id": "gid://shopify/Job/j1", "done": True},
                "status": "COMPLETED",
                "resultingCustomerId": "gid://shopify/Customer/c1",
                "errors": [],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_GET_CUSTOMER_MERGE_JOB,
                {"job_id": "gid://shopify/Job/j1"},
            )
        assert result.ok
        assert result.data["status"] == "COMPLETED"
        assert result.data["is_terminal"] is True
        assert result.data["job_done"] is True
        assert result.data["resulting_customer_id"] == \
            "gid://shopify/Customer/c1"

    def test_get_job_in_progress_not_terminal(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        a = ShopifyCustomerMergeAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "customerMergeJobStatus": {
                "job": {"id": "gid://shopify/Job/j1", "done": False},
                "status": "RUNNING",
                "resultingCustomerId": None,
                "errors": [],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_GET_CUSTOMER_MERGE_JOB,
                {"job_id": "gid://shopify/Job/j1"},
            )
        assert result.ok
        assert result.data["status"] == "RUNNING"
        assert result.data["is_terminal"] is False

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.customer_merge import (
            ShopifyCustomerMergeAdapter,
        )
        assert ShopifyCustomerMergeAdapter._normalise_customer({}) == {}


# ── ShopifyFulfillmentEventsAdapter ───────────────────────


class TestShopifyFulfillmentEventsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter()
        assert a.name == "shopify_fulfillment_events"
        for cap in (
            Capability.SHOPIFY_LIST_FULFILLMENT_EVENTS,
            Capability.SHOPIFY_CREATE_FULFILLMENT_EVENT,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_requires_fulfillment_id(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_LIST_FULFILLMENT_EVENTS, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_list_happy_path(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "fulfillment": {
                "id": "gid://shopify/Fulfillment/1",
                "name": "#F1",
                "status": "SUCCESS",
                "events": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [
                        {"node": {
                            "id": "gid://shopify/FulfillmentEvent/e1",
                            "status": "PICKED_UP",
                            "happenedAt": "2026-04-25T08:00:00Z",
                            "city": "Austin",
                            "country": "US",
                        }},
                        {"node": {
                            "id": "gid://shopify/FulfillmentEvent/e2",
                            "status": "DELIVERED",
                            "happenedAt": "2026-04-26T15:30:00Z",
                            "city": "Seattle",
                            "country": "US",
                            "latitude": 47.6062,
                            "longitude": -122.3321,
                        }},
                    ],
                },
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_FULFILLMENT_EVENTS,
                {"fulfillment_id": "gid://shopify/Fulfillment/1"},
            )
        assert result.ok
        assert result.data["count"] == 2
        statuses = [e["status"] for e in result.data["events"]]
        assert statuses == ["PICKED_UP", "DELIVERED"]
        delivered = result.data["events"][1]
        assert delivered["is_terminal"] is True
        assert delivered["latitude"] == 47.6062
        assert delivered["city"] == "Seattle"

    def test_list_clamps_limit(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"fulfillment": None}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_FULFILLMENT_EVENTS,
                {"fulfillment_id": "gid://shopify/Fulfillment/1",
                 "limit": 9999},
            )
        assert captured["first"] == 250

    def test_list_handles_missing_fulfillment(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"fulfillment": None}):
            result = a.execute(
                Capability.SHOPIFY_LIST_FULFILLMENT_EVENTS,
                {"fulfillment_id": "gid://shopify/Fulfillment/missing"},
            )
        assert result.ok
        assert result.data["fulfillment_found"] is False
        assert result.data["count"] == 0

    # ── Create input builder ─────────────────────

    def test_create_requires_fulfillment_id(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_event_input({"status": "IN_TRANSIT"})

    def test_create_requires_status(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_event_input({
                "fulfillment_id": "gid://shopify/Fulfillment/1",
            })

    def test_create_invalid_status_rejected(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_event_input({
                "fulfillment_id": "gid://shopify/Fulfillment/1",
                "status": "TELEPORTING",
            })

    def test_create_full_shape(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter(shop_url="s", access_token="t")
        out = a._build_event_input({
            "fulfillment_id": "gid://shopify/Fulfillment/1",
            "status": "in_transit",
            "address1": "550 Mainland",
            "city": "Memphis",
            "country": "US",
            "latitude": 35.1,
            "longitude": -90.05,
            "happened_at": "2026-04-26T12:00:00Z",
            "estimated_delivery_at": "2026-04-28T17:00:00Z",
            "message": "At sort facility",
        })
        assert out["fulfillmentId"] == "gid://shopify/Fulfillment/1"
        assert out["status"] == "IN_TRANSIT"
        assert out["city"] == "Memphis"
        assert out["latitude"] == 35.1
        assert out["happenedAt"] == "2026-04-26T12:00:00Z"
        assert out["estimatedDeliveryAt"] == "2026-04-28T17:00:00Z"

    def test_create_lat_lng_must_be_numeric(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_event_input({
                "fulfillment_id": "gid://shopify/Fulfillment/1",
                "status": "IN_TRANSIT",
                "latitude": "north",
            })

    # ── Create — happy path ──────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"fulfillmentEventCreate": {
                "fulfillmentEvent": {
                    "id": "gid://shopify/FulfillmentEvent/new",
                    "status": v["fulfillmentEvent"]["status"],
                    "city": v["fulfillmentEvent"].get("city", ""),
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_FULFILLMENT_EVENT,
                {
                    "fulfillment_id": "gid://shopify/Fulfillment/1",
                    "status": "DELIVERED",
                    "city": "Seattle",
                },
            )
        assert result.ok
        # Pattern A: variable name matches input type.
        assert captured["fulfillmentEvent"]["status"] == "DELIVERED"
        assert result.data["event"]["is_terminal"] is True

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        a = ShopifyFulfillmentEventsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "fulfillmentEventCreate": {
                "fulfillmentEvent": None,
                "userErrors": [{"field": ["fulfillmentId"],
                                "message": "not found"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_FULFILLMENT_EVENT,
                {
                    "fulfillment_id": "gid://shopify/Fulfillment/missing",
                    "status": "IN_TRANSIT",
                },
            )
        assert not result.ok

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.fulfillment_events import (
            ShopifyFulfillmentEventsAdapter,
        )
        assert ShopifyFulfillmentEventsAdapter._normalise_event({}) == {}
        assert ShopifyFulfillmentEventsAdapter._normalise_event(None) == {}


# ── ShopifyCustomerConsentAdapter ─────────────────────────


class TestShopifyCustomerConsentAdapter:
    def test_metadata(self):
        from core.adapters.shopify.customer_consent import (
            ShopifyCustomerConsentAdapter,
        )
        a = ShopifyCustomerConsentAdapter()
        assert a.name == "shopify_customer_consent"
        for cap in (
            Capability.SHOPIFY_UPDATE_SMS_CONSENT,
            Capability.SHOPIFY_UPDATE_EMAIL_CONSENT,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.customer_consent import (
            ShopifyCustomerConsentAdapter,
        )
        a = ShopifyCustomerConsentAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input builder ────────────────────────────

    def test_input_requires_customer_id(self):
        from core.adapters.shopify.customer_consent import (
            ShopifyCustomerConsentAdapter,
        )
        a = ShopifyCustomerConsentAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input({"marketing_state": "SUBSCRIBED"}, sms=True)

    def test_input_requires_marketing_state(self):
        from core.adapters.shopify.customer_consent import (
            ShopifyCustomerConsentAdapter,
        )
        a = ShopifyCustomerConsentAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input(
                {"customer_id": "gid://shopify/Customer/c1"}, sms=True,
            )

    def test_input_invalid_marketing_state_rejected(self):
        from core.adapters.shopify.customer_consent import (
            ShopifyCustomerConsentAdapter,
        )
        a = ShopifyCustomerConsentAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input({
                "customer_id": "gid://shopify/Customer/c1",
                "marketing_state": "MAYBE",
            }, sms=True)

    def test_input_invalid_opt_in_rejected(self):
        from core.adapters.shopify.customer_consent import (
            ShopifyCustomerConsentAdapter,
        )
        a = ShopifyCustomerConsentAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input({
                "customer_id": "gid://shopify/Customer/c1",
                "marketing_state": "SUBSCRIBED",
                "marketing_opt_in_level": "DOUBLE_OPT_IN",
            }, sms=True)

    def test_input_invalid_consent_source_rejected(self):
        from core.adapters.shopify.customer_consent import (
            ShopifyCustomerConsentAdapter,
        )
        a = ShopifyCustomerConsentAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input({
                "customer_id": "gid://shopify/Customer/c1",
                "marketing_state": "SUBSCRIBED",
                "consent_collected_from": "SLACK",
            }, sms=True)

    def test_input_sms_full_shape(self):
        from core.adapters.shopify.customer_consent import (
            ShopifyCustomerConsentAdapter,
        )
        a = ShopifyCustomerConsentAdapter(shop_url="s", access_token="t")
        out = a._build_input({
            "customer_id": "gid://shopify/Customer/c1",
            "marketing_state": "subscribed",
            "marketing_opt_in_level": "confirmed_opt_in",
            "consent_collected_from": "shopify",
            "consent_updated_at": "2026-04-26T10:00:00Z",
        }, sms=True)
        assert out["customerId"] == "gid://shopify/Customer/c1"
        consent = out["smsMarketingConsent"]
        assert consent["marketingState"] == "SUBSCRIBED"
        assert consent["marketingOptInLevel"] == "CONFIRMED_OPT_IN"
        assert consent["consentCollectedFrom"] == "SHOPIFY"
        assert consent["consentUpdatedAt"] == "2026-04-26T10:00:00Z"

    def test_input_email_strips_consent_collected_from(self):
        from core.adapters.shopify.customer_consent import (
            ShopifyCustomerConsentAdapter,
        )
        a = ShopifyCustomerConsentAdapter(shop_url="s", access_token="t")
        out = a._build_input({
            "customer_id": "gid://shopify/Customer/c1",
            "marketing_state": "SUBSCRIBED",
            "marketing_opt_in_level": "SINGLE_OPT_IN",
            # collected_from is SMS-only — adapter must NOT include it
            # in the email shape (Shopify rejects with selectionMismatch).
            "consent_collected_from": "SHOPIFY",
        }, sms=False)
        consent = out["emailMarketingConsent"]
        assert "consentCollectedFrom" not in consent
        assert consent["marketingState"] == "SUBSCRIBED"

    # ── SMS update — happy path ──────────────────

    def test_update_sms_happy_path(self):
        from core.adapters.shopify.customer_consent import (
            ShopifyCustomerConsentAdapter,
        )
        a = ShopifyCustomerConsentAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"customerSmsMarketingConsentUpdate": {
                "customer": {
                    "id": v["input"]["customerId"],
                    "phone": "+15551234567",
                    "smsMarketingConsent": {
                        "marketingState": (
                            v["input"]["smsMarketingConsent"]["marketingState"]
                        ),
                        "marketingOptInLevel": "CONFIRMED_OPT_IN",
                        "consentCollectedFrom": "SHOPIFY",
                        "consentUpdatedAt": "2026-04-26T10:00:00Z",
                    },
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_SMS_CONSENT, {
                "customer_id": "gid://shopify/Customer/c1",
                "marketing_state": "SUBSCRIBED",
                "marketing_opt_in_level": "CONFIRMED_OPT_IN",
                "consent_collected_from": "SHOPIFY",
            })
        assert result.ok
        assert captured["input"]["customerId"] == "gid://shopify/Customer/c1"
        assert result.data["marketing_state"] == "SUBSCRIBED"
        assert result.data["consent_collected_from"] == "SHOPIFY"
        assert result.data["phone"] == "+15551234567"

    def test_update_sms_user_errors_fail_fast(self):
        from core.adapters.shopify.customer_consent import (
            ShopifyCustomerConsentAdapter,
        )
        a = ShopifyCustomerConsentAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "customerSmsMarketingConsentUpdate": {
                "customer": None,
                "userErrors": [{"field": ["customerId"],
                                "message": "Customer has no phone",
                                "code": "INVALID"}],
            }
        }):
            result = a.execute(Capability.SHOPIFY_UPDATE_SMS_CONSENT, {
                "customer_id": "gid://shopify/Customer/no-phone",
                "marketing_state": "SUBSCRIBED",
            })
        assert not result.ok

    # ── Email update — happy path ────────────────

    def test_update_email_happy_path(self):
        from core.adapters.shopify.customer_consent import (
            ShopifyCustomerConsentAdapter,
        )
        a = ShopifyCustomerConsentAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"customerEmailMarketingConsentUpdate": {
                "customer": {
                    "id": v["input"]["customerId"],
                    "email": "x@y.com",
                    "emailMarketingConsent": {
                        "marketingState": "UNSUBSCRIBED",
                        "marketingOptInLevel": "SINGLE_OPT_IN",
                        "consentUpdatedAt": "2026-04-26T11:00:00Z",
                    },
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPDATE_EMAIL_CONSENT, {
                "customer_id": "gid://shopify/Customer/c1",
                "marketing_state": "UNSUBSCRIBED",
                "marketing_opt_in_level": "SINGLE_OPT_IN",
            })
        assert result.ok
        assert result.data["marketing_state"] == "UNSUBSCRIBED"
        assert result.data["email"] == "x@y.com"
        # Email payload shouldn't carry consent_collected_from in
        # response since it's SMS-only.
        assert "consent_collected_from" not in result.data


# ── ShopifyInventoryActivationAdapter ─────────────────────


class TestShopifyInventoryActivationAdapter:
    def test_metadata(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter()
        assert a.name == "shopify_inventory_activation"
        for cap in (
            Capability.SHOPIFY_ACTIVATE_INVENTORY_AT_LOCATION,
            Capability.SHOPIFY_DEACTIVATE_INVENTORY_AT_LOCATION,
            Capability.SHOPIFY_ADJUST_INVENTORY_QUANTITIES,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Activate ─────────────────────────────────

    def test_activate_requires_item_id(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_ACTIVATE_INVENTORY_AT_LOCATION,
            {"location_id": "gid://shopify/Location/1"},
        )
        assert not result.ok

    def test_activate_requires_location_id(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_ACTIVATE_INVENTORY_AT_LOCATION,
            {"inventory_item_id": "gid://shopify/InventoryItem/1"},
        )
        assert not result.ok

    def test_activate_happy_path_with_initial_quantity(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"inventoryActivate": {
                "inventoryLevel": {
                    "id": "gid://shopify/InventoryLevel/lvl1",
                    "location": {
                        "id": v["locationId"],
                        "name": "Shop location",
                    },
                    "item": {
                        "id": v["inventoryItemId"],
                        "sku": "LANT-1",
                        "tracked": True,
                    },
                    "quantities": [
                        {"name": "available", "quantity": v["available"]},
                        {"name": "on_hand", "quantity": v["available"]},
                    ],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_ACTIVATE_INVENTORY_AT_LOCATION,
                {
                    "inventory_item_id": "gid://shopify/InventoryItem/i1",
                    "location_id": "gid://shopify/Location/loc1",
                    "available": 25,
                },
            )
        assert result.ok
        assert captured["inventoryItemId"] == \
            "gid://shopify/InventoryItem/i1"
        assert captured["available"] == 25
        level = result.data["inventory_level"]
        assert level["sku"] == "LANT-1"
        assert level["available"] == 25

    def test_activate_available_must_be_int(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_ACTIVATE_INVENTORY_AT_LOCATION,
            {
                "inventory_item_id": "gid://shopify/InventoryItem/1",
                "location_id": "gid://shopify/Location/1",
                "available": "many",
            },
        )
        assert not result.ok

    def test_activate_user_errors_fail_fast(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"inventoryActivate": {
            "inventoryLevel": None,
            "userErrors": [{"field": ["locationId"],
                            "message": "Location not found",
                            "code": "INVALID"}],
        }}):
            result = a.execute(
                Capability.SHOPIFY_ACTIVATE_INVENTORY_AT_LOCATION,
                {
                    "inventory_item_id": "gid://shopify/InventoryItem/1",
                    "location_id": "gid://shopify/Location/missing",
                },
            )
        assert not result.ok

    # ── Deactivate ───────────────────────────────

    def test_deactivate_requires_level_id(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_DEACTIVATE_INVENTORY_AT_LOCATION, {},
        )
        assert not result.ok

    def test_deactivate_happy_path(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"inventoryDeactivate": {"userErrors": []}}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_DEACTIVATE_INVENTORY_AT_LOCATION,
                {"inventory_level_id": "gid://shopify/InventoryLevel/lvl1"},
            )
        assert result.ok
        assert result.data["deactivated"] is True
        assert captured["inventoryLevelId"] == \
            "gid://shopify/InventoryLevel/lvl1"

    # ── Adjust ───────────────────────────────────

    def test_adjust_requires_reason(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_adjust_input({"changes": []})

    def test_adjust_invalid_reason_rejected(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_adjust_input({
                "reason": "vibes",
                "changes": [{"inventory_item_id": "i1", "location_id": "l1",
                             "delta": 5}],
            })

    def test_adjust_invalid_quantity_name_rejected(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_adjust_input({
                "reason": "received",
                "name": "stock",
                "changes": [{"inventory_item_id": "i1", "location_id": "l1",
                             "delta": 5}],
            })

    def test_adjust_requires_non_empty_changes(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_adjust_input({"reason": "received", "changes": []})

    def test_adjust_change_requires_delta(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_adjust_input({
                "reason": "received",
                "changes": [{"inventory_item_id": "i1", "location_id": "l1"}],
            })

    def test_adjust_zero_delta_rejected(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_adjust_input({
                "reason": "received",
                "changes": [{"inventory_item_id": "i1", "location_id": "l1",
                             "delta": 0}],
            })

    def test_adjust_full_shape(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        out = a._build_adjust_input({
            "reason": "received",
            "name": "available",
            "changes": [
                {"inventory_item_id": "gid://shopify/InventoryItem/1",
                 "location_id": "gid://shopify/Location/1",
                 "delta": 5,
                 "ledger_document_uri": "shopai://po/12345"},
                {"inventory_item_id": "gid://shopify/InventoryItem/2",
                 "location_id": "gid://shopify/Location/1",
                 "delta": -3},
            ],
        })
        assert out["reason"] == "received"
        assert out["name"] == "available"
        assert len(out["changes"]) == 2
        assert out["changes"][0]["delta"] == 5
        assert out["changes"][0]["ledgerDocumentUri"] == \
            "shopai://po/12345"
        assert out["changes"][1]["delta"] == -3

    def test_adjust_happy_path(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        a = ShopifyInventoryActivationAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "inventoryAdjustQuantities": {
                "inventoryAdjustmentGroup": {
                    "id": "gid://shopify/InventoryAdjustmentGroup/g1",
                    "reason": "received",
                    "changes": [{
                        "delta": 5,
                        "name": "available",
                        "quantityAfterChange": 30,
                        "item": {
                            "id": "gid://shopify/InventoryItem/1",
                            "sku": "LANT-1",
                        },
                        "location": {
                            "id": "gid://shopify/Location/1",
                            "name": "Shop location",
                        },
                    }],
                },
                "userErrors": [],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_ADJUST_INVENTORY_QUANTITIES,
                {
                    "reason": "received",
                    "changes": [{
                        "inventory_item_id": "gid://shopify/InventoryItem/1",
                        "location_id": "gid://shopify/Location/1",
                        "delta": 5,
                    }],
                },
            )
        assert result.ok
        assert result.data["count"] == 1
        change = result.data["changes"][0]
        assert change["delta"] == 5
        assert change["quantity_after_change"] == 30
        assert change["sku"] == "LANT-1"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.inventory_activation import (
            ShopifyInventoryActivationAdapter,
        )
        assert ShopifyInventoryActivationAdapter._normalise_level({}) == {}
        assert ShopifyInventoryActivationAdapter._normalise_change(None) == {}


# ── ShopifyDiscountCodeBxgyAdapter ────────────────────────


class TestShopifyDiscountCodeBxgyAdapter:
    def test_metadata(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter()
        assert a.name == "shopify_discount_code_bxgy"
        for cap in (
            Capability.SHOPIFY_CREATE_DISCOUNT_BXGY,
            Capability.SHOPIFY_DELETE_DISCOUNT_BXGY,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input ────────────────────────────────────

    def test_create_requires_title(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input({
                "code": "BUNDLE3",
                "starts_at": "2026-04-26T00:00:00Z",
                "customer_buys": {"value": {"quantity": 2},
                                  "items": {"all": True}},
                "customer_gets": {"value": {"percentage": 50},
                                  "items": {"all": True}},
            })

    def test_create_requires_code(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input({
                "title": "Bundle",
                "starts_at": "2026-04-26T00:00:00Z",
                "customer_buys": {"value": {"quantity": 2},
                                  "items": {"all": True}},
                "customer_gets": {"value": {"percentage": 50},
                                  "items": {"all": True}},
            })

    def test_create_requires_customer_buys(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_input({
                "title": "Bundle", "code": "BUNDLE3",
                "starts_at": "2026-04-26T00:00:00Z",
                "customer_gets": {"value": {"percentage": 50},
                                  "items": {"all": True}},
            })

    def test_buys_quantity_must_be_positive(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_customer_buys({
                "value": {"quantity": 0},
                "items": {"all": True},
            })

    def test_gets_percentage_range_enforced(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_customer_gets({
                "value": {"percentage": 150},
                "items": {"all": True},
            })

    def test_gets_requires_value_kind(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_customer_gets({
                "value": {},
                "items": {"all": True},
            })

    def test_items_must_specify_all_or_products_or_collections(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_items({}, label="customer_buys.items")

    def test_items_collections_form(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        out = a._build_items(
            {"collections": ["gid://shopify/Collection/1"]},
            label="customer_buys.items",
        )
        assert out == {"collections": {"add": ["gid://shopify/Collection/1"]}}

    def test_items_products_form(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        out = a._build_items(
            {"products": ["gid://shopify/Product/1",
                          "gid://shopify/Product/2"]},
            label="customer_gets.items",
        )
        assert out == {"products": {
            "productsToAdd": ["gid://shopify/Product/1",
                              "gid://shopify/Product/2"],
        }}

    def test_input_full_shape(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        out = a._build_input({
            "title": "Bundle",
            "code": "BUNDLE3",
            "starts_at": "2026-04-26T00:00:00Z",
            "ends_at": "2026-12-31T23:59:59Z",
            "uses_per_order_limit": 1,
            "usage_limit": 1000,
            "customer_buys": {
                "value": {"quantity": 2},
                "items": {"all": True},
            },
            "customer_gets": {
                "value": {"percentage": 50},
                "items": {"all": True},
                "quantity": 1,
            },
        })
        assert out["title"] == "Bundle"
        assert out["code"] == "BUNDLE3"
        assert out["usesPerOrderLimit"] == 1
        assert out["usageLimit"] == 1000
        assert out["customerBuys"]["value"]["quantity"] == "2"
        # ShopAI 0-100 → Shopify 0-1 conversion.
        gets = out["customerGets"]["value"]["discountOnQuantity"]
        assert gets["effect"]["percentage"] == 0.5
        assert gets["quantity"] == "1"

    # ── Create — happy path ──────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"discountCodeBxgyCreate": {
                "codeDiscountNode": {
                    "id": "gid://shopify/DiscountCodeNode/new",
                    "codeDiscount": {
                        "title": v["bxgyCodeDiscount"]["title"],
                        "summary": "Buy 2 get 1 50% off",
                        "status": "ACTIVE",
                        "startsAt": (
                            v["bxgyCodeDiscount"]["startsAt"]
                        ),
                        "endsAt": v["bxgyCodeDiscount"].get("endsAt", ""),
                        "usesPerOrderLimit": (
                            v["bxgyCodeDiscount"].get(
                                "usesPerOrderLimit"
                            )
                        ),
                        "codes": {
                            "edges": [{
                                "node": {"code": v["bxgyCodeDiscount"]["code"]},
                            }],
                        },
                    },
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_DISCOUNT_BXGY,
                {
                    "title": "Bundle Pack",
                    "code": "BUNDLE3",
                    "starts_at": "2026-04-26T00:00:00Z",
                    "uses_per_order_limit": 1,
                    "customer_buys": {
                        "value": {"quantity": 2},
                        "items": {"all": True},
                    },
                    "customer_gets": {
                        "value": {"percentage": 50},
                        "items": {"all": True},
                        "quantity": 1,
                    },
                },
            )
        assert result.ok
        # Pattern A: variable name matches input type.
        assert captured["bxgyCodeDiscount"]["title"] == "Bundle Pack"
        assert result.data["title"] == "Bundle Pack"
        assert result.data["status"] == "ACTIVE"
        assert "BUNDLE3" in result.data["codes"]

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "discountCodeBxgyCreate": {
                "codeDiscountNode": None,
                "userErrors": [{"field": ["bxgyCodeDiscount", "code"],
                                "message": "Code is taken",
                                "code": "TAKEN"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_DISCOUNT_BXGY,
                {
                    "title": "Dup", "code": "DUP",
                    "starts_at": "2026-04-26T00:00:00Z",
                    "customer_buys": {"value": {"quantity": 2},
                                      "items": {"all": True}},
                    "customer_gets": {"value": {"percentage": 50},
                                      "items": {"all": True}},
                },
            )
        assert not result.ok

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_DELETE_DISCOUNT_BXGY, {})
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.discount_code_bxgy import (
            ShopifyDiscountCodeBxgyAdapter,
        )
        a = ShopifyDiscountCodeBxgyAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"discountCodeDelete": {
            "deletedCodeDiscountId": (
                "gid://shopify/DiscountCodeNode/1"
            ),
            "userErrors": [],
        }}):
            result = a.execute(
                Capability.SHOPIFY_DELETE_DISCOUNT_BXGY,
                {"id": "gid://shopify/DiscountCodeNode/1"},
            )
        assert result.ok
        assert result.data["deleted_id"] == \
            "gid://shopify/DiscountCodeNode/1"


# ── ShopifySubscriptionDraftAdapter ───────────────────────


class TestShopifySubscriptionDraftAdapter:
    def test_metadata(self):
        from core.adapters.shopify.subscription_draft import (
            ShopifySubscriptionDraftAdapter,
        )
        a = ShopifySubscriptionDraftAdapter()
        assert a.name == "shopify_subscription_draft"
        for cap in (
            Capability.SHOPIFY_CREATE_SUBSCRIPTION_DRAFT,
            Capability.SHOPIFY_UPDATE_SUBSCRIPTION_DRAFT,
            Capability.SHOPIFY_COMMIT_SUBSCRIPTION_DRAFT,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.subscription_draft import (
            ShopifySubscriptionDraftAdapter,
        )
        a = ShopifySubscriptionDraftAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Create ───────────────────────────────────

    def test_create_requires_contract_id(self):
        from core.adapters.shopify.subscription_draft import (
            ShopifySubscriptionDraftAdapter,
        )
        a = ShopifySubscriptionDraftAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_CREATE_SUBSCRIPTION_DRAFT, {})
        assert not result.ok

    def test_create_happy_path(self):
        from core.adapters.shopify.subscription_draft import (
            ShopifySubscriptionDraftAdapter,
        )
        a = ShopifySubscriptionDraftAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"subscriptionContractUpdate": {
                "draft": {
                    "id": "gid://shopify/SubscriptionDraft/d1",
                    "status": "DRAFT",
                    "nextBillingDate": "2026-05-26T00:00:00Z",
                    "note": "",
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_SUBSCRIPTION_DRAFT,
                {"contract_id":
                 "gid://shopify/SubscriptionContract/c1"},
            )
        assert result.ok
        # Pattern A: contractId at field level.
        assert captured["contractId"] == \
            "gid://shopify/SubscriptionContract/c1"
        assert result.data["draft_id"] == \
            "gid://shopify/SubscriptionDraft/d1"

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.subscription_draft import (
            ShopifySubscriptionDraftAdapter,
        )
        a = ShopifySubscriptionDraftAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "subscriptionContractUpdate": {
                "draft": None,
                "userErrors": [{"field": ["contractId"],
                                "message": "Contract is cancelled",
                                "code": "INVALID"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_SUBSCRIPTION_DRAFT,
                {"contract_id":
                 "gid://shopify/SubscriptionContract/cancelled"},
            )
        assert not result.ok

    # ── Update ───────────────────────────────────

    def test_update_requires_draft_id(self):
        from core.adapters.shopify.subscription_draft import (
            ShopifySubscriptionDraftAdapter,
        )
        a = ShopifySubscriptionDraftAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_UPDATE_SUBSCRIPTION_DRAFT,
            {"next_billing_date": "2026-06-01T00:00:00Z"},
        )
        assert not result.ok

    def test_update_no_fields_rejected(self):
        from core.adapters.shopify.subscription_draft import (
            ShopifySubscriptionDraftAdapter,
        )
        a = ShopifySubscriptionDraftAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_UPDATE_SUBSCRIPTION_DRAFT,
            {"draft_id": "gid://shopify/SubscriptionDraft/d1"},
        )
        assert not result.ok

    def test_update_happy_path(self):
        from core.adapters.shopify.subscription_draft import (
            ShopifySubscriptionDraftAdapter,
        )
        a = ShopifySubscriptionDraftAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"subscriptionDraftUpdate": {
                "draft": {
                    "id": v["draftId"],
                    "status": "DRAFT",
                    "nextBillingDate": v["input"].get("nextBillingDate", ""),
                    "note": v["input"].get("note", ""),
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_UPDATE_SUBSCRIPTION_DRAFT,
                {
                    "draft_id": "gid://shopify/SubscriptionDraft/d1",
                    "next_billing_date": "2026-06-01T00:00:00Z",
                    "note": "Customer requested 8-week cadence",
                    "payment_method_id": (
                        "gid://shopify/CustomerPaymentMethod/m1"
                    ),
                },
            )
        assert result.ok
        assert captured["draftId"] == "gid://shopify/SubscriptionDraft/d1"
        inp = captured["input"]
        assert inp["nextBillingDate"] == "2026-06-01T00:00:00Z"
        assert inp["note"] == "Customer requested 8-week cadence"
        assert inp["paymentMethodId"] == \
            "gid://shopify/CustomerPaymentMethod/m1"

    # ── Commit ───────────────────────────────────

    def test_commit_requires_draft_id(self):
        from core.adapters.shopify.subscription_draft import (
            ShopifySubscriptionDraftAdapter,
        )
        a = ShopifySubscriptionDraftAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_COMMIT_SUBSCRIPTION_DRAFT, {})
        assert not result.ok

    def test_commit_happy_path(self):
        from core.adapters.shopify.subscription_draft import (
            ShopifySubscriptionDraftAdapter,
        )
        a = ShopifySubscriptionDraftAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "subscriptionDraftCommit": {
                "contract": {
                    "id": "gid://shopify/SubscriptionContract/c1",
                    "status": "ACTIVE",
                    "nextBillingDate": "2026-06-01T00:00:00Z",
                },
                "userErrors": [],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_COMMIT_SUBSCRIPTION_DRAFT,
                {"draft_id": "gid://shopify/SubscriptionDraft/d1"},
            )
        assert result.ok
        assert result.data["contract_id"] == \
            "gid://shopify/SubscriptionContract/c1"
        assert result.data["status"] == "ACTIVE"
        assert result.data["next_billing_date"] == \
            "2026-06-01T00:00:00Z"

    def test_commit_user_errors_fail_fast(self):
        from core.adapters.shopify.subscription_draft import (
            ShopifySubscriptionDraftAdapter,
        )
        a = ShopifySubscriptionDraftAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "subscriptionDraftCommit": {
                "contract": None,
                "userErrors": [{"field": ["draftId"],
                                "message": "Draft already committed",
                                "code": "ALREADY_COMMITTED"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_COMMIT_SUBSCRIPTION_DRAFT,
                {"draft_id": "gid://shopify/SubscriptionDraft/committed"},
            )
        assert not result.ok


# ── ShopifyCatalogsAdapter ────────────────────────────────


class TestShopifyCatalogsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.catalogs import ShopifyCatalogsAdapter
        a = ShopifyCatalogsAdapter()
        assert a.name == "shopify_catalogs"
        for cap in (
            Capability.SHOPIFY_LIST_CATALOGS,
            Capability.SHOPIFY_GET_CATALOG,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.catalogs import ShopifyCatalogsAdapter
        a = ShopifyCatalogsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_happy_path_company_location(self):
        from core.adapters.shopify.catalogs import ShopifyCatalogsAdapter
        a = ShopifyCatalogsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "catalogs": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "__typename": "CompanyLocationCatalog",
                    "id": "gid://shopify/CompanyLocationCatalog/1",
                    "title": "B2B Tier 1",
                    "status": "ACTIVE",
                    "priceList": {
                        "id": "gid://shopify/PriceList/p1",
                        "name": "Wholesale Tier 1",
                        "currency": "USD",
                    },
                    "publication": {
                        "id": "gid://shopify/Publication/pub1",
                        "catalog": {"id": "gid://shopify/CompanyLocationCatalog/1"},
                    },
                }}],
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_CATALOGS, {})
        assert result.ok
        c = result.data["catalogs"][0]
        assert c["type"] == "COMPANY_LOCATION"
        assert c["price_list_name"] == "Wholesale Tier 1"
        assert c["currency_code"] == "USD"
        assert c["title"] == "B2B Tier 1"

    def test_list_market_catalog_type_mapping(self):
        from core.adapters.shopify.catalogs import ShopifyCatalogsAdapter
        a = ShopifyCatalogsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "catalogs": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [{"node": {
                    "__typename": "MarketCatalog",
                    "id": "gid://shopify/MarketCatalog/m1",
                    "title": "France EUR",
                    "status": "ACTIVE",
                }}],
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_CATALOGS, {})
        assert result.data["catalogs"][0]["type"] == "MARKET"

    def test_list_invalid_type_rejected(self):
        from core.adapters.shopify.catalogs import ShopifyCatalogsAdapter
        a = ShopifyCatalogsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_LIST_CATALOGS, {
            "type": "BAD",
        })
        assert not result.ok

    def test_list_passes_type_and_query_filter(self):
        from core.adapters.shopify.catalogs import ShopifyCatalogsAdapter
        a = ShopifyCatalogsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"catalogs": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_CATALOGS, {
                "type": "company_location",
                "query": "title:Wholesale",
            })
        assert captured["type"] == "COMPANY_LOCATION"
        assert captured["query"] == "title:Wholesale"

    def test_list_clamps_limit(self):
        from core.adapters.shopify.catalogs import ShopifyCatalogsAdapter
        a = ShopifyCatalogsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"catalogs": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_CATALOGS, {"limit": 9999})
        assert captured["first"] == 250

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.catalogs import ShopifyCatalogsAdapter
        a = ShopifyCatalogsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_CATALOG, {})
        assert not result.ok

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.catalogs import ShopifyCatalogsAdapter
        a = ShopifyCatalogsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"catalog": None}):
            result = a.execute(Capability.SHOPIFY_GET_CATALOG, {
                "id": "gid://shopify/CompanyLocationCatalog/999",
            })
        assert result.ok
        assert result.data["found"] is False

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.catalogs import ShopifyCatalogsAdapter
        assert ShopifyCatalogsAdapter._normalise_catalog({}) == {}
        assert ShopifyCatalogsAdapter._normalise_catalog(None) == {}


# ── ShopifyFulfillmentHoldAdapter ─────────────────────────


class TestShopifyFulfillmentHoldAdapter:
    def test_metadata(self):
        from core.adapters.shopify.fulfillment_hold import (
            ShopifyFulfillmentHoldAdapter,
        )
        a = ShopifyFulfillmentHoldAdapter()
        assert a.name == "shopify_fulfillment_hold"
        for cap in (
            Capability.SHOPIFY_HOLD_FULFILLMENT_ORDER,
            Capability.SHOPIFY_RELEASE_FULFILLMENT_ORDER_HOLD,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.fulfillment_hold import (
            ShopifyFulfillmentHoldAdapter,
        )
        a = ShopifyFulfillmentHoldAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Hold input ───────────────────────────────

    def test_hold_requires_fulfillment_order_id(self):
        from core.adapters.shopify.fulfillment_hold import (
            ShopifyFulfillmentHoldAdapter,
        )
        a = ShopifyFulfillmentHoldAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_HOLD_FULFILLMENT_ORDER, {
            "reason": "OTHER",
        })
        assert not result.ok

    def test_hold_requires_reason(self):
        from core.adapters.shopify.fulfillment_hold import (
            ShopifyFulfillmentHoldAdapter,
        )
        a = ShopifyFulfillmentHoldAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_hold_input({})

    def test_hold_invalid_reason_rejected(self):
        from core.adapters.shopify.fulfillment_hold import (
            ShopifyFulfillmentHoldAdapter,
        )
        a = ShopifyFulfillmentHoldAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_hold_input({"reason": "VIBES"})

    def test_hold_full_shape(self):
        from core.adapters.shopify.fulfillment_hold import (
            ShopifyFulfillmentHoldAdapter,
        )
        a = ShopifyFulfillmentHoldAdapter(shop_url="s", access_token="t")
        out = a._build_hold_input({
            "reason": "high_risk_of_fraud",
            "reason_notes": "AI fraud score 0.92",
            "notify_merchant": True,
            "external_id": "shopai-hold-001",
        })
        assert out["reason"] == "HIGH_RISK_OF_FRAUD"
        assert out["reasonNotes"] == "AI fraud score 0.92"
        assert out["notifyMerchant"] is True
        assert out["externalId"] == "shopai-hold-001"

    # ── Hold ─────────────────────────────────────

    def test_hold_happy_path(self):
        from core.adapters.shopify.fulfillment_hold import (
            ShopifyFulfillmentHoldAdapter,
        )
        a = ShopifyFulfillmentHoldAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"fulfillmentOrderHold": {
                "fulfillmentOrder": {
                    "id": v["id"],
                    "status": "ON_HOLD",
                    "requestStatus": "UNSUBMITTED",
                    "fulfillmentHolds": [{
                        "id": "gid://shopify/FulfillmentHold/h1",
                        "reason": (
                            v["fulfillmentHold"]["reason"]
                        ),
                        "reasonNotes": (
                            v["fulfillmentHold"].get("reasonNotes", "")
                        ),
                        "heldByApp": {"id": "gid://shopify/App/100"},
                    }],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_HOLD_FULFILLMENT_ORDER,
                {
                    "fulfillment_order_id":
                        "gid://shopify/FulfillmentOrder/1",
                    "reason": "HIGH_RISK_OF_FRAUD",
                    "reason_notes": "AI score 0.92",
                    "notify_merchant": True,
                },
            )
        assert result.ok
        # Pattern A: id at field level, hold input as $fulfillmentHold.
        assert captured["id"] == "gid://shopify/FulfillmentOrder/1"
        assert captured["fulfillmentHold"]["reason"] == "HIGH_RISK_OF_FRAUD"
        fo = result.data["fulfillment_order"]
        assert fo["status"] == "ON_HOLD"
        assert fo["is_held"] is True
        assert fo["holds"][0]["reason"] == "HIGH_RISK_OF_FRAUD"

    def test_hold_user_errors_fail_fast(self):
        from core.adapters.shopify.fulfillment_hold import (
            ShopifyFulfillmentHoldAdapter,
        )
        a = ShopifyFulfillmentHoldAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "fulfillmentOrderHold": {
                "fulfillmentOrder": None,
                "userErrors": [{"field": ["id"],
                                "message": "Already shipped",
                                "code": "INVALID"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_HOLD_FULFILLMENT_ORDER,
                {
                    "fulfillment_order_id":
                        "gid://shopify/FulfillmentOrder/shipped",
                    "reason": "OTHER",
                },
            )
        assert not result.ok

    # ── Release ──────────────────────────────────

    def test_release_requires_id(self):
        from core.adapters.shopify.fulfillment_hold import (
            ShopifyFulfillmentHoldAdapter,
        )
        a = ShopifyFulfillmentHoldAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_RELEASE_FULFILLMENT_ORDER_HOLD, {},
        )
        assert not result.ok

    def test_release_happy_path_with_external_id(self):
        from core.adapters.shopify.fulfillment_hold import (
            ShopifyFulfillmentHoldAdapter,
        )
        a = ShopifyFulfillmentHoldAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"fulfillmentOrderReleaseHold": {
                "fulfillmentOrder": {
                    "id": v["id"],
                    "status": "OPEN",
                    "fulfillmentHolds": [],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_RELEASE_FULFILLMENT_ORDER_HOLD,
                {
                    "fulfillment_order_id":
                        "gid://shopify/FulfillmentOrder/1",
                    "external_id": "shopai-hold-001",
                },
            )
        assert result.ok
        assert captured["externalId"] == "shopai-hold-001"
        assert result.data["fulfillment_order"]["is_held"] is False

    def test_release_works_without_external_id(self):
        from core.adapters.shopify.fulfillment_hold import (
            ShopifyFulfillmentHoldAdapter,
        )
        a = ShopifyFulfillmentHoldAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"fulfillmentOrderReleaseHold": {
                "fulfillmentOrder": {
                    "id": v["id"],
                    "status": "OPEN",
                    "fulfillmentHolds": [],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_RELEASE_FULFILLMENT_ORDER_HOLD,
                {"fulfillment_order_id": "gid://shopify/FulfillmentOrder/1"},
            )
        assert "externalId" not in captured

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.fulfillment_hold import (
            ShopifyFulfillmentHoldAdapter,
        )
        assert ShopifyFulfillmentHoldAdapter._normalise_fulfillment_order(
            {},
        ) == {}


# ── ShopifyPaymentsPayoutsAdapter ─────────────────────────


class TestShopifyPaymentsPayoutsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.payments_payouts import (
            ShopifyPaymentsPayoutsAdapter,
        )
        a = ShopifyPaymentsPayoutsAdapter()
        assert a.name == "shopify_payments_payouts"
        for cap in (
            Capability.SHOPIFY_LIST_PAYOUTS,
            Capability.SHOPIFY_GET_PAYOUT,
            Capability.SHOPIFY_GET_PAYMENTS_BALANCE,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.payments_payouts import (
            ShopifyPaymentsPayoutsAdapter,
        )
        a = ShopifyPaymentsPayoutsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.payments_payouts import (
            ShopifyPaymentsPayoutsAdapter,
        )
        a = ShopifyPaymentsPayoutsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "shopifyPaymentsAccount": {
                "payouts": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [{"node": {
                        "id": "gid://shopify/ShopifyPaymentsPayout/p1",
                        "status": "PAID",
                        "issuedAt": "2026-04-25T10:00:00Z",
                        "bankAccount": {
                            "id": "gid://shopify/ShopifyPaymentsBankAccount/b1",
                            "bankName": "Chase",
                        },
                        "gross": {"amount": "1000.00", "currencyCode": "USD"},
                        "net": {"amount": "950.00", "currencyCode": "USD"},
                    }}],
                },
            }
        }):
            result = a.execute(Capability.SHOPIFY_LIST_PAYOUTS, {})
        assert result.ok
        assert result.data["count"] == 1
        assert result.data["shop_uses_shopify_payments"] is True
        p = result.data["payouts"][0]
        assert p["status"] == "PAID"
        assert p["gross_amount"] == "1000.00"
        assert p["net_amount"] == "950.00"
        assert p["bank_name"] == "Chase"

    def test_list_handles_no_shopify_payments(self):
        from core.adapters.shopify.payments_payouts import (
            ShopifyPaymentsPayoutsAdapter,
        )
        a = ShopifyPaymentsPayoutsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "shopifyPaymentsAccount": None,
        }):
            result = a.execute(Capability.SHOPIFY_LIST_PAYOUTS, {})
        assert result.ok
        assert result.data["count"] == 0
        assert result.data["shop_uses_shopify_payments"] is False

    def test_list_clamps_limit(self):
        from core.adapters.shopify.payments_payouts import (
            ShopifyPaymentsPayoutsAdapter,
        )
        a = ShopifyPaymentsPayoutsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"shopifyPaymentsAccount": None}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(Capability.SHOPIFY_LIST_PAYOUTS, {"limit": 9999})
        assert captured["first"] == 250

    # ── Get ──────────────────────────────────────

    def test_get_requires_id(self):
        from core.adapters.shopify.payments_payouts import (
            ShopifyPaymentsPayoutsAdapter,
        )
        a = ShopifyPaymentsPayoutsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_GET_PAYOUT, {})
        assert not result.ok

    def test_get_happy_path(self):
        from core.adapters.shopify.payments_payouts import (
            ShopifyPaymentsPayoutsAdapter,
        )
        a = ShopifyPaymentsPayoutsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"node": {
            "id": "gid://shopify/ShopifyPaymentsPayout/p1",
            "status": "SCHEDULED",
            "gross": {"amount": "500.00", "currencyCode": "USD"},
            "net": {"amount": "485.00", "currencyCode": "USD"},
        }}):
            result = a.execute(
                Capability.SHOPIFY_GET_PAYOUT,
                {"id": "gid://shopify/ShopifyPaymentsPayout/p1"},
            )
        assert result.ok
        p = result.data["payout"]
        assert p["status"] == "SCHEDULED"
        assert p["net_amount"] == "485.00"

    def test_get_missing_returns_not_found(self):
        from core.adapters.shopify.payments_payouts import (
            ShopifyPaymentsPayoutsAdapter,
        )
        a = ShopifyPaymentsPayoutsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"node": None}):
            result = a.execute(
                Capability.SHOPIFY_GET_PAYOUT,
                {"id": "gid://shopify/ShopifyPaymentsPayout/999"},
            )
        assert result.ok
        assert result.data["found"] is False

    # ── Balance ──────────────────────────────────

    def test_get_balance_happy_path(self):
        from core.adapters.shopify.payments_payouts import (
            ShopifyPaymentsPayoutsAdapter,
        )
        a = ShopifyPaymentsPayoutsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "shopifyPaymentsAccount": {
                "balance": [
                    {"amount": "1234.56", "currencyCode": "USD"},
                    {"amount": "200.00", "currencyCode": "EUR"},
                ],
                "defaultCurrency": "USD",
                "payoutSchedule": {
                    "interval": "WEEKLY",
                    "monthlyAnchor": 0,
                    "weeklyAnchor": "FRIDAY",
                },
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_GET_PAYMENTS_BALANCE, {},
            )
        assert result.ok
        assert len(result.data["balances"]) == 2
        assert result.data["default_currency"] == "USD"
        assert result.data["payout_interval"] == "WEEKLY"
        assert result.data["payout_weekly_anchor"] == "FRIDAY"

    def test_get_balance_no_payments_account(self):
        from core.adapters.shopify.payments_payouts import (
            ShopifyPaymentsPayoutsAdapter,
        )
        a = ShopifyPaymentsPayoutsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "shopifyPaymentsAccount": None,
        }):
            result = a.execute(
                Capability.SHOPIFY_GET_PAYMENTS_BALANCE, {},
            )
        assert result.ok
        assert result.data["shop_uses_shopify_payments"] is False
        assert result.data["balances"] == []

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.payments_payouts import (
            ShopifyPaymentsPayoutsAdapter,
        )
        assert ShopifyPaymentsPayoutsAdapter._normalise_payout({}) == {}
        assert ShopifyPaymentsPayoutsAdapter._normalise_payout(None) == {}


# ── ShopifyOrderInvoiceSendAdapter ────────────────────────


class TestShopifyOrderInvoiceSendAdapter:
    def test_metadata(self):
        from core.adapters.shopify.order_invoice import (
            ShopifyOrderInvoiceSendAdapter,
        )
        a = ShopifyOrderInvoiceSendAdapter()
        assert a.name == "shopify_order_invoice"
        assert Capability.SHOPIFY_SEND_ORDER_INVOICE in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.order_invoice import (
            ShopifyOrderInvoiceSendAdapter,
        )
        a = ShopifyOrderInvoiceSendAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Send ─────────────────────────────────────

    def test_send_requires_order_id(self):
        from core.adapters.shopify.order_invoice import (
            ShopifyOrderInvoiceSendAdapter,
        )
        a = ShopifyOrderInvoiceSendAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_SEND_ORDER_INVOICE, {
            "to": "x@y.com",
        })
        assert not result.ok

    def test_email_input_bcc_string_split(self):
        from core.adapters.shopify.order_invoice import (
            ShopifyOrderInvoiceSendAdapter,
        )
        a = ShopifyOrderInvoiceSendAdapter(shop_url="s", access_token="t")
        out = a._build_email_input({
            "to": "buyer@example.com",
            "from": "sales@example.com",
            "bcc": "x@y.com, z@y.com",
            "subject": "Receipt",
            "custom_message": "Replacement copy.",
        })
        assert out["to"] == "buyer@example.com"
        assert out["from"] == "sales@example.com"
        assert out["bcc"] == ["x@y.com", "z@y.com"]
        assert out["customMessage"] == "Replacement copy."

    def test_email_to_must_be_string(self):
        from core.adapters.shopify.order_invoice import (
            ShopifyOrderInvoiceSendAdapter,
        )
        a = ShopifyOrderInvoiceSendAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_email_input({"to": 123})

    def test_send_happy_path(self):
        from core.adapters.shopify.order_invoice import (
            ShopifyOrderInvoiceSendAdapter,
        )
        a = ShopifyOrderInvoiceSendAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"orderInvoiceSend": {
                "order": {
                    "id": v["id"],
                    "name": "#1001",
                    "email": v.get("email", {}).get(
                        "to", "buyer@y.com",
                    ),
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_SEND_ORDER_INVOICE,
                {
                    "order_id": "gid://shopify/Order/1",
                    "to": "buyer@example.com",
                    "subject": "Your receipt",
                },
            )
        assert result.ok
        # Pattern A: id at field level.
        assert captured["id"] == "gid://shopify/Order/1"
        assert captured["email"]["to"] == "buyer@example.com"
        assert result.data["order_name"] == "#1001"
        assert result.data["email"] == "buyer@example.com"

    def test_send_works_without_email_input(self):
        from core.adapters.shopify.order_invoice import (
            ShopifyOrderInvoiceSendAdapter,
        )
        a = ShopifyOrderInvoiceSendAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"orderInvoiceSend": {
                "order": {
                    "id": v["id"],
                    "name": "#1001",
                    "email": "buyer@y.com",
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_SEND_ORDER_INVOICE,
                {"order_id": "gid://shopify/Order/1"},
            )
        assert "email" not in captured

    def test_send_user_errors_fail_fast(self):
        from core.adapters.shopify.order_invoice import (
            ShopifyOrderInvoiceSendAdapter,
        )
        a = ShopifyOrderInvoiceSendAdapter(shop_url="s", access_token="t")
        # Pattern F: orderInvoiceSend.userErrors is bare UserError
        # (no code field). Test fixture omits 'code'.
        with patch.object(a, "_gql", return_value={"orderInvoiceSend": {
            "order": None,
            "userErrors": [{"field": ["email", "to"],
                            "message": "Invalid email"}],
        }}):
            result = a.execute(
                Capability.SHOPIFY_SEND_ORDER_INVOICE,
                {
                    "order_id": "gid://shopify/Order/1",
                    "to": "not-an-email",
                },
            )
        assert not result.ok


# ── ShopifyCompanyContactRolesAdapter ─────────────────────


class TestShopifyCompanyContactRolesAdapter:
    def test_metadata(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter()
        assert a.name == "shopify_company_contact_roles"
        for cap in (
            Capability.SHOPIFY_LIST_COMPANY_CONTACT_ROLES,
            Capability.SHOPIFY_ASSIGN_COMPANY_CONTACT_ROLE,
            Capability.SHOPIFY_REVOKE_COMPANY_CONTACT_ROLE,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_requires_company_id(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_LIST_COMPANY_CONTACT_ROLES, {},
        )
        assert not result.ok

    def test_list_happy_path(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "company": {
                "id": "gid://shopify/Company/c1",
                "name": "Acme Corp",
                "contactRoles": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "edges": [
                        {"node": {
                            "id": "gid://shopify/CompanyContactRole/1",
                            "name": "Ordering",
                            "note": "Can place orders",
                        }},
                        {"node": {
                            "id": "gid://shopify/CompanyContactRole/2",
                            "name": "Location_admin",
                            "note": "",
                        }},
                    ],
                },
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_COMPANY_CONTACT_ROLES,
                {"company_id": "gid://shopify/Company/c1"},
            )
        assert result.ok
        assert result.data["count"] == 2
        assert result.data["company_found"] is True
        names = {r["name"] for r in result.data["roles"]}
        assert names == {"Ordering", "Location_admin"}

    def test_list_handles_missing_company(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"company": None}):
            result = a.execute(
                Capability.SHOPIFY_LIST_COMPANY_CONTACT_ROLES,
                {"company_id": "gid://shopify/Company/missing"},
            )
        assert result.ok
        assert result.data["company_found"] is False
        assert result.data["count"] == 0

    def test_list_clamps_limit(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"company": None}

        with patch.object(a, "_gql", side_effect=fake_gql):
            a.execute(
                Capability.SHOPIFY_LIST_COMPANY_CONTACT_ROLES,
                {
                    "company_id": "gid://shopify/Company/c1",
                    "limit": 9999,
                },
            )
        assert captured["first"] == 250

    # ── Assign ───────────────────────────────────

    def test_assign_requires_location_id(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_ASSIGN_COMPANY_CONTACT_ROLE,
            {"assignments": [{"contact_id": "c1", "role_id": "r1"}]},
        )
        assert not result.ok

    def test_assign_requires_assignments(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_ASSIGN_COMPANY_CONTACT_ROLE,
            {"company_location_id": "gid://shopify/CompanyLocation/1"},
        )
        assert not result.ok

    def test_assign_each_entry_needs_contact_and_role(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_ASSIGN_COMPANY_CONTACT_ROLE,
            {
                "company_location_id": "gid://shopify/CompanyLocation/1",
                "assignments": [{"contact_id": "c1"}],
            },
        )
        assert not result.ok

    def test_assign_happy_path(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"companyLocationAssignRoles": {
                "roleAssignments": [{
                    "id": "gid://shopify/CompanyContactRoleAssignment/ra1",
                    "role": {
                        "id": "gid://shopify/CompanyContactRole/1",
                        "name": "Ordering",
                    },
                    "companyContact": {
                        "id": "gid://shopify/CompanyContact/c1",
                    },
                    "companyLocation": {
                        "id": v["companyLocationId"],
                    },
                }],
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_ASSIGN_COMPANY_CONTACT_ROLE,
                {
                    "company_location_id":
                        "gid://shopify/CompanyLocation/loc1",
                    "assignments": [
                        {
                            "contact_id":
                                "gid://shopify/CompanyContact/c1",
                            "role_id":
                                "gid://shopify/CompanyContactRole/1",
                        },
                    ],
                },
            )
        assert result.ok
        # Pattern A: locationId at field level + rolesToAssign list.
        assert captured["companyLocationId"] == \
            "gid://shopify/CompanyLocation/loc1"
        assert captured["rolesToAssign"][0]["companyContactId"] == \
            "gid://shopify/CompanyContact/c1"
        assert result.data["count"] == 1
        assert result.data["assignments"][0]["role_name"] == "Ordering"

    def test_assign_user_errors_fail_fast(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "companyLocationAssignRoles": {
                "roleAssignments": [],
                "userErrors": [{"field": ["companyLocationId"],
                                "message": "Location not found",
                                "code": "INVALID"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_ASSIGN_COMPANY_CONTACT_ROLE,
                {
                    "company_location_id":
                        "gid://shopify/CompanyLocation/missing",
                    "assignments": [
                        {"contact_id": "c1", "role_id": "r1"},
                    ],
                },
            )
        assert not result.ok

    # ── Revoke ───────────────────────────────────

    def test_revoke_requires_location(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_REVOKE_COMPANY_CONTACT_ROLE,
            {"role_assignment_ids":
             ["gid://shopify/CompanyContactRoleAssignment/ra1"]},
        )
        assert not result.ok

    def test_revoke_requires_role_ids(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_REVOKE_COMPANY_CONTACT_ROLE,
            {"company_location_id": "gid://shopify/CompanyLocation/1"},
        )
        assert not result.ok

    def test_revoke_accepts_string_id(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"companyLocationRevokeRoles": {
                "revokedRoleAssignmentIds": v["rolesToRevoke"],
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_REVOKE_COMPANY_CONTACT_ROLE,
                {
                    "company_location_id":
                        "gid://shopify/CompanyLocation/loc1",
                    "role_assignment_ids":
                        "gid://shopify/CompanyContactRoleAssignment/ra1",
                },
            )
        assert result.ok
        assert captured["rolesToRevoke"] == [
            "gid://shopify/CompanyContactRoleAssignment/ra1",
        ]
        assert result.data["count"] == 1

    def test_revoke_happy_path(self):
        from core.adapters.shopify.company_contact_roles import (
            ShopifyCompanyContactRolesAdapter,
        )
        a = ShopifyCompanyContactRolesAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "companyLocationRevokeRoles": {
                "revokedRoleAssignmentIds": [
                    "gid://shopify/CompanyContactRoleAssignment/ra1",
                    "gid://shopify/CompanyContactRoleAssignment/ra2",
                ],
                "userErrors": [],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_REVOKE_COMPANY_CONTACT_ROLE,
                {
                    "company_location_id":
                        "gid://shopify/CompanyLocation/loc1",
                    "role_assignment_ids": [
                        "gid://shopify/CompanyContactRoleAssignment/ra1",
                        "gid://shopify/CompanyContactRoleAssignment/ra2",
                    ],
                },
            )
        assert result.ok
        assert result.data["count"] == 2
        assert "gid://shopify/CompanyContactRoleAssignment/ra1" in (
            result.data["revoked_assignment_ids"]
        )


# ── ShopifyMetaobjectsUpsertAdapter ───────────────────────


class TestShopifyMetaobjectsUpsertAdapter:
    def test_metadata(self):
        from core.adapters.shopify.metaobjects_upsert import (
            ShopifyMetaobjectsUpsertAdapter,
        )
        a = ShopifyMetaobjectsUpsertAdapter()
        assert a.name == "shopify_metaobjects_upsert"
        for cap in (
            Capability.SHOPIFY_UPSERT_METAOBJECT,
            Capability.SHOPIFY_BULK_DELETE_METAOBJECTS,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.metaobjects_upsert import (
            ShopifyMetaobjectsUpsertAdapter,
        )
        a = ShopifyMetaobjectsUpsertAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Upsert ───────────────────────────────────

    def test_upsert_requires_type(self):
        from core.adapters.shopify.metaobjects_upsert import (
            ShopifyMetaobjectsUpsertAdapter,
        )
        a = ShopifyMetaobjectsUpsertAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPSERT_METAOBJECT, {
            "handle": "x",
            "fields": [{"key": "title", "value": "x"}],
        })
        assert not result.ok

    def test_upsert_requires_handle(self):
        from core.adapters.shopify.metaobjects_upsert import (
            ShopifyMetaobjectsUpsertAdapter,
        )
        a = ShopifyMetaobjectsUpsertAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPSERT_METAOBJECT, {
            "type": "recipe",
            "fields": [{"key": "title", "value": "x"}],
        })
        assert not result.ok

    def test_upsert_requires_non_empty_fields(self):
        from core.adapters.shopify.metaobjects_upsert import (
            ShopifyMetaobjectsUpsertAdapter,
        )
        a = ShopifyMetaobjectsUpsertAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPSERT_METAOBJECT, {
            "type": "recipe", "handle": "x", "fields": [],
        })
        assert not result.ok

    def test_upsert_field_requires_key(self):
        from core.adapters.shopify.metaobjects_upsert import (
            ShopifyMetaobjectsUpsertAdapter,
        )
        a = ShopifyMetaobjectsUpsertAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_UPSERT_METAOBJECT, {
            "type": "recipe", "handle": "x",
            "fields": [{"value": "x"}],
        })
        assert not result.ok

    def test_upsert_field_value_coerced_to_string(self):
        from core.adapters.shopify.metaobjects_upsert import (
            ShopifyMetaobjectsUpsertAdapter,
        )
        a = ShopifyMetaobjectsUpsertAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"metaobjectUpsert": {
                "metaobject": {
                    "id": "gid://shopify/Metaobject/m1",
                    "type": v["handle"]["type"],
                    "handle": v["handle"]["handle"],
                    "fields": v["metaobject"]["fields"],
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(Capability.SHOPIFY_UPSERT_METAOBJECT, {
                "type": "recipe",
                "handle": "cookies",
                "fields": [
                    {"key": "title", "value": "Cookies"},
                    # Numeric value gets coerced to string per
                    # metafield convention.
                    {"key": "cook_time_minutes", "value": 12},
                ],
            })
        assert result.ok
        # Pattern A: handle lookup + metaobject input as separate args.
        assert captured["handle"]["type"] == "recipe"
        assert captured["handle"]["handle"] == "cookies"
        assert captured["metaobject"]["fields"][1]["value"] == "12"
        m = result.data["metaobject"]
        assert m["type"] == "recipe"
        assert m["handle"] == "cookies"
        assert m["field_map"]["title"] == "Cookies"

    def test_upsert_user_errors_fail_fast(self):
        from core.adapters.shopify.metaobjects_upsert import (
            ShopifyMetaobjectsUpsertAdapter,
        )
        a = ShopifyMetaobjectsUpsertAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"metaobjectUpsert": {
            "metaobject": None,
            "userErrors": [{"field": ["handle"],
                            "message": "Type not found",
                            "code": "INVALID"}],
        }}):
            result = a.execute(Capability.SHOPIFY_UPSERT_METAOBJECT, {
                "type": "missing", "handle": "x",
                "fields": [{"key": "title", "value": "x"}],
            })
        assert not result.ok

    # ── Bulk delete ──────────────────────────────

    def test_bulk_delete_requires_ids(self):
        from core.adapters.shopify.metaobjects_upsert import (
            ShopifyMetaobjectsUpsertAdapter,
        )
        a = ShopifyMetaobjectsUpsertAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_BULK_DELETE_METAOBJECTS, {},
        )
        assert not result.ok

    def test_bulk_delete_accepts_string_id(self):
        from core.adapters.shopify.metaobjects_upsert import (
            ShopifyMetaobjectsUpsertAdapter,
        )
        a = ShopifyMetaobjectsUpsertAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"metaobjectBulkDelete": {
                "job": {
                    "id": "gid://shopify/Job/j1",
                    "done": False,
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_BULK_DELETE_METAOBJECTS,
                {"ids": "gid://shopify/Metaobject/m1"},
            )
        assert result.ok
        assert captured["where"]["ids"] == ["gid://shopify/Metaobject/m1"]

    def test_bulk_delete_happy_path(self):
        from core.adapters.shopify.metaobjects_upsert import (
            ShopifyMetaobjectsUpsertAdapter,
        )
        a = ShopifyMetaobjectsUpsertAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "metaobjectBulkDelete": {
                "job": {
                    "id": "gid://shopify/Job/j1",
                    "done": False,
                },
                "userErrors": [],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_BULK_DELETE_METAOBJECTS,
                {"ids": [
                    "gid://shopify/Metaobject/m1",
                    "gid://shopify/Metaobject/m2",
                ]},
            )
        assert result.ok
        assert result.data["job_id"] == "gid://shopify/Job/j1"
        assert result.data["queued_count"] == 2

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.metaobjects_upsert import (
            ShopifyMetaobjectsUpsertAdapter,
        )
        assert ShopifyMetaobjectsUpsertAdapter._normalise_metaobject({}) == {}
        assert ShopifyMetaobjectsUpsertAdapter._normalise_metaobject(None) == {}


# ── ShopifyAppSubscriptionsAdapter ────────────────────────


class TestShopifyAppSubscriptionsAdapter:
    def test_metadata(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter()
        assert a.name == "shopify_app_subscriptions"
        for cap in (
            Capability.SHOPIFY_LIST_APP_SUBSCRIPTIONS,
            Capability.SHOPIFY_CREATE_APP_SUBSCRIPTION,
            Capability.SHOPIFY_CANCEL_APP_SUBSCRIPTION,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── List ─────────────────────────────────────

    def test_list_happy_path(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "currentAppInstallation": {
                "activeSubscriptions": [{
                    "id": "gid://shopify/AppSubscription/sub1",
                    "name": "ShopAI Pro",
                    "status": "ACTIVE",
                    "test": False,
                    "trialDays": 14,
                    "currentPeriodEnd": "2026-05-25T00:00:00Z",
                    "lineItems": [{
                        "id": "gid://shopify/AppSubscriptionLineItem/li1",
                        "plan": {
                            "pricingDetails": {
                                "__typename": "AppRecurringPricing",
                                "interval": "EVERY_30_DAYS",
                                "price": {
                                    "amount": "29.99",
                                    "currencyCode": "USD",
                                },
                            },
                        },
                    }],
                }],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_APP_SUBSCRIPTIONS, {},
            )
        assert result.ok
        assert result.data["count"] == 1
        sub = result.data["subscriptions"][0]
        assert sub["name"] == "ShopAI Pro"
        assert sub["status"] == "ACTIVE"
        assert sub["trial_days"] == 14
        assert sub["line_items"][0]["kind"] == "AppRecurringPricing"
        assert sub["line_items"][0]["price"] == "29.99"

    def test_list_handles_no_installation(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={
            "currentAppInstallation": None,
        }):
            result = a.execute(
                Capability.SHOPIFY_LIST_APP_SUBSCRIPTIONS, {},
            )
        assert result.ok
        assert result.data["count"] == 0
        assert result.data["installation_found"] is False

    # ── Input builder ────────────────────────────

    def test_create_requires_name(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_CREATE_APP_SUBSCRIPTION, {
            "return_url": "https://x.com/done",
            "line_items": [{
                "recurring": {"price": "10", "interval": "EVERY_30_DAYS"},
            }],
        })
        assert not result.ok

    def test_create_requires_return_url(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_CREATE_APP_SUBSCRIPTION, {
            "name": "Plan",
            "line_items": [{
                "recurring": {"price": "10", "interval": "EVERY_30_DAYS"},
            }],
        })
        assert not result.ok

    def test_create_return_url_must_be_http(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_CREATE_APP_SUBSCRIPTION, {
            "name": "Plan",
            "return_url": "ftp://x.com/done",
            "line_items": [{
                "recurring": {"price": "10", "interval": "EVERY_30_DAYS"},
            }],
        })
        assert not result.ok

    def test_create_requires_line_items(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        result = a.execute(Capability.SHOPIFY_CREATE_APP_SUBSCRIPTION, {
            "name": "Plan", "return_url": "https://x.com/done",
        })
        assert not result.ok

    def test_line_item_rejects_both_recurring_and_usage(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_line_item({
                "recurring": {"price": "10"},
                "usage": {"terms": "t", "capped_amount": "100"},
            }, 0)

    def test_recurring_invalid_interval_rejected(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        with pytest.raises(AdapterValidationError):
            a._build_recurring(
                {"price": "10", "interval": "WEEKLY"}, 0,
            )

    def test_recurring_full_shape(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        out = a._build_recurring({
            "price": "29.99",
            "interval": "every_30_days",
            "discount": {
                "duration_limit_in_intervals": 3,
                "value": {"percentage": 0.5},
            },
        }, 0)
        assert out["price"]["amount"] == 29.99
        assert out["interval"] == "EVERY_30_DAYS"
        assert out["discount"]["durationLimitInIntervals"] == 3
        assert out["discount"]["value"]["percentage"] == 0.5

    def test_usage_full_shape(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        out = a._build_usage({
            "terms": "Per metaobject upsert",
            "capped_amount": "100",
        }, 0)
        assert out["terms"] == "Per metaobject upsert"
        assert out["cappedAmount"]["amount"] == 100.0
        assert out["cappedAmount"]["currencyCode"] == "USD"

    # ── Create — happy path ──────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"appSubscriptionCreate": {
                "appSubscription": {
                    "id": "gid://shopify/AppSubscription/new",
                    "name": v["name"],
                    "status": "PENDING",
                    "test": v.get("test", False),
                    "trialDays": v.get("trialDays", 0),
                },
                "confirmationUrl":
                    "https://shopify-shop.myshopify.com/admin/charges/123/RECURRING_APPLICATION_CHARGE/123",
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_APP_SUBSCRIPTION,
                {
                    "name": "ShopAI Pro",
                    "return_url": "https://shopai.dev/billing/success",
                    "test": True,
                    "trial_days": 14,
                    "line_items": [{
                        "recurring": {
                            "price": "29.99",
                            "interval": "EVERY_30_DAYS",
                        },
                    }],
                },
            )
        assert result.ok
        assert captured["name"] == "ShopAI Pro"
        assert captured["test"] is True
        assert captured["trialDays"] == 14
        assert (captured["lineItems"][0]["plan"]
                ["appRecurringPricingDetails"]["interval"]
                == "EVERY_30_DAYS")
        assert "confirmation_url" in result.data
        assert "/admin/charges/" in result.data["confirmation_url"]

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        with patch.object(a, "_gql", return_value={"appSubscriptionCreate": {
            "appSubscription": None,
            "confirmationUrl": None,
            "userErrors": [{"field": ["lineItems"],
                            "message": "Plan exceeds quota",
                            "code": "INVALID"}],
        }}):
            result = a.execute(
                Capability.SHOPIFY_CREATE_APP_SUBSCRIPTION,
                {
                    "name": "Plan",
                    "return_url": "https://x.com/done",
                    "line_items": [{
                        "recurring": {"price": "9999",
                                      "interval": "EVERY_30_DAYS"},
                    }],
                },
            )
        assert not result.ok

    # ── Cancel ───────────────────────────────────

    def test_cancel_requires_id(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        result = a.execute(
            Capability.SHOPIFY_CANCEL_APP_SUBSCRIPTION, {},
        )
        assert not result.ok

    def test_cancel_happy_path(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        a = ShopifyAppSubscriptionsAdapter(shop_url="s", access_token="t")
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"appSubscriptionCancel": {
                "appSubscription": {
                    "id": v["id"],
                    "status": "CANCELLED",
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CANCEL_APP_SUBSCRIPTION,
                {
                    "id": "gid://shopify/AppSubscription/sub1",
                    "prorate": True,
                },
            )
        assert result.ok
        assert captured["prorate"] is True
        assert result.data["status"] == "CANCELLED"

    def test_normalise_handles_empty(self):
        from core.adapters.shopify.app_subscriptions import (
            ShopifyAppSubscriptionsAdapter,
        )
        assert ShopifyAppSubscriptionsAdapter._normalise_subscription(
            {},
        ) == {}


# ── ShopifyDiscountCodeFreeShippingAdapter ────────────────


class TestShopifyDiscountCodeFreeShippingAdapter:
    def test_metadata(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter()
        assert a.name == "shopify_discount_code_free_shipping"
        for cap in (
            Capability.SHOPIFY_CREATE_DISCOUNT_FREE_SHIPPING,
            Capability.SHOPIFY_DELETE_DISCOUNT_FREE_SHIPPING,
        ):
            assert cap in a.capabilities

    def test_unsupported_capability_returns_failure(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql"):
            result = a.execute(Capability.SHOPIFY_ASSESS_RISK, {})
        assert not result.ok

    # ── Input ────────────────────────────────────

    def test_create_requires_title(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter(
            shop_url="s", access_token="t",
        )
        with pytest.raises(AdapterValidationError):
            a._build_input({
                "code": "SHIPFREE",
                "starts_at": "2026-04-26T00:00:00Z",
            })

    def test_create_requires_code(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter(
            shop_url="s", access_token="t",
        )
        with pytest.raises(AdapterValidationError):
            a._build_input({
                "title": "Free Ship",
                "starts_at": "2026-04-26T00:00:00Z",
            })

    def test_default_destination_is_all(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter(
            shop_url="s", access_token="t",
        )
        out = a._build_input({
            "title": "Free Ship",
            "code": "SHIPFREE",
            "starts_at": "2026-04-26T00:00:00Z",
        })
        assert out["destination"] == {"all": True}
        # Pattern C from BXGY: customerSelection silently required.
        assert out["customerSelection"] == {"all": True}

    def test_destination_countries_uppercase(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter(
            shop_url="s", access_token="t",
        )
        out = a._build_destination({"countries": ["us", "ca"]})
        assert out["countries"]["add"] == ["US", "CA"]
        assert out["countries"]["includeRestOfWorld"] is False

    def test_destination_invalid_shape_rejected(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter(
            shop_url="s", access_token="t",
        )
        with pytest.raises(AdapterValidationError):
            a._build_destination({})

    def test_minimum_subtotal_passed(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter(
            shop_url="s", access_token="t",
        )
        out = a._build_input({
            "title": "Free Ship",
            "code": "SHIPFREE50",
            "starts_at": "2026-04-26T00:00:00Z",
            "minimum_subtotal": 50,
        })
        assert (out["minimumRequirement"]["subtotal"]
                ["greaterThanOrEqualToSubtotal"] == 50.0)

    def test_input_full_shape(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter(
            shop_url="s", access_token="t",
        )
        out = a._build_input({
            "title": "Free Ship US/CA",
            "code": "SHIPFREEUSCA",
            "starts_at": "2026-04-26T00:00:00Z",
            "ends_at": "2026-12-31T23:59:59Z",
            "minimum_subtotal": "25.00",
            "destination": {"countries": ["US", "CA"]},
            "applies_once_per_customer": True,
            "usage_limit": 1000,
        })
        assert out["title"] == "Free Ship US/CA"
        assert out["code"] == "SHIPFREEUSCA"
        assert out["appliesOncePerCustomer"] is True
        assert out["usageLimit"] == 1000
        assert out["destination"]["countries"]["add"] == ["US", "CA"]

    # ── Create ───────────────────────────────────

    def test_create_happy_path(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter(
            shop_url="s", access_token="t",
        )
        captured: dict = {}

        def fake_gql(q, v):
            captured.update(v)
            return {"discountCodeFreeShippingCreate": {
                "codeDiscountNode": {
                    "id": "gid://shopify/DiscountCodeNode/new",
                    "codeDiscount": {
                        "title":
                            v["freeShippingCodeDiscount"]["title"],
                        "summary": "Free shipping",
                        "status": "ACTIVE",
                        "startsAt":
                            v["freeShippingCodeDiscount"]["startsAt"],
                        "endsAt": "",
                        "appliesOncePerCustomer": False,
                        "usageLimit": None,
                        "codes": {"edges": [{
                            "node": {
                                "code":
                                    v["freeShippingCodeDiscount"]["code"],
                            },
                        }]},
                    },
                },
                "userErrors": [],
            }}

        with patch.object(a, "_gql", side_effect=fake_gql):
            result = a.execute(
                Capability.SHOPIFY_CREATE_DISCOUNT_FREE_SHIPPING,
                {
                    "title": "Free Shipping",
                    "code": "SHIPFREE",
                    "starts_at": "2026-04-26T00:00:00Z",
                },
            )
        assert result.ok
        # Pattern A: variable name matches input type.
        assert captured["freeShippingCodeDiscount"]["title"] == \
            "Free Shipping"
        assert "SHIPFREE" in result.data["codes"]
        assert result.data["status"] == "ACTIVE"

    def test_create_user_errors_fail_fast(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql", return_value={
            "discountCodeFreeShippingCreate": {
                "codeDiscountNode": None,
                "userErrors": [{"field":
                                ["freeShippingCodeDiscount", "code"],
                                "message": "Code is taken",
                                "code": "TAKEN"}],
            }
        }):
            result = a.execute(
                Capability.SHOPIFY_CREATE_DISCOUNT_FREE_SHIPPING,
                {
                    "title": "Dup",
                    "code": "DUP",
                    "starts_at": "2026-04-26T00:00:00Z",
                },
            )
        assert not result.ok

    # ── Delete ───────────────────────────────────

    def test_delete_requires_id(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter(
            shop_url="s", access_token="t",
        )
        result = a.execute(
            Capability.SHOPIFY_DELETE_DISCOUNT_FREE_SHIPPING, {},
        )
        assert not result.ok

    def test_delete_happy_path(self):
        from core.adapters.shopify.discount_code_free_shipping import (
            ShopifyDiscountCodeFreeShippingAdapter,
        )
        a = ShopifyDiscountCodeFreeShippingAdapter(
            shop_url="s", access_token="t",
        )
        with patch.object(a, "_gql", return_value={"discountCodeDelete": {
            "deletedCodeDiscountId":
                "gid://shopify/DiscountCodeNode/1",
            "userErrors": [],
        }}):
            result = a.execute(
                Capability.SHOPIFY_DELETE_DISCOUNT_FREE_SHIPPING,
                {"id": "gid://shopify/DiscountCodeNode/1"},
            )
        assert result.ok
        assert result.data["deleted_id"] == \
            "gid://shopify/DiscountCodeNode/1"

