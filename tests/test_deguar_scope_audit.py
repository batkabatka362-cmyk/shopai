"""Tests for scripts/deguar_scope_audit.py.

Pure-function coverage of the diff logic + error-path
coverage for the HTTP fetch. No network hits.
"""
from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

from scripts import deguar_scope_audit as mod


# ── diff() logic ─────────────────────────────────────────


class TestDiff:
    def test_all_granted_empty_missing(self):
        all_scopes = [n["scope"] for n in mod._NEEDS]
        d = mod.diff(all_scopes)
        assert d["missing"] == []
        assert len(d["granted"]) == len(mod._NEEDS)

    def test_all_missing(self):
        d = mod.diff([])
        assert d["granted"] == []
        assert len(d["missing"]) == len(mod._NEEDS)
        # Every missing row carries the "why" metadata
        for row in d["missing"]:
            assert "why" in row
            assert row["why"]

    def test_partial_grant(self):
        d = mod.diff(["read_products", "write_products"])
        granted = {r["scope"] for r in d["granted"]}
        missing = {r["scope"] for r in d["missing"]}
        assert granted == {"read_products", "write_products"}
        # The blocking scopes flagged in tracker §8 must show up
        assert "write_price_rules" in missing
        assert "write_shop_policies" in missing
        assert "write_online_store_navigation" in missing
        assert "write_themes" in missing

    def test_extra_scopes_surfaced(self):
        """Granted scopes ShopAI doesn't claim to need should
        appear in 'extra'."""
        d = mod.diff([
            "read_products",
            "write_fulfillments",  # not in our NEEDS
            "read_locations",      # not in our NEEDS
        ])
        extras = {r["scope"] for r in d["extra"]}
        assert "write_fulfillments" in extras
        assert "read_locations" in extras
        # read_products in needs, NOT in extra
        assert "read_products" not in extras

    def test_deterministic_order(self):
        """Two runs with the same input produce identical diffs
        (needed for CI / grep-based alerting)."""
        a = mod.diff(["read_products", "write_products"])
        b = mod.diff(["write_products", "read_products"])
        assert a == b


# ── fetch_granted() ─────────────────────────────────────


class TestFetchGranted:
    def test_parses_handles(self):
        payload = {
            "access_scopes": [
                {"handle": "read_products"},
                {"handle": "write_products"},
                {"handle": "read_orders"},
            ],
        }
        with patch.object(mod, "_api", return_value=payload):
            out = mod.fetch_granted(url="x.com", token="t")
        assert out == sorted(
            ["read_products", "write_products", "read_orders"],
        )

    def test_empty_response(self):
        with patch.object(mod, "_api", return_value={}):
            out = mod.fetch_granted(url="x.com", token="t")
        assert out == []

    def test_skips_rows_without_handle(self):
        payload = {"access_scopes": [
            {"handle": "read_products"},
            {"access": "nope"},  # malformed row, skipped
            {"handle": ""},       # empty, skipped
            {"handle": "write_products"},
        ]}
        with patch.object(mod, "_api", return_value=payload):
            out = mod.fetch_granted(url="x.com", token="t")
        assert out == ["read_products", "write_products"]


# ── main() error paths ──────────────────────────────────


class TestMain:
    def test_missing_env_rc2(self, monkeypatch, capsys):
        monkeypatch.delenv("SHOPAI_SHOPIFY_URL", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_KEY", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_TOKEN", raising=False)
        rc = mod.main([])
        assert rc == 2
        err = capsys.readouterr().err
        assert "SHOPAI_SHOPIFY_URL" in err

    def test_401_rc3(self, monkeypatch, capsys):
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "x.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "bad")

        def boom(*, url, token):
            raise urllib.error.HTTPError(
                "u", 401, "Unauthorized", None, None,
            )
        with patch.object(mod, "fetch_granted", boom):
            rc = mod.main([])
        assert rc == 3
        err = capsys.readouterr().err
        assert "token rejected" in err

    def test_rc1_on_missing_scopes(self, monkeypatch, capsys):
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "x.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "good")
        # Only grant one scope → many missing
        with patch.object(
            mod, "fetch_granted",
            lambda *, url, token: ["read_products"],
        ):
            rc = mod.main([])
        assert rc == 1  # some missing
        out = capsys.readouterr().out
        assert "MISSING" in out
        assert "write_products" in out

    def test_rc0_when_fully_granted(self, monkeypatch, capsys):
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "x.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "good")
        all_needed = [n["scope"] for n in mod._NEEDS]
        with patch.object(
            mod, "fetch_granted",
            lambda *, url, token: all_needed,
        ):
            rc = mod.main([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "All required scopes granted" in out
