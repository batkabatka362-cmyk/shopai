"""W963-146: GA4 adapter tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_config(monkeypatch):
    monkeypatch.setenv("GA4_MEASUREMENT_ID", "G-XXXX")
    monkeypatch.setenv("GA4_API_SECRET", "secret123")
    from core.adapters.config import reset_config
    reset_config()
    yield
    reset_config()


class TestMetadata:
    def test_name(self):
        from core.adapters.analytics.ga4 import GA4Adapter
        assert GA4Adapter().name == "ga4"

    def test_category_analytics(self):
        from core.adapters.base import AdapterCategory
        from core.adapters.analytics.ga4 import GA4Adapter
        assert (
            GA4Adapter().category
            == AdapterCategory.ANALYTICS
        )

    def test_capabilities(self):
        from core.adapters.base import Capability
        from core.adapters.analytics.ga4 import GA4Adapter
        caps = GA4Adapter().capabilities
        assert Capability.ANALYTICS_TRACK_EVENT in caps
        assert Capability.ANALYTICS_IDENTIFY in caps

    def test_is_configured_requires_both(
        self, monkeypatch,
    ):
        from core.adapters.config import reset_config
        from core.adapters.analytics.ga4 import GA4Adapter

        assert GA4Adapter().is_configured()
        monkeypatch.delenv(
            "GA4_MEASUREMENT_ID", raising=False,
        )
        reset_config()
        assert not GA4Adapter().is_configured()


class TestTrackEvent:
    def test_validation(self):
        from core.adapters.base import Capability
        from core.adapters.analytics.ga4 import GA4Adapter
        result = GA4Adapter().execute(
            Capability.ANALYTICS_TRACK_EVENT,
            {"user_id": "u1"},
        )
        assert not result.ok

    def test_payload_shape(self):
        from core.adapters.analytics.ga4 import GA4Adapter
        a = GA4Adapter()
        body = a._build_event_payload(
            event_name="purchase",
            user_id="u1",
            event_params={
                "value": 49.99,
                "currency": "USD",
            },
        )
        assert body["client_id"] == "u1"
        assert body["user_id"] == "u1"
        assert body["events"][0]["name"] == "purchase"
        params = body["events"][0]["params"]
        assert params["value"] == 49.99
        assert params["engagement_time_msec"] == 100

    def test_track_happy_path(self):
        from core.adapters.base import Capability
        from core.adapters.analytics.ga4 import GA4Adapter
        fake_resp = MagicMock()
        fake_resp.status_code = 204
        fake_resp.text = ""
        with patch(
            "core.adapters.analytics._base."
            "_requests.post",
            return_value=fake_resp,
        ) as mock_post:
            result = GA4Adapter().execute(
                Capability.ANALYTICS_TRACK_EVENT,
                {
                    "event_name": "purchase",
                    "user_id": "u1",
                    "event_params": {
                        "value": 49.99,
                        "currency": "USD",
                    },
                },
            )
        assert result.ok
        assert result.data["event_sent"] is True
        # Verify URL had both query params
        call_args = mock_post.call_args
        url = call_args.args[0]
        assert "measurement_id=G-XXXX" in url
        assert "api_secret=secret123" in url


class TestIdentify:
    def test_identify_validation(self):
        from core.adapters.base import Capability
        from core.adapters.analytics.ga4 import GA4Adapter
        result = GA4Adapter().execute(
            Capability.ANALYTICS_IDENTIFY,
            {},
        )
        assert not result.ok

    def test_identify_payload_shape(self):
        from core.adapters.analytics.ga4 import GA4Adapter
        body = GA4Adapter()._build_identify_payload(
            user_id="u1",
            traits={"plan": "premium"},
        )
        assert body["user_id"] == "u1"
        assert body["events"][0]["name"] == (
            "user_engagement"
        )
        assert body["events"][0]["params"][
            "plan"
        ] == "premium"


class TestPerStoreRouting:
    def test_per_store_measurement_id(
        self, monkeypatch,
    ):
        from core.adapters.analytics.ga4 import GA4Adapter
        from core.adapters.config import reset_config
        from core.context import active_store
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_GA4_MEASUREMENT_ID",
            "G-STOREA",
        )
        reset_config()
        a = GA4Adapter()
        with active_store("store_a"):
            assert a._measurement_id() == "G-STOREA"
        assert a._measurement_id() == "G-XXXX"

    def test_per_store_api_secret(self, monkeypatch):
        from core.adapters.analytics.ga4 import GA4Adapter
        from core.adapters.config import reset_config
        from core.context import active_store
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_GA4_API_SECRET",
            "store_a_secret",
        )
        reset_config()
        a = GA4Adapter()
        with active_store("store_a"):
            assert a._api_key() == "store_a_secret"


class TestBootstrap:
    def test_registers_ga4(self):
        from core.adapters.registry import AdapterRegistry
        from core.adapters.analytics.bootstrap import (
            register_all,
        )
        registry = AdapterRegistry()
        status = register_all(registry=registry)
        assert "ga4" in status
        assert registry.has("ga4")
