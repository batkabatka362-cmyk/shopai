"""Tests for scripts/shopify_oauth_install.py — HMAC verify,
shop validation, env upsert, and the GET /, GET /callback
dispatch.
"""
from __future__ import annotations

import hmac
import hashlib
import pathlib
import time
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest

from scripts import shopify_oauth_install as mod


def _now_ts() -> str:
    """Fresh UNIX timestamp string. Tests must use this rather
    than a hard-coded value because the script rejects
    timestamps outside a 1h freshness window — local + CI
    runs are weeks apart on the wall clock."""
    return str(int(time.time()))


# ── verify_hmac ──────────────────────────────────────────


class TestVerifyHmac:
    def _sign(self, params: dict, secret: str) -> str:
        pairs = sorted(params.items())
        canonical = "&".join(f"{k}={v}" for k, v in pairs)
        return hmac.new(
            secret.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()

    def test_valid_signature_passes(self):
        secret = "s3cr3t"
        params = {
            "shop": "x.myshopify.com",
            "timestamp": _now_ts(),
        }
        sig = self._sign(params, secret)
        query = urllib.parse.urlencode(
            {**params, "hmac": sig},
        )
        assert mod.verify_hmac(
            query, client_secret=secret,
        ) is True

    def test_wrong_secret_fails(self):
        params = {"shop": "x.myshopify.com"}
        sig = self._sign(params, "right")
        query = urllib.parse.urlencode(
            {**params, "hmac": sig},
        )
        assert mod.verify_hmac(
            query, client_secret="wrong",
        ) is False

    def test_no_hmac_param_fails(self):
        assert mod.verify_hmac(
            "shop=x.myshopify.com", client_secret="x",
        ) is False

    def test_signature_param_ignored(self):
        """Legacy `signature` param must not break HMAC."""
        secret = "s"
        params = {
            "shop": "x.myshopify.com",
            "timestamp": "1",
        }
        sig = self._sign(params, secret)
        query = urllib.parse.urlencode({
            **params,
            "signature": "old-legacy-value",
            "hmac": sig,
        })
        assert mod.verify_hmac(
            query, client_secret=secret,
        ) is True


# ── verify_shop ──────────────────────────────────────────


class TestVerifyShop:
    def test_valid(self):
        assert mod.verify_shop("ts0efe-ih.myshopify.com")

    def test_bad_suffix(self):
        assert not mod.verify_shop("ts0efe-ih.com")

    def test_empty(self):
        assert not mod.verify_shop("")

    def test_invalid_chars(self):
        # Shopify handles allow alnum + hyphen only.
        assert not mod.verify_shop(
            "bad!shop.myshopify.com",
        )

    def test_too_long_handle(self):
        handle = "x" * 61  # >60 chars
        assert not mod.verify_shop(
            f"{handle}.myshopify.com",
        )


# ── write_token_to_env ───────────────────────────────────


class TestWriteTokenToEnv:
    def test_create_new_file(self, tmp_path):
        env = tmp_path / ".env"
        mod.write_token_to_env(
            "shpat_abc", env_path=env,
        )
        assert (
            "SHOPAI_SHOPIFY_KEY=shpat_abc"
            in env.read_text()
        )

    def test_preserve_other_lines(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "OTHER=val\nSHOPAI_SHOPIFY_URL=x\n",
        )
        mod.write_token_to_env(
            "shpat_new", env_path=env,
        )
        text = env.read_text()
        assert "OTHER=val" in text
        assert "SHOPAI_SHOPIFY_URL=x" in text
        assert "SHOPAI_SHOPIFY_KEY=shpat_new" in text

    def test_replace_existing_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "SHOPAI_SHOPIFY_KEY=old_token\nOTHER=x\n",
        )
        mod.write_token_to_env(
            "shpat_new", env_path=env,
        )
        text = env.read_text()
        assert "old_token" not in text
        assert "SHOPAI_SHOPIFY_KEY=shpat_new" in text
        # Only one SHOPAI_SHOPIFY_KEY line
        assert text.count(
            "SHOPAI_SHOPIFY_KEY=",
        ) == 1


# ── Path dispatch (/, /callback, 404) ───────────────────


