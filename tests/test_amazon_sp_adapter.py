"""AmazonSPAdapter regression — LWA + orders + catalog."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "AMAZON_SP_CLIENT_ID",
        "AMAZON_SP_CLIENT_SECRET",
        "AMAZON_SP_REFRESH_TOKEN",
        "AMAZON_SP_REGION",
        "AMAZON_SP_MARKETPLACE_IDS",
    ):
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


def _configure(monkeypatch, *, region="na", marketplaces=""):
    monkeypatch.setenv(
        "AMAZON_SP_CLIENT_ID", "amzn1.app.client.x",
    )
    monkeypatch.setenv(
        "AMAZON_SP_CLIENT_SECRET", "s" * 30,
    )
    monkeypatch.setenv(
        "AMAZON_SP_REFRESH_TOKEN", "Atzr|refresh-x",
    )
    monkeypatch.setenv("AMAZON_SP_REGION", region)
    if marketplaces:
        monkeypatch.setenv(
            "AMAZON_SP_MARKETPLACE_IDS", marketplaces,
        )
    get_config().reload()


def _adapter(monkeypatch, **kw):
    _configure(monkeypatch, **kw)
    from core.adapters.marketplace import AmazonSPAdapter
    a = AmazonSPAdapter()
    # Short-circuit LWA for every test.
    import time as _t
    a._token.value = "lwa-test"
    a._token.expires_at_monotonic = _t.monotonic() + 3600
    return a


# ── Metadata + regions ────────────────────────────────────


class TestMetadata:
    def test_fields(self):
        from core.adapters.marketplace import AmazonSPAdapter
        a = AmazonSPAdapter()
        assert a.name == "amazon_sp"
        assert a.category == AdapterCategory.MARKETPLACE
        assert a.priority == 60
        assert Capability.AMAZON_LIST_ORDERS in a.capabilities
        assert Capability.AMAZON_GET_ORDER in a.capabilities
        assert (
            Capability.AMAZON_SEARCH_CATALOG in a.capabilities
        )

    def test_region_na_default(self, monkeypatch):
        a = _adapter(monkeypatch)
        assert a.base_url.endswith(".amazon.com")
        assert "-na." in a.base_url

    def test_region_eu(self, monkeypatch):
        a = _adapter(monkeypatch, region="eu")
        assert "-eu." in a.base_url

    def test_region_unknown_falls_back_to_na(
        self, monkeypatch,
    ):
        a = _adapter(monkeypatch, region="mars")
        assert "-na." in a.base_url


# ── Configuration ────────────────────────────────────────


class TestConfiguration:
    def test_unconfigured_without_refresh(self, monkeypatch):
        from core.adapters.marketplace import AmazonSPAdapter
        monkeypatch.setenv(
            "AMAZON_SP_CLIENT_ID", "x",
        )
        monkeypatch.setenv(
            "AMAZON_SP_CLIENT_SECRET", "y",
        )
        get_config().reload()
        assert not AmazonSPAdapter().is_configured()

    def test_configured_when_all_set(self, monkeypatch):
        _configure(monkeypatch)
        from core.adapters.marketplace import AmazonSPAdapter
        assert AmazonSPAdapter().is_configured()

    def test_marketplace_ids_default(self, monkeypatch):
        a = _adapter(monkeypatch)
        assert a._marketplace_ids() == ["ATVPDKIKX0DER"]

    def test_marketplace_ids_custom(self, monkeypatch):
        a = _adapter(
            monkeypatch,
            marketplaces="ATVPDKIKX0DER,A2Q3Y263D00KWC",
        )
        assert a._marketplace_ids() == [
            "ATVPDKIKX0DER", "A2Q3Y263D00KWC",
        ]


# ── list_orders ──────────────────────────────────────────


class TestListOrders:
    def test_default_window_seven_days(self, monkeypatch):
        a = _adapter(monkeypatch)
        captured = {}

        def fake_req(method, path, *, query=None, body=None):
            captured.update({
                "path": path, "query": query,
            })
            return {
                "payload": {
                    "Orders": [],
                    "NextToken": "",
                },
            }

        with patch.object(
            a, "_sp_request", side_effect=fake_req,
        ):
            res = a.execute(
                Capability.AMAZON_LIST_ORDERS, {},
            )
        assert res.ok
        assert captured["path"] == "/orders/v0/orders"
        # Default statuses + marketplace.
        assert captured["query"]["OrderStatuses"] == "Unshipped"
        assert "ATVPDKIKX0DER" in (
            captured["query"]["MarketplaceIds"]
        )
        # Default created_after is populated (ISO-like).
        assert captured["query"]["CreatedAfter"]

    def test_per_page_clamped(self, monkeypatch):
        a = _adapter(monkeypatch)
        captured = {}

        def fake_req(method, path, *, query=None, body=None):
            captured["query"] = query
            return {"payload": {"Orders": []}}

        with patch.object(
            a, "_sp_request", side_effect=fake_req,
        ):
            a.execute(
                Capability.AMAZON_LIST_ORDERS,
                {"max_results_per_page": 999},
            )
        assert captured["query"]["MaxResultsPerPage"] == 100

    def test_status_must_be_list(self, monkeypatch):
        a = _adapter(monkeypatch)
        res = a.execute(
            Capability.AMAZON_LIST_ORDERS,
            {"order_statuses": "Shipped"},
        )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_normalises_camel_case_to_snake(
        self, monkeypatch,
    ):
        a = _adapter(monkeypatch)

        def fake_req(method, path, *, query=None, body=None):
            return {"payload": {"Orders": [{
                "AmazonOrderId": "114-1234567-1234567",
                "OrderStatus": "Unshipped",
                "PurchaseDate": "2026-04-20T10:00:00Z",
                "LastUpdateDate": "2026-04-21T01:00:00Z",
                "OrderTotal": {
                    "Amount": "29.99",
                    "CurrencyCode": "USD",
                },
                "MarketplaceId": "ATVPDKIKX0DER",
                "FulfillmentChannel": "MFN",
                "SalesChannel": "Amazon.com",
                "NumberOfItemsShipped": 0,
                "NumberOfItemsUnshipped": 2,
                "IsPrime": False,
                "IsBusinessOrder": False,
                "ShipmentServiceLevelCategory": "Standard",
                "BuyerInfo": {
                    "BuyerEmail": (
                        "abcd@marketplace.amazon.com"
                    ),
                },
            }]}}

        with patch.object(
            a, "_sp_request", side_effect=fake_req,
        ):
            res = a.execute(
                Capability.AMAZON_LIST_ORDERS, {},
            )
        assert res.ok
        assert res.data["total"] == 1
        o = res.data["orders"][0]
        assert o["order_id"] == "114-1234567-1234567"
        assert o["status"] == "Unshipped"
        assert o["total_amount"] == 29.99
        assert o["currency"] == "USD"
        assert o["item_count"] == 2
        # Anonymised email flag true when @marketplace.amazon.
        assert o["buyer_info_anonymised"] is True


# ── get_order ────────────────────────────────────────────


class TestGetOrder:
    def test_requires_order_id(self, monkeypatch):
        a = _adapter(monkeypatch)
        res = a.execute(Capability.AMAZON_GET_ORDER, {})
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_happy(self, monkeypatch):
        a = _adapter(monkeypatch)

        def fake_req(method, path, *, query=None, body=None):
            assert path.endswith("/orders/v0/orders/X-1")
            return {"payload": {
                "AmazonOrderId": "X-1",
                "OrderStatus": "Shipped",
                "OrderTotal": {
                    "Amount": "10.00", "CurrencyCode": "USD",
                },
            }}

        with patch.object(
            a, "_sp_request", side_effect=fake_req,
        ):
            res = a.execute(
                Capability.AMAZON_GET_ORDER,
                {"order_id": "X-1"},
            )
        assert res.ok
        assert res.data["order"]["order_id"] == "X-1"


# ── search_catalog ───────────────────────────────────────


class TestSearchCatalog:
    def test_requires_keywords_or_asin(self, monkeypatch):
        a = _adapter(monkeypatch)
        res = a.execute(
            Capability.AMAZON_SEARCH_CATALOG, {},
        )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_keywords_search(self, monkeypatch):
        a = _adapter(monkeypatch)
        captured = {}

        def fake_req(method, path, *, query=None, body=None):
            captured["query"] = query
            return {"items": [{
                "asin": "B0TEST",
                "summaries": [{
                    "itemName": "Cozy Mushroom Lamp",
                    "brand": "DeguarTest",
                    "manufacturer": "Deguar",
                    "itemClassification": "STANDARD",
                }],
                "images": [{
                    "images": [{"link": "https://img/x.jpg"}],
                }],
            }]}

        with patch.object(
            a, "_sp_request", side_effect=fake_req,
        ):
            res = a.execute(
                Capability.AMAZON_SEARCH_CATALOG,
                {"keywords": "cozy lamp"},
            )
        assert res.ok
        assert captured["query"]["keywords"] == "cozy lamp"
        item = res.data["items"][0]
        assert item["asin"] == "B0TEST"
        assert item["title"] == "Cozy Mushroom Lamp"
        assert item["image_url"] == "https://img/x.jpg"

    def test_asin_search_sets_identifiers(
        self, monkeypatch,
    ):
        a = _adapter(monkeypatch)
        captured = {}

        def fake_req(method, path, *, query=None, body=None):
            captured["query"] = query
            return {"items": []}

        with patch.object(
            a, "_sp_request", side_effect=fake_req,
        ):
            a.execute(
                Capability.AMAZON_SEARCH_CATALOG,
                {"asin": "B09XYZ"},
            )
        assert captured["query"]["identifiers"] == "B09XYZ"
        assert captured["query"]["identifiersType"] == "ASIN"

    def test_page_size_clamped(self, monkeypatch):
        a = _adapter(monkeypatch)
        captured = {}

        def fake_req(method, path, *, query=None, body=None):
            captured["query"] = query
            return {"items": []}

        with patch.object(
            a, "_sp_request", side_effect=fake_req,
        ):
            a.execute(
                Capability.AMAZON_SEARCH_CATALOG,
                {"keywords": "x", "page_size": 999},
            )
        # Amazon caps catalog page size at 20.
        assert captured["query"]["pageSize"] == 20


# ── LWA token flow ───────────────────────────────────────


class TestLWA:
    def test_token_cached_between_calls(self, monkeypatch):
        _configure(monkeypatch)
        from core.adapters.marketplace import AmazonSPAdapter
        a = AmazonSPAdapter()
        n = {"v": 0}

        def fake_fetch():
            n["v"] += 1
            return ("tok", 600.0)

        with patch.object(
            a, "_fetch_token", side_effect=fake_fetch,
        ):
            assert a._access_token() == "tok"
            assert a._access_token() == "tok"
        assert n["v"] == 1


# ── Bootstrap ────────────────────────────────────────────


class TestBootstrap:
    def test_registered(self):
        from core.adapters.marketplace.bootstrap import (
            register_all,
        )
        status = register_all()
        assert "amazon_sp" in status

    def test_configured_flag_reflects_env(
        self, monkeypatch,
    ):
        _configure(monkeypatch)
        from core.adapters.marketplace.bootstrap import (
            register_all,
        )
        status = register_all()
        assert status["amazon_sp"] is True
