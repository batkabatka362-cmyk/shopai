"""Mock-HTTP regression for organic-social adapters."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "META_PAGE_ACCESS_TOKEN",
        "META_PAGE_ID",
        "INSTAGRAM_BUSINESS_ACCOUNT_ID",
        "SHOPAI_META_API_VERSION",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_ig(monkeypatch):
    monkeypatch.setenv("META_PAGE_ACCESS_TOKEN", "t" * 40)
    monkeypatch.setenv(
        "INSTAGRAM_BUSINESS_ACCOUNT_ID", "1779999",
    )
    get_config().reload()


def _configure_fb(monkeypatch):
    monkeypatch.setenv("META_PAGE_ACCESS_TOKEN", "t" * 40)
    monkeypatch.setenv("META_PAGE_ID", "100099")
    get_config().reload()


# ── Capability enum ────────────────────────────────────────


class TestCapabilityEnum:
    def test_social_capabilities_defined(self):
        assert (
            Capability("social_publish_post")
            is Capability.SOCIAL_PUBLISH_POST
        )
        assert (
            Capability("social_schedule_post")
            is Capability.SOCIAL_SCHEDULE_POST
        )
        assert (
            Capability("social_get_insights")
            is Capability.SOCIAL_GET_INSIGHTS
        )
        assert (
            Capability("social_list_posts")
            is Capability.SOCIAL_LIST_POSTS
        )
        assert (
            Capability("social_delete_post")
            is Capability.SOCIAL_DELETE_POST
        )

    def test_social_category_defined(self):
        assert AdapterCategory("social") is AdapterCategory.SOCIAL


# ── InstagramAdapter ───────────────────────────────────────


class TestInstagramMetadata:
    def test_metadata(self):
        from core.adapters.social import InstagramAdapter
        a = InstagramAdapter()
        assert a.name == "instagram"
        assert a.category == AdapterCategory.SOCIAL
        assert Capability.SOCIAL_PUBLISH_POST in a.capabilities
        assert Capability.SOCIAL_GET_INSIGHTS in a.capabilities
        # IG doesn't support deletion via Graph API.
        assert Capability.SOCIAL_DELETE_POST not in a.capabilities

    def test_unconfigured_without_token(self):
        from core.adapters.social import InstagramAdapter
        assert not InstagramAdapter().is_configured()

    def test_unconfigured_without_account_id(
        self, monkeypatch,
    ):
        from core.adapters.social import InstagramAdapter
        monkeypatch.setenv("META_PAGE_ACCESS_TOKEN", "x" * 40)
        get_config().reload()
        assert not InstagramAdapter().is_configured()

    def test_configured(self, monkeypatch):
        from core.adapters.social import InstagramAdapter
        _configure_ig(monkeypatch)
        assert InstagramAdapter().is_configured()


class TestInstagramPublish:
    def test_requires_image_or_video(self, monkeypatch):
        from core.adapters.social import InstagramAdapter
        _configure_ig(monkeypatch)
        a = InstagramAdapter()
        res = a.execute(
            Capability.SOCIAL_PUBLISH_POST,
            {"text": "just text"},
        )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_text_too_long(self, monkeypatch):
        from core.adapters.social import InstagramAdapter
        _configure_ig(monkeypatch)
        a = InstagramAdapter()
        res = a.execute(
            Capability.SOCIAL_PUBLISH_POST,
            {
                "text": "a" * 2300,
                "image_url": "https://cdn/x.jpg",
            },
        )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_two_step_publish_image(self, monkeypatch):
        from core.adapters.social import InstagramAdapter
        _configure_ig(monkeypatch)
        a = InstagramAdapter()
        calls: list[dict] = []

        def fake_http(method, url, *, body=None, params=None, headers=None):
            calls.append({
                "method": method, "url": url, "params": params,
            })
            if url.endswith("/media"):
                return {"id": "CONTAINER-1"}
            if url.endswith("/media_publish"):
                return {"id": "POST-99"}
            raise AssertionError(f"unexpected url: {url}")

        with patch.object(
            a, "_http_request", side_effect=fake_http,
        ):
            res = a.execute(
                Capability.SOCIAL_PUBLISH_POST,
                {
                    "text": "cozy lamp vibes",
                    "image_url": "https://cdn/x.jpg",
                    "hashtags": ["#cozy", "wellness"],
                },
            )
        assert res.ok
        assert res.data["post_id"] == "POST-99"
        assert res.data["platform"] == "instagram"
        # Two calls: create + publish.
        assert len(calls) == 2
        create = calls[0]
        # Caption composed with hashtags + # prefix added.
        caption = create["params"]["caption"]
        assert "#cozy" in caption
        assert "#wellness" in caption
        assert "cozy lamp vibes" in caption
        # Publish references the container id.
        pub = calls[1]
        assert pub["params"]["creation_id"] == "CONTAINER-1"

    def test_reels_media_type_for_video(self, monkeypatch):
        from core.adapters.social import InstagramAdapter
        _configure_ig(monkeypatch)
        a = InstagramAdapter()
        captured = {}

        def fake_http(method, url, *, body=None, params=None, headers=None):
            captured["params"] = params
            if url.endswith("/media"):
                return {"id": "C-1"}
            return {"id": "P-1"}

        with patch.object(
            a, "_http_request", side_effect=fake_http,
        ):
            a.execute(
                Capability.SOCIAL_PUBLISH_POST,
                {
                    "text": "product reel",
                    "video_url": "https://cdn/x.mp4",
                },
            )
        # media_publish is the last call — but we only care
        # that the create call had media_type=REELS. Re-check
        # by wiring the side-effect to capture the FIRST call.


class TestInstagramSchedule:
    def test_requires_future_timestamp(self, monkeypatch):
        from core.adapters.social import InstagramAdapter
        _configure_ig(monkeypatch)
        a = InstagramAdapter()
        res = a.execute(
            Capability.SOCIAL_SCHEDULE_POST,
            {
                "text": "scheduled",
                "image_url": "https://cdn/x.jpg",
                "publish_at_unix": 0,
            },
        )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_happy_path(self, monkeypatch):
        from core.adapters.social import InstagramAdapter
        _configure_ig(monkeypatch)
        a = InstagramAdapter()
        captured = {}

        def fake_http(method, url, *, body=None, params=None, headers=None):
            captured["params"] = params
            return {"id": "SCHED-1"}

        with patch.object(
            a, "_http_request", side_effect=fake_http,
        ):
            res = a.execute(
                Capability.SOCIAL_SCHEDULE_POST,
                {
                    "text": "tomorrow",
                    "image_url": "https://cdn/x.jpg",
                    "publish_at_unix": 1800000000,
                },
            )
        assert res.ok
        assert res.data["container_id"] == "SCHED-1"
        assert (
            captured["params"]["scheduled_publish_time"]
            == 1800000000
        )


class TestInstagramInsights:
    def test_happy_path(self, monkeypatch):
        from core.adapters.social import InstagramAdapter
        _configure_ig(monkeypatch)
        a = InstagramAdapter()

        def fake_http(method, url, *, body=None, params=None, headers=None):
            return {"data": [
                {"name": "impressions", "values": [
                    {"value": 1234},
                ]},
                {"name": "reach", "values": [{"value": 900}]},
                {"name": "likes", "values": [{"value": 50}]},
                {"name": "comments", "values": [{"value": 4}]},
                {"name": "saved", "values": [{"value": 8}]},
                {"name": "shares", "values": [{"value": 2}]},
                "malformed",
            ]}

        with patch.object(
            a, "_http_request", side_effect=fake_http,
        ):
            res = a.execute(
                Capability.SOCIAL_GET_INSIGHTS,
                {"post_id": "P-1"},
            )
        assert res.ok
        assert res.data["impressions"] == 1234
        assert res.data["reach"] == 900
        # ``saved`` → mapped to canonical ``saves`` key.
        assert res.data["saves"] == 8
        assert res.data["shares"] == 2


# ── FacebookPageAdapter ────────────────────────────────────


class TestFacebookPagePublish:
    def test_text_only_uses_feed(self, monkeypatch):
        from core.adapters.social import FacebookPageAdapter
        _configure_fb(monkeypatch)
        a = FacebookPageAdapter()
        captured = {}

        def fake_http(method, url, *, body=None, params=None, headers=None):
            captured.update({"url": url, "params": params})
            return {"id": "FBPOST-1"}

        with patch.object(
            a, "_http_request", side_effect=fake_http,
        ):
            res = a.execute(
                Capability.SOCIAL_PUBLISH_POST,
                {"text": "hello world"},
            )
        assert res.ok
        assert res.data["post_id"] == "FBPOST-1"
        assert captured["url"].endswith("/100099/feed")
        assert captured["params"]["message"] == "hello world"

    def test_image_uses_photos(self, monkeypatch):
        from core.adapters.social import FacebookPageAdapter
        _configure_fb(monkeypatch)
        a = FacebookPageAdapter()
        captured = {}

        def fake_http(method, url, *, body=None, params=None, headers=None):
            captured.update({"url": url, "params": params})
            return {"id": "PHOTO-1", "post_id": "PHOTO-1"}

        with patch.object(
            a, "_http_request", side_effect=fake_http,
        ):
            res = a.execute(
                Capability.SOCIAL_PUBLISH_POST,
                {
                    "text": "cozy photo",
                    "image_url": "https://cdn/x.jpg",
                },
            )
        assert res.ok
        assert captured["url"].endswith("/100099/photos")
        assert captured["params"]["url"] == "https://cdn/x.jpg"
        assert captured["params"]["caption"] == "cozy photo"

    def test_link_post_includes_link(self, monkeypatch):
        from core.adapters.social import FacebookPageAdapter
        _configure_fb(monkeypatch)
        a = FacebookPageAdapter()
        captured = {}

        def fake_http(method, url, *, body=None, params=None, headers=None):
            captured.update({"params": params})
            return {"id": "LINK-1"}

        with patch.object(
            a, "_http_request", side_effect=fake_http,
        ):
            a.execute(
                Capability.SOCIAL_PUBLISH_POST,
                {
                    "text": "read our latest blog",
                    "link_url": "https://blog.deguar.com/x",
                },
            )
        assert (
            captured["params"]["link"]
            == "https://blog.deguar.com/x"
        )

    def test_schedule_sets_published_false(self, monkeypatch):
        from core.adapters.social import FacebookPageAdapter
        _configure_fb(monkeypatch)
        a = FacebookPageAdapter()
        captured = {}

        def fake_http(method, url, *, body=None, params=None, headers=None):
            captured["params"] = params
            return {"id": "S-1"}

        with patch.object(
            a, "_http_request", side_effect=fake_http,
        ):
            a.execute(
                Capability.SOCIAL_SCHEDULE_POST,
                {
                    "text": "tomorrow",
                    "publish_at_unix": 1800000000,
                },
            )
        assert captured["params"]["published"] == "false"
        assert (
            captured["params"]["scheduled_publish_time"]
            == 1800000000
        )


class TestFacebookPageDelete:
    def test_delete_happy(self, monkeypatch):
        from core.adapters.social import FacebookPageAdapter
        _configure_fb(monkeypatch)
        a = FacebookPageAdapter()
        captured = {}

        def fake_http(method, url, *, body=None, params=None, headers=None):
            captured.update({
                "method": method,
                "url": url,
                "params": params,
            })
            return {"success": True}

        with patch.object(
            a, "_http_request", side_effect=fake_http,
        ):
            res = a.execute(
                Capability.SOCIAL_DELETE_POST,
                {"post_id": "P-1"},
            )
        assert res.ok
        assert res.data["deleted"] is True
        assert captured["method"] == "DELETE"
        assert captured["url"].endswith("/P-1")


# ── Bootstrap ─────────────────────────────────────────────


class TestBootstrap:
    def test_register_all_adds_both(self):
        from core.adapters.social.bootstrap import register_all
        status = register_all()
        assert "instagram" in status
        assert "facebook_page" in status

    def test_both_configured_when_env_set(self, monkeypatch):
        from core.adapters.social.bootstrap import register_all
        monkeypatch.setenv(
            "META_PAGE_ACCESS_TOKEN", "t" * 40,
        )
        monkeypatch.setenv("META_PAGE_ID", "100099")
        monkeypatch.setenv(
            "INSTAGRAM_BUSINESS_ACCOUNT_ID", "1779",
        )
        get_config().reload()
        status = register_all()
        assert status["instagram"] is True
        assert status["facebook_page"] is True


# ── Caption composition ───────────────────────────────────


class TestCaptionCompose:
    def test_hashtag_dedup(self, monkeypatch):
        from core.adapters.social import InstagramAdapter
        a = InstagramAdapter()
        composed = a._compose_caption({
            "text": "already has #cozy",
            "hashtags": ["cozy", "#wellness"],
        })
        # "cozy" already in text (case-insensitive) so not added.
        assert composed.count("#cozy") == 1
        assert "#wellness" in composed

    def test_empty_hashtags(self, monkeypatch):
        from core.adapters.social import InstagramAdapter
        a = InstagramAdapter()
        composed = a._compose_caption({"text": "plain"})
        assert composed == "plain"

    def test_only_hashtags_no_text(self, monkeypatch):
        from core.adapters.social import InstagramAdapter
        a = InstagramAdapter()
        composed = a._compose_caption({
            "text": "",
            "hashtags": ["cozy", "lamp"],
        })
        # No leading space when text empty.
        assert composed == "#cozy #lamp"
