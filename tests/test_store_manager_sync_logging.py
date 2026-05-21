"""Tests for ``data_pipeline.store.store_manager`` +
``data_pipeline.store.sync_service`` -- silent-failure fixes
on OAuth-to-static fallback + per-product cost-sync fetch.

Before:
- ``_resolve_token`` / ``_resolve_env_token`` silently fell
  back to the static key on OAuth failure. Broken OAuth
  credentials silently degraded to legacy auth -- operator
  doesn't see the signal until the next token rotation.
- ``SyncService`` per-product inventory-item fetch silently
  swallowed errors inside its loop. Stale costs on individual
  products had no diagnostic breadcrumb.

After: each path logs (warning for the OAuth fall-back since
it's a security-relevant signal; debug for the per-product
loop since it can be high-cardinality).
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

# Import modules at top so utils.logger has configured the
# named loggers before fixtures attach.
from data_pipeline.store import store_manager as _sm_mod  # noqa: F401
from data_pipeline.store import sync_service as _ss_mod  # noqa: F401


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _attach(logger_name: str) -> _ListHandler:
    handler = _ListHandler()
    target = logging.getLogger(logger_name)
    target.setLevel(logging.DEBUG)
    target.addHandler(handler)
    return handler


def _detach(logger_name: str, handler: _ListHandler) -> None:
    logging.getLogger(logger_name).removeHandler(handler)


@pytest.fixture
def sm_log():
    handler = _attach("shopai.store_manager")
    yield handler
    _detach("shopai.store_manager", handler)


class TestResolveTokenLogging:

    def test_oauth_failure_logs_warning_and_returns_static(
        self, sm_log,
    ):
        from data_pipeline.store.store_manager import StoreManager
        creds = {
            "client_id": "id", "client_secret": "sec",
            "shop_url": "test.myshopify.com",
            "api_key": "static-key",
        }
        with patch(
            "data_pipeline.store.store_manager._get_auth_instance",
            side_effect=RuntimeError("oauth refresh broken"),
        ):
            token = StoreManager._resolve_token(creds)
        # Behavior contract: falls back to static key
        assert token == "static-key"
        # Log fired with shop_url + error
        msgs = [r.getMessage() for r in sm_log.records]
        assert any(
            "OAuth token resolve failed" in m
            and "test.myshopify.com" in m
            and "oauth refresh broken" in m
            for m in msgs
        )

    def test_oauth_success_no_log(self, sm_log):
        from data_pipeline.store.store_manager import StoreManager
        creds = {
            "client_id": "id", "client_secret": "sec",
            "shop_url": "test.myshopify.com",
        }
        auth = MagicMock()
        auth.get_token.return_value = "oauth-token"
        with patch(
            "data_pipeline.store.store_manager._get_auth_instance",
            return_value=auth,
        ):
            token = StoreManager._resolve_token(creds)
        assert token == "oauth-token"
        warnings = [
            r for r in sm_log.records
            if r.levelno >= logging.WARNING
        ]
        assert warnings == []

    def test_no_oauth_creds_returns_api_key_no_log(self, sm_log):
        from data_pipeline.store.store_manager import StoreManager
        creds = {"api_key": "static-key"}
        token = StoreManager._resolve_token(creds)
        assert token == "static-key"
        # No OAuth attempt -> no log
        assert sm_log.records == []


class TestResolveEnvTokenLogging:

    def test_oauth_env_failure_logs_warning(self, sm_log):
        from data_pipeline.store.store_manager import StoreManager
        env = {
            "SHOPAI_SHOPIFY_CLIENT_ID": "id",
            "SHOPAI_SHOPIFY_CLIENT_SECRET": "sec",
            "SHOPAI_SHOPIFY_URL": "env.myshopify.com",
            "SHOPAI_SHOPIFY_KEY": "env-static",
        }
        with patch.dict("os.environ", env, clear=False), patch(
            "data_pipeline.store.store_manager._get_auth_instance",
            side_effect=RuntimeError("env oauth broken"),
        ):
            token = StoreManager._resolve_env_token()
        assert token == "env-static"
        msgs = [r.getMessage() for r in sm_log.records]
        assert any(
            "OAuth env-token resolve failed" in m
            and "env.myshopify.com" in m
            and "env oauth broken" in m
            for m in msgs
        )


# ─── SyncService per-product cost-sync log ───────────────────


@pytest.fixture
def ss_log():
    handler = _attach("shopai.sync_service")
    yield handler
    _detach("shopai.sync_service", handler)


class TestSyncServiceCostLog:
    """Verify the inner per-product cost-fetch logs at debug
    when an item fetch fails. The outer loop continues."""

    def test_per_product_fetch_failure_logs_with_pid(
        self, ss_log,
    ):
        from data_pipeline.store.sync_service import SyncService
        sm = MagicMock()
        sm.db._get_conn.return_value = MagicMock()
        svc = SyncService(sm)
        creds = {
            "api_key": "tok",
            "shop_url": "test.myshopify.com",
        }
        products = [{
            "id": "P1",
            "variants": [{"inventory_item_id": "I1"}],
        }]
        with patch(
            "data_pipeline.ingestion.api.shopify_api._normalize_shop_url",
            return_value="test.myshopify.com",
        ), patch(
            "urllib.request.urlopen",
            side_effect=ConnectionError("net down"),
        ):
            svc._sync_product_costs("store-a", creds, products)
        msgs = [r.getMessage() for r in ss_log.records]
        # The per-product debug log fired with the product id
        assert any(
            "inventory_item fetch failed" in m
            and "P1" in m
            and "net down" in m
            for m in msgs
        )
