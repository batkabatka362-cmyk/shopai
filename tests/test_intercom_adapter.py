"""Tests for the Intercom helpdesk adapter.

Real HTTP calls are forbidden — every test patches
``_http_request`` to return canned responses.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("INTERCOM_ACCESS_TOKEN", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_intercom(monkeypatch, *, key="ic-test-token"):
    monkeypatch.setenv("INTERCOM_ACCESS_TOKEN", key)
    get_config().reload()


class TestIntercomMetadata:
    def test_metadata(self):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        a = IntercomAdapter()
        assert a.name == "intercom"
        assert a.category == AdapterCategory.HELPDESK
        assert Capability.HELPDESK_LIST_CONVERSATIONS in a.capabilities
        assert Capability.HELPDESK_SEND_REPLY in a.capabilities
        assert Capability.HELPDESK_SEARCH_CONTACTS in a.capabilities
        assert Capability.HELPDESK_CREATE_TICKET in a.capabilities
        assert a.priority == 90

    def test_unconfigured_without_key(self):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        assert not IntercomAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        _configure_intercom(monkeypatch)
        assert IntercomAdapter().is_configured()


class TestIntercomAuth:
    def test_auth_headers(self, monkeypatch):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        _configure_intercom(monkeypatch, key="my-token")
        a = IntercomAdapter()
        headers = a._auth_headers()
        assert headers["Authorization"] == "Bearer my-token"
        assert headers["Intercom-Version"] == "2.11"
        assert headers["Content-Type"] == "application/json"


class TestIntercomListConversations:
    def test_list_conversations_happy_path(self, monkeypatch):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        _configure_intercom(monkeypatch)
        a = IntercomAdapter()

        raw = {
            "conversations": [
                {
                    "id": "conv_001",
                    "state": "open",
                    "source": {"subject": "Order issue", "body": "My order..."},
                    "created_at": 1712345678,
                    "updated_at": 1712345700,
                    "waiting_since": 1712345690,
                    "statistics": {"first_contact_reply_at": 1712345695},
                    "assignee": {"type": "admin"},
                },
                {
                    "id": "conv_002",
                    "state": "closed",
                    "source": {"subject": "", "body": "Quick question about shipping to Europe"},
                    "created_at": 1712340000,
                    "updated_at": 1712341000,
                    "waiting_since": None,
                    "statistics": {},
                    "assignee": None,
                },
            ],
            "total_count": 42,
            "pages": {"next": "https://api.intercom.io/conversations?page=2"},
        }

        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.HELPDESK_LIST_CONVERSATIONS,
                {"page": 1, "per_page": 20},
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["total"] == 42
        assert result.data["has_next"] is True
        assert result.data["conversations"][0]["id"] == "conv_001"
        assert result.data["conversations"][0]["title"] == "Order issue"
        # Second conversation has no subject — falls back to body[:80]
        assert "Quick question" in result.data["conversations"][1]["title"]

    def test_list_conversations_empty(self, monkeypatch):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        _configure_intercom(monkeypatch)
        a = IntercomAdapter()

        raw = {"conversations": [], "total_count": 0, "pages": {}}

        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.HELPDESK_LIST_CONVERSATIONS, {},
            )

        assert result.ok
        assert result.data["count"] == 0
        assert result.data["has_next"] is False


class TestIntercomSendReply:
    def test_send_reply_requires_conversation_id(self, monkeypatch):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        _configure_intercom(monkeypatch)
        a = IntercomAdapter()

        result = a.execute(
            Capability.HELPDESK_SEND_REPLY,
            {"body": "Thanks for reaching out!"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_send_reply_requires_body(self, monkeypatch):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        _configure_intercom(monkeypatch)
        a = IntercomAdapter()

        result = a.execute(
            Capability.HELPDESK_SEND_REPLY,
            {"conversation_id": "conv_001"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_send_reply_happy_path(self, monkeypatch):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        _configure_intercom(monkeypatch)
        a = IntercomAdapter()

        raw = {"type": "conversation", "id": "conv_001"}

        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.HELPDESK_SEND_REPLY,
                {
                    "conversation_id": "conv_001",
                    "body": "Your order has been shipped!",
                    "admin_id": "admin_123",
                },
            )

        assert result.ok
        assert result.data["conversation_id"] == "conv_001"
        assert result.data["sent"] is True

        # Verify POST body
        call_args = mocked.call_args
        body = call_args.kwargs["body"]
        assert body["body"] == "Your order has been shipped!"
        assert body["admin_id"] == "admin_123"
        assert body["message_type"] == "comment"


class TestIntercomSearchContacts:
    def test_search_requires_query(self, monkeypatch):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        _configure_intercom(monkeypatch)
        a = IntercomAdapter()

        result = a.execute(
            Capability.HELPDESK_SEARCH_CONTACTS,
            {},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_search_contacts_by_email(self, monkeypatch):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        _configure_intercom(monkeypatch)
        a = IntercomAdapter()

        raw = {
            "data": [
                {
                    "id": "contact_001",
                    "external_id": "ext_123",
                    "email": "customer@example.com",
                    "name": "John Doe",
                    "role": "user",
                    "created_at": 1712340000,
                    "last_seen_at": 1712345678,
                    "custom_attributes": {"plan": "premium"},
                },
            ],
            "total_count": 1,
        }

        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.HELPDESK_SEARCH_CONTACTS,
                {"query": "customer@example.com", "field": "email"},
            )

        assert result.ok
        assert result.data["count"] == 1
        assert result.data["contacts"][0]["email"] == "customer@example.com"
        assert result.data["contacts"][0]["name"] == "John Doe"
        assert result.data["contacts"][0]["custom_attributes"]["plan"] == "premium"

        # Verify search body
        body = mocked.call_args.kwargs["body"]
        assert body["query"]["field"] == "email"
        assert body["query"]["value"] == "customer@example.com"


class TestIntercomCreateTicket:
    def test_create_ticket_requires_body(self, monkeypatch):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        _configure_intercom(monkeypatch)
        a = IntercomAdapter()

        result = a.execute(
            Capability.HELPDESK_CREATE_TICKET,
            {"contact_id": "contact_001"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_create_ticket_requires_contact_id(self, monkeypatch):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        _configure_intercom(monkeypatch)
        a = IntercomAdapter()

        result = a.execute(
            Capability.HELPDESK_CREATE_TICKET,
            {"body": "I need help with my order"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_create_ticket_happy_path(self, monkeypatch):
        from core.adapters.helpdesk.intercom import IntercomAdapter
        _configure_intercom(monkeypatch)
        a = IntercomAdapter()

        raw = {"id": "conv_new_001", "type": "conversation"}

        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.HELPDESK_CREATE_TICKET,
                {
                    "contact_id": "contact_001",
                    "body": "I need help with my order #1234",
                    "subject": "Order #1234 inquiry",
                },
            )

        assert result.ok
        assert result.data["conversation_id"] == "conv_new_001"
        assert result.data["contact_id"] == "contact_001"
        assert result.data["created"] is True

        # Verify POST body includes subject
        body = mocked.call_args.kwargs["body"]
        assert body["subject"] == "Order #1234 inquiry"
        assert body["from"]["id"] == "contact_001"


class TestIntercomBootstrap:
    def test_register_all(self):
        from core.adapters.helpdesk.bootstrap import register_all
        status = register_all()
        assert "intercom" in status

    def test_router_finds_intercom(self, monkeypatch):
        from core.adapters.helpdesk.bootstrap import register_all
        _configure_intercom(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.HELPDESK_LIST_CONVERSATIONS)
        assert chosen.name == "intercom"
