"""Tests for scripts/deguar_collection_check.py."""
from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

from scripts import deguar_collection_check as mod
from scripts._shopify_client import ShopifyClient


# ── Helpers ─────────────────────────────────────────────


def _smart(handle: str, rules: list[dict] | None = None,
           published: bool = True) -> dict:
    return {
        "id": hash(handle) & 0xFFFFFFFF,
        "handle": handle,
        "title": handle.replace("-", " ").title(),
        "rules": rules or [{
            "column": "tag", "relation": "equals",
            "condition": "cozy",
        }],
        "published_at": "2026-04-20T00:00:00Z" if published else None,
        "disjunctive": False,
    }


def _client():
    return ShopifyClient(url="x.myshopify.com", token="t")


# ── _summarise_rules ────────────────────────────────────


class TestSummariseRules:
    def test_single_rule(self):
        c = _smart("cozy-bedroom")
        out = mod._summarise_rules(c)
        assert "tag" in out
        assert "cozy" in out

    def test_disjunctive_rules(self):
        c = _smart("multi", rules=[
            {"column": "tag", "relation": "equals", "condition": "a"},
            {"column": "tag", "relation": "equals", "condition": "b"},
        ])
        c["disjunctive"] = True
        out = mod._summarise_rules(c)
        assert " OR " in out

    def test_no_rules_marks_manual(self):
        c = {"rules": []}
        assert "manual" in mod._summarise_rules(c)


# ── fetch_all_collections ────────────────────────────────


class TestFetchAll:
    def test_merges_smart_and_custom(self):
        def fake_get(self, path):
            if "smart_collections" in path:
                return {"smart_collections": [
                    _smart("cozy-bedroom"),
                ]}
            if "custom_collections" in path:
                return {"custom_collections": [{
                    "id": 999, "handle": "best-sellers",
                    "title": "Best Sellers", "published_at": "x",
                }]}
            return {}
        with patch.object(ShopifyClient, "get", fake_get):
            out = mod.fetch_all_collections(_client())
        handles = {c["handle"] for c in out}
        assert handles == {"cozy-bedroom", "best-sellers"}
        kinds = {c["handle"]: c["kind"] for c in out}
        assert kinds["cozy-bedroom"] == "smart"
        assert kinds["best-sellers"] == "custom"


# ── product_count ────────────────────────────────────────


class TestProductCount:
    def test_counts_products(self):
        def fake_get(self, path):
            return {"products": [{"id": 1}, {"id": 2}, {"id": 3}]}
        with patch.object(ShopifyClient, "get", fake_get):
            n = mod.product_count(_client(), "123")
        assert n == 3

    def test_404_returns_zero(self):
        def fake_get(self, path):
            raise urllib.error.HTTPError(
                "u", 404, "Not Found", None, None,
            )
        with patch.object(ShopifyClient, "get", fake_get):
            n = mod.product_count(_client(), "123")
        assert n == 0


# ── audit() ──────────────────────────────────────────────


