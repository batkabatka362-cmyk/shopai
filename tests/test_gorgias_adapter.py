"""W963-145: Gorgias helpdesk adapter tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_config(monkeypatch):
    monkeypatch.setenv("GORGIAS_API_KEY", "key123")
    monkeypatch.setenv("GORGIAS_USERNAME", "bot@acme.com")
    monkeypatch.setenv("GORGIAS_SUBDOMAIN", "acme")
    from core.adapters.config import reset_config
    reset_config()
    yield
    reset_config()


class TestMetadata:
    def test_name(self):
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        assert GorgiasAdapter().name == "gorgias"

    def test_category_helpdesk(self):
        from core.adapters.base import AdapterCategory
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        assert (
            GorgiasAdapter().category
            == AdapterCategory.HELPDESK
        )

    def test_capabilities(self):
        from core.adapters.base import Capability
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        caps = GorgiasAdapter().capabilities
        assert Capability.HELPDESK_LIST_TICKETS in caps
        assert Capability.HELPDESK_GET_TICKET in caps
        assert Capability.HELPDESK_SEND_REPLY in caps
        assert (
            Capability.HELPDESK_UPDATE_TICKET_TAGS in caps
        )
        assert Capability.HELPDESK_CREATE_TICKET in caps

    def test_is_configured_requires_all_three(
        self, monkeypatch,
    ):
        from core.adapters.config import reset_config
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        assert GorgiasAdapter().is_configured()

        monkeypatch.delenv(
            "GORGIAS_USERNAME", raising=False,
        )
        reset_config()
        assert not GorgiasAdapter().is_configured()


class TestBaseUrl:
    def test_base_url_built_from_subdomain(self):
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        assert (
            GorgiasAdapter().base_url
            == "https://acme.gorgias.com"
        )

    def test_per_store_subdomain_override(
        self, monkeypatch,
    ):
        from core.adapters.config import reset_config
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        from core.context import active_store
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_B_GORGIAS_SUBDOMAIN",
            "betashop",
        )
        reset_config()
        a = GorgiasAdapter()
        with active_store("store_b"):
            assert (
                a.base_url
                == "https://betashop.gorgias.com"
            )


class TestAuthHeaders:
    def test_basic_auth_encoded(self):
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        h = GorgiasAdapter()._auth_headers()
        assert h["Authorization"].startswith("Basic ")
        assert h["Content-Type"] == "application/json"


class TestList:
    def test_list_path_clamps(self):
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        path = GorgiasAdapter()._list_path(
            limit=500, status_filter="open",
        )
        assert "limit=100" in path
        assert "status=open" in path

    def test_list_parses(self):
        from core.adapters.base import Capability
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.text = ""
        fake_resp.json.return_value = {
            "data": [
                {
                    "id": 42,
                    "subject": "Where is my order?",
                    "status": "open",
                    "channel": "email",
                    "customer": {
                        "email": "x@y.z",
                        "firstname": "Jane",
                        "lastname": "Doe",
                    },
                    "tags": [
                        {"name": "shipping"},
                    ],
                    "last_message_datetime": "2026-06-12",
                    "created_datetime": "2026-06-11",
                },
            ],
        }
        with patch(
            "core.adapters.helpdesk._base."
            "_requests.get",
            return_value=fake_resp,
        ):
            result = GorgiasAdapter().execute(
                Capability.HELPDESK_LIST_TICKETS,
                {"limit": 30, "status": "open"},
            )
        assert result.ok
        assert result.data["count"] == 1
        t = result.data["tickets"][0]
        assert t["id"] == "42"
        assert t["status"] == "open"
        assert "shipping" in t["tags"]
        assert t["customer"]["email"] == "x@y.z"


class TestReply:
    def test_reply_validation(self):
        from core.adapters.base import Capability
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        result = GorgiasAdapter().execute(
            Capability.HELPDESK_SEND_REPLY,
            {"ticket_id": "1"},
        )
        assert not result.ok

    def test_reply_happy(self):
        from core.adapters.base import Capability
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        fake_resp = MagicMock()
        fake_resp.status_code = 201
        fake_resp.text = ""
        fake_resp.json.return_value = {"id": 99}
        with patch(
            "core.adapters.helpdesk._base."
            "_requests.post",
            return_value=fake_resp,
        ):
            result = GorgiasAdapter().execute(
                Capability.HELPDESK_SEND_REPLY,
                {
                    "ticket_id": "42",
                    "body": "Your order is in transit.",
                },
            )
        assert result.ok
        assert result.data["reply_sent"] is True


class TestUpdateTags:
    def test_tags_validation(self):
        from core.adapters.base import Capability
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        result = GorgiasAdapter().execute(
            Capability.HELPDESK_UPDATE_TICKET_TAGS,
            {"ticket_id": "1", "tags": []},
        )
        assert not result.ok

    def test_tags_payload_shape(self):
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        payload = GorgiasAdapter()\
            ._build_update_tags_payload(
                ticket_id="1",
                tags=["shopai-support-shipping"],
            )
        assert payload == {
            "tags": [
                {"name": "shopai-support-shipping"},
            ],
        }


class TestCreateTicket:
    def test_create_validation(self):
        from core.adapters.base import Capability
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        result = GorgiasAdapter().execute(
            Capability.HELPDESK_CREATE_TICKET,
            {"subject": "x"},
        )
        assert not result.ok

    def test_create_happy(self):
        from core.adapters.base import Capability
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        fake_resp = MagicMock()
        fake_resp.status_code = 201
        fake_resp.text = ""
        fake_resp.json.return_value = {
            "id": 77,
        }
        with patch(
            "core.adapters.helpdesk._base."
            "_requests.post",
            return_value=fake_resp,
        ):
            result = GorgiasAdapter().execute(
                Capability.HELPDESK_CREATE_TICKET,
                {
                    "subject": "Order missing",
                    "body": "Where is it?",
                    "customer_email": "x@y.z",
                },
            )
        assert result.ok
        assert result.data["ticket_id"] == 77


class TestPerStoreRouting:
    def test_per_store_api_key_override(
        self, monkeypatch,
    ):
        from core.adapters.helpdesk.gorgias import (
            GorgiasAdapter,
        )
        from core.adapters.config import reset_config
        from core.context import active_store
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_GORGIAS_API_KEY",
            "store_a_key",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_GORGIAS_USERNAME",
            "store_a_user",
        )
        reset_config()
        a = GorgiasAdapter()
        with active_store("store_a"):
            assert a._api_key() == "store_a_key"
            assert a._gorgias_user() == "store_a_user"


class TestBootstrap:
    def test_bootstrap_registers_gorgias(self):
        from core.adapters.registry import AdapterRegistry
        from core.adapters.helpdesk.bootstrap import (
            register_all,
        )
        registry = AdapterRegistry()
        status = register_all(registry=registry)
        assert "gorgias" in status
        assert registry.has("gorgias")
