"""Tests for Shopify OAuth token management."""
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

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


class TestTokenRefreshBackoff:
    """Test the failure backoff logic added in the perf fix."""

    def _auth(self):
        from core.auth.shopify_auth import ShopifyAuth
        return ShopifyAuth("backoff.myshopify.com", "cid", "csecret")

    def test_get_token_returns_cached_on_refresh_failure(self):
        auth = self._auth()
        with patch.object(auth, "_request_token",
                          side_effect=RuntimeError("boom")):
            token = auth.get_token()
        assert token == ""
        assert auth._last_refresh_failure > 0

    def test_backoff_skips_retry_within_window(self):
        auth = self._auth()
        auth._last_refresh_failure = time.time()
        auth._access_token = "stale"
        # Refresh should NOT be called while within backoff window
        with patch.object(auth, "_request_token") as mocked:
            token = auth.get_token()
        assert token == "stale"
        mocked.assert_not_called()

    def test_backoff_retries_after_window(self):
        auth = self._auth()
        auth._last_refresh_failure = time.time() - 301  # past 300s backoff
        fake_data = {"access_token": "fresh", "expires_in": 7200}
        with patch.object(auth, "_request_token", return_value=fake_data), \
             patch.object(auth, "_save_cached_token"):
            token = auth.get_token()
        assert token == "fresh"

    def test_valid_token_skips_refresh_entirely(self):
        auth = self._auth()
        auth._access_token = "good"
        auth._expires_at = time.time() + 86400
        with patch.object(auth, "_request_token") as mocked:
            token = auth.get_token()
        assert token == "good"
        mocked.assert_not_called()


class TestRefreshTokenSuccess:
    """Test the happy path of refresh_token."""

    def test_refresh_updates_token_and_expiry(self):
        from core.auth.shopify_auth import ShopifyAuth
        auth = ShopifyAuth("refresh.myshopify.com", "cid", "csecret")
        fake = {"access_token": "abc123", "expires_in": 3600}
        with patch.object(auth, "_request_token", return_value=fake), \
             patch.object(auth, "_save_cached_token"):
            token = auth.refresh_token()
        assert token == "abc123"
        assert auth._access_token == "abc123"
        assert auth._expires_at > time.time() + 3500

    def test_refresh_raises_on_bad_response(self):
        from core.auth.shopify_auth import ShopifyAuth
        auth = ShopifyAuth("refresh.myshopify.com", "cid", "csecret")
        with patch.object(auth, "_request_token",
                          side_effect=RuntimeError("401 unauthorized")):
            with pytest.raises(RuntimeError):
                auth.refresh_token()


class TestAuthUrl:
    def test_default_scopes_and_redirect(self):
        from core.auth.shopify_auth import ShopifyAuth
        auth = ShopifyAuth("mystore.myshopify.com", "cid", "secret")
        url = auth.get_auth_url()
        assert url.startswith("https://mystore.myshopify.com/admin/oauth/authorize?")
        assert "client_id=cid" in url
        assert "read_products" in url
        assert "admin%2Fauth%2Fcallback" in url

    def test_custom_scopes_and_redirect(self):
        from core.auth.shopify_auth import ShopifyAuth
        auth = ShopifyAuth("s.myshopify.com", "cid", "secret")
        url = auth.get_auth_url(
            scopes="read_orders",
            redirect_uri="https://example.com/cb",
        )
        assert "scope=read_orders" in url
        assert "example.com" in url


class TestExchangeCode:
    def test_exchange_success_sets_token(self):
        from core.auth import shopify_auth as sa
        auth = sa.ShopifyAuth("ex.myshopify.com", "cid", "secret")

        class _FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self):
                return json.dumps({"access_token": "xch_tok", "expires_in": 1800}).encode()

        with patch.object(sa.urllib.request, "urlopen", return_value=_FakeResp()), \
             patch.object(auth, "_save_cached_token"):
            tok = auth.exchange_code("AUTH_CODE_XYZ")
        assert tok == "xch_tok"
        assert auth._access_token == "xch_tok"
        assert auth._expires_at > time.time() + 1700

    def test_exchange_raises_when_no_token(self):
        from core.auth import shopify_auth as sa
        auth = sa.ShopifyAuth("ex.myshopify.com", "cid", "secret")

        class _FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self):
                return json.dumps({"error": "invalid_code"}).encode()

        with patch.object(sa.urllib.request, "urlopen", return_value=_FakeResp()):
            with pytest.raises(ValueError):
                auth.exchange_code("bad")


class TestTokenDiskCache:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        from core.auth import shopify_auth as sa

        cache_dir = tmp_path / "data"
        cache_file = cache_dir / ".shopify_tokens.json"
        monkeypatch.setattr(sa, "_TOKEN_CACHE_DIR", cache_dir)
        monkeypatch.setattr(sa, "_TOKEN_CACHE_FILE", cache_file)

        a1 = sa.ShopifyAuth("disk.myshopify.com", "cidlong12345", "secret")
        a1._access_token = "persist_tok"
        a1._expires_at = time.time() + 7200
        a1._save_cached_token()
        assert cache_file.exists()

        # New instance should load it
        a2 = sa.ShopifyAuth("disk.myshopify.com", "cidlong12345", "secret")
        assert a2._access_token == "persist_tok"

    def test_expired_cached_token_not_loaded(self, tmp_path, monkeypatch):
        from core.auth import shopify_auth as sa
        cache_dir = tmp_path / "data"
        cache_file = cache_dir / ".shopify_tokens.json"
        cache_dir.mkdir()
        cache_file.write_text(json.dumps({
            "old.myshopify.com": {
                "access_token": "stale",
                "expires_at": time.time() - 100,
                "client_id": "cid...",
            }
        }))
        monkeypatch.setattr(sa, "_TOKEN_CACHE_DIR", cache_dir)
        monkeypatch.setattr(sa, "_TOKEN_CACHE_FILE", cache_file)
        auth = sa.ShopifyAuth("old.myshopify.com", "cid", "secret")
        assert auth._access_token == ""

    def test_load_all_cached_missing_file(self, tmp_path, monkeypatch):
        from core.auth import shopify_auth as sa
        monkeypatch.setattr(sa, "_TOKEN_CACHE_FILE", tmp_path / "nope.json")
        assert sa.ShopifyAuth._load_all_cached() == {}


