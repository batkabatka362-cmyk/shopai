"""Tests for the Zendesk helpdesk adapter."""
from __future__ import annotations

import base64
from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
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
    for var in ("ZENDESK_SUBDOMAIN", "ZENDESK_EMAIL", "ZENDESK_API_TOKEN"):
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


def _configure(monkeypatch):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "acme")
    monkeypatch.setenv("ZENDESK_EMAIL", "agent@acme.com")
    monkeypatch.setenv("ZENDESK_API_TOKEN", "tok123")
    get_config().reload()


class TestZendeskMetadata:
    def test_metadata(self):
        from core.adapters.helpdesk.zendesk import ZendeskAdapter
        a = ZendeskAdapter()
        assert a.name == "zendesk"
        assert a.category == AdapterCategory.HELPDESK
        assert Capability.HELPDESK_LIST_CONVERSATIONS in a.capabilities
        assert Capability.HELPDESK_SEND_REPLY in a.capabilities
        assert Capability.HELPDESK_SEARCH_CONTACTS in a.capabilities
        assert Capability.HELPDESK_CREATE_TICKET in a.capabilities
        assert a.priority == 80

    def test_unconfigured_without_creds(self):
        from core.adapters.helpdesk.zendesk import ZendeskAdapter
        assert not ZendeskAdapter().is_configured()

    def test_configured_with_creds(self, monkeypatch):
        from core.adapters.helpdesk.zendesk import ZendeskAdapter
        _configure(monkeypatch)
        a = ZendeskAdapter()
        assert a.is_configured()
        assert a.base_url == "https://acme.zendesk.com/api/v2"


class TestZendeskAuth:
    def test_basic_auth_header(self, monkeypatch):
        from core.adapters.helpdesk.zendesk import ZendeskAdapter
        _configure(monkeypatch)
        headers = ZendeskAdapter()._auth_headers()
        expected = base64.b64encode(
            b"agent@acme.com/token:tok123"
        ).decode()
        assert headers["Authorization"] == f"Basic {expected}"


class TestZendeskListConversations:
    def test_list_happy_path(self, monkeypatch):
        from core.adapters.helpdesk.zendesk import ZendeskAdapter
        _configure(monkeypatch)
        a = ZendeskAdapter()

        raw = {
            "tickets": [{
                "id": 101,
                "subject": "Order missing",
                "status": "open",
                "priority": "high",
                "created_at": "2026-04-10T00:00:00Z",
                "tags": ["refund"],
            }],
            "count": 1,
            "next_page": None,
        }

        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(Capability.HELPDESK_LIST_CONVERSATIONS, {})

        assert result.ok
        assert result.data["count"] == 1
        assert result.data["conversations"][0]["id"] == "101"
        assert result.data["conversations"][0]["title"] == "Order missing"
        assert result.data["conversations"][0]["state"] == "open"
        assert mocked.call_args[0][0] == "GET"

    def test_list_with_status_filter(self, monkeypatch):
        from core.adapters.helpdesk.zendesk import ZendeskAdapter
        _configure(monkeypatch)
        a = ZendeskAdapter()

        raw = {"results": [], "count": 0}
        with patch.object(a, "_http_request", return_value=raw) as mocked:
            a.execute(
                Capability.HELPDESK_LIST_CONVERSATIONS,
                {"status": "open"},
            )
        url = mocked.call_args[0][1]
        assert "search.json" in url
        assert "status:open" in url


class TestZendeskSendReply:
    def test_send_reply_happy_path(self, monkeypatch):
        from core.adapters.helpdesk.zendesk import ZendeskAdapter
        _configure(monkeypatch)
        a = ZendeskAdapter()

        raw = {"ticket": {"id": 101}}
        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.HELPDESK_SEND_REPLY,
                {
                    "conversation_id": 101,
                    "body": "Thanks, your refund is on the way.",
                    "public": True,
                },
            )

        assert result.ok
        assert result.data["sent"] is True
        assert result.data["conversation_id"] == "101"

        method, url = mocked.call_args[0][:2]
        assert method == "PUT"
        assert url.endswith("/tickets/101.json")
        body = mocked.call_args[1]["body"]
        assert body["ticket"]["comment"]["body"].startswith("Thanks")
        assert body["ticket"]["comment"]["public"] is True

    def test_send_reply_requires_body(self, monkeypatch):
        from core.adapters.helpdesk.zendesk import ZendeskAdapter
        _configure(monkeypatch)
        result = ZendeskAdapter().execute(
            Capability.HELPDESK_SEND_REPLY, {"conversation_id": 1},
        )
        assert not result.ok


class TestZendeskSearchContacts:
    def test_search_happy_path(self, monkeypatch):
        from core.adapters.helpdesk.zendesk import ZendeskAdapter
        _configure(monkeypatch)
        a = ZendeskAdapter()

        raw = {
            "users": [{
                "id": 7,
                "email": "jane@example.com",
                "name": "Jane",
                "role": "end-user",
            }],
            "count": 1,
        }

        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.HELPDESK_SEARCH_CONTACTS,
                {"query": "jane@example.com"},
            )

        assert result.ok
        assert result.data["count"] == 1
        assert result.data["contacts"][0]["email"] == "jane@example.com"
        url = mocked.call_args[0][1]
        assert "users/search.json" in url


class TestZendeskCreateTicket:
    def test_create_ticket_happy_path(self, monkeypatch):
        from core.adapters.helpdesk.zendesk import ZendeskAdapter
        _configure(monkeypatch)
        a = ZendeskAdapter()

        raw = {"ticket": {"id": 202, "subject": "Where is my order?"}}
        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.HELPDESK_CREATE_TICKET,
                {
                    "subject": "Where is my order?",
                    "body": "Order #123 was delayed.",
                    "requester_email": "buyer@example.com",
                    "priority": "normal",
                },
            )

        assert result.ok
        assert result.data["conversation_id"] == "202"
        assert result.data["created"] is True

        body = mocked.call_args[1]["body"]
        assert body["ticket"]["subject"] == "Where is my order?"
        assert body["ticket"]["requester"]["email"] == "buyer@example.com"


class TestZendeskBootstrap:
    def test_register_all_includes_zendesk(self):
        from core.adapters.helpdesk.bootstrap import register_all
        status = register_all()
        assert "zendesk" in status
