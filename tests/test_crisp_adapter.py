"""Tests for the Crisp helpdesk adapter."""
from __future__ import annotations

import base64
from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    Capability,
    get_config,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("CRISP_IDENTIFIER", "CRISP_KEY", "CRISP_WEBSITE_ID"):
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
    monkeypatch.setenv("CRISP_IDENTIFIER", "id-abc")
    monkeypatch.setenv("CRISP_KEY", "key-123")
    monkeypatch.setenv("CRISP_WEBSITE_ID", "site-uuid")
    get_config().reload()


class TestCrispMetadata:
    def test_metadata(self):
        from core.adapters.helpdesk.crisp import CrispAdapter
        a = CrispAdapter()
        assert a.name == "crisp"
        assert a.category == AdapterCategory.HELPDESK
        assert Capability.HELPDESK_LIST_CONVERSATIONS in a.capabilities
        assert Capability.HELPDESK_SEND_REPLY in a.capabilities
        assert a.priority == 70

    def test_unconfigured_without_creds(self):
        from core.adapters.helpdesk.crisp import CrispAdapter
        assert not CrispAdapter().is_configured()

    def test_configured_with_creds(self, monkeypatch):
        from core.adapters.helpdesk.crisp import CrispAdapter
        _configure(monkeypatch)
        assert CrispAdapter().is_configured()


class TestCrispAuth:
    def test_basic_auth_and_tier(self, monkeypatch):
        from core.adapters.helpdesk.crisp import CrispAdapter
        _configure(monkeypatch)
        headers = CrispAdapter()._auth_headers()
        expected = base64.b64encode(b"id-abc:key-123").decode()
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["X-Crisp-Tier"] == "plugin"


class TestCrispListConversations:
    def test_list_happy_path(self, monkeypatch):
        from core.adapters.helpdesk.crisp import CrispAdapter
        _configure(monkeypatch)
        a = CrispAdapter()

        raw = {
            "data": [{
                "session_id": "sess-1",
                "state": "unresolved",
                "last_message": "Hi there, I need help",
                "created_at": 1700000000,
                "updated_at": 1700000100,
                "unread": {"operator": 2},
                "meta": {"subject": "Help", "email": "a@b.com"},
            }],
        }

        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(Capability.HELPDESK_LIST_CONVERSATIONS, {})

        assert result.ok
        assert result.data["count"] == 1
        assert result.data["conversations"][0]["id"] == "sess-1"
        assert result.data["conversations"][0]["state"] == "unresolved"
        assert result.data["conversations"][0]["unread_count"] == 2

        url = mocked.call_args[0][1]
        assert "/website/site-uuid/conversations/1" in url


class TestCrispSendReply:
    def test_send_reply_happy_path(self, monkeypatch):
        from core.adapters.helpdesk.crisp import CrispAdapter
        _configure(monkeypatch)
        a = CrispAdapter()

        raw = {"data": {}}
        with patch.object(a, "_http_request", return_value=raw) as mocked:
            result = a.execute(
                Capability.HELPDESK_SEND_REPLY,
                {
                    "conversation_id": "sess-1",
                    "body": "Here's your refund confirmation.",
                },
            )

        assert result.ok
        assert result.data["sent"] is True
        assert result.data["conversation_id"] == "sess-1"

        body = mocked.call_args[1]["body"]
        assert body["type"] == "text"
        assert body["content"].startswith("Here's")
        assert body["from"] == "operator"

    def test_send_reply_requires_body(self, monkeypatch):
        from core.adapters.helpdesk.crisp import CrispAdapter
        _configure(monkeypatch)
        result = CrispAdapter().execute(
            Capability.HELPDESK_SEND_REPLY, {"conversation_id": "x"},
        )
        assert not result.ok


class TestCrispSearchContacts:
    def test_search_happy_path(self, monkeypatch):
        from core.adapters.helpdesk.crisp import CrispAdapter
        _configure(monkeypatch)
        a = CrispAdapter()

        raw = {
            "data": [{
                "people_id": "p1",
                "email": "jane@example.com",
                "person": {"nickname": "Jane"},
                "created_at": 1700000000,
            }],
        }

        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.HELPDESK_SEARCH_CONTACTS,
                {"email": "jane@example.com"},
            )

        assert result.ok
        assert result.data["count"] == 1
        assert result.data["contacts"][0]["email"] == "jane@example.com"
        assert result.data["contacts"][0]["name"] == "Jane"


class TestCrispCreateTicket:
    def test_create_ticket_happy_path(self, monkeypatch):
        from core.adapters.helpdesk.crisp import CrispAdapter
        _configure(monkeypatch)
        a = CrispAdapter()

        raw_create = {"data": {"session_id": "new-sess"}}
        raw_msg = {"data": {}}

        def _http(*args, **kwargs):
            # First call creates, subsequent calls add message / meta.
            if "/message" in args[1]:
                return raw_msg
            return raw_create

        with patch.object(a, "_http_request", side_effect=_http) as mocked:
            result = a.execute(
                Capability.HELPDESK_CREATE_TICKET,
                {
                    "body": "I need a replacement item.",
                    "email": "buyer@example.com",
                    "nickname": "Buyer",
                },
            )

        assert result.ok
        assert result.data["conversation_id"] == "new-sess"
        assert result.data["created"] is True
        # 3 calls: create, message, meta.
        assert mocked.call_count == 3

    def test_create_ticket_requires_body(self, monkeypatch):
        from core.adapters.helpdesk.crisp import CrispAdapter
        _configure(monkeypatch)
        result = CrispAdapter().execute(Capability.HELPDESK_CREATE_TICKET, {})
        assert not result.ok


class TestCrispBootstrap:
    def test_register_all_includes_crisp(self):
        from core.adapters.helpdesk.bootstrap import register_all
        status = register_all()
        assert "crisp" in status
