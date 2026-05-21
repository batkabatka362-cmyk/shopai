"""Tests for ``tools.adapters.shopify`` -- silent-failure fixes
on ``health_check`` and ``_get_store_info``.

Before:
- ``health_check`` set healthy=False on probe failure but
  dropped the exception detail, leaving operators with only
  "Shopify API unreachable or not configured" -- can't tell
  auth failure from network blip.
- ``_get_store_info`` silently fell back from the live API
  call to the config-only payload with no log.

After: both paths log + the health_check error message carries
the actual exception string so the HealthStatus.error field
is debuggable.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

# Import the module at the top so the utils.logger.get_logger
# call has already configured the logger before fixtures
# attach. Otherwise the fixture's setLevel(DEBUG) gets reset to
# WARNING when the module is first imported, dropping records.
from tools.adapters import shopify as _shopify_adapter_mod  # noqa: F401


_LOGGER = "shopai.tools.shopify"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def adapter_log() -> _ListHandler:
    handler = _ListHandler()
    target = logging.getLogger(_LOGGER)
    original_level = target.level
    target.setLevel(logging.DEBUG)
    target.addHandler(handler)
    try:
        yield handler
    finally:
        target.removeHandler(handler)
        target.setLevel(original_level)


def _messages(handler: _ListHandler) -> list[str]:
    return [r.getMessage() for r in handler.records]


def _configured_adapter(api_mock=None):
    """Build a ShopifyAdapter wired with a token + injected api."""
    from tools.adapters.shopify import ShopifyAdapter
    adapter = ShopifyAdapter()
    adapter._credentials = {"access_token": "t-tok"}
    adapter._shop_domain = "test.myshopify.com"
    adapter._api = api_mock or MagicMock()
    return adapter


class TestHealthCheckSurfacesError:
    """health_check should carry the actual probe exception in
    HealthStatus.error so operators can distinguish auth /
    network / schema failure."""

    def test_probe_failure_logs_and_surfaces_error(
        self, adapter_log,
    ):
        api = MagicMock()
        api.fetch_products.side_effect = RuntimeError(
            "401 Unauthorized: invalid token"
        )
        adapter = _configured_adapter(api_mock=api)
        health = adapter.health_check()

        assert health.healthy is False
        # The actual exception is in the error field, not a
        # generic "unreachable" message
        assert "Shopify API probe failed" in health.error
        assert "401 Unauthorized" in health.error
        assert "invalid token" in health.error
        # And the warning fired with the shop domain
        msgs = _messages(adapter_log)
        assert any(
            "health probe failed" in m
            and "test.myshopify.com" in m
            and "401" in m
            for m in msgs
        )

    def test_probe_success_returns_healthy_no_log(
        self, adapter_log,
    ):
        api = MagicMock()
        api.fetch_products.return_value = {"products": []}
        adapter = _configured_adapter(api_mock=api)
        health = adapter.health_check()
        assert health.healthy is True
        assert health.error is None
        # No warnings on the happy path
        warnings = [
            r for r in adapter_log.records
            if r.levelno >= logging.WARNING
        ]
        assert warnings == []

    def test_unconfigured_returns_generic_error(self):
        """When no api / token is configured, fall back to the
        generic 'unreachable' message (it's the right shape --
        there's no exception to surface)."""
        from tools.adapters.shopify import ShopifyAdapter
        adapter = ShopifyAdapter()
        health = adapter.health_check()
        assert health.healthy is False
        assert "unreachable" in (health.error or "").lower() \
            or "not configured" in (health.error or "").lower()


class TestGetStoreInfoFallbackLogging:
    """_get_store_info silently fell back to config-only when
    the live call failed. Now it logs the exception."""

    def test_live_failure_logs_and_falls_back(
        self, adapter_log,
    ):
        adapter = _configured_adapter()
        # Patch the inner updater._make_request to raise
        from unittest.mock import patch as _patch
        with _patch(
            "execution.shopify.product_updater.ProductUpdater._make_request",
            side_effect=RuntimeError("schema-mismatch"),
        ):
            result = adapter._get_store_info({})
        # Behavior contract preserved: fall-back to config dict
        assert result["source"] == "config"
        assert result["shop_domain"] == "test.myshopify.com"
        # New: the failure is logged with the shop domain
        msgs = _messages(adapter_log)
        assert any(
            "Live get_store_info failed" in m
            and "test.myshopify.com" in m
            and "schema-mismatch" in m
            for m in msgs
        )

    def test_no_api_returns_config_without_log(
        self, adapter_log,
    ):
        """When the adapter has no api configured, returning the
        config dict is the EXPECTED path -- no log."""
        from tools.adapters.shopify import ShopifyAdapter
        adapter = ShopifyAdapter()
        adapter._shop_domain = "test.myshopify.com"
        result = adapter._get_store_info({})
        assert result["source"] == "config"
        assert adapter_log.records == []
