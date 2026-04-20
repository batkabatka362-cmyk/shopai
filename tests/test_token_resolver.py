"""Tests for core.auth.token_resolver — D1 OAuth activation path."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from core.auth import token_resolver as tr


class _EnvSandbox:
    """Context manager that clears + restores auth env vars."""

    KEYS = (
        "SHOPAI_SHOPIFY_CLIENT_ID",
        "SHOPAI_SHOPIFY_CLIENT_SECRET",
        "SHOPAI_SHOPIFY_KEY",
    )

    def __enter__(self):
        self._orig = {
            k: os.environ.get(k) for k in self.KEYS
        }
        for k in self.KEYS:
            os.environ.pop(k, None)
        tr._reset_for_tests()
        return self

    def __exit__(self, *a):
        for k, v in self._orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        tr._reset_for_tests()


class TestResolve(unittest.TestCase):
    def test_no_config_returns_blank(self):
        with _EnvSandbox():
            self.assertEqual(
                tr.resolve_access_token(
                    "shop.myshopify.com",
                ),
                "",
            )

    def test_legacy_key_only(self):
        with _EnvSandbox():
            os.environ[
                "SHOPAI_SHOPIFY_KEY"
            ] = "legacy-tok-1"
            self.assertEqual(
                tr.resolve_access_token(
                    "shop.myshopify.com",
                ),
                "legacy-tok-1",
            )
            self.assertEqual(
                tr.source_for("shop.myshopify.com"),
                "legacy_static",
            )

    def test_blank_shop_uses_legacy_key(self):
        with _EnvSandbox():
            os.environ["SHOPAI_SHOPIFY_KEY"] = "legacy"
            self.assertEqual(
                tr.resolve_access_token(""), "legacy",
            )

    def test_oauth_config_prefers_expiring_token(self):
        with _EnvSandbox():
            os.environ.update({
                "SHOPAI_SHOPIFY_CLIENT_ID": "cid",
                "SHOPAI_SHOPIFY_CLIENT_SECRET": "secret",
                "SHOPAI_SHOPIFY_KEY": "legacy",
            })
            # Patch ExpiringTokenAuth so we don't hit a db
            class _FakeAuth:
                def get_access_token(self, shop):
                    return f"oauth-{shop}"

                def token_status(self, shop):
                    return {"status": "ok"}

            with patch(
                "core.auth.token_resolver._make_auth",
                return_value=_FakeAuth(),
            ):
                token = tr.resolve_access_token(
                    "shop.myshopify.com",
                )
            self.assertEqual(
                token, "oauth-shop.myshopify.com",
            )

    def test_oauth_miss_falls_through_to_legacy(self):
        with _EnvSandbox():
            os.environ.update({
                "SHOPAI_SHOPIFY_CLIENT_ID": "cid",
                "SHOPAI_SHOPIFY_CLIENT_SECRET": "secret",
                "SHOPAI_SHOPIFY_KEY": "legacy",
            })

            class _UninstalledAuth:
                def get_access_token(self, shop):
                    from core.auth.shopify_expiring_token import (
                        TokenExchangeError,
                    )
                    raise TokenExchangeError(
                        "not installed",
                    )

                def token_status(self, shop):
                    return {"status": "not_installed"}

            with patch(
                "core.auth.token_resolver._make_auth",
                return_value=_UninstalledAuth(),
            ):
                token = tr.resolve_access_token(
                    "shop.myshopify.com",
                )
            self.assertEqual(token, "legacy")

    def test_has_oauth_config(self):
        with _EnvSandbox():
            self.assertFalse(tr.has_oauth_config())
            os.environ[
                "SHOPAI_SHOPIFY_CLIENT_ID"
            ] = "cid"
            self.assertFalse(tr.has_oauth_config())
            os.environ[
                "SHOPAI_SHOPIFY_CLIENT_SECRET"
            ] = "s"
            self.assertTrue(tr.has_oauth_config())


class TestSource(unittest.TestCase):
    def test_none_when_unconfigured(self):
        with _EnvSandbox():
            self.assertEqual(
                tr.source_for("shop"), "none",
            )

    def test_legacy_when_only_key_set(self):
        with _EnvSandbox():
            os.environ["SHOPAI_SHOPIFY_KEY"] = "k"
            self.assertEqual(
                tr.source_for("shop"), "legacy_static",
            )


class TestConnectorActivation(unittest.TestCase):
    def test_connector_uses_resolver(self):
        with _EnvSandbox():
            os.environ.update({
                "SHOPAI_SHOPIFY_URL": "s.myshopify.com",
                "SHOPAI_SHOPIFY_KEY": "legacy-k",
            })
            # Fresh import so the connector picks up env
            from core.bridge.shopify_connector import (
                ShopifyLiveConnector,
            )
            c = ShopifyLiveConnector()
            self.assertEqual(c._api_key, "legacy-k")
            self.assertTrue(c.is_configured)


if __name__ == "__main__":
    unittest.main()
