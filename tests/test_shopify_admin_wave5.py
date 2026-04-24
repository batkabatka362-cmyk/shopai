"""Wave 5 shopify_admin — shop + locales + currencies +
access scopes (+ 5b-f add to this file)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)
from core.adapters.shopify_admin.shop import (
    AccessScopes, Currencies, Locales, Shop,
)


def _fake_client():
    return MagicMock(spec=ShopifyAdminClient)


# ── Shop ──────────────────────────────────────────────────


class TestShopGet:
    def test_happy(self):
        c = _fake_client()
        c.get.return_value = {
            "shop": {
                "id": 99, "name": "Deguar",
                "email": "owner@deguar.com",
                "currency": "USD",
            },
        }
        shop = Shop.get(c)
        assert shop["name"] == "Deguar"

    def test_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            Shop.get(c)


class TestShopMetafields:
    def test_list_with_namespace(self):
        c = _fake_client()
        c.get.return_value = {"metafields": [
            {"id": 1, "namespace": "shopai"}, "oops",
        ]}
        out = Shop.list_metafields(c, namespace="shopai")
        assert len(out) == 1
        params = c.get.call_args[1]["params"]
        assert params["namespace"] == "shopai"

    def test_list_limit_clamped(self):
        c = _fake_client()
        c.get.return_value = {"metafields": []}
        Shop.list_metafields(c, limit=9999)
        assert c.get.call_args[1]["params"]["limit"] == 250

    def test_create_requires_namespace_and_key(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Shop.create_metafield(
                c, namespace="", key="k", value="v",
            )
        with pytest.raises(ValueError):
            Shop.create_metafield(
                c, namespace="n", key="", value="v",
            )

    def test_create_happy(self):
        c = _fake_client()
        c.post.return_value = {"metafield": {"id": 1}}
        out = Shop.create_metafield(
            c, namespace="shopai", key="brand",
            value='{"voice":"calm_cozy"}',
            value_type="json",
        )
        assert out["id"] == 1
        body = c.post.call_args[0][1]["metafield"]
        assert body["namespace"] == "shopai"
        assert body["type"] == "json"

    def test_update_happy(self):
        c = _fake_client()
        c.put.return_value = {
            "metafield": {"id": 1, "value": "new"},
        }
        out = Shop.update_metafield(
            c, 1, value="new", value_type="json",
        )
        assert out["value"] == "new"
        body = c.put.call_args[0][1]["metafield"]
        assert body["id"] == 1
        assert body["value"] == "new"

    def test_delete(self):
        c = _fake_client()
        Shop.delete_metafield(c, 7)
        assert c.delete.call_args[0][0] == "metafields/7.json"


# ── AccessScopes ──────────────────────────────────────────


class TestAccessScopes:
    def test_list_scopes(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {
                "currentAppInstallation": {
                    "accessScopes": [
                        {"handle": "read_products"},
                        {"handle": "write_products"},
                        "malformed",
                    ],
                },
            },
        }
        out = AccessScopes.list_scopes(c)
        assert out == ["read_products", "write_products"]

    def test_has_scope_true(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"currentAppInstallation": {
                "accessScopes": [{"handle": "write_products"}],
            }},
        }
        assert AccessScopes.has_scope(c, "write_products")

    def test_has_scope_false(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"currentAppInstallation": {
                "accessScopes": [{"handle": "read_products"}],
            }},
        }
        assert not AccessScopes.has_scope(c, "write_orders")

    def test_has_scope_empty_handle(self):
        c = _fake_client()
        assert AccessScopes.has_scope(c, "") is False


# ── Locales ──────────────────────────────────────────────


class TestLocales:
    def test_list(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"shopLocales": [
                {"locale": "en", "primary": True},
                {"locale": "de", "primary": False},
                "oops",
            ]},
        }
        out = Locales.list_locales(c)
        assert len(out) == 2

    def test_enable_happy(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"shopLocaleEnable": {
                "shopLocale": {"locale": "de", "published": False},
                "userErrors": [],
            }},
        }
        out = Locales.enable(c, "de")
        assert out["locale"] == "de"

    def test_enable_requires_locale(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Locales.enable(c, "")

    def test_enable_user_error_raises(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"shopLocaleEnable": {
                "shopLocale": None,
                "userErrors": [{
                    "field": "locale",
                    "message": "not supported",
                }],
            }},
        }
        with pytest.raises(ShopifyAdminError):
            Locales.enable(c, "zz")

    def test_disable_returns_handle(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"shopLocaleDisable": {
                "locale": "de", "userErrors": [],
            }},
        }
        assert Locales.disable(c, "de") == "de"

    def test_set_published(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"shopLocaleUpdate": {
                "shopLocale": {"locale": "de", "published": True},
                "userErrors": [],
            }},
        }
        out = Locales.set_published(
            c, "de", published=True,
        )
        assert out["published"] is True
        variables = c.graphql.call_args[1]["variables"]
        assert (
            variables["shopLocale"]["published"] is True
        )


# ── Currencies ───────────────────────────────────────────


class TestCurrencies:
    def test_get_settings(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"shop": {
                "currencyCode": "USD",
                "enabledPresentmentCurrencies": [
                    "USD", "EUR", "GBP",
                ],
                "currencyFormats": {
                    "moneyFormat": "${{amount}}",
                    "moneyWithCurrencyFormat": (
                        "${{amount}} USD"
                    ),
                },
            }},
        }
        out = Currencies.get_settings(c)
        assert out["base"] == "USD"
        assert "EUR" in out["enabled_presentment"]
        assert out["money_format"] == "${{amount}}"

    def test_enable_uppercases(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"currencyActivate": {
                "currencySettings": [
                    {"currencyCode": "EUR", "enabled": True},
                ],
                "userErrors": [],
            }},
        }
        out = Currencies.enable(c, ["eur"])
        assert out[0]["currencyCode"] == "EUR"
        variables = c.graphql.call_args[1]["variables"]
        assert variables["currencies"] == ["EUR"]

    def test_enable_requires_list(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Currencies.enable(c, [])

    def test_disable_happy(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"currencyDeactivate": {
                "currencySettings": [],
                "userErrors": [],
            }},
        }
        Currencies.disable(c, ["EUR"])
        variables = c.graphql.call_args[1]["variables"]
        assert variables["currencies"] == ["EUR"]

    def test_disable_user_error_raises(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"currencyDeactivate": {
                "currencySettings": [],
                "userErrors": [{
                    "field": "currencies",
                    "message": "cannot disable base",
                }],
            }},
        }
        with pytest.raises(ShopifyAdminError):
            Currencies.disable(c, ["USD"])


# ── OrderRisks (wave 5b additions) ───────────────────────


from core.adapters.shopify_admin.orders import OrderRisks


class TestOrderRisksGetUpdate:
    def test_get_happy(self):
        c = _fake_client()
        c.get.return_value = {
            "risk": {
                "id": 7, "order_id": 99,
                "recommendation": "accept",
            },
        }
        out = OrderRisks.get(c, 99, 7)
        assert out["recommendation"] == "accept"
        assert (
            c.get.call_args[0][0]
            == "orders/99/risks/7.json"
        )

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            OrderRisks.get(c, 99, 7)

    def test_update_empty_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            OrderRisks.update(c, 99, 7, fields={})

    def test_update_happy(self):
        c = _fake_client()
        c.put.return_value = {
            "risk": {
                "id": 7, "recommendation": "cancel",
            },
        }
        out = OrderRisks.update(
            c, 99, 7,
            fields={"recommendation": "cancel"},
        )
        assert out["recommendation"] == "cancel"
        body = c.put.call_args[0][1]["risk"]
        assert body["id"] == 7


# ── Disputes ─────────────────────────────────────────────


from core.adapters.shopify_admin.disputes import Disputes


class TestDisputes:
    def test_list_basic(self):
        c = _fake_client()
        c.get.return_value = {"disputes": [
            {"id": 1, "status": "needs_response"},
            "malformed",
        ]}
        out = Disputes.list_disputes(c)
        assert len(out) == 1
        assert (
            c.get.call_args[0][0]
            == "shopify_payments/disputes.json"
        )

    def test_list_validates_status_enum(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Disputes.list_disputes(c, status="fake")

    def test_list_with_filters(self):
        c = _fake_client()
        c.get.return_value = {"disputes": []}
        Disputes.list_disputes(
            c,
            status="under_review",
            initiated_at_min="2026-04-01T00:00:00Z",
            initiated_at_max="2026-04-30T00:00:00Z",
        )
        params = c.get.call_args[1]["params"]
        assert params["status"] == "under_review"
        assert params["initiated_at_min"] == (
            "2026-04-01T00:00:00Z"
        )
        assert params["initiated_at_max"] == (
            "2026-04-30T00:00:00Z"
        )

    def test_limit_clamped(self):
        c = _fake_client()
        c.get.return_value = {"disputes": []}
        Disputes.list_disputes(c, limit=9999)
        assert c.get.call_args[1]["params"]["limit"] == 250

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            Disputes.get(c, 9)

    def test_needs_response_shortcut(self):
        c = _fake_client()
        c.get.return_value = {"disputes": [
            {"id": 1, "status": "needs_response"},
        ]}
        Disputes.needs_response(c)
        params = c.get.call_args[1]["params"]
        assert params["status"] == "needs_response"

    def test_loss_total_sums_lost_and_refunded(self):
        """Hits both ``lost`` and ``charge_refunded`` buckets
        and sums their ``amount`` fields."""
        c = _fake_client()
        # Two list calls; return lists keyed by status param.
        returns = {
            "lost": {"disputes": [
                {"id": 1, "amount": "12.50"},
                {"id": 2, "amount": "3.00"},
                "malformed",
            ]},
            "charge_refunded": {"disputes": [
                {"id": 3, "amount": "10.00"},
                {"id": 4, "amount": "not-numeric"},
            ]},
        }

        def side_effect(path, *, params=None):
            status = (params or {}).get("status")
            return returns[status]

        c.get.side_effect = side_effect
        out = Disputes.loss_total_usd(
            c, initiated_at_min="2026-04-01",
        )
        # 12.50 + 3.00 + 10.00 = 25.50 (bad amount skipped).
        assert out == 25.50


# ── FulfillmentServices (wave 5c) ────────────────────────


from core.adapters.shopify_admin.fulfillments import (
    FulfillmentEvents, FulfillmentServices,
)


class TestFulfillmentServices:
    def test_list_scope_validated(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            FulfillmentServices.list_services(c, scope="bad")

    def test_list_happy(self):
        c = _fake_client()
        c.get.return_value = {"fulfillment_services": [
            {"id": 1, "name": "3PL A"}, "oops",
        ]}
        out = FulfillmentServices.list_services(c)
        assert len(out) == 1
        assert (
            c.get.call_args[1]["params"]["scope"]
            == "current_client"
        )

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            FulfillmentServices.get(c, 1)

    def test_create_rejects_http_callback(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            FulfillmentServices.create(
                c, name="3PL",
                callback_url="http://insecure.example",
            )

    def test_create_requires_name(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            FulfillmentServices.create(
                c, name="",
                callback_url="https://3pl.example",
            )

    def test_create_happy(self):
        c = _fake_client()
        c.post.return_value = {
            "fulfillment_service": {"id": 7, "name": "3PL"},
        }
        out = FulfillmentServices.create(
            c, name="3PL",
            callback_url="https://3pl.example/hook",
            inventory_management=True,
            tracking_support=False,
        )
        assert out["id"] == 7
        body = c.post.call_args[0][1]["fulfillment_service"]
        assert body["callback_url"] == (
            "https://3pl.example/hook"
        )
        assert body["tracking_support"] is False
        assert body["format"] == "json"

    def test_update_empty_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            FulfillmentServices.update(c, 1, fields={})

    def test_update_happy(self):
        c = _fake_client()
        c.put.return_value = {
            "fulfillment_service": {"id": 1, "name": "new"},
        }
        FulfillmentServices.update(
            c, 1, fields={"name": "new"},
        )
        body = c.put.call_args[0][1]["fulfillment_service"]
        assert body["id"] == 1
        assert body["name"] == "new"

    def test_delete(self):
        c = _fake_client()
        FulfillmentServices.delete(c, 1)
        assert c.delete.call_args[0][0] == (
            "fulfillment_services/1.json"
        )


# ── FulfillmentEvents ────────────────────────────────────


class TestFulfillmentEvents:
    def test_list_basic(self):
        c = _fake_client()
        c.get.return_value = {"fulfillment_events": [
            {"id": 1, "status": "in_transit"}, "oops",
        ]}
        out = FulfillmentEvents.list_events(
            c, order_id=99, fulfillment_id=7,
        )
        assert len(out) == 1
        assert (
            c.get.call_args[0][0]
            == "orders/99/fulfillments/7/events.json"
        )

    def test_create_validates_status(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            FulfillmentEvents.create(
                c, order_id=99, fulfillment_id=7,
                status="teleported",
            )

    def test_create_happy(self):
        c = _fake_client()
        c.post.return_value = {
            "fulfillment_event": {"id": 55},
        }
        out = FulfillmentEvents.create(
            c, order_id=99, fulfillment_id=7,
            status="out_for_delivery",
            message="On the truck",
            city="Ulaanbaatar", country="MN",
            happened_at="2026-04-24T12:00:00Z",
        )
        assert out["id"] == 55
        body = c.post.call_args[0][1]["event"]
        assert body["status"] == "out_for_delivery"
        assert body["city"] == "Ulaanbaatar"
        assert body["country"] == "MN"
        assert body["happened_at"] == (
            "2026-04-24T12:00:00Z"
        )

    def test_create_minimal_omits_optionals(self):
        c = _fake_client()
        c.post.return_value = {
            "fulfillment_event": {"id": 1},
        }
        FulfillmentEvents.create(
            c, order_id=99, fulfillment_id=7,
            status="confirmed",
        )
        body = c.post.call_args[0][1]["event"]
        # Optional keys absent when not passed.
        assert "message" not in body
        assert "city" not in body

    def test_delete(self):
        c = _fake_client()
        FulfillmentEvents.delete(
            c, order_id=99, fulfillment_id=7, event_id=3,
        )
        assert c.delete.call_args[0][0] == (
            "orders/99/fulfillments/7/events/3.json"
        )


# ── Customer metafields + saved searches + segments (5d) ──


from core.adapters.shopify_admin.customers import (
    CustomerMetafields, CustomerSavedSearches,
    CustomerSegments,
)


class TestCustomerMetafields:
    def test_list_with_namespace(self):
        c = _fake_client()
        c.get.return_value = {"metafields": [
            {"id": 1, "namespace": "loyalty"},
        ]}
        out = CustomerMetafields.list_metafields(
            c, 42, namespace="loyalty",
        )
        assert len(out) == 1
        assert (
            c.get.call_args[0][0]
            == "customers/42/metafields.json"
        )
        params = c.get.call_args[1]["params"]
        assert params["namespace"] == "loyalty"

    def test_create_requires_ns_and_key(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            CustomerMetafields.create(
                c, 42, namespace="", key="k", value="v",
            )

    def test_create_happy(self):
        c = _fake_client()
        c.post.return_value = {"metafield": {"id": 9}}
        out = CustomerMetafields.create(
            c, 42,
            namespace="loyalty",
            key="tier",
            value="vip",
            value_type="single_line_text_field",
        )
        assert out["id"] == 9
        body = c.post.call_args[0][1]["metafield"]
        assert body["namespace"] == "loyalty"
        assert body["key"] == "tier"

    def test_update_happy(self):
        c = _fake_client()
        c.put.return_value = {"metafield": {"id": 9}}
        CustomerMetafields.update(
            c, 42, 9, value="gold",
        )
        body = c.put.call_args[0][1]["metafield"]
        assert body["value"] == "gold"

    def test_delete(self):
        c = _fake_client()
        CustomerMetafields.delete(c, 42, 9)
        assert c.delete.call_args[0][0] == (
            "customers/42/metafields/9.json"
        )


class TestCustomerSavedSearches:
    def test_list(self):
        c = _fake_client()
        c.get.return_value = {
            "customer_saved_searches": [
                {"id": 1, "name": "VIP"}, "oops",
            ],
        }
        out = CustomerSavedSearches.list_searches(c)
        assert len(out) == 1

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            CustomerSavedSearches.get(c, 7)

    def test_create_requires_query(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            CustomerSavedSearches.create(
                c, name="VIP", query="",
            )

    def test_create_happy(self):
        c = _fake_client()
        c.post.return_value = {
            "customer_saved_search": {
                "id": 1, "name": "VIP",
            },
        }
        CustomerSavedSearches.create(
            c, name="VIP",
            query="total_spent:>=500 orders_count:>=3",
        )
        body = c.post.call_args[0][1][
            "customer_saved_search"
        ]
        assert body["name"] == "VIP"

    def test_update_empty_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            CustomerSavedSearches.update(
                c, 7, fields={},
            )

    def test_update_happy(self):
        c = _fake_client()
        c.put.return_value = {
            "customer_saved_search": {"id": 7},
        }
        CustomerSavedSearches.update(
            c, 7, fields={"name": "renamed"},
        )
        body = c.put.call_args[0][1][
            "customer_saved_search"
        ]
        assert body["id"] == 7

    def test_delete(self):
        c = _fake_client()
        CustomerSavedSearches.delete(c, 7)
        assert c.delete.call_args[0][0] == (
            "customer_saved_searches/7.json"
        )

    def test_list_matching_customers(self):
        c = _fake_client()
        c.get.return_value = {"customers": [
            {"id": 1}, "oops", {"id": 2},
        ]}
        out = CustomerSavedSearches.list_matching_customers(
            c, 7,
        )
        assert len(out) == 2
        assert (
            c.get.call_args[0][0]
            == "customer_saved_searches/7/customers.json"
        )


class TestCustomerSegments:
    def test_list(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"segments": {"edges": [
                {"node": {
                    "id": "gid://shopify/Segment/1",
                    "name": "High LTV",
                }},
                "malformed",
            ]}},
        }
        out = CustomerSegments.list_segments(c)
        assert len(out) == 1
        assert out[0]["name"] == "High LTV"

    def test_create_requires_query(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            CustomerSegments.create(
                c, name="VIP", query="",
            )

    def test_create_happy(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"segmentCreate": {
                "segment": {
                    "id": "gid://shopify/Segment/9",
                    "name": "VIP",
                },
                "userErrors": [],
            }},
        }
        out = CustomerSegments.create(
            c, name="VIP", query="amount_spent > 500",
        )
        assert out["id"] == "gid://shopify/Segment/9"

    def test_create_user_error_raises(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"segmentCreate": {
                "segment": None,
                "userErrors": [{
                    "field": "query",
                    "message": "invalid syntax",
                }],
            }},
        }
        with pytest.raises(ShopifyAdminError):
            CustomerSegments.create(
                c, name="x", query="garbage",
            )

    def test_delete_returns_gid(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"segmentDelete": {
                "deletedSegmentId":
                    "gid://shopify/Segment/9",
                "userErrors": [],
            }},
        }
        out = CustomerSegments.delete(c, 9)
        assert out == "gid://shopify/Segment/9"

    def test_delete_accepts_full_gid(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"segmentDelete": {
                "deletedSegmentId":
                    "gid://shopify/Segment/7",
                "userErrors": [],
            }},
        }
        CustomerSegments.delete(
            c, "gid://shopify/Segment/7",
        )
        assert (
            c.graphql.call_args[1]["variables"]["id"]
            == "gid://shopify/Segment/7"
        )


# ── Automatic discounts (5e) ──────────────────────────────


from core.adapters.shopify_admin.discounts import (
    AutomaticDiscounts,
)


class TestAutomaticDiscounts:
    def test_list(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"automaticDiscountNodes": {"edges": [
                {"node": {
                    "id":
                        "gid://shopify/DiscountAutomaticNode/1",
                    "automaticDiscount": {
                        "title": "Spring 10%",
                        "status": "ACTIVE",
                        "startsAt": "2026-04-01T00:00:00Z",
                        "endsAt": "2026-04-30T00:00:00Z",
                    },
                }},
                "malformed",
            ]}},
        }
        out = AutomaticDiscounts.list_discounts(c)
        assert len(out) == 1
        assert out[0]["title"] == "Spring 10%"
        assert out[0]["status"] == "ACTIVE"

    def test_create_basic_requires_title(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            AutomaticDiscounts.create_basic_percentage(
                c, title="", value_pct=10,
                starts_at="2026-04-01T00:00:00Z",
            )

    def test_create_basic_invalid_pct(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            AutomaticDiscounts.create_basic_percentage(
                c, title="x", value_pct=0,
                starts_at="2026-04-01T00:00:00Z",
            )
        with pytest.raises(ValueError):
            AutomaticDiscounts.create_basic_percentage(
                c, title="x", value_pct=150,
                starts_at="2026-04-01T00:00:00Z",
            )

    def test_create_basic_happy(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"discountAutomaticBasicCreate": {
                "automaticDiscountNode": {
                    "id":
                        "gid://shopify/DiscountAutomaticNode/7",
                },
                "userErrors": [],
            }},
        }
        out = AutomaticDiscounts.create_basic_percentage(
            c,
            title="Spring 10%",
            value_pct=10,
            starts_at="2026-04-01T00:00:00Z",
            ends_at="2026-04-30T00:00:00Z",
        )
        assert out == (
            "gid://shopify/DiscountAutomaticNode/7"
        )
        variables = c.graphql.call_args[1]["variables"]
        inp = variables["input"]
        # 10% becomes 0.10 decimal on the wire.
        assert inp["customerGets"]["value"][
            "percentage"
        ] == 0.10
        assert inp["endsAt"] == "2026-04-30T00:00:00Z"

    def test_create_basic_user_error_raises(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"discountAutomaticBasicCreate": {
                "automaticDiscountNode": None,
                "userErrors": [{
                    "field": "title",
                    "message": "already exists",
                }],
            }},
        }
        with pytest.raises(ShopifyAdminError):
            AutomaticDiscounts.create_basic_percentage(
                c, title="Dupe", value_pct=10,
                starts_at="2026-04-01T00:00:00Z",
            )

    def test_create_bxgy_validates_quantities(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            AutomaticDiscounts.create_bxgy(
                c, title="BOGO",
                customer_buys_qty=0,
                customer_gets_qty=1,
                starts_at="2026-04-01T00:00:00Z",
            )

    def test_create_bxgy_happy(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"discountAutomaticBxgyCreate": {
                "automaticDiscountNode": {
                    "id":
                        "gid://shopify/DiscountAutomaticNode/9",
                },
                "userErrors": [],
            }},
        }
        out = AutomaticDiscounts.create_bxgy(
            c, title="BOGO",
            customer_buys_qty=2,
            customer_gets_qty=1,
            starts_at="2026-04-01T00:00:00Z",
            uses_per_order_limit=1,
        )
        assert out == (
            "gid://shopify/DiscountAutomaticNode/9"
        )
        inp = c.graphql.call_args[1]["variables"]["input"]
        assert inp["customerBuys"]["value"]["quantity"] == "2"
        assert inp["usesPerOrderLimit"] == "1"

    def test_delete_returns_gid(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"discountAutomaticDelete": {
                "deletedAutomaticDiscountId":
                    "gid://shopify/DiscountAutomaticNode/7",
                "userErrors": [],
            }},
        }
        out = AutomaticDiscounts.delete(c, 7)
        assert out == (
            "gid://shopify/DiscountAutomaticNode/7"
        )


# ── ArticleComments (5e) ─────────────────────────────────


from core.adapters.shopify_admin.content import (
    ArticleComments,
)


class TestArticleComments:
    def test_list_basic(self):
        c = _fake_client()
        c.get.return_value = {"comments": [
            {"id": 1, "status": "unapproved"},
            "malformed",
        ]}
        out = ArticleComments.list_comments(c)
        assert len(out) == 1
        assert c.get.call_args[0][0] == "comments.json"

    def test_list_validates_status(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            ArticleComments.list_comments(
                c, status="pending",
            )

    def test_list_with_article_filter(self):
        c = _fake_client()
        c.get.return_value = {"comments": []}
        ArticleComments.list_comments(
            c, article_id=42, status="unapproved",
        )
        params = c.get.call_args[1]["params"]
        assert params["article_id"] == 42
        assert params["status"] == "unapproved"

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            ArticleComments.get(c, 1)

    def test_approve(self):
        c = _fake_client()
        c.post.return_value = {
            "comment": {"id": 1, "status": "published"},
        }
        ArticleComments.approve(c, 1)
        assert c.post.call_args[0][0] == (
            "comments/1/approve.json"
        )
        assert c.post.call_args[0][1] == {}

    def test_mark_spam(self):
        c = _fake_client()
        c.post.return_value = {
            "comment": {"id": 1, "status": "spam"},
        }
        ArticleComments.mark_spam(c, 1)
        assert c.post.call_args[0][0] == (
            "comments/1/spam.json"
        )

    def test_restore(self):
        c = _fake_client()
        c.post.return_value = {
            "comment": {"id": 1, "status": "unapproved"},
        }
        ArticleComments.restore(c, 1)
        assert c.post.call_args[0][0] == (
            "comments/1/restore.json"
        )

    def test_remove(self):
        c = _fake_client()
        c.post.return_value = {
            "comment": {"id": 1, "status": "removed"},
        }
        ArticleComments.remove(c, 1)
        assert c.post.call_args[0][0] == (
            "comments/1/remove.json"
        )

    def test_missing_comment_response_raises(self):
        c = _fake_client()
        c.post.return_value = {}
        with pytest.raises(ShopifyAdminError):
            ArticleComments.approve(c, 1)
