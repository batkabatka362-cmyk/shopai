"""Tests for engines.tiktok_publisher — W963-12."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from engines.tiktok_publisher import TikTokPublisherEngine
from engines.tiktok_publisher.connect import connect_tiktok
from engines.tiktok_publisher.publisher import (
    list_posts,
    publish_post,
)
from engines.tiktok_publisher.status import (
    TikTokStatus,
    get_status,
)


# ── Status ────────────────────────────────────────────────


class TestStatus:
    def test_skip_live_no_creds(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in (
                "TIKTOK_ACCESS_TOKEN", "TIKTOK_BUSINESS_ID",
            ):
                os.environ.pop(k, None)
            s = get_status(skip_live=True)
        assert not s.credentials_present
        assert not s.business_id_present

    def test_ready_requires_all_three(self):
        s = TikTokStatus(
            adapter_registered=True,
            credentials_present=True,
            business_id_present=True,
        )
        assert s.ready
        s.business_id_present = False
        assert not s.ready


# ── Connect ───────────────────────────────────────────────


class TestConnect:
    def test_missing_token(self, tmp_path):
        res = connect_tiktok(
            access_token="", business_id="biz",
            env_path=str(tmp_path / ".env"),
        )
        assert not res.success

    def test_missing_business_id(self, tmp_path):
        res = connect_tiktok(
            access_token="t", business_id="",
            env_path=str(tmp_path / ".env"),
        )
        assert not res.success

    def test_writes_both_keys(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("OTHER=v\n")
        res = connect_tiktok(
            access_token="TKN", business_id="B123",
            env_path=str(env),
        )
        assert res.success
        c = env.read_text()
        assert "TIKTOK_ACCESS_TOKEN=TKN" in c
        assert "TIKTOK_BUSINESS_ID=B123" in c
        assert "OTHER=v" in c

    def test_replaces_existing(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("TIKTOK_ACCESS_TOKEN=OLD\n")
        connect_tiktok(
            access_token="NEW", business_id="B",
            env_path=str(env),
        )
        c = env.read_text()
        assert "TIKTOK_ACCESS_TOKEN=NEW" in c
        assert "OLD" not in c

    def test_sets_process_env(self, tmp_path):
        connect_tiktok(
            access_token="P", business_id="B",
            env_path=str(tmp_path / ".env"),
        )
        assert os.environ.get("TIKTOK_ACCESS_TOKEN") == "P"
        assert os.environ.get("TIKTOK_BUSINESS_ID") == "B"


# ── Publisher: list_posts ─────────────────────────────────


class TestListPosts:
    def test_router_error(self):
        with patch(
            "core.adapters.router.get_router",
            side_effect=Exception("nope"),
        ):
            res = list_posts()
        assert not res.success

    def test_success(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True,
            data={"posts": [
                {"id": "p1", "caption": "test"},
            ]},
            error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ):
            res = list_posts(limit=10)
        assert res.success
        assert len(res.posts) == 1


# ── Publisher: publish_post ───────────────────────────────


class TestPublishPost:
    def test_missing_caption(self):
        res = publish_post(
            caption="", media_url="https://x.com/i.jpg",
        )
        assert not res.success

    def test_missing_media(self):
        res = publish_post(
            caption="hi", media_url="",
        )
        assert not res.success

    def test_non_http_media(self):
        res = publish_post(
            caption="hi", media_url="ftp://x/i.jpg",
        )
        assert not res.success
        assert "HTTP(S)" in res.error

    def test_invalid_media_type(self):
        res = publish_post(
            caption="hi",
            media_url="https://x.com/i.jpg",
            media_type="AUDIO",
        )
        assert not res.success

    def test_router_unavailable(self):
        with patch(
            "core.adapters.router.get_router",
            side_effect=Exception("nope"),
        ):
            res = publish_post(
                caption="hi",
                media_url="https://x.com/i.jpg",
            )
        assert not res.success

    def test_success(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True,
            data={
                "publish_id": "P_ABC",
                "share_url": "https://tiktok.com/v/P_ABC",
                "status": "PROCESSING",
            },
            error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            res = publish_post(
                caption="My post",
                media_url="https://x.com/img.jpg",
            )
        assert res.success
        assert res.publish_id == "P_ABC"


# ── Engine Pattern Q envelope ─────────────────────────────


class TestEngineEnvelope:
    def test_empty_input_returns_status(self):
        result = TikTokPublisherEngine().run({})
        assert result["status"] == "success"
        assert result["data"]["action"] == "status"

    def test_none_input(self):
        result = TikTokPublisherEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_error(self):
        result = TikTokPublisherEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream(self):
        result = TikTokPublisherEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_unknown_action(self):
        result = TikTokPublisherEngine().run({
            "data": {"action": "delete"},
        })
        assert result["status"] == "error"


class TestEnginePublishAction:
    def test_missing_caption(self):
        result = TikTokPublisherEngine().run({
            "data": {
                "action": "publish-post",
                "media_url": "https://x.com/i.jpg",
            },
        })
        assert result["data"]["published"] is False

    def test_publish_succeeds_with_mock(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True,
            data={"publish_id": "P", "status": "PROCESSING"},
            error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            result = TikTokPublisherEngine().run({
                "data": {
                    "action": "publish-post",
                    "caption": "Hi",
                    "media_url": "https://x.com/i.jpg",
                    "business_id": "B",
                },
            })
        assert result["data"]["published"] is True
