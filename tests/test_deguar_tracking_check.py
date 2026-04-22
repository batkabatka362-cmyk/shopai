"""Tests for scripts/deguar_tracking_check.py.

Pure unit + main() exit-code coverage. Storefront HTML fetches
go through a monkeypatched ``_fetch_public`` so tests never hit
the network.
"""
from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

from scripts import deguar_tracking_check as mod


# ── detect_pixels() ──────────────────────────────────────


class TestDetectPixels:
    def test_meta_pixel_via_fbq(self):
        html = "<script>fbq('init', '123');</script>"
        out = mod.detect_pixels(html)
        assert out["Meta Pixel"] is True

    def test_meta_pixel_via_connect(self):
        html = ('<script src="https://connect.facebook.net/'
                'en_US/fbevents.js"></script>')
        out = mod.detect_pixels(html)
        assert out["Meta Pixel"] is True

    def test_meta_pixel_via_tr(self):
        html = ('<img src="https://www.facebook.net/tr?id=123'
                '&ev=PageView"/>')
        out = mod.detect_pixels(html)
        assert out["Meta Pixel"] is True

    def test_tiktok_pixel_detected(self):
        html = "<script>ttq.load('TIKTOK123')</script>"
        assert mod.detect_pixels(html)["TikTok Pixel"] is True

    def test_ga4_detected(self):
        html = ('<script src="https://www.googletagmanager.com'
                '/gtag/js?id=G-ABC123"></script>')
        out = mod.detect_pixels(html)
        assert out["Google Analytics 4"] is True

    def test_nothing_detected_on_clean_html(self):
        html = "<html><body><h1>hi</h1></body></html>"
        out = mod.detect_pixels(html)
        assert not any(out.values())

    def test_case_insensitive(self):
        """Signatures match regardless of HTML case."""
        html = "<SCRIPT>FBQ('init')</SCRIPT>"
        assert mod.detect_pixels(html)["Meta Pixel"] is True


# ── fetch_script_tags() ──────────────────────────────────


class TestFetchScriptTags:
    def test_parses_response(self):
        with patch(
            "scripts._shopify_client.ShopifyClient.get",
            return_value={"script_tags": [
                {"id": 1, "src": "https://a.com/tag.js",
                 "display_scope": "all"},
            ]},
        ):
            from scripts._shopify_client import ShopifyClient
            out = mod.fetch_script_tags(
                ShopifyClient(url="x.com", token="t"),
            )
        assert len(out) == 1
        assert out[0]["src"] == "https://a.com/tag.js"

    def test_empty_response(self):
        with patch(
            "scripts._shopify_client.ShopifyClient.get",
            return_value={},
        ):
            from scripts._shopify_client import ShopifyClient
            out = mod.fetch_script_tags(
                ShopifyClient(url="x.com", token="t"),
            )
        assert out == []


# ── main() exit codes ────────────────────────────────────


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "x.myshopify.com")
    monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_good")


def _make_page_stubs(pages: dict[str, str]):
    """Build a fake _fetch_public that returns canned HTML per
    URL. Unknown URLs return empty string."""
    def fake(url):
        for substr, html in pages.items():
            if substr in url:
                return html
        return ""
    return fake


class TestMainExitCodes:
    def test_rc0_meta_everywhere(self, env, capsys):
        """Meta fbq on home + cart + product → rc 0."""
        meta_html = "<script>fbq('init', 'ABC')</script>"
        fake = _make_page_stubs({
            "https://x.myshopify.com/": meta_html,
            "/cart": meta_html,
            "/products/": meta_html,
        })
        with patch.object(mod, "_fetch_public", fake), \
             patch.object(
                 mod, "_first_product_handle",
                 return_value="galaxy",
             ), \
             patch.object(
                 mod, "fetch_script_tags", return_value=[],
             ):
            rc = mod.main([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "attribution ready" in out

    def test_rc1_partial_coverage(self, env, capsys):
        """Meta on home only, missing cart → rc 1."""
        def fake(url):
            if url.endswith("/"):
                return "<script>fbq('init')</script>"
            return "<html></html>"
        with patch.object(mod, "_fetch_public", fake), \
             patch.object(
                 mod, "_first_product_handle",
                 return_value="galaxy",
             ), \
             patch.object(
                 mod, "fetch_script_tags", return_value=[],
             ):
            rc = mod.main([])
        assert rc == 1
        out = capsys.readouterr().out
        assert "not firing on all" in out

    def test_rc2_no_meta_anywhere(self, env, capsys):
        fake = _make_page_stubs({
            "/": "<html>no pixel here</html>",
        })
        with patch.object(mod, "_fetch_public", fake), \
             patch.object(
                 mod, "_first_product_handle",
                 return_value="galaxy",
             ), \
             patch.object(
                 mod, "fetch_script_tags", return_value=[],
             ):
            rc = mod.main([])
        assert rc == 2
        out = capsys.readouterr().out
        assert "No Meta Pixel" in out

    def test_env_missing_rc2(self, monkeypatch, capsys):
        monkeypatch.delenv("SHOPAI_SHOPIFY_URL", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_KEY", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_TOKEN", raising=False)
        rc = mod.main([])
        assert rc == 2

    def test_script_tags_403_handled_gracefully(self, env, capsys):
        """403 on script_tags.json shouldn't abort the audit —
        storefront scrape still completes."""
        meta_html = "<script>fbq('init', 'A')</script>"

        def fake(url):
            # Only the home page ("/") has the pixel
            if url.rstrip("/") == "https://x.myshopify.com":
                return meta_html
            return "<html></html>"

        def boom(client):
            raise urllib.error.HTTPError(
                "u", 403, "Forbidden", None, None,
            )
        with patch.object(mod, "_fetch_public", fake), \
             patch.object(
                 mod, "_first_product_handle",
                 return_value="galaxy",
             ), \
             patch.object(mod, "fetch_script_tags", boom):
            rc = mod.main([])
        out = capsys.readouterr().out
        assert "read_script_tags" in out
        # Only home has meta → rc 1 (partial)
        assert rc == 1

    def test_skip_scripts_flag(self, env, capsys):
        meta_html = "<script>fbq('init')</script>"
        fake = _make_page_stubs({
            "/": meta_html, "/cart": meta_html,
            "/products/": meta_html,
        })
        with patch.object(mod, "_fetch_public", fake), \
             patch.object(
                 mod, "_first_product_handle",
                 return_value="galaxy",
             ) as first_call:
            # Also ensures fetch_script_tags never called
            with patch.object(
                mod, "fetch_script_tags",
                side_effect=AssertionError("should not be called"),
            ):
                rc = mod.main(["--skip-scripts"])
        assert rc == 0
        assert first_call.called
