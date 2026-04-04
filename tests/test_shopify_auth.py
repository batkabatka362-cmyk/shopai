"""Tests for Shopify OAuth token management."""
import os
import tempfile
import time
import pytest


class TestShopifyAuth:
    """Test OAuth token manager."""

    def test_init(self):
        from core.auth.shopify_auth import ShopifyAuth
        auth = ShopifyAuth("test.myshopify.com", "client_id", "client_secret")
        assert auth.is_configured

    def test_not_configured(self):
        from core.auth.shopify_auth import ShopifyAuth
        auth = ShopifyAuth("", "", "")
        assert not auth.is_configured

    def test_token_status_no_token(self):
        from core.auth.shopify_auth import ShopifyAuth
        auth = ShopifyAuth("test.myshopify.com", "cid", "csecret")
        status = auth.token_status
        assert status["shop"] == "test.myshopify.com"
        assert status["has_token"] is False
        assert status["is_valid"] is False

    def test_token_status_with_token(self):
        from core.auth.shopify_auth import ShopifyAuth
        auth = ShopifyAuth("test.myshopify.com", "cid", "csecret")
        auth._access_token = "test_token"
        auth._expires_at = time.time() + 86400
        status = auth.token_status
        assert status["has_token"] is True
        assert status["is_valid"] is True
        assert status["expires_in_h"] > 20

    def test_is_valid_expired(self):
        from core.auth.shopify_auth import ShopifyAuth
        auth = ShopifyAuth("test.myshopify.com", "cid", "csecret")
        auth._access_token = "old_token"
        auth._expires_at = time.time() - 100  # Expired
        assert not auth._is_valid()

    def test_is_valid_within_buffer(self):
        from core.auth.shopify_auth import ShopifyAuth
        auth = ShopifyAuth("test.myshopify.com", "cid", "csecret")
        auth._access_token = "token"
        # Expires in 30 min but buffer is 1 hour → invalid
        auth._expires_at = time.time() + 1800
        assert not auth._is_valid()

    def test_get_token_returns_cached(self):
        from core.auth.shopify_auth import ShopifyAuth
        auth = ShopifyAuth("test.myshopify.com", "cid", "csecret")
        auth._access_token = "cached_token"
        auth._expires_at = time.time() + 86400
        assert auth.get_token() == "cached_token"


class TestShopifyAuthManager:
    """Test multi-store OAuth manager."""

    def test_init(self):
        from core.auth.shopify_auth import ShopifyAuthManager
        mgr = ShopifyAuthManager()
        assert mgr is not None

    def test_add_store(self):
        from core.auth.shopify_auth import ShopifyAuthManager
        mgr = ShopifyAuthManager()
        auth = mgr.add_store("test.myshopify.com", "cid", "csecret")
        assert auth is not None
        assert auth.is_configured

    def test_get_auth(self):
        from core.auth.shopify_auth import ShopifyAuthManager
        mgr = ShopifyAuthManager()
        mgr.add_store("test.myshopify.com", "cid", "csecret")
        auth = mgr.get_auth("test.myshopify.com")
        assert auth is not None

    def test_get_all_status(self):
        from core.auth.shopify_auth import ShopifyAuthManager
        mgr = ShopifyAuthManager()
        mgr.add_store("s1.myshopify.com", "c1", "s1")
        mgr.add_store("s2.myshopify.com", "c2", "s2")
        status = mgr.get_all_status()
        assert len(status) == 2

    def test_load_from_env_legacy(self):
        from core.auth.shopify_auth import ShopifyAuthManager
        os.environ["SHOPAI_SHOPIFY_URL"] = "test.myshopify.com"
        os.environ["SHOPAI_SHOPIFY_KEY"] = "shpat_test123"
        os.environ.pop("SHOPAI_SHOPIFY_CLIENT_ID", None)
        os.environ.pop("SHOPAI_SHOPIFY_CLIENT_SECRET", None)
        mgr = ShopifyAuthManager()
        count = mgr.load_from_env()
        assert count == 1
        auth = mgr.get_auth("test.myshopify.com")
        assert auth is not None
        assert auth.get_token() == "shpat_test123"
        # Cleanup
        os.environ.pop("SHOPAI_SHOPIFY_URL", None)
        os.environ.pop("SHOPAI_SHOPIFY_KEY", None)

    def test_load_from_env_oauth(self):
        from core.auth.shopify_auth import ShopifyAuthManager
        os.environ["SHOPAI_SHOPIFY_URL"] = "oauth.myshopify.com"
        os.environ["SHOPAI_SHOPIFY_CLIENT_ID"] = "test_client_id"
        os.environ["SHOPAI_SHOPIFY_CLIENT_SECRET"] = "test_client_secret"
        os.environ.pop("SHOPAI_SHOPIFY_KEY", None)
        mgr = ShopifyAuthManager()
        count = mgr.load_from_env()
        assert count == 1
        auth = mgr.get_auth("oauth.myshopify.com")
        assert auth is not None
        assert auth.is_configured
        # Cleanup
        os.environ.pop("SHOPAI_SHOPIFY_URL", None)
        os.environ.pop("SHOPAI_SHOPIFY_CLIENT_ID", None)
        os.environ.pop("SHOPAI_SHOPIFY_CLIENT_SECRET", None)


class TestStoreManagerOAuth:
    """Test StoreManager OAuth integration."""

    def test_add_store_with_oauth(self):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        tmp = tempfile.mktemp(suffix=".db")
        db = ShopAIDatabase(tmp)
        sm = StoreManager(db)
        sm.add_store("test", "test.myshopify.com",
                     client_id="cid", client_secret="csecret")
        creds = sm.get_credentials("test")
        assert creds["shop_url"] == "test.myshopify.com"
        assert creds["client_id"] == "cid"

    def test_add_store_legacy(self):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        tmp = tempfile.mktemp(suffix=".db")
        db = ShopAIDatabase(tmp)
        sm = StoreManager(db)
        sm.add_store("test", "test.myshopify.com", api_key="shpat_xxx")
        creds = sm.get_credentials("test")
        assert creds["api_key"] == "shpat_xxx"


class TestCLIStoreAddOAuth:
    """Test CLI store add with OAuth."""

    def test_parser_accepts_oauth(self):
        from cli import build_parser
        parser = build_parser()
        args = parser.parse_args([
            "store", "add", "mystore", "mystore.myshopify.com",
            "--client-id", "test_cid", "--client-secret", "test_secret",
        ])
        assert args.client_id == "test_cid"
        assert args.client_secret == "test_secret"

    def test_parser_accepts_legacy(self):
        from cli import build_parser
        parser = build_parser()
        args = parser.parse_args([
            "store", "add", "mystore", "mystore.myshopify.com",
            "--api-key", "shpat_xxx",
        ])
        assert args.api_key == "shpat_xxx"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
