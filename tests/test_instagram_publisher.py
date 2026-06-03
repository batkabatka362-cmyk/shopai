"""Tests for engines.instagram_publisher — W963-15."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from engines.instagram_publisher import InstagramPublisherEngine
from engines.instagram_publisher.connect import connect_instagram
from engines.instagram_publisher.publisher import (
    list_posts,
    publish_post,
)
from engines.instagram_publisher.status import (
    InstagramStatus,
    get_status,
)


# ── Status ────────────────────────────────────────────────


class TestStatus:
    def test_skip_live_no_creds(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in (
                "INSTAGRAM_ACCESS_TOKEN",
                "INSTAGRAM_ACCOUNT_ID",
            ):
                os.environ.pop(k, None)
            s = get_status(skip_live=True)
        assert not s.credentials_present
        assert not s.account_id_present

    def test_ready_requires_all_three(self):
        s = InstagramStatus(
            adapter_registered=True,
            credentials_present=True,
            account_id_present=True,
        )
        assert s.ready
        s.account_id_present = False
        assert not s.ready


# ── Connect ───────────────────────────────────────────────


class TestConnect:
    def test_missing_token(self, tmp_path):
        res = connect_instagram(
            access_token="", account_id="acct",
            env_path=str(tmp_path / ".env"),
        )
        assert not res.success

    def test_missing_account(self, tmp_path):
        res = connect_instagram(
            access_token="t", account_id="",
            env_path=str(tmp_path / ".env"),
        )
        assert not res.success

    def test_writes_both_keys(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("OTHER=v\n")
        res = connect_instagram(
            access_token="TKN", account_id="A123",
            env_path=str(env),
        )
        assert res.success
        c = env.read_text()
        assert "INSTAGRAM_ACCESS_TOKEN=TKN" in c
        assert "INSTAGRAM_ACCOUNT_ID=A123" in c
        assert "OTHER=v" in c

    def test_replaces_existing(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("INSTAGRAM_ACCESS_TOKEN=OLD\n")
        connect_instagram(
            access_token="NEW", account_id="A",
            env_path=str(env),
        )
        c = env.read_text()
        assert "INSTAGRAM_ACCESS_TOKEN=NEW" in c
        assert "OLD" not in c

    def test_sets_process_env(self, tmp_path):
        connect_instagram(
            access_token="P", account_id="A",
            env_path=str(tmp_path / ".env"),
        )
        assert os.environ.get("INSTAGRAM_ACCESS_TOKEN") == "P"
        assert os.environ.get("INSTAGRAM_ACCOUNT_ID") == "A"


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
            data={"posts": [{"id": "p1", "caption": "x"}]},
            error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ):
            res = list_posts(limit=5)
        assert res.success
        assert len(res.posts) == 1


# ── Publisher: publish_post ───────────────────────────────


class TestPublishPost:
    def test_missing_media(self):
        res = publish_post(caption="hi", media_url="")
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
                "post_id": "MEDIA_XYZ",
                "creation_id": "CTR_ABC",
                "media_type": "IMAGE",
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
        assert res.post_id == "MEDIA_XYZ"
        assert res.creation_id == "CTR_ABC"

    def test_failure_recorded(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=False, data=None, error="container failed",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            res = publish_post(
                caption="hi",
                media_url="https://x.com/i.jpg",
            )
        assert not res.success
        assert "container failed" in res.error


# ── Engine Pattern Q envelope ─────────────────────────────


class TestEngineEnvelope:
    def test_empty_input_returns_status(self):
        result = InstagramPublisherEngine().run({})
        assert result["status"] == "success"
        assert result["data"]["action"] == "status"

    def test_none_input(self):
        result = InstagramPublisherEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_error(self):
        result = InstagramPublisherEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream(self):
        result = InstagramPublisherEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_unknown_action(self):
        result = InstagramPublisherEngine().run({
            "data": {"action": "delete"},
        })
        assert result["status"] == "error"


class TestEnginePublishAction:
    def test_missing_media_url(self):
        result = InstagramPublisherEngine().run({
            "data": {
                "action": "publish-post",
                "caption": "hi",
            },
        })
        assert result["data"]["published"] is False

    def test_publish_succeeds_with_mock(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True,
            data={"post_id": "M1", "creation_id": "C1"},
            error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            result = InstagramPublisherEngine().run({
                "data": {
                    "action": "publish-post",
                    "caption": "Hi",
                    "media_url": "https://x.com/i.jpg",
                },
            })
        assert result["data"]["published"] is True
