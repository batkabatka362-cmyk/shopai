"""Tests for engines.pinterest_publisher — W963-10."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from engines.pinterest_publisher import PinterestPublisherEngine
from engines.pinterest_publisher.connect import connect_pinterest
from engines.pinterest_publisher.publisher import (
    list_boards,
    publish_pin,
)
from engines.pinterest_publisher.status import (
    PinterestStatus,
    get_status,
)


# ── Status ────────────────────────────────────────────────


class TestStatus:
    def test_skip_live_returns_creds_only(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PINTEREST_ACCESS_TOKEN", None)
            s = get_status(skip_live=True)
        assert not s.credentials_present
        assert not s.auth_verified

    def test_ready_property_requires_both(self):
        s = PinterestStatus(
            adapter_registered=True,
            credentials_present=True,
        )
        assert s.ready
        s.credentials_present = False
        assert not s.ready


# ── Connect ───────────────────────────────────────────────


class TestConnect:
    def test_empty_token_rejected(self, tmp_path):
        res = connect_pinterest(
            access_token="",
            env_path=str(tmp_path / ".env"),
        )
        assert not res.success

    def test_writes_to_env(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("OTHER=v\n")
        res = connect_pinterest(
            access_token="pina_TOKEN",
            env_path=str(env),
        )
        assert res.success
        content = env.read_text()
        assert "PINTEREST_ACCESS_TOKEN=pina_TOKEN" in content

    def test_replaces_existing(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("PINTEREST_ACCESS_TOKEN=old\n")
        connect_pinterest(
            access_token="new", env_path=str(env),
        )
        c = env.read_text()
        assert "PINTEREST_ACCESS_TOKEN=new" in c
        assert "old" not in c

    def test_sets_process_env(self, tmp_path):
        connect_pinterest(
            access_token="PROC",
            env_path=str(tmp_path / ".env"),
        )
        assert (
            os.environ.get("PINTEREST_ACCESS_TOKEN") == "PROC"
        )


# ── Publisher: list_boards ────────────────────────────────


class TestListBoards:
    def test_router_error(self):
        with patch(
            "core.adapters.router.get_router",
            side_effect=Exception("no router"),
        ):
            res = list_boards()
        assert not res.success
        assert "router" in res.error.lower()

    def test_successful_list(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True,
            data={"boards": [
                {"id": "b1", "name": "Beauty"},
                {"id": "b2", "name": "Home"},
            ]},
            error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ):
            res = list_boards(limit=10)
        assert res.success
        assert len(res.boards) == 2


# ── Publisher: publish_pin ────────────────────────────────


class TestPublishPin:
    def test_missing_board_id_rejected(self):
        res = publish_pin(
            board_id="", title="T",
            image_url="https://x.com/i.jpg",
        )
        assert not res.success
        assert "board_id" in res.error

    def test_missing_title_rejected(self):
        res = publish_pin(
            board_id="b1", title="",
            image_url="https://x.com/i.jpg",
        )
        assert not res.success
        assert "title" in res.error

    def test_non_http_image_rejected(self):
        res = publish_pin(
            board_id="b1", title="T",
            image_url="ftp://x.com/i.jpg",
        )
        assert not res.success
        assert "HTTP(S)" in res.error

    def test_router_unavailable(self):
        with patch(
            "core.adapters.router.get_router",
            side_effect=Exception("nope"),
        ):
            res = publish_pin(
                board_id="b1", title="T",
                image_url="https://x.com/i.jpg",
            )
        assert not res.success

    def test_successful_publish_returns_pin_id(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True,
            data={
                "pin_id": "PIN_123",
                "url": "https://pin.it/abc",
            },
            error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            res = publish_pin(
                board_id="b1", title="Hello",
                image_url="https://x.com/i.jpg",
                link="https://shop.com/p/1",
            )
        assert res.success
        assert res.pin_id == "PIN_123"
        assert res.pin_url == "https://pin.it/abc"

    def test_failed_publish_recorded(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=False, data=None, error="rate limited",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            res = publish_pin(
                board_id="b1", title="T",
                image_url="https://x.com/i.jpg",
            )
        assert not res.success
        assert "rate limited" in res.error


# ── Engine Pattern Q envelope ─────────────────────────────


class TestEngineEnvelope:
    def test_empty_input_returns_status(self):
        result = PinterestPublisherEngine().run({})
        assert result["status"] == "success"
        assert result["data"]["action"] == "status"

    def test_none_input(self):
        result = PinterestPublisherEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_error(self):
        result = PinterestPublisherEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream(self):
        result = PinterestPublisherEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_unknown_action(self):
        result = PinterestPublisherEngine().run({
            "data": {"action": "delete"},
        })
        assert result["status"] == "error"


class TestEnginePublishAction:
    def test_publish_requires_board(self):
        result = PinterestPublisherEngine().run({
            "data": {
                "action": "publish-pin",
                "title": "T",
                "image_url": "https://x.com/i.jpg",
            },
        })
        assert result["data"]["published"] is False

    def test_publish_succeeds_with_mock(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"pin_id": "PIN_X"}, error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            result = PinterestPublisherEngine().run({
                "data": {
                    "action": "publish-pin",
                    "board_id": "b1",
                    "title": "Hello",
                    "image_url": "https://x.com/i.jpg",
                },
            })
        assert result["data"]["published"] is True
