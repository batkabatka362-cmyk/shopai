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
    def test_register_all_adds_thirty_adapters(self):
        from core.adapters.shopify.bootstrap import register_all
        status = register_all()
        assert len(status) == 30
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
        }

    def test_register_all_idempotent(self):
        from core.adapters.shopify.bootstrap import register_all
        register_all()
        # Second call must not raise
        register_all()
        assert len(get_registry()) == 30

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
