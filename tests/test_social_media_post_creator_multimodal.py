"""Tests for the multi-modal image-gen path in
``engines.social_media.post_creator``.

The existing template-based caption flow is untested-elsewhere
(legacy gap); this file focuses on the NEW behavior added by
the multi-modal PR:

  1. ``generate_media=False`` default -- no router call, posts
     have no media_url.
  2. Pattern J guard -- under pytest the router is never called
     even when ``generate_media=True``.
  3. Mocked router happy path -> post carries media_url + model.
  4. Router not-ok -> post still publishes (no media_url).
  5. Router raises -> post still publishes (no media_url).
  6. Image-only post types: video post_types skip media gen.
  7. Platform -> DALL-E size mapping (Instagram square, TikTok
     vertical, Pinterest vertical, Twitter landscape).
  8. Prompt includes product + brand + voice + visual context.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from engines.social_media.post_creator import create_posts


def _ok(data):
    return SimpleNamespace(ok=True, data=data, error=None)


def _fail(error="x"):
    return SimpleNamespace(ok=False, data=None, error=error)


_BRAND = {"name": "Glow Labs", "voice": "professional"}
_PRODUCTS = [{"title": "YouthBoost LED Lifter"}]


def _calendar(platform="instagram", post_type="single_image"):
    return [{"platform": platform, "post_type": post_type}]


class TestGenerateMediaDefaultOff:

    def test_no_router_call_when_flag_off(self):
        """Default ``generate_media=False`` -- patched router
        crashes if called. We rely on the flag short-circuiting."""
        def _explode(*a, **kw):
            raise AssertionError("router should not be called")

        router = SimpleNamespace(execute=_explode)
        with patch("core.adapters.get_router", return_value=router):
            out = create_posts(
                _calendar(), _BRAND, "awareness", _PRODUCTS,
            )
        assert out["status"] == "success"
        post = out["posts"][0]
        assert "media_url" not in post
        assert "media_b64" not in post


class TestPatternJGuard:

    def test_pytest_env_blocks_live_media_gen(self, monkeypatch):
        """Even with ``generate_media=True``, pytest short-circuits
        the live router call so tests don't hit DALL-E."""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        # No router mock -- if Pattern J failed, the lookup
        # would crash on AttributeError. Template fallback
        # (no media_url added) must run.
        out = create_posts(
            _calendar(), _BRAND, "awareness", _PRODUCTS,
            generate_media=True,
        )
        post = out["posts"][0]
        assert "media_url" not in post


class TestLLMHappyPath:

    def _run(self, llm_data, platform="instagram", post_type="single_image"):
        captured = {}

        def _exec(cap, params):
            captured["cap"] = cap
            captured["params"] = params
            return _ok(llm_data)

        router = SimpleNamespace(execute=_exec)
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            out = create_posts(
                _calendar(platform=platform, post_type=post_type),
                _BRAND, "awareness", _PRODUCTS,
                generate_media=True,
            )
        return out, captured

    def test_image_url_propagated(self):
        out, captured = self._run({
            "images": [{
                "url": "https://cdn.openai.com/dalle/asset-12345.png",
                "revised_prompt": "...",
            }],
            "model": "dall-e-3",
        })
        post = out["posts"][0]
        assert post["media_url"].endswith(".png")
        assert post["media_model"] == "dall-e-3"
        assert post["media_size"] == "1024x1024"

    def test_b64_propagated(self):
        out, _ = self._run({
            "images": [{
                "b64_json": "iVBORw0KGgoAAAA",
            }],
            "model": "dall-e-3",
        })
        post = out["posts"][0]
        assert post["media_b64"].startswith("iVBORw0K")

    def test_prompt_includes_product_and_brand(self):
        _, captured = self._run({
            "images": [{"url": "x"}], "model": "dall-e-3",
        })
        prompt = captured["params"]["prompt"]
        assert "YouthBoost LED Lifter" in prompt
        assert "Glow Labs" in prompt
        assert "instagram" in prompt.lower()


class TestPlatformSizeMapping:

    def _size_for(self, platform):
        router = SimpleNamespace(
            execute=lambda c, p: _ok({
                "images": [{"url": "x"}], "model": "dall-e-3",
            }),
        )
        captured = {}

        def _exec(c, p):
            captured.update(p)
            return _ok({"images": [{"url": "x"}], "model": "dall-e-3"})

        router = SimpleNamespace(execute=_exec)
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            create_posts(
                _calendar(platform=platform, post_type="single_image"),
                _BRAND, "awareness", _PRODUCTS,
                generate_media=True,
            )
        return captured.get("size", "")

    def test_instagram_square(self):
        assert self._size_for("instagram") == "1024x1024"

    def test_tiktok_vertical(self):
        assert self._size_for("tiktok") == "1024x1792"

    def test_pinterest_vertical(self):
        assert self._size_for("pinterest") == "1024x1792"

    def test_twitter_landscape(self):
        assert self._size_for("twitter") == "1792x1024"

    def test_unknown_platform_defaults_square(self):
        assert self._size_for("mastodon") == "1024x1024"


class TestSkipsVideoPostTypes:

    def test_reels_skipped(self):
        """Video post_types (reels, video, short_video) don't
        trigger image gen -- those are video-gen's domain (a
        follow-up PR)."""
        def _explode(*a, **kw):
            raise AssertionError("image gen should not run for reels")

        router = SimpleNamespace(execute=_explode)
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            out = create_posts(
                _calendar(platform="tiktok", post_type="reels"),
                _BRAND, "awareness", _PRODUCTS,
                generate_media=True,
            )
        post = out["posts"][0]
        assert "media_url" not in post


class TestGracefulDegrade:

    def test_router_not_ok_publishes_without_media(self):
        router = SimpleNamespace(execute=lambda c, p: _fail("quota"))
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            out = create_posts(
                _calendar(), _BRAND, "awareness", _PRODUCTS,
                generate_media=True,
            )
        post = out["posts"][0]
        # Post still made; visual_description fallback still there
        assert post["caption"]
        assert "media_url" not in post

    def test_router_raises_publishes_without_media(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            out = create_posts(
                _calendar(), _BRAND, "awareness", _PRODUCTS,
                generate_media=True,
            )
        post = out["posts"][0]
        assert post["caption"]
        assert "media_url" not in post

    def test_empty_images_list_publishes_without_media(self):
        router = SimpleNamespace(
            execute=lambda c, p: _ok({"images": [], "model": "dall-e-3"}),
        )
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}), \
             patch("core.adapters.get_router", return_value=router):
            out = create_posts(
                _calendar(), _BRAND, "awareness", _PRODUCTS,
                generate_media=True,
            )
        post = out["posts"][0]
        assert "media_url" not in post
