"""Tests for thrash_block_log (Wave 930)."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.automation.thrash_block_log import (
    BlockEntry,
    block_count,
    recent_blocks,
    record_block,
)


@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    with patch(
        "core.automation.thrash_block_log."
        "_is_test_environment",
        return_value=False,
    ):
        yield


class TestRecord:

    def test_appends_one(self, tmp_path):
        p = tmp_path / "b.json"
        record_block(
            engine="loyalty",
            action_type="mint_loyalty_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            store_id="store-7",
            reason="thrash_guardrail_blocked: ...",
            path=p,
        )
        assert block_count(path=p) == 1

    def test_appends_multiple(self, tmp_path):
        p = tmp_path / "b.json"
        for _ in range(3):
            record_block(
                engine="loyalty",
                action_type="mint",
                capability="X",
                store_id="store-7",
                reason="r",
                path=p,
            )
        assert block_count(path=p) == 3


class TestRecent:

    def test_newest_first(self, tmp_path):
        p = tmp_path / "b.json"
        for i in range(3):
            record_block(
                engine=f"e-{i}",
                action_type="a",
                capability="c",
                store_id=None,
                reason="r",
                path=p,
            )
        rows = recent_blocks(path=p)
        assert rows[0].engine == "e-2"
        assert rows[-1].engine == "e-0"

    def test_store_filter(self, tmp_path):
        p = tmp_path / "b.json"
        record_block(
            engine="x", action_type="a", capability="c",
            store_id="a", reason="r", path=p,
        )
        record_block(
            engine="x", action_type="a", capability="c",
            store_id="b", reason="r", path=p,
        )
        rows = recent_blocks(path=p, store_id="a")
        assert len(rows) == 1
        assert rows[0].store_id == "a"

    def test_engine_filter(self, tmp_path):
        p = tmp_path / "b.json"
        record_block(
            engine="loyalty", action_type="a", capability="c",
            store_id=None, reason="r", path=p,
        )
        record_block(
            engine="affiliate", action_type="a",
            capability="c", store_id=None, reason="r",
            path=p,
        )
        rows = recent_blocks(path=p, engine="loyalty")
        assert len(rows) == 1
        assert rows[0].engine == "loyalty"

    def test_window_filter(self, tmp_path):
        p = tmp_path / "b.json"
        # Manually inject an old row
        import json as _json
        old_ts = time.time() - 7200
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps([{
            "blocked_at": old_ts,
            "engine": "x", "action_type": "a",
            "capability": "c", "store_id": None,
            "reason": "old",
        }]), encoding="utf-8")
        record_block(
            engine="y", action_type="a", capability="c",
            store_id=None, reason="new", path=p,
        )
        rows = recent_blocks(path=p, window_hours=1.0)
        assert len(rows) == 1
        assert rows[0].reason == "new"


class TestBlockEntry:

    def test_to_dict(self):
        e = BlockEntry(
            blocked_at=123.0,
            engine="e", action_type="a", capability="c",
            store_id="s", reason="r",
        )
        d = e.to_dict()
        assert d["engine"] == "e"
        assert d["store_id"] == "s"


class TestPytestGuard:

    def test_short_circuits(self, tmp_path):
        from core.automation import thrash_block_log
        p = tmp_path / "b.json"
        with patch.object(
            thrash_block_log,
            "_is_test_environment",
            return_value=True,
        ):
            record_block(
                engine="x", action_type="a",
                capability="c", store_id=None,
                reason="r", path=p,
            )
        assert not p.exists()
