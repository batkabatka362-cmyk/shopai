"""Tests for ``core.autonomous.transfer_history``."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.autonomous import transfer_history as th


@pytest.fixture
def tmp_history(tmp_path):
    history_path = tmp_path / "transfer_history.json"
    th._reset_for_tests(history_path)
    yield history_path
    th._reset_for_tests(
        Path("data/transfer_history.json"),
    )


class TestPatternJ:

    def test_default_short_circuits(self, tmp_history):
        ok = th.record_transfer(
            target_store_id="a",
            source_store_id="b",
            engine="loyalty",
            action_type="mint",
            capability="cap",
        )
        assert ok is False
        assert not tmp_history.exists()

    def test_disabled_guard_writes(self, tmp_history):
        with patch(
            "core.autonomous.transfer_history."
            "_is_test_environment",
            return_value=False,
        ):
            ok = th.record_transfer(
                target_store_id="a",
                source_store_id="b",
                engine="loyalty",
                action_type="mint",
                capability="cap",
            )
        assert ok is True
        assert tmp_history.exists()


class TestRecordTransfer:

    def _w(self):
        return patch(
            "core.autonomous.transfer_history."
            "_is_test_environment",
            return_value=False,
        )

    def test_required_fields_validated(self, tmp_history):
        with self._w():
            ok = th.record_transfer(
                target_store_id="",
                source_store_id="b",
                engine="loyalty",
                action_type="mint",
                capability="cap",
            )
        assert ok is False

    def test_round_trip(self, tmp_history):
        with self._w():
            th.record_transfer(
                target_store_id="store_b",
                source_store_id="store_a",
                engine="loyalty",
                action_type="mint_recovery",
                capability="SHOPAI_X",
                action_id="enq_1",
                metrics={"revenue": 500.0},
            )
        events = th.recent_history()
        assert len(events) == 1
        e = events[0]
        assert e.target_store_id == "store_b"
        assert e.source_store_id == "store_a"
        assert e.engine == "loyalty"
        assert e.action_id == "enq_1"
        assert e.metrics["revenue"] == 500.0

    def test_target_store_filter(self, tmp_history):
        with self._w():
            th.record_transfer(
                target_store_id="store_a",
                source_store_id="src",
                engine="e",
                action_type="t",
                capability="c",
            )
            th.record_transfer(
                target_store_id="store_b",
                source_store_id="src",
                engine="e",
                action_type="t",
                capability="c",
            )
        events_a = th.recent_history(
            target_store_id="store_a",
        )
        events_b = th.recent_history(
            target_store_id="store_b",
        )
        assert len(events_a) == 1
        assert events_a[0].target_store_id == "store_a"
        assert len(events_b) == 1

    def test_window_filter(self, tmp_history):
        with self._w():
            th.record_transfer(
                target_store_id="a",
                source_store_id="b",
                engine="e",
                action_type="t",
                capability="c",
            )
        rows = json.loads(tmp_history.read_text())
        rows[0]["recorded_at"] = time.time() - 86400 * 30
        tmp_history.write_text(json.dumps(rows))
        assert th.recent_history(
            since_seconds=86400 * 7,
        ) == []
        assert len(th.recent_history(
            since_seconds=86400 * 60,
        )) == 1

    def test_cap_drops_oldest(self, tmp_history):
        with self._w():
            for i in range(1001):
                th.record_transfer(
                    target_store_id=f"t_{i}",
                    source_store_id="s",
                    engine="e",
                    action_type="t",
                    capability="c",
                )
        raw = json.loads(tmp_history.read_text())
        assert len(raw) == 1000

    def test_corrupt_file_fails_open(self, tmp_history):
        tmp_history.write_text("not json{")
        assert th.recent_history() == []


class TestTransferStats:

    def _w(self):
        return patch(
            "core.autonomous.transfer_history."
            "_is_test_environment",
            return_value=False,
        )

    def test_empty(self, tmp_history):
        stats = th.transfer_stats()
        assert stats["total"] == 0
        assert stats["by_target"] == {}
        assert stats["last_transfer_at"] is None

    def test_aggregates(self, tmp_history):
        with self._w():
            th.record_transfer(
                target_store_id="store_b",
                source_store_id="store_a",
                engine="loyalty",
                action_type="mint",
                capability="c",
            )
            th.record_transfer(
                target_store_id="store_c",
                source_store_id="store_a",
                engine="loyalty",
                action_type="mint",
                capability="c",
            )
            th.record_transfer(
                target_store_id="store_b",
                source_store_id="store_d",
                engine="affiliate",
                action_type="pay",
                capability="c",
            )
        stats = th.transfer_stats()
        assert stats["total"] == 3
        assert stats["by_target"]["store_b"] == 2
        assert stats["by_target"]["store_c"] == 1
        assert stats["by_source"]["store_a"] == 2
        assert stats["by_engine"]["loyalty"] == 2


class TestClear:

    def test_under_pytest_no_op(self, tmp_history):
        tmp_history.write_text("[]")
        th.clear()
        assert tmp_history.exists()

    def test_with_guard_off(self, tmp_history):
        tmp_history.write_text("[]")
        with patch(
            "core.autonomous.transfer_history."
            "_is_test_environment",
            return_value=False,
        ):
            th.clear()
        assert not tmp_history.exists()