def _sign_query(params: dict, secret: str) -> str:
    pairs = sorted(params.items())
    canonical = "&".join(f"{k}={v}" for k, v in pairs)
    return hmac.new(
        secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()


class TestPathDispatch:
    """Simulate the handler's do_GET by calling verify_hmac +
    the redirect logic directly. Full integration with the
    HTTP server is covered by the script's manual-run smoke
    test; this class pins the routing contract."""

    def _make_handler(self):
        h = mod._InstallHandler.__new__(mod._InstallHandler)
        h.__class__.client_id = "test_id"
        h.__class__.client_secret = "test_secret"
        h.__class__.redirect_uri = "http://localhost:9000/callback"
        h.__class__.scope_string = "read_products,write_products"
        h.__class__.env_path = pathlib.Path("/tmp/_unused")
        h.__class__.result = {}
        import threading
        h.__class__.done_event = threading.Event()
        return h

    def test_unknown_path_404s(self):
        h = self._make_handler()
        h.path = "/unknown"
        h.wfile = MagicMock()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        h.do_GET()
        h.send_response.assert_called_with(404)

    def test_root_without_code_redirects_to_authorize(self):
        """The fix in this commit: / (App URL) redirects to
        Shopify's /admin/oauth/authorize rather than 404."""
        h = self._make_handler()
        shop = "ts0efe-ih.myshopify.com"
        params = {
            "shop": shop,
            "timestamp": _now_ts(),
            "host": "YWRtaW4uc2hvcGlmeS5jb20",
        }
        sig = _sign_query(
            params, h.__class__.client_secret,
        )
        h.path = "/?" + urllib.parse.urlencode(
            {**params, "hmac": sig},
        )
        h.wfile = MagicMock()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        h.do_GET()
        # 302 redirect
        h.send_response.assert_called_with(302)
        # Location header points at Shopify's authorize endpoint
        location_calls = [
            c for c in h.send_header.call_args_list
            if c.args and c.args[0] == "Location"
        ]
        assert location_calls, "no Location header set"
        target = location_calls[0].args[1]
        assert "admin/oauth/authorize" in target
        assert f"{shop}" in target
        assert "client_id=test_id" in target
        assert "scope=" in target

    def test_callback_without_code_also_redirects(self):
        """Backwards compat: /callback without code still
        redirects to authorize (no regression on the old
        path)."""
        h = self._make_handler()
        params = {
            "shop": "ts0efe-ih.myshopify.com",
            "timestamp": _now_ts(),
        }
        sig = _sign_query(
            params, h.__class__.client_secret,
        )
        h.path = "/callback?" + urllib.parse.urlencode(
            {**params, "hmac": sig},
        )
        h.wfile = MagicMock()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        h.do_GET()
        h.send_response.assert_called_with(302)

    def test_bad_hmac_fails_fast(self):
        h = self._make_handler()
        h.path = (
            "/?shop=ts0efe-ih.myshopify.com"
            "&timestamp=1777029332&hmac=WRONG"
        )
        h.wfile = MagicMock()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()
        h.do_GET()
        # HMAC failure → 400
        h.send_response.assert_called_with(400)
        assert h.__class__.result.get("ok") is False
        assert "HMAC" in h.__class__.result.get("error", "")

    def test_callback_with_code_exchanges_and_saves(
        self, tmp_path,
    ):
        """Full OAuth exchange path: /callback?code=X runs
        _exchange_code and writes the token."""
        h = self._make_handler()
        h.__class__.env_path = tmp_path / ".env"
        shop = "ts0efe-ih.myshopify.com"
        params = {
            "shop": shop,
            "timestamp": _now_ts(),
            "code": "0a1b2c",
        }
        sig = _sign_query(
            params, h.__class__.client_secret,
        )
        h.path = "/callback?" + urllib.parse.urlencode(
            {**params, "hmac": sig},
        )
        h.wfile = MagicMock()
        h.send_response = MagicMock()
        h.send_header = MagicMock()
        h.end_headers = MagicMock()

        with patch.object(
            mod, "_exchange_code",
            return_value="shpat_xxx",
        ):
            h.do_GET()
        h.send_response.assert_called_with(200)
        assert h.__class__.result["ok"] is True
        assert h.__class__.result["shop"] == shop
        assert (
            "SHOPAI_SHOPIFY_KEY=shpat_xxx"
            in h.__class__.env_path.read_text()
        )


# ── _load_dotenv (Windows / PowerShell UX) ──────────────


class TestLoadDotenv:
    def test_populates_missing_vars(
        self, tmp_path, monkeypatch,
    ):
        env = tmp_path / ".env"
        env.write_text(
            "SHOPAI_SHOPIFY_CLIENT_ID=abc123\n"
            "SHOPAI_SHOPIFY_CLIENT_SECRET=secret_xyz\n",
        )
        # Make sure neither is in env initially.
        monkeypatch.delenv(
            "SHOPAI_SHOPIFY_CLIENT_ID", raising=False,
        )
        monkeypatch.delenv(
            "SHOPAI_SHOPIFY_CLIENT_SECRET", raising=False,
        )
        mod._load_dotenv(env)
        import os
        assert os.environ["SHOPAI_SHOPIFY_CLIENT_ID"] == "abc123"
        assert (
            os.environ["SHOPAI_SHOPIFY_CLIENT_SECRET"]
            == "secret_xyz"
        )

    def test_does_not_override_existing_env(
        self, tmp_path, monkeypatch,
    ):
        env = tmp_path / ".env"
        env.write_text(
            "SHOPAI_SHOPIFY_CLIENT_ID=from_file\n",
        )
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_CLIENT_ID", "from_shell",
        )
        mod._load_dotenv(env)
        import os
        # Shell export wins.
        assert (
            os.environ["SHOPAI_SHOPIFY_CLIENT_ID"]
            == "from_shell"
        )

    def test_skips_missing_file(self, tmp_path):
        # Should not raise.
        mod._load_dotenv(tmp_path / "nonexistent.env")

    def test_strips_quotes_and_comments(
        self, tmp_path, monkeypatch,
    ):
        env = tmp_path / ".env"
        env.write_text(
            "# comment line ignored\n"
            "\n"
            'SHOPAI_SHOPIFY_URL="ts0efe-ih.myshopify.com"\n'
            "SHOPAI_SHOPIFY_CLIENT_ID='abc'\n",
        )
        monkeypatch.delenv(
            "SHOPAI_SHOPIFY_URL", raising=False,
        )
        monkeypatch.delenv(
            "SHOPAI_SHOPIFY_CLIENT_ID", raising=False,
        )
        mod._load_dotenv(env)
        import os
        assert (
            os.environ["SHOPAI_SHOPIFY_URL"]
            == "ts0efe-ih.myshopify.com"
        )
        assert (
            os.environ["SHOPAI_SHOPIFY_CLIENT_ID"] == "abc"
        )