class TestAudit:
    def test_all_expected_healthy(self):
        expected_handles = list(mod._EXPECTED)
        colls = [_smart(h) for h in expected_handles]

        with patch.object(
            mod, "fetch_all_collections", return_value=colls,
        ), patch.object(
            mod, "product_count", return_value=5,
        ):
            result = mod.audit(_client(), min_products=3)
        assert len(result["healthy"]) == len(expected_handles)
        assert result["empty"] == []
        assert result["missing"] == []
        assert result["thin"] == []

    def test_missing_flagged(self):
        # Only one of the five created
        colls = [_smart("cozy-bedroom")]
        with patch.object(
            mod, "fetch_all_collections", return_value=colls,
        ), patch.object(
            mod, "product_count", return_value=5,
        ):
            result = mod.audit(_client(), min_products=3)
        missing_handles = {
            r["handle"] for r in result["missing"]
        }
        assert "best-sellers" in missing_handles
        assert "aromatherapy" in missing_handles
        assert "cozy-bedroom" not in missing_handles

    def test_empty_flagged_when_count_zero(self):
        colls = [_smart(h) for h in mod._EXPECTED]

        def fake_count(client, cid):
            # aromatherapy returns 0; rest return 5
            if cid == (hash("aromatherapy") & 0xFFFFFFFF):
                return 0
            return 5

        with patch.object(
            mod, "fetch_all_collections", return_value=colls,
        ), patch.object(
            mod, "product_count", side_effect=fake_count,
        ):
            result = mod.audit(_client(), min_products=3)
        empty_handles = {r["handle"] for r in result["empty"]}
        assert "aromatherapy" in empty_handles

    def test_thin_flagged_below_min(self):
        colls = [_smart(h) for h in mod._EXPECTED]

        def fake_count(client, cid):
            if cid == (hash("under-25-gift") & 0xFFFFFFFF):
                return 1  # below default min=3
            return 10

        with patch.object(
            mod, "fetch_all_collections", return_value=colls,
        ), patch.object(
            mod, "product_count", side_effect=fake_count,
        ):
            result = mod.audit(_client(), min_products=3)
        thin_handles = {r["handle"] for r in result["thin"]}
        assert "under-25-gift" in thin_handles

    def test_extra_collections_surfaced(self):
        expected = [_smart(h) for h in mod._EXPECTED]
        extras = [
            _smart("ancient-legacy-collection"),
            _smart("all"),         # built-in — should NOT appear
            _smart("frontpage"),   # built-in — should NOT appear
        ]
        with patch.object(
            mod, "fetch_all_collections",
            return_value=expected + extras,
        ), patch.object(
            mod, "product_count", return_value=5,
        ):
            result = mod.audit(_client(), min_products=3)
        extra_handles = {r["handle"] for r in result["extra"]}
        assert "ancient-legacy-collection" in extra_handles
        assert "all" not in extra_handles
        assert "frontpage" not in extra_handles


# ── main() ──────────────────────────────────────────────


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "x.myshopify.com")
    monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_good")


class TestMain:
    def test_rc0_all_healthy(self, env):
        colls = [_smart(h) for h in mod._EXPECTED]
        with patch.object(
            mod, "fetch_all_collections", return_value=colls,
        ), patch.object(
            mod, "product_count", return_value=5,
        ):
            rc = mod.main([])
        assert rc == 0

    def test_rc1_when_thin(self, env):
        colls = [_smart(h) for h in mod._EXPECTED]
        with patch.object(
            mod, "fetch_all_collections", return_value=colls,
        ), patch.object(
            mod, "product_count", return_value=1,  # < default 3
        ):
            rc = mod.main([])
        assert rc == 1

    def test_rc2_when_empty(self, env):
        colls = [_smart(h) for h in mod._EXPECTED]
        with patch.object(
            mod, "fetch_all_collections", return_value=colls,
        ), patch.object(
            mod, "product_count", return_value=0,
        ):
            rc = mod.main([])
        assert rc == 2

    def test_rc2_when_missing(self, env):
        # Only one collection present
        with patch.object(
            mod, "fetch_all_collections",
            return_value=[_smart("cozy-bedroom")],
        ), patch.object(
            mod, "product_count", return_value=5,
        ):
            rc = mod.main([])
        assert rc == 2

    def test_env_missing_rc2(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_SHOPIFY_URL", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_KEY", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_TOKEN", raising=False)
        rc = mod.main([])
        assert rc == 2

    def test_403_rc3(self, env, capsys):
        def boom(*args, **kwargs):
            raise urllib.error.HTTPError(
                "u", 403, "Forbidden", None, None,
            )
        with patch.object(mod, "audit", boom):
            rc = mod.main([])
        assert rc == 3
        err = capsys.readouterr().err
        assert "read_products" in err
