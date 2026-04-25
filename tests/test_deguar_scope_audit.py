"""Tests for scripts/deguar_scope_audit.py.

After the canonical-list refactor (commit 8050173) the audit
script is a thin shell around ``core.auth.shopify_scopes``.
These tests cover the script's specific surface area:
fetch_granted() HTTP parsing, print_report() formatting, and
main() entry-point plumbing. The diff-logic itself is tested
in tests/test_shopify_scopes.py (closer to the source of
truth).
"""
from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

from core.auth.shopify_scopes import (
    all_scopes,
    diff_granted,
    required_scopes,
)
from scripts import deguar_scope_audit as mod


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
        with patch(
            "scripts._shopify_client.ShopifyClient.oauth_get",
            return_value=payload,
        ):
            out = mod.fetch_granted(url="x.com", token="t")
        assert out == sorted(
            ["read_products", "write_products", "read_orders"],
        )

    def test_empty_response(self):
        with patch(
            "scripts._shopify_client.ShopifyClient.oauth_get",
            return_value={},
        ):
            out = mod.fetch_granted(url="x.com", token="t")
        assert out == []

    def test_skips_rows_without_handle(self):
        payload = {"access_scopes": [
            {"handle": "read_products"},
            {"access": "nope"},  # malformed, skipped
            {"handle": ""},       # empty, skipped
            {"handle": "write_products"},
        ]}
        with patch(
            "scripts._shopify_client.ShopifyClient.oauth_get",
            return_value=payload,
        ):
            out = mod.fetch_granted(url="x.com", token="t")
        assert out == ["read_products", "write_products"]


# ── print_report() ──────────────────────────────────────


class TestPrintReport:
    def test_rc_0_when_all_granted(self, capsys):
        handles = [s.handle for s in all_scopes()]
        d = diff_granted(handles)
        rc = mod.print_report(d)
        assert rc == 0
        out = capsys.readouterr().out
        assert "All required + recommended scopes granted" in out

    def test_rc_1_when_required_missing(self, capsys):
        d = diff_granted([])
        rc = mod.print_report(d)
        # Exit 1 — required scopes are missing
        assert rc == 1
        out = capsys.readouterr().out
        assert "MISSING REQUIRED" in out
        # One of the actually-required handles must appear
        req_handles = {s.handle for s in required_scopes()}
        assert any(h in out for h in req_handles)

    def test_rc_0_when_only_recommended_missing(self, capsys):
        """Grant every required scope + no recommended →
        exit 0 (recommended is opt-in, not blocking)."""
        handles = [s.handle for s in required_scopes()]
        d = diff_granted(handles)
        rc = mod.print_report(d)
        assert rc == 0
        out = capsys.readouterr().out
        # Report still surfaces the missing recommended bucket
        assert "Missing recommended" in out

    def test_extra_bucket_printed(self, capsys):
        d = diff_granted(
            [s.handle for s in all_scopes()]
            + ["read_something_unexpected"],
        )
        mod.print_report(d)
        out = capsys.readouterr().out
        assert "read_something_unexpected" in out


# ── main() entry point ──────────────────────────────────


class TestMain:
    def test_missing_env_rc2(self, monkeypatch, capsys):
        monkeypatch.delenv("SHOPAI_SHOPIFY_URL", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_KEY", raising=False)
        monkeypatch.delenv(
            "SHOPAI_SHOPIFY_TOKEN", raising=False,
        )
        rc = mod.main([])
        assert rc == 2
        err = capsys.readouterr().err
        assert "SHOPAI_SHOPIFY_URL" in err

    def test_401_rc3(self, monkeypatch, capsys):
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_URL", "x.myshopify.com",
        )
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

    def test_rc1_on_missing_required(
        self, monkeypatch, capsys,
    ):
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_URL", "x.myshopify.com",
        )
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "good")
        with patch.object(
            mod, "fetch_granted",
            lambda *, url, token: ["read_products"],
        ):
            rc = mod.main([])
        assert rc == 1  # required scopes missing
        out = capsys.readouterr().out
        assert "MISSING REQUIRED" in out
        # write_products is required, missing in this grant
        assert "write_products" in out

    def test_rc0_when_fully_granted(
        self, monkeypatch, capsys,
    ):
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_URL", "x.myshopify.com",
        )
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "good")
        all_needed = [s.handle for s in all_scopes()]
        with patch.object(
            mod, "fetch_granted",
            lambda *, url, token: all_needed,
        ):
            rc = mod.main([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "All required + recommended scopes granted" in out

    def test_list_only_does_not_touch_network(
        self, monkeypatch, capsys,
    ):
        """--list-only short-circuits before
        fetch_granted runs; should succeed with no env
        or network."""
        # Explicitly blow up fetch_granted so if --list-only
        # accidentally calls it the test fails loudly.
        with patch.object(
            mod, "fetch_granted",
            side_effect=AssertionError(
                "--list-only should not call fetch_granted",
            ),
        ):
            rc = mod.main(["--list-only"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Required (" in out
        assert "Recommended (" in out
