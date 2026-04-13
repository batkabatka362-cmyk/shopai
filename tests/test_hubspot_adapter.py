"""Tests for the HubSpot CRM adapter."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure(monkeypatch, *, token="hs-test-token"):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", token)
    get_config().reload()


class TestHubSpotMetadata:
    def test_metadata(self):
        from core.adapters.crm.hubspot import HubSpotAdapter
        a = HubSpotAdapter()
        assert a.name == "hubspot"
        assert a.category == AdapterCategory.CRM
        assert Capability.CRM_SEARCH_CONTACTS in a.capabilities
        assert Capability.CRM_UPSERT_CONTACT in a.capabilities
        assert Capability.CRM_LIST_DEALS in a.capabilities
        assert Capability.CRM_CREATE_DEAL in a.capabilities
        assert a.priority == 90

    def test_unconfigured_without_key(self):
        from core.adapters.crm.hubspot import HubSpotAdapter
        assert not HubSpotAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.crm.hubspot import HubSpotAdapter
        _configure(monkeypatch)
        assert HubSpotAdapter().is_configured()


class TestHubSpotAuth:
    def test_auth_headers(self, monkeypatch):
        from core.adapters.crm.hubspot import HubSpotAdapter
        _configure(monkeypatch, token="abc123")
        headers = HubSpotAdapter()._auth_headers()
        assert headers["Authorization"] == "Bearer abc123"
        assert headers["Content-Type"] == "application/json"


class TestHubSpotSearchContacts:
    def test_search_happy_path(self, monkeypatch):
        from core.adapters.crm.hubspot import HubSpotAdapter
        _configure(monkeypatch)
        a = HubSpotAdapter()

        raw = {
            "total": 1,
            "results": [{
                "id": "51",
                "properties": {
                    "email": "jane@example.com",
                    "firstname": "Jane",
                    "lastname": "Doe",
                    "phone": "+14155551212",
                    "company": "Acme",
                    "lifecyclestage": "customer",
                },
            }],
        }

        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.CRM_SEARCH_CONTACTS,
                {"email": "jane@example.com"},
            )

        assert result.ok
        assert result.data["count"] == 1
        assert result.data["contacts"][0]["id"] == "51"
        assert result.data["contacts"][0]["email"] == "jane@example.com"
        assert result.data["contacts"][0]["first_name"] == "Jane"

        method, url = mocked.call_args[0][:2]
        assert method == "POST"
        assert url.endswith("/crm/v3/objects/contacts/search")
        body = mocked.call_args[1]["body"]
        assert body["filterGroups"][0]["filters"][0]["value"] == "jane@example.com"

    def test_search_requires_query(self, monkeypatch):
        from core.adapters.crm.hubspot import HubSpotAdapter
        _configure(monkeypatch)
        a = HubSpotAdapter()
        result = a.execute(Capability.CRM_SEARCH_CONTACTS, {})
        assert not result.ok


class TestHubSpotUpsertContact:
    def test_upsert_happy_path(self, monkeypatch):
        from core.adapters.crm.hubspot import HubSpotAdapter
        _configure(monkeypatch)
        a = HubSpotAdapter()

        raw = {"id": "123", "properties": {"email": "jane@example.com"}}

        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.CRM_UPSERT_CONTACT,
                {
                    "email": "jane@example.com",
                    "first_name": "Jane",
                    "last_name": "Doe",
                    "phone": "+14155551212",
                },
            )

        assert result.ok
        assert result.data["contact_id"] == "123"
        assert result.data["upserted"] is True

        method, url = mocked.call_args[0][:2]
        assert method == "PATCH"
        assert "jane@example.com" in url
        assert "idProperty=email" in url
        body = mocked.call_args[1]["body"]
        assert body["properties"]["email"] == "jane@example.com"
        assert body["properties"]["firstname"] == "Jane"
        assert body["properties"]["lastname"] == "Doe"

    def test_upsert_requires_email(self, monkeypatch):
        from core.adapters.crm.hubspot import HubSpotAdapter
        _configure(monkeypatch)
        result = HubSpotAdapter().execute(Capability.CRM_UPSERT_CONTACT, {})
        assert not result.ok


class TestHubSpotListDeals:
    def test_list_deals_happy_path(self, monkeypatch):
        from core.adapters.crm.hubspot import HubSpotAdapter
        _configure(monkeypatch)
        a = HubSpotAdapter()

        raw = {
            "results": [{
                "id": "9",
                "properties": {
                    "dealname": "Big Sale",
                    "amount": "5000",
                    "dealstage": "proposal",
                    "closedate": "2026-05-01",
                    "pipeline": "default",
                },
            }],
            "paging": {"next": {"after": "next-cursor"}},
        }

        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(Capability.CRM_LIST_DEALS, {"limit": 5})

        assert result.ok
        assert result.data["count"] == 1
        assert result.data["deals"][0]["name"] == "Big Sale"
        assert result.data["deals"][0]["amount"] == "5000"
        assert result.data["next_cursor"] == "next-cursor"


class TestHubSpotCreateDeal:
    def test_create_deal_happy_path(self, monkeypatch):
        from core.adapters.crm.hubspot import HubSpotAdapter
        _configure(monkeypatch)
        a = HubSpotAdapter()

        raw = {"id": "55", "properties": {"dealname": "Enterprise Deal"}}

        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.CRM_CREATE_DEAL,
                {
                    "name": "Enterprise Deal",
                    "amount": 25000,
                    "stage": "qualifiedtobuy",
                    "contact_id": "51",
                },
            )

        assert result.ok
        assert result.data["deal_id"] == "55"
        assert result.data["created"] is True

        body = mocked.call_args[1]["body"]
        assert body["properties"]["dealname"] == "Enterprise Deal"
        assert body["properties"]["amount"] == "25000"
        assert body["associations"][0]["to"]["id"] == "51"

    def test_create_deal_requires_name(self, monkeypatch):
        from core.adapters.crm.hubspot import HubSpotAdapter
        _configure(monkeypatch)
        result = HubSpotAdapter().execute(Capability.CRM_CREATE_DEAL, {})
        assert not result.ok


class TestHubSpotBootstrap:
    def test_register_all_includes_hubspot(self):
        from core.adapters.crm.bootstrap import register_all
        status = register_all()
        assert "hubspot" in status

    def test_router_finds_hubspot(self, monkeypatch):
        from core.adapters.crm.bootstrap import register_all
        _configure(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.CRM_SEARCH_CONTACTS)
        assert chosen.name == "hubspot"
