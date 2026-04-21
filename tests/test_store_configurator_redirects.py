"""StoreConfigurator redirects feature tests (Phase 2b).

301 redirects for common marketing vanity URLs so /shop,
/store, /catalog, /products etc. resolve to the canonical
Shopify paths. Idempotent — existing redirects skipped.
"""
from __future__ import annotations

import pytest


def _make(dry_run: bool = False):
    from execution.store_configurator import StoreConfigurator
    return StoreConfigurator(dry_run=dry_run)


def _install_fake_client(
    monkeypatch, responses=None, track_calls=None,
):
    responses = responses or {}
    track_calls = (
        track_calls if track_calls is not None else []
    )

    class FakeClient:
        def __init__(self, shop_url, token, **kw):
            pass

        def get(self, path, *, params=None):
            track_calls.append(("GET", path, params))
            return responses.get(f"GET {path}", {})

        def post(self, path, *, json=None):
            track_calls.append(("POST", path, json))
            return responses.get(
                f"POST {path}",
                {"redirect": {"id": 1}},
            )

        def put(self, path, *, json=None):
            track_calls.append(("PUT", path, json))
            return {}

        def delete(self, path):
            track_calls.append(("DELETE", path, None))
            return {}

    monkeypatch.setattr(
        "execution.store_configurator.ShopifyClient",
        FakeClient,
    )
    return track_calls


class TestRedirectsFeatureEnabled:
    def test_redirects_in_all_features(self):
        from execution.store_configurator import ALL_FEATURES
        assert "redirects" in ALL_FEATURES


class TestRedirectsDryRun:
    def test_all_seven_planned(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="general",
            features=["redirects"],
        )
        r = result["results"]["redirects"]
        assert r["status"] == "dry_run"
        assert set(r["created"]) == {
            "/shop", "/store", "/catalog", "/products",
            "/blog", "/contact", "/about",
        }


class TestRedirectsLive:
    def test_posts_for_missing_paths(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET redirects.json": {
                    "redirects": [],
                },
            },
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["redirects"],
        )
        posts = [
            c for c in calls
            if c[0] == "POST"
            and c[1] == "redirects.json"
        ]
        assert len(posts) == 7
        for p in posts:
            assert "path" in p[2]["redirect"]
            assert "target" in p[2]["redirect"]
        r = result["results"]["redirects"]
        assert r["status"] == "success"
        assert len(r["created"]) == 7

    def test_existing_paths_skipped(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET redirects.json": {
                    "redirects": [
                        {"id": 1, "path": "/shop",
                         "target": "/old"},
                        {"id": 2, "path": "/blog",
                         "target": "/blogs/news"},
                    ],
                },
            },
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["redirects"],
        )
        posts = [
            c for c in calls
            if c[0] == "POST"
            and c[1] == "redirects.json"
        ]
        # 7 - 2 existing = 5 posts
        assert len(posts) == 5
        r = result["results"]["redirects"]
        assert "/shop" in r["skipped"]
        assert "/blog" in r["skipped"]

    def test_targets_map_correctly(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET redirects.json": {"redirects": []},
            },
        )
        c = _make(dry_run=False)
        c.configure(
            "x.myshopify.com", "tok",
            features=["redirects"],
        )
        mapping = {
            call[2]["redirect"]["path"]:
                call[2]["redirect"]["target"]
            for call in calls
            if call[0] == "POST"
            and call[1] == "redirects.json"
        }
        assert mapping["/shop"] == "/collections/all"
        assert mapping["/blog"] == "/blogs/news"
        assert mapping["/about"] == "/pages/about"
        assert mapping["/contact"] == "/pages/contact"

    def test_partial_failure_isolation(self, monkeypatch):
        call_state = {"count": 0}

        class FakeClient:
            def __init__(self, *a, **kw): pass
            def get(self, path, *, params=None):
                return {"redirects": []}
            def post(self, path, *, json=None):
                call_state["count"] += 1
                if call_state["count"] == 3:
                    return {"error": "conflict"}
                return {"redirect": {"id": call_state["count"]}}
            def put(self, path, *, json=None):
                return {}
            def delete(self, path):
                return {}

        monkeypatch.setattr(
            "execution.store_configurator.ShopifyClient",
            FakeClient,
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["redirects"],
        )
        r = result["results"]["redirects"]
        assert r["status"] == "partial"
        assert len(r["created"]) == 6
        assert len(r["errors"]) == 1