class TestAuthManagerEdgeCases:
    def test_get_token_unknown_store_raises(self):
        from core.auth.shopify_auth import ShopifyAuthManager
        mgr = ShopifyAuthManager()
        with pytest.raises(ValueError):
            mgr.get_token("ghost.myshopify.com")

    def test_get_auth_unknown_returns_none(self):
        from core.auth.shopify_auth import ShopifyAuthManager
        mgr = ShopifyAuthManager()
        assert mgr.get_auth("ghost.myshopify.com") is None

    def test_refresh_all_reports_success_and_failure(self):
        from core.auth.shopify_auth import ShopifyAuthManager
        mgr = ShopifyAuthManager()
        ok = mgr.add_store("ok.myshopify.com", "c", "s")
        bad = mgr.add_store("bad.myshopify.com", "c", "s")
        with patch.object(ok, "refresh_token", return_value="tok"), \
             patch.object(bad, "refresh_token", side_effect=RuntimeError("fail")):
            results = mgr.refresh_all()
        assert results["ok.myshopify.com"]["status"] == "refreshed"
        assert results["bad.myshopify.com"]["status"] == "failed"
        assert "fail" in results["bad.myshopify.com"]["error"]

    def test_load_from_env_no_credentials_returns_zero(self):
        from core.auth.shopify_auth import ShopifyAuthManager
        saved = {k: os.environ.pop(k, None) for k in (
            "SHOPAI_SHOPIFY_URL", "SHOPAI_SHOPIFY_KEY",
            "SHOPAI_SHOPIFY_CLIENT_ID", "SHOPAI_SHOPIFY_CLIENT_SECRET",
        )}
        try:
            mgr = ShopifyAuthManager()
            assert mgr.load_from_env() == 0
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


class TestStoreManagerCaching:
    """Cover the _get_auth_instance cache + credential resolution."""

    def _fresh_sm(self):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        import data_pipeline.store.store_manager as sm_mod
        sm_mod._auth_instances.clear()
        tmp = tempfile.mktemp(suffix=".db")
        return StoreManager(ShopAIDatabase(tmp)), sm_mod

    def test_auth_instance_is_cached(self):
        from data_pipeline.store.store_manager import _get_auth_instance
        import data_pipeline.store.store_manager as sm_mod
        sm_mod._auth_instances.clear()
        a = _get_auth_instance("cache.myshopify.com", "cid", "sec")
        b = _get_auth_instance("cache.myshopify.com", "cid", "sec")
        assert a is b
        c = _get_auth_instance("other.myshopify.com", "cid", "sec")
        assert c is not a

    def test_get_credentials_oauth_calls_auth_once(self):
        sm, _ = self._fresh_sm()
        sm.add_store("s1", "s1.myshopify.com",
                     client_id="cid", client_secret="sec")
        creds = sm.get_credentials("s1")
        assert creds["shop_url"] == "s1.myshopify.com"
        assert creds["client_id"] == "cid"

    def test_get_credentials_legacy_api_key(self):
        sm, _ = self._fresh_sm()
        sm.add_store("s2", "s2.myshopify.com", api_key="shpat_legacy")
        creds = sm.get_credentials("s2")
        assert creds["api_key"] == "shpat_legacy"

    def test_get_credentials_env_fallback(self, monkeypatch):
        sm, _ = self._fresh_sm()
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "env.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_env")
        monkeypatch.delenv("SHOPAI_SHOPIFY_CLIENT_ID", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_CLIENT_SECRET", raising=False)
        creds = sm.get_credentials("unknown_store")
        assert creds["shop_url"] == "env.myshopify.com"
        assert creds["api_key"] == "shpat_env"

    def test_set_credentials_and_active_store(self):
        sm, _ = self._fresh_sm()
        sm.add_store("a", "a.myshopify.com", api_key="k1")
        sm.add_store("b", "b.myshopify.com", api_key="k2")
        # first added = active
        assert sm.active_store_id == "a"
        sm.set_active_store("b")
        assert sm.active_store_id == "b"
        # Unknown store
        result = sm.set_active_store("ghost")
        assert "error" in result
        # still b
        assert sm.active_store_id == "b"

    def test_remove_store_reassigns_active(self):
        sm, _ = self._fresh_sm()
        sm.add_store("a", "a.myshopify.com", api_key="k1")
        sm.add_store("b", "b.myshopify.com", api_key="k2")
        sm.remove_store("a")
        # active was 'a'; should fall back to remaining
        assert sm.active_store_id == "b"

    def test_list_stores_marks_active_and_credentials(self):
        sm, _ = self._fresh_sm()
        sm.add_store("a", "a.myshopify.com", api_key="k")
        stores = sm.list_stores()
        assert len(stores) == 1
        assert stores[0]["is_active"] is True
        assert stores[0]["has_credentials"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
