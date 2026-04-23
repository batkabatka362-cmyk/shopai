"""Tests for scripts/deguar_backup.py."""
from __future__ import annotations

import json
import os
import urllib.error
from unittest.mock import patch

import pytest

from scripts import deguar_backup as mod
from scripts._shopify_client import ShopifyClient


def _client():
    return ShopifyClient(url="x.myshopify.com", token="t")


# ── _safe_get ───────────────────────────────────────────


class TestSafeGet:
    def test_returns_payload(self):
        with patch.object(
            ShopifyClient, "get",
            return_value={"products": [{"id": 1}]},
        ):
            out = mod._safe_get(_client(), "products.json", "x")
        assert out == {"products": [{"id": 1}]}

    def test_404_returns_none(self, capsys):
        def boom(self, p):
            raise urllib.error.HTTPError(
                "u", 404, "Not Found", None, None,
            )
        with patch.object(ShopifyClient, "get", boom):
            out = mod._safe_get(_client(), "x.json", "X")
        assert out is None
        assert "skipped" in capsys.readouterr().out

    def test_403_returns_none(self):
        def boom(self, p):
            raise urllib.error.HTTPError(
                "u", 403, "Forbidden", None, None,
            )
        with patch.object(ShopifyClient, "get", boom):
            out = mod._safe_get(_client(), "x.json", "X")
        assert out is None

    def test_500_propagates(self):
        def boom(self, p):
            raise urllib.error.HTTPError(
                "u", 500, "Server Error", None, None,
            )
        with patch.object(ShopifyClient, "get", boom):
            with pytest.raises(urllib.error.HTTPError):
                mod._safe_get(_client(), "x.json", "X")


# ── _backup_resource ────────────────────────────────────


class TestBackupResource:
    def test_writes_file_and_returns_count(self, tmp_path):
        with patch.object(
            ShopifyClient, "get",
            return_value={"products": [{"id": 1}, {"id": 2}]},
        ):
            n = mod._backup_resource(
                _client(), str(tmp_path),
                "products.json", "products.json", "Products",
            )
        assert n == 2
        path = tmp_path / "products.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["products"][0]["id"] == 1

    def test_returns_minus_one_on_skip(self, tmp_path):
        def boom(self, p):
            raise urllib.error.HTTPError(
                "u", 404, "Not Found", None, None,
            )
        with patch.object(ShopifyClient, "get", boom):
            n = mod._backup_resource(
                _client(), str(tmp_path),
                "x.json", "x.json", "X",
            )
        assert n == -1

    def test_payload_without_list_returns_one(self, tmp_path):
        """shop.json has shape {shop: {...}} — single dict, not
        a list. Count should be 1, not crash."""
        with patch.object(
            ShopifyClient, "get",
            return_value={"shop": {"name": "Deguar", "id": 1}},
        ):
            n = mod._backup_resource(
                _client(), str(tmp_path),
                "shop.json", "shop.json", "Shop",
            )
        assert n == 1


# ── _backup_product_metafields ──────────────────────────


class TestProductMetafields:
    def test_one_file_per_product(self, tmp_path):
        with patch.object(
            ShopifyClient, "get",
            return_value={"metafields": [
                {"id": 1, "namespace": "global"},
            ]},
        ):
            n = mod._backup_product_metafields(
                _client(), str(tmp_path), ["111", "222"],
            )
        assert n == 2
        sub = tmp_path / "product-metafields"
        assert (sub / "111.json").exists()
        assert (sub / "222.json").exists()

    def test_per_product_404_skipped(self, tmp_path, capsys):
        call_count = {"n": 0}

        def fake_get(self, p):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise urllib.error.HTTPError(
                    "u", 404, "Not Found", None, None,
                )
            return {"metafields": []}

        with patch.object(ShopifyClient, "get", fake_get):
            n = mod._backup_product_metafields(
                _client(), str(tmp_path), ["111", "222"],
            )
        assert n == 1  # only second one wrote
        sub = tmp_path / "product-metafields"
        assert not (sub / "111.json").exists()
        assert (sub / "222.json").exists()


# ── _backup_blog_articles ───────────────────────────────


