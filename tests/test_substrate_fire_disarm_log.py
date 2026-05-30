"""Tests for substrate_fire_disarm_log (W858)."""
from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from core.automation.substrate_fire_disarm_log import (
    DisarmLogEntry,
    disarm_log_size,
    last_disarm_at,
    recent_disarms,
    record_disarm_decisions,
)


@dataclass
class FakeDecision:
    domain: str = ""
    consecutive_days: int = 0
    threshold: int = 0
    would_disarm: bool = False
    disarmed: bool = False
    reason: str = ""


class TestRecord:

    def test_record_no_ops_under_pytest(self):
        before = disarm_log_size()
        record_disarm_decisions([
            FakeDecision(
                domain="shipping_alert",
                consecutive_days=5,
                threshold=3,
                would_disarm=True,
                disarmed=True,
                reason="auto-disarmed",
            ),
        ])
        assert disarm_log_size() == before

    def test_record_skips_missing_domain(self):
        record_disarm_decisions([FakeDecision()])
        # No exception, no growth

    def test_record_handles_empty(self):
        record_disarm_decisions([])

    def test_record_handles_none(self):
        record_disarm_decisions(None)  # type: ignore


class TestPersistencePath:

    def test_round_trip_read(self):
        fd, path = tempfile.mkstemp(
            suffix="_disarm_test.json",
        )
        try:
            with patch(
                "core.automation.action_log."
                "is_test_environment",
                return_value=False,
            ), patch(
                "core.automation.substrate_fire_disarm_log."
                "_LOG_PATH",
                Path(path),
            ):
                from core.automation import (
                    substrate_fire_disarm_log as _l,
                )
                _l.record_disarm_decisions([
                    FakeDecision(
                        domain="shipping_alert",
                        consecutive_days=5,
                        threshold=3,
                        would_disarm=True,
                        disarmed=True,
                        reason="auto",
                    ),
                ])
                rows = _l.recent_disarms(window_hours=24.0)
                assert len(rows) == 1
                assert rows[0]["disarmed"] is True
        finally:
            try:
                Path(path).unlink()
            except OSError:
                pass

    def test_only_disarmed_filter(self):
        fd, path = tempfile.mkstemp(
            suffix="_disarm_test.json",
        )
        try:
            with patch(
                "core.automation.action_log."
                "is_test_environment",
                return_value=False,
            ), patch(
                "core.automation.substrate_fire_disarm_log."
                "_LOG_PATH",
                Path(path),
            ):
                from core.automation import (
                    substrate_fire_disarm_log as _l,
                )
                _l.record_disarm_decisions([
                    FakeDecision(
                        domain="a", would_disarm=True,
                        disarmed=False,
                    ),
                    FakeDecision(
                        domain="b", would_disarm=True,
                        disarmed=True,
                    ),
                ])
                rows = _l.recent_disarms(
                    window_hours=24.0,
                    only_disarmed=True,
                )
                assert len(rows) == 1
                assert rows[0]["domain"] == "b"
        finally:
            try:
                Path(path).unlink()
            except OSError:
                pass


class TestLastDisarmAt:

    def test_no_history_returns_none(self):
        with patch(
            "core.automation.substrate_fire_disarm_log."
            "recent_disarms",
            return_value=[],
        ):
            assert last_disarm_at("shipping_alert") is None

    def test_returns_most_recent_timestamp(self):
        now = time.time()
        rows = [
            {"domain": "x", "recorded_at": now},
            {"domain": "x", "recorded_at": now - 3600.0},
        ]
        with patch(
            "core.automation.substrate_fire_disarm_log."
            "recent_disarms",
            return_value=rows,
        ):
            ts = last_disarm_at("x")
        assert ts == now


class TestEntryDataclass:

    def test_defaults(self):
        e = DisarmLogEntry(
            domain="x", consecutive_days=3, threshold=3,
        )
        assert not e.disarmed
        assert e.recorded_at > 0
