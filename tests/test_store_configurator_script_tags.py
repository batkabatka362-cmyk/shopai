"""StoreConfigurator script_tags tests (Phase 2e).

Auto-installs tracking pixels (Meta / TikTok / GA) via
Shopify's legacy script_tags API. Env-gated so accidentally
configured analytics-off stores stay clean.
"""
from __future__ import annotations


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
        def __init__(self, *a, **kw): pass

        def get(self, path, *, params=None):
            track_calls.append(("GET", path, params))
            return responses.get(f"GET {path}", {})

        def post(self, path, *, json=None):
            track_calls.append(("POST", path, json))
            return responses.get(
                f"POST {path}",
                {"script_tag": {"id": 1}},
            )

        def put(self, path, *, json=None):
            return {}

        def delete(self, path):
            return {}

    monkeypatch.setattr(
        "execution.store_configurator.ShopifyClient",
        FakeClient,
    )
    return track_calls


class TestScriptTagsFeatureEnabled:
    def test_script_tags_in_all_features(self):
        from execution.store_configurator import ALL_FEATURES
        assert "script_tags" in ALL_FEATURES


class TestScriptTagsEnvGate:
    def test_no_env_returns_skipped(self, monkeypatch):
        _install_fake_client(monkeypatch)
        for env in (
            "SHOPAI_META_PIXEL_SRC",
            "SHOPAI_TIKTOK_PIXEL_SRC",
            "SHOPAI_GA_SRC",
        ):
            monkeypatch.delenv(env, raising=False)
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["script_tags"],
        )
        s = result["results"]["script_tags"]
        assert s["status"] == "skipped"
        assert "SHOPAI_META_PIXEL_SRC" in s["reason"]

    def test_non_https_sources_rejected(self, monkeypatch):
        _install_fake_client(monkeypatch)
        monkeypatch.setenv(
            "SHOPAI_META_PIXEL_SRC",
            "http://evil.example.com/pixel.js",
        )
        monkeypatch.delenv(
            "SHOPAI_TIKTOK_PIXEL_SRC", raising=False,
        )
        monkeypatch.delenv(
            "SHOPAI_GA_SRC", raising=False,
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["script_tags"],
        )
        s = result["results"]["script_tags"]
        # Non-https filtered → no valid sources → skipped
        assert s["status"] == "skipped"


class TestScriptTagsDryRun:
    def test_plan_entries(self, monkeypatch):
        _install_fake_client(monkeypatch)
        monkeypatch.setenv(
            "SHOPAI_META_PIXEL_SRC",
            "https://cdn.example.com/meta.js",
        )
        monkeypatch.setenv(
            "SHOPAI_GA_SRC",
            "https://www.googletagmanager.com/gtag/js?id=GA-1",
        )
        monkeypatch.delenv(
            "SHOPAI_TIKTOK_PIXEL_SRC", raising=False,
        )
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["script_tags"],
        )
        s = result["results"]["script_tags"]
        assert s["status"] == "dry_run"
        assert set(s["installed"]) == {
            "meta_pixel", "google_analytics",
        }


class TestScriptTagsLive:
    def test_posts_for_missing_sources(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET script_tags.json": {
                    "script_tags": [],
                },
            },
        )
        monkeypatch.setenv(
            "SHOPAI_META_PIXEL_SRC",
            "https://cdn.example.com/meta.js",
        )
        monkeypatch.delenv(
            "SHOPAI_TIKTOK_PIXEL_SRC", raising=False,
        )
        monkeypatch.delenv(
            "SHOPAI_GA_SRC", raising=False,
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["script_tags"],
        )
        posts = [
            c for c in calls
            if c[0] == "POST"
            and c[1] == "script_tags.json"
        ]
        assert len(posts) == 1
        body = posts[0][2]["script_tag"]
        assert body["event"] == "onload"
        assert body["src"] == "https://cdn.example.com/meta.js"
        s = result["results"]["script_tags"]
        assert s["status"] == "success"
        assert s["installed"] == ["meta_pixel"]

    def test_existing_src_skipped(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET script_tags.json": {
                    "script_tags": [
                        {
                            "id": 1,
                            "src": "https://cdn.example.com/meta.js",
                        },
                    ],
                },
            },
        )
        monkeypatch.setenv(
            "SHOPAI_META_PIXEL_SRC",
            "https://cdn.example.com/meta.js",
        )
        monkeypatch.setenv(
            "SHOPAI_GA_SRC",
            "https://cdn.example.com/ga.js",
        )
        monkeypatch.delenv(
            "SHOPAI_TIKTOK_PIXEL_SRC", raising=False,
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["script_tags"],
        )
        posts = [
            c for c in calls
            if c[0] == "POST"
            and c[1] == "script_tags.json"
        ]
        assert len(posts) == 1  # only GA installed
        s = result["results"]["script_tags"]
        assert s["installed"] == ["google_analytics"]
        assert s["existing"] == ["meta_pixel"]