class TestBlogArticles:
    def test_aggregates_across_blogs(self, tmp_path):
        with patch.object(
            ShopifyClient, "get",
            return_value={"articles": [
                {"id": 1, "title": "A"},
                {"id": 2, "title": "B"},
            ]},
        ):
            n = mod._backup_blog_articles(
                _client(), str(tmp_path),
                blogs=[
                    {"id": 100, "title": "News"},
                    {"id": 200, "title": "Deals"},
                ],
            )
        assert n == 4  # 2 articles × 2 blogs
        sub = tmp_path / "articles"
        assert (sub / "100.json").exists()
        assert (sub / "200.json").exists()

    def test_blog_without_id_skipped(self, tmp_path):
        with patch.object(
            ShopifyClient, "get",
            return_value={"articles": [{"id": 1}]},
        ):
            n = mod._backup_blog_articles(
                _client(), str(tmp_path),
                blogs=[{"title": "no id"}, {"id": 100}],
            )
        assert n == 1
        sub = tmp_path / "articles"
        assert (sub / "100.json").exists()


# ── main() integration ──────────────────────────────────


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "x.myshopify.com")
    monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_good")


class TestMain:
    def test_full_snapshot_writes_manifest(self, env, tmp_path):
        # Minimal stub for every resource
        responses = {
            "shop.json": {"shop": {"id": 1, "name": "Deguar"}},
            "products.json?limit=250": {"products": [
                {"id": 100, "title": "P1"},
                {"id": 200, "title": "P2"},
            ]},
            "smart_collections.json?limit=250": {
                "smart_collections": [{"id": 1}],
            },
            "custom_collections.json?limit=250": {
                "custom_collections": [],
            },
            "pages.json?limit=250": {"pages": [
                {"id": 1, "title": "About"},
            ]},
            "blogs.json?limit=250": {"blogs": [{"id": 50}]},
            "script_tags.json?limit=250": {"script_tags": []},
            "webhooks.json?limit=250": {"webhooks": [
                {"id": 1, "topic": "orders/create"},
            ]},
            "redirects.json?limit=250": {"redirects": []},
            "shipping_zones.json": {"shipping_zones": [
                {"name": "Z1"},
            ]},
            "policies.json": {"policies": [
                {"title": "Privacy"},
            ]},
            "themes.json": {"themes": [
                {"id": 1, "role": "main"},
            ]},
            # Per-product metafields
            "products/100/metafields.json": {"metafields": [
                {"id": 1},
            ]},
            "products/200/metafields.json": {"metafields": []},
            # Articles
            "blogs/50/articles.json?limit=250": {
                "articles": [{"id": 1, "title": "Welcome"}],
            },
        }

        def fake_get(self, p):
            if p in responses:
                return responses[p]
            raise urllib.error.HTTPError(
                "u", 404, "Not Found", None, None,
            )

        with patch.object(ShopifyClient, "get", fake_get):
            rc = mod.main(["--out", str(tmp_path)])
        assert rc == 0

        # Find the snapshot folder (timestamped subdir)
        subs = [p for p in tmp_path.iterdir() if p.is_dir()]
        assert len(subs) == 1
        snap = subs[0]

        # Manifest exists + has counts
        manifest = json.loads(
            (snap / "manifest.json").read_text(),
        )
        assert manifest["store"] == "x.myshopify.com"
        counts = manifest["counts"]
        assert counts["Products + variants"] == 2
        assert counts["Pages (About/FAQ/etc)"] == 1
        assert counts["Webhook subscriptions"] == 1

        # Per-product metafield files written
        assert (snap / "product-metafields" / "100.json").exists()
        assert (snap / "product-metafields" / "200.json").exists()

        # Articles written
        assert (snap / "articles" / "50.json").exists()

    def test_skip_metafields_flag(self, env, tmp_path):
        """--skip-metafields should skip ONLY the slow per-product
        loop, not the rest of the snapshot."""
        # Minimum responses for non-metafield path
        responses = {
            "shop.json": {"shop": {"id": 1}},
            "products.json?limit=250": {"products": [
                {"id": 100},
            ]},
        }

        def fake_get(self, p):
            return responses.get(p, {})

        with patch.object(ShopifyClient, "get", fake_get):
            rc = mod.main([
                "--out", str(tmp_path), "--skip-metafields",
            ])
        assert rc == 0
        snap = next(p for p in tmp_path.iterdir() if p.is_dir())
        # No per-product metafield dir
        assert not (snap / "product-metafields").exists()
        # But shop.json still backed up
        assert (snap / "shop.json").exists()

    def test_env_missing_rc2(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SHOPAI_SHOPIFY_URL", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_KEY", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_TOKEN", raising=False)
        rc = mod.main(["--out", str(tmp_path)])
        assert rc == 2
