"""Tests for core.auth.shopify_expiring_token (Wave A-1)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.auth.shopify_expiring_token import (
    ExpiringTokenAuth,
    ExpiringTokenRecord,
    ExpiringTokenStore,
    TokenExchangeError,
)


def _resp(status=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = payload or {}
    return r


def _http(**kw):
    c = MagicMock()
    return c


class TestStore(unittest.TestCase):
    def test_save_then_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = ExpiringTokenStore(
                db_path=Path(tmp) / "t.db",
            )
            rec = ExpiringTokenRecord(
                shop="demo.myshopify.com",
                access_token="at",
                access_expires_at=1000.0,
                refresh_token="rt",
                refresh_expires_at=2000.0,
            )
            s.save(rec)
            got = s.load("demo.myshopify.com")
            self.assertEqual(got.access_token, "at")
            self.assertEqual(got.refresh_token, "rt")
            s.close()

    def test_load_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = ExpiringTokenStore(
                db_path=Path(tmp) / "t.db",
            )
            self.assertIsNone(s.load("nope"))
            s.close()

    def test_delete_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = ExpiringTokenStore(
                db_path=Path(tmp) / "t.db",
            )
            for shop in ("a.myshopify.com", "b.myshopify.com"):
                s.save(ExpiringTokenRecord(
                    shop=shop, access_token="x",
                    access_expires_at=100.0,
                    refresh_token="r",
                    refresh_expires_at=200.0,
                ))
            self.assertEqual(len(s.list_shops()), 2)
            self.assertTrue(s.delete("a.myshopify.com"))
            self.assertEqual(len(s.list_shops()), 1)
            s.close()


class TestRecordValidity(unittest.TestCase):
    def test_access_valid_true(self):
        rec = ExpiringTokenRecord(
            shop="s", access_token="at",
            access_expires_at=1000.0,
            refresh_token="rt",
            refresh_expires_at=10000.0,
        )
        self.assertTrue(
            rec.access_valid(now=100.0, buffer=60.0),
        )

    def test_access_valid_false_within_buffer(self):
        rec = ExpiringTokenRecord(
            shop="s", access_token="at",
            access_expires_at=100.0,
            refresh_token="rt",
            refresh_expires_at=10000.0,
        )
        self.assertFalse(
            rec.access_valid(now=50.0, buffer=100.0),
        )

    def test_access_valid_blank_token(self):
        rec = ExpiringTokenRecord(
            shop="s", access_token="",
            access_expires_at=1000.0,
            refresh_token="rt",
            refresh_expires_at=10000.0,
        )
        self.assertFalse(
            rec.access_valid(now=0.0, buffer=0.0),
        )

    def test_refresh_valid_expired(self):
        rec = ExpiringTokenRecord(
            shop="s", access_token="at",
            access_expires_at=10.0,
            refresh_token="rt",
            refresh_expires_at=100.0,
        )
        self.assertFalse(
            rec.refresh_valid(now=200.0),
        )


class TestAuthInstall(unittest.TestCase):
    def test_install_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ExpiringTokenStore(
                db_path=Path(tmp) / "t.db",
            )
            auth = ExpiringTokenAuth(
                client_id="ci", client_secret="cs",
                store=store,
                now_fn=lambda: 1000.0,
            )
            rec = auth.install(
                shop="demo.myshopify.com",
                access_token="at1",
                refresh_token="rt1",
            )
            self.assertEqual(rec.access_token, "at1")
            self.assertEqual(rec.access_expires_at, 1000.0 + 3600.0)
            self.assertEqual(
                rec.refresh_expires_at,
                1000.0 + 90 * 86400.0,
            )
            store.close()

    def test_install_missing_creds_raises(self):
        with self.assertRaises(ValueError):
            ExpiringTokenAuth(
                client_id="", client_secret="cs",
            )


class TestGetAccessToken(unittest.TestCase):
    def _setup(self, tmp, *, now=1000.0):
        store = ExpiringTokenStore(
            db_path=Path(tmp) / "t.db",
        )
        http = MagicMock()
        auth = ExpiringTokenAuth(
            client_id="ci", client_secret="cs",
            store=store, http=http,
            now_fn=lambda: now,
        )
        return auth, http, store

    def test_fresh_token_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth, http, store = self._setup(tmp, now=1000.0)
            auth.install(
                shop="s.myshopify.com",
                access_token="fresh",
                refresh_token="rt",
            )
            tok = auth.get_access_token("s.myshopify.com")
            self.assertEqual(tok, "fresh")
            http.post.assert_not_called()
            store.close()

    def test_expired_access_triggers_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth, http, store = self._setup(tmp, now=1000.0)
            # Install then fast-forward clock to expired
            auth.install(
                shop="s.myshopify.com",
                access_token="old",
                refresh_token="rt",
            )
            auth._now_fn = lambda: 1000.0 + 3600.0 + 1
            http.post.return_value = _resp(
                200,
                payload={
                    "access_token": "NEW",
                    "refresh_token": "RT2",
                    "expires_in": 3600,
                    "refresh_token_expires_in": 7776000,
                },
            )
            tok = auth.get_access_token("s.myshopify.com")
            self.assertEqual(tok, "NEW")
            http.post.assert_called_once()
            # Subsequent call uses refreshed state
            auth._now_fn = lambda: 1000.0 + 3600.0 + 2
            tok2 = auth.get_access_token("s.myshopify.com")
            self.assertEqual(tok2, "NEW")
            self.assertEqual(
                http.post.call_count, 1,
            )
            store.close()

    def test_unknown_shop_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth, _, store = self._setup(tmp)
            with self.assertRaises(TokenExchangeError):
                auth.get_access_token("unknown.shop")
            store.close()

    def test_refresh_expired_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth, http, store = self._setup(tmp, now=1000.0)
            auth.install(
                shop="s.myshopify.com",
                access_token="at",
                refresh_token="rt",
                access_ttl_s=60,
                refresh_ttl_s=120,
            )
            auth._now_fn = lambda: 2000.0   # both expired
            with self.assertRaises(TokenExchangeError):
                auth.get_access_token("s.myshopify.com")
            store.close()

    def test_invalidate_forces_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth, http, store = self._setup(tmp, now=1000.0)
            auth.install(
                shop="s.myshopify.com",
                access_token="at",
                refresh_token="rt",
            )
            auth.invalidate("s.myshopify.com")
            http.post.return_value = _resp(
                200,
                payload={
                    "access_token": "FRESH",
                    "refresh_token": "rt",
                    "expires_in": 3600,
                    "refresh_token_expires_in": 7776000,
                },
            )
            tok = auth.get_access_token("s.myshopify.com")
            self.assertEqual(tok, "FRESH")
            store.close()


class TestRefreshErrors(unittest.TestCase):
    def _expired_setup(self, tmp, *, http):
        store = ExpiringTokenStore(
            db_path=Path(tmp) / "t.db",
        )
        auth = ExpiringTokenAuth(
            client_id="ci", client_secret="cs",
            store=store, http=http,
            now_fn=lambda: 1000.0,
        )
        auth.install(
            shop="s.myshopify.com",
            access_token="old",
            refresh_token="rt",
        )
        auth._now_fn = lambda: 10000.0   # access expired
        return auth, store

    def test_http_error_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = MagicMock()
            http.post.return_value = _resp(
                500, text="boom",
            )
            auth, store = self._expired_setup(
                tmp, http=http,
            )
            with self.assertRaises(TokenExchangeError):
                auth.get_access_token("s.myshopify.com")
            store.close()

    def test_network_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = MagicMock()
            http.post.side_effect = RuntimeError(
                "net",
            )
            auth, store = self._expired_setup(
                tmp, http=http,
            )
            with self.assertRaises(TokenExchangeError):
                auth.get_access_token("s.myshopify.com")
            store.close()

    def test_missing_access_in_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = MagicMock()
            http.post.return_value = _resp(
                200, payload={"refresh_token": "x"},
            )
            auth, store = self._expired_setup(
                tmp, http=http,
            )
            with self.assertRaises(TokenExchangeError):
                auth.get_access_token("s.myshopify.com")
            store.close()


class TestStatus(unittest.TestCase):
    def test_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = ExpiringTokenAuth(
                client_id="ci", client_secret="cs",
                store=ExpiringTokenStore(
                    db_path=Path(tmp) / "t.db",
                ),
                now_fn=lambda: 1000.0,
            )
            s = auth.token_status("unknown")
            self.assertEqual(s["status"], "not_installed")

    def test_active_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ExpiringTokenStore(
                db_path=Path(tmp) / "t.db",
            )
            auth = ExpiringTokenAuth(
                client_id="ci", client_secret="cs",
                store=store, now_fn=lambda: 1000.0,
            )
            auth.install(
                shop="s", access_token="at",
                refresh_token="rt",
            )
            s = auth.token_status("s")
            self.assertEqual(s["status"], "active")
            self.assertGreater(
                s["access_expires_in_s"], 0,
            )
            store.close()


class TestDict(unittest.TestCase):
    def test_record_dict(self):
        rec = ExpiringTokenRecord(
            shop="s", access_token="at",
            access_expires_at=1.0,
            refresh_token="rt",
            refresh_expires_at=2.0,
        )
        d = rec.as_dict()
        self.assertEqual(d["shop"], "s")


if __name__ == "__main__":
    unittest.main()
