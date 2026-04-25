"""StoreConfigurator blog welcome-article tests (Phase 2c).

Seeds the default `news` blog with one welcome article. A
fresh store's blog shows "no posts yet" — first-visit trust
damage. This feature keeps the blog looking alive from
day one.
"""
from __future__ import annotations


def _make(dry_run: bool = False):
    from execution.store_configurator import StoreConfigurator
    return StoreConfigurator(dry_run=dry_run)


def _install_fake_client(
    monkeypatch,
    responses=None,
    track_calls=None,
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
                {"article": {"id": 1}},
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


class TestBlogFeatureEnabled:
    def test_blog_in_all_features(self):
        from execution.store_configurator import ALL_FEATURES
        assert "blog" in ALL_FEATURES


class TestBlogDryRun:
    def test_dry_run_plans_article(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses={
                "GET blogs.json": {
                    "blogs": [
                        {
                            "id": 99, "handle": "news",
                            "title": "News",
                        },
                    ],
                },
            },
        )
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="fashion", store_name="Vogue Co",
            features=["blog"],
        )
        b = result["results"]["blog"]
        assert b["status"] == "dry_run"
        assert b["blog_id"] == 99
        assert b["created"].startswith("welcome-to-")


class TestBlogLive:
    def test_creates_article_when_missing(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET blogs.json": {
                    "blogs": [
                        {
                            "id": 77, "handle": "news",
                            "title": "News",
                        },
                    ],
                },
                "GET blogs/77/articles.json": {
                    "articles": [],
                },
            },
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="beauty", store_name="Glow",
            features=["blog"],
        )
        posts = [
            c for c in calls
            if c[0] == "POST"
            and "articles.json" in c[1]
        ]
        assert len(posts) == 1
        article = posts[0][2]["article"]
        assert article["title"] == "Welcome to Glow"
        assert article["handle"].startswith("welcome-to-")
        assert article["published"] is True
        b = result["results"]["blog"]
        assert b["status"] == "success"

    def test_skips_existing_article(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET blogs.json": {
                    "blogs": [
                        {
                            "id": 77, "handle": "news",
                            "title": "News",
                        },
                    ],
                },
                "GET blogs/77/articles.json": {
                    "articles": [
                        {
                            "id": 1,
                            "handle": "welcome-to-glow",
                            "title": "old",
                        },
                    ],
                },
            },
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="beauty", store_name="Glow",
            features=["blog"],
        )
        posts = [
            c for c in calls
            if c[0] == "POST"
            and "articles.json" in c[1]
        ]
        assert len(posts) == 0
        b = result["results"]["blog"]
        assert b["status"] == "skipped"
        assert b["skipped"] == "welcome-to-glow"

    def test_no_default_blog_returns_skipped(
        self, monkeypatch,
    ):
        _install_fake_client(
            monkeypatch,
            responses={
                "GET blogs.json": {"blogs": []},
            },
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["blog"],
        )
        b = result["results"]["blog"]
        assert b["status"] == "skipped"
        # Reason surfaced as an error entry
        reasons = [e["step"] for e in b["errors"]]
        assert "find_default_blog" in reasons

    def test_list_blogs_error_recorded(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses={
                "GET blogs.json": {
                    "error": "rate limited",
                },
            },
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["blog"],
        )
        b = result["results"]["blog"]
        assert b["status"] == "error"
        assert any(
            "rate limited" in e.get("error", "")
            for e in b["errors"]
        )


class TestBlogArticleTemplate:
    def test_niche_appears_in_body(self):
        from execution.store_configurator import (
            _blog_welcome_article,
        )
        a = _blog_welcome_article("tech", "GadgetHub")
        assert "GadgetHub" in a["title"]
        assert "everyday tech" in a["body_html"]
        assert "welcome-to-gadgethub" == a["handle"]

    def test_handle_truncated(self):
        from execution.store_configurator import (
            _blog_welcome_article,
        )
        a = _blog_welcome_article("general", "x" * 200)
        assert len(a["handle"]) <= 63

    def test_tags_include_niche(self):
        from execution.store_configurator import (
            _blog_welcome_article,
        )
        a = _blog_welcome_article("beauty", "Co")
        assert "beauty" in a["tags"]
        assert "welcome" in a["tags"]
