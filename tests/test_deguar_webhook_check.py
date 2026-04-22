"""Tests for scripts/deguar_webhook_check.py.

Covers:
  * URL-flagging heuristic (localhost / HTTP / cloudflare trial)
  * diff() logic (covered / missing / extra)
  * fetch_webhooks parses response
  * main() exit codes: 0 healthy / 1 URL-flagged / 2 missing
  * 403 + 401 error paths with actionable messages
"""
from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

from scripts import deguar_webhook_check as mod


# ── URL flag heuristic ────────────────────────────────────


class TestFlagUrl:
    def test_empty_url(self):
        assert mod._flag_url("") == "MISSING"

    def test_localhost_flagged(self):
        assert "UNREACHABLE" in mod._flag_url("https://localhost/cb")
        assert "UNREACHABLE" in mod._flag_url("https://127.0.0.1/cb")
        assert "UNREACHABLE" in mod._flag_url("https://192.168.1.5/cb")

    def test_http_flagged(self):
        assert "HTTPS" in mod._flag_url("http://example.com/cb")

    def test_cloudflare_trial_flagged(self):
        flag = mod._flag_url(
            "https://abc-def.trycloudflare.com/cb",
        )
        assert "TRIAL" in flag

    def test_clean_https_passes(self):
        assert mod._flag_url("https://api.deguar.com/cb") == ""

    def test_not_https_flagged(self):
        assert mod._flag_url("ftp://example.com") == "NOT HTTPS"


# ── diff() ───────────────────────────────────────────────


class TestDiff:
    def test_all_missing(self):
        d = mod.diff([])
        assert d["covered"] == []
        assert len(d["missing"]) == len(mod._NEEDS)
        # Each missing row carries "why"
        assert all("why" in r for r in d["missing"])

    def test_all_covered(self):
        registered = [
            {
                "id": i, "topic": n["topic"],
                "address": "https://api.deguar.com/cb",
                "format": "json",
            }
            for i, n in enumerate(mod._NEEDS)
        ]
        d = mod.diff(registered)
        assert d["missing"] == []
        assert len(d["covered"]) == len(mod._NEEDS)
        # None flagged (clean https URL)
        assert all(row["flag"] == "" for row in d["covered"])

    def test_covered_with_bad_url_flagged(self):
        registered = [{
            "id": 1, "topic": "orders/create",
            "address": "http://localhost:8080/cb",
            "format": "json",
        }]
        d = mod.diff(registered)
        assert any(
            row["topic"] == "orders/create"
            for row in d["covered"]
        )
        covered = [r for r in d["covered"]
                   if r["topic"] == "orders/create"][0]
        assert covered["flag"]  # non-empty (localhost)

    def test_extra_topics_surfaced(self):
        registered = [{
            "id": 99, "topic": "carts/create",
            "address": "https://api.deguar.com/cb",
        }]
        d = mod.diff(registered)
        extra_topics = {r["topic"] for r in d["extra"]}
        assert "carts/create" in extra_topics

    def test_multiple_hooks_same_topic(self):
        registered = [
            {
                "id": 1, "topic": "orders/create",
                "address": "https://a.com/cb",
            },
            {
                "id": 2, "topic": "orders/create",
                "address": "https://b.com/cb",
            },
        ]
        d = mod.diff(registered)
        covered = [r for r in d["covered"]
                   if r["topic"] == "orders/create"]
        assert len(covered) == 2

    def test_deterministic_order(self):
        registered = [
            {"id": 1, "topic": "orders/create",
             "address": "https://a.com/cb"},
            {"id": 2, "topic": "orders/paid",
             "address": "https://a.com/cb"},
        ]
        a = mod.diff(registered)
        b = mod.diff(list(reversed(registered)))
        assert a == b


# ── fetch_webhooks ───────────────────────────────────────


class TestFetchWebhooks:
    def test_parses_response(self):
        client_like = patch(
            "scripts._shopify_client.ShopifyClient.get",
            return_value={"webhooks": [
                {"id": 1, "topic": "orders/create",
                 "address": "https://x.com/cb"},
            ]},
        )
        with client_like:
            from scripts._shopify_client import ShopifyClient
            out = mod.fetch_webhooks(
                ShopifyClient(url="x.myshopify.com", token="t"),
            )
        assert len(out) == 1
        assert out[0]["topic"] == "orders/create"

    def test_empty_response(self):
        with patch(
            "scripts._shopify_client.ShopifyClient.get",
            return_value={},
        ):
            from scripts._shopify_client import ShopifyClient
            out = mod.fetch_webhooks(
                ShopifyClient(url="x.myshopify.com", token="t"),
            )
        assert out == []


# ── main() exit codes ────────────────────────────────────


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "x.myshopify.com")
    monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_good")


class TestMain:
    def test_rc0_all_covered_clean_urls(self, env, capsys):
        clean = [
            {"id": i, "topic": n["topic"],
             "address": "https://api.deguar.com/cb",
             "format": "json"}
            for i, n in enumerate(mod._NEEDS)
        ]
        with patch.object(mod, "fetch_webhooks", return_value=clean):
            rc = mod.main([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Covered topics (5)" in out

    def test_rc1_when_url_flagged(self, env, capsys):
        flagged = [
            {"id": i, "topic": n["topic"],
             "address": "http://localhost/cb", "format": "json"}
            for i, n in enumerate(mod._NEEDS)
        ]
        with patch.object(mod, "fetch_webhooks", return_value=flagged):
            rc = mod.main([])
        assert rc == 1
        out = capsys.readouterr().out
        assert "UNREACHABLE" in out

    def test_rc2_when_missing(self, env, capsys):
        with patch.object(mod, "fetch_webhooks", return_value=[]):
            rc = mod.main([])
        assert rc == 2
        out = capsys.readouterr().out
        assert "MISSING (5)" in out
        assert "SHOPAI_WEBHOOK_CALLBACK_URL" in out

    def test_env_missing_rc2(self, monkeypatch, capsys):
        monkeypatch.delenv("SHOPAI_SHOPIFY_URL", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_KEY", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_TOKEN", raising=False)
        rc = mod.main([])
        assert rc == 2
        err = capsys.readouterr().err
        assert "SHOPAI_SHOPIFY_URL" in err

    def test_401_rc3(self, env, capsys):
        def boom(client):
            raise urllib.error.HTTPError(
                "u", 401, "Unauthorized", None, None,
            )
        with patch.object(mod, "fetch_webhooks", boom):
            rc = mod.main([])
        assert rc == 3
        err = capsys.readouterr().err
        assert "token rejected" in err

    def test_403_rc3_points_at_scope(self, env, capsys):
        def boom(client):
            raise urllib.error.HTTPError(
                "u", 403, "Forbidden", None, None,
            )
        with patch.object(mod, "fetch_webhooks", boom):
            rc = mod.main([])
        assert rc == 3
        err = capsys.readouterr().err
        # The fix message points at the scope audit script
        assert "read_webhooks" in err
        assert "scope_audit" in err
