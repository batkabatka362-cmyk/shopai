"""Tests for substrate_fire_alert_history (W853)."""
from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from core.automation.substrate_fire_alert_history import (
    AlertHistoryEntry,
    alert_history_log_size,
    consecutive_critical_days,
    recent_alerts,
    record_alerts,
)


@dataclass
class FakeAlert:
    domain: str = ""
    kind: str = ""
    severity: str = ""
    success_rate: float = 0.0
    errors: int = 0
    sample_size: int = 0
    reason: str = ""


class TestRecord:

    def test_record_no_ops_under_pytest(self):
        # Pattern J inherited from action_log
        before = alert_history_log_size()
        record_alerts([
            FakeAlert(
                domain="shipping_alert",
                kind="low_success_rate",
                severity="critical",
                reason="test",
            ),
        ])
        assert alert_history_log_size() == before

    def test_record_skips_missing_domain(self):
        before = alert_history_log_size()
        record_alerts([FakeAlert(kind="low_success_rate")])
        assert alert_history_log_size() == before

    def test_record_handles_empty_list(self):
        record_alerts([])
        # No exception, no growth

    def test_record_handles_none(self):
        record_alerts(None)  # type: ignore


class TestPersistencePath:
    """Lift Pattern J to exercise real recorder behavior."""

    def test_record_and_read_round_trip(self):
        fd, path = tempfile.mkstemp(
            suffix="_alerts_test.json",
        )
        try:
            with patch(
                "core.automation.action_log."
                "is_test_environment",
                return_value=False,
            ), patch(
                "core.automation.substrate_fire_alert_history."
                "_LOG_PATH",
                Path(path),
            ):
                from core.automation import (
                    substrate_fire_alert_history as _h,
                )
                _h.record_alerts([
                    FakeAlert(
                        domain="shipping_alert",
                        kind="low_success_rate",
                        severity="critical",
                        success_rate=0.1,
                        errors=9,
                        sample_size=10,
                        reason="rate dropped",
                    ),
                ])
                rows = _h.recent_alerts(window_hours=24.0)
                assert len(rows) == 1
                assert rows[0]["domain"] == "shipping_alert"
                assert rows[0]["severity"] == "critical"
                assert rows[0]["success_rate"] == 0.1
        finally:
            try:
                Path(path).unlink()
            except OSError:
                pass

    def test_store_filter_works(self):
        fd, path = tempfile.mkstemp(
            suffix="_alerts_test.json",
        )
        try:
            with patch(
                "core.automation.action_log."
                "is_test_environment",
                return_value=False,
            ), patch(
                "core.automation.substrate_fire_alert_history."
                "_LOG_PATH",
                Path(path),
            ):
                from core.automation import (
                    substrate_fire_alert_history as _h,
                )
                _h.record_alerts(
                    [FakeAlert(
                        domain="shipping_alert",
                        kind="x", severity="critical",
                    )],
                    store_id="store-1",
                )
                _h.record_alerts(
                    [FakeAlert(
                        domain="shipping_alert",
                        kind="y", severity="critical",
                    )],
                    store_id="store-2",
                )
                rows = _h.recent_alerts(
                    window_hours=24.0,
                    store_id="store-1",
                )
                assert len(rows) == 1
        finally:
            try:
                Path(path).unlink()
            except OSError:
                pass


class TestConsecutiveCriticalDays:

    def test_no_alerts_returns_zero(self):
        with patch(
            "core.automation.substrate_fire_alert_history."
            "recent_alerts",
            return_value=[],
        ):
            n = consecutive_critical_days("shipping_alert")
        assert n == 0

    def test_same_day_alerts_count_as_one(self):
        now = time.time()
        rows = [
            {
                "domain": "x", "severity": "critical",
                "recorded_at": now,
            },
            {
                "domain": "x", "severity": "critical",
                "recorded_at": now - 60.0,
            },
        ]
        with patch(
            "core.automation.substrate_fire_alert_history."
            "recent_alerts",
            return_value=rows,
        ):
            n = consecutive_critical_days("x")
        assert n == 1

    def test_three_distinct_days(self):
        now = time.time()
        rows = [
            {
                "domain": "x", "severity": "critical",
                "recorded_at": now,
            },
            {
                "domain": "x", "severity": "critical",
                "recorded_at": now - 86400.0,
            },
            {
                "domain": "x", "severity": "critical",
                "recorded_at": now - 2 * 86400.0,
            },
        ]
        with patch(
            "core.automation.substrate_fire_alert_history."
            "recent_alerts",
            return_value=rows,
        ):
            n = consecutive_critical_days("x")
        assert n == 3


class TestEntryDataclass:

    def test_defaults(self):
        e = AlertHistoryEntry(
            domain="x", kind="y", severity="z",
        )
        assert e.store_id == ""
        assert e.recorded_at > 0
