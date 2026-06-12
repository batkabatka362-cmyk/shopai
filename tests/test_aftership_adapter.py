"""W963-144: AfterShip adapter tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Adapter import lives inside test methods to avoid
# module-level side effects when the registry is in a
# half-loaded state.


@pytest.fixture(autouse=True)
def _reset_config(monkeypatch):
    monkeypatch.setenv("AFTERSHIP_API_KEY", "test_key")
    from core.adapters.config import reset_config
    reset_config()
    yield
    reset_config()


class TestMetadata:
    def test_name(self):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        assert AfterShipAdapter().name == "aftership"

    def test_category_is_tracking(self):
        from core.adapters.base import AdapterCategory
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        assert (
            AfterShipAdapter().category
            == AdapterCategory.TRACKING
        )

    def test_capabilities(self):
        from core.adapters.base import Capability
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        caps = AfterShipAdapter().capabilities
        assert Capability.TRACKING_REGISTER in caps
        assert Capability.TRACKING_LOOKUP in caps
        assert Capability.TRACKING_LIST_RECENT in caps

    def test_is_configured(self):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        assert AfterShipAdapter().is_configured()


class TestRegister:
    def test_register_validation_requires_tracking_number(
        self,
    ):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        from core.adapters.base import Capability
        a = AfterShipAdapter()
        result = a.execute(
            Capability.TRACKING_REGISTER,
            {"carrier": "ups"},
        )
        assert not result.ok
        assert "tracking_number" in str(
            result.error,
        ).lower()

    def test_register_validation_requires_carrier(self):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        from core.adapters.base import Capability
        a = AfterShipAdapter()
        result = a.execute(
            Capability.TRACKING_REGISTER,
            {"tracking_number": "1Z999"},
        )
        assert not result.ok

    def test_register_payload_shape(self):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        a = AfterShipAdapter()
        payload = a._register_payload(
            tracking_number="1Z999",
            carrier="ups",
            title="My Order",
            customer_email="x@y.z",
            order_id="42",
        )
        assert payload == {
            "tracking": {
                "tracking_number": "1Z999",
                "slug": "ups",
                "title": "My Order",
                "emails": ["x@y.z"],
                "order_id": "42",
            },
        }

    def test_register_happy_path(self):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        from core.adapters.base import Capability
        a = AfterShipAdapter()
        fake_resp = MagicMock()
        fake_resp.status_code = 201
        fake_resp.text = ""
        fake_resp.json.return_value = {
            "meta": {"code": 201},
            "data": {
                "tracking": {
                    "id": "trk_123",
                    "tracking_number": "1Z999",
                    "slug": "ups",
                    "tag": "InfoReceived",
                },
            },
        }
        with patch(
            "core.adapters.tracking._base._requests.post",
            return_value=fake_resp,
        ):
            result = a.execute(
                Capability.TRACKING_REGISTER,
                {
                    "tracking_number": "1Z999",
                    "carrier": "ups",
                },
            )
        assert result.ok
        assert result.data["registered"] is True
        assert result.data["tracking_id"] == "trk_123"
        assert result.data["status"] == "info_received"


class TestLookup:
    def test_lookup_path_format(self):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        path = AfterShipAdapter()._lookup_path(
            tracking_number="1Z999", carrier="ups",
        )
        assert path == "/v4/trackings/ups/1Z999"

    def test_lookup_parses_events(self):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        from core.adapters.base import Capability
        a = AfterShipAdapter()
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.text = ""
        fake_resp.json.return_value = {
            "data": {
                "tracking": {
                    "tracking_number": "1Z999",
                    "slug": "ups",
                    "tag": "InTransit",
                    "subtag_message": (
                        "Out for delivery"
                    ),
                    "expected_delivery": "2026-06-15",
                    "updated_at": (
                        "2026-06-12T14:32:00Z"
                    ),
                    "title": "My Order",
                    "checkpoints": [
                        {
                            "checkpoint_time": (
                                "2026-06-12T14:32:00Z"
                            ),
                            "city": "Chicago",
                            "state": "IL",
                            "country_name": "United States",
                            "message": "Departed facility",
                            "tag": "InTransit",
                        },
                    ],
                },
            },
        }
        with patch(
            "core.adapters.tracking._base._requests.get",
            return_value=fake_resp,
        ):
            result = a.execute(
                Capability.TRACKING_LOOKUP,
                {
                    "tracking_number": "1Z999",
                    "carrier": "ups",
                },
            )
        assert result.ok
        d = result.data
        assert d["status"] == "in_transit"
        assert len(d["events"]) == 1
        ev = d["events"][0]
        assert "Chicago" in ev["location"]
        assert ev["status_normalised"] == "in_transit"

    def test_lookup_auth_error_surfaces(self):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        from core.adapters.base import Capability
        a = AfterShipAdapter()
        fake_resp = MagicMock()
        fake_resp.status_code = 401
        fake_resp.text = "Unauthorized"
        with patch(
            "core.adapters.tracking._base._requests.get",
            return_value=fake_resp,
        ):
            result = a.execute(
                Capability.TRACKING_LOOKUP,
                {
                    "tracking_number": "1Z999",
                    "carrier": "ups",
                },
            )
        assert not result.ok


class TestListRecent:
    def test_list_path_clamps_limit(self):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        a = AfterShipAdapter()
        assert a._list_path(limit=0).endswith("limit=1")
        assert a._list_path(limit=500).endswith(
            "limit=200",
        )
        assert a._list_path(limit=50).endswith(
            "limit=50",
        )

    def test_list_parses_count(self):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        from core.adapters.base import Capability
        a = AfterShipAdapter()
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.text = ""
        fake_resp.json.return_value = {
            "data": {
                "trackings": [
                    {
                        "tracking_number": "1",
                        "slug": "ups",
                        "tag": "Delivered",
                        "updated_at": "x",
                    },
                    {
                        "tracking_number": "2",
                        "slug": "fedex",
                        "tag": "InTransit",
                        "updated_at": "y",
                    },
                ],
            },
        }
        with patch(
            "core.adapters.tracking._base._requests.get",
            return_value=fake_resp,
        ):
            result = a.execute(
                Capability.TRACKING_LIST_RECENT,
                {"limit": 10},
            )
        assert result.ok
        assert result.data["count"] == 2
        assert result.data["trackings"][0][
            "status"
        ] == "delivered"


class TestPerStoreRouting:
    """W963-117 chain: per-store env var > fleet env var.
    AfterShip adapter inherits this via TrackingBaseAdapter."""

    def test_per_store_override_used(self, monkeypatch):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        from core.adapters.config import reset_config
        from core.context import active_store

        monkeypatch.setenv(
            "AFTERSHIP_API_KEY", "fleet_key",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_AFTERSHIP_API_KEY",
            "store_a_key",
        )
        reset_config()
        a = AfterShipAdapter()
        with active_store("store_a"):
            assert a._api_key() == "store_a_key"

    def test_fleet_fallback(self, monkeypatch):
        from core.adapters.tracking.aftership import (
            AfterShipAdapter,
        )
        from core.adapters.config import reset_config
        from core.context import active_store

        monkeypatch.setenv(
            "AFTERSHIP_API_KEY", "fleet_key",
        )
        monkeypatch.delenv(
            "SHOPAI_STORE_STORE_B_AFTERSHIP_API_KEY",
            raising=False,
        )
        reset_config()
        a = AfterShipAdapter()
        with active_store("store_b"):
            assert a._api_key() == "fleet_key"


class TestBootstrap:
    def test_register_all_registers_aftership(self):
        from core.adapters.registry import AdapterRegistry
        from core.adapters.tracking.bootstrap import (
            register_all,
        )
        registry = AdapterRegistry()
        status = register_all(registry=registry)
        assert "aftership" in status

    def test_idempotent(self):
        from core.adapters.registry import AdapterRegistry
        from core.adapters.tracking.bootstrap import (
            register_all,
        )
        registry = AdapterRegistry()
        register_all(registry=registry)
        register_all(registry=registry)
        assert registry.has("aftership")
