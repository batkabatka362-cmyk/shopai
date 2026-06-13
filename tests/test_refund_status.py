"""Tests for engines.returns_management.refund_log + refund_status."""
from __future__ import annotations

import time
from unittest.mock import patch

from engines.returns_management.refund_log import (
    RefundLogEntry,
    record_refund,
    recent_refunds,
)
from engines.returns_management.refund_status import (
    get_refund_status,
)


# ─── refund_log ──────────────────────────────────────────


class TestRefundLogPersistence:

    def test_record_refund_no_op_under_pytest(self):
        """Pattern J: PYTEST_CURRENT_TEST guard prevents test
        runs from polluting the production refund log."""
        # We're running under pytest, so PYTEST_CURRENT_TEST is
        # set. record_refund must be a no-op.
        with patch(
            "engines.returns_management.refund_log._save",
        ) as save_mock:
            record_refund(RefundLogEntry(
                return_id="r1", order_id="o1",
                refund_amount=10.0, status="recorded",
                applied=True,
            ))
        save_mock.assert_not_called()

    def test_record_refund_persists_when_guard_off(
        self, monkeypatch,
    ):
        """Lift the Pattern J guard + verify the row reaches
        the save layer."""
        # Override the test-env detector for this single test
        monkeypatch.setattr(
            "engines.returns_management.refund_log."
            "_is_test_environment",
            lambda: False,
        )
        captured = []
        with patch(
            "engines.returns_management.refund_log._load",
            return_value=[],
        ), patch(
            "engines.returns_management.refund_log._save",
            side_effect=lambda rows: captured.extend(rows),
        ):
            record_refund(RefundLogEntry(
                return_id="r1", order_id="o1",
                refund_amount=25.0, status="recorded",
                applied=True,
            ))
        assert len(captured) == 1
        assert captured[0]["return_id"] == "r1"

    def test_record_refund_ignores_non_entry(self, monkeypatch):
        monkeypatch.setattr(
            "engines.returns_management.refund_log."
            "_is_test_environment",
            lambda: False,
        )
        with patch(
            "engines.returns_management.refund_log._save",
        ) as save_mock:
            record_refund("not_a_dataclass")  # type: ignore[arg-type]
        save_mock.assert_not_called()


class TestRecentRefunds:
    """recent_refunds reads the persisted log + filters by
    window + store_id."""

    def _stub_log(self, rows):
        """Helper to patch _load with synthetic rows."""
        return patch(
            "engines.returns_management.refund_log._load",
            return_value=rows,
        )

    def test_filters_by_window_hours(self):
        now = time.time()
        rows = [
            {
                "return_id": "r1", "order_id": "o1",
                "store_id": "", "recorded_at": now - 7200,
                "applied": True, "refund_amount": 10,
            },  # 2h ago -- inside 4h window
            {
                "return_id": "r2", "order_id": "o2",
                "store_id": "", "recorded_at": now - 36000,
                "applied": True, "refund_amount": 20,
            },  # 10h ago -- outside 4h window
        ]
        with self._stub_log(rows):
            out = recent_refunds(window_hours=4.0)
        assert len(out) == 1
        assert out[0]["return_id"] == "r1"

    def test_filters_by_store_id(self):
        now = time.time()
        rows = [
            {
                "return_id": "r1", "order_id": "o1",
                "store_id": "store_a", "recorded_at": now,
            },
            {
                "return_id": "r2", "order_id": "o2",
                "store_id": "store_b", "recorded_at": now,
            },
        ]
        with self._stub_log(rows):
            out = recent_refunds(store_id="store_a")
        assert len(out) == 1
        assert out[0]["return_id"] == "r1"

    def test_sorts_newest_first(self):
        now = time.time()
        rows = [
            {
                "return_id": "old", "order_id": "o1",
                "recorded_at": now - 3600,
            },
            {
                "return_id": "new", "order_id": "o2",
                "recorded_at": now - 60,
            },
        ]
        with self._stub_log(rows):
            out = recent_refunds(window_hours=2.0)
        assert out[0]["return_id"] == "new"
        assert out[1]["return_id"] == "old"


# ─── refund_status ───────────────────────────────────────


class TestRefundStatusReport:

    def _stub_recent(self, rows):
        return patch(
            "engines.returns_management.refund_status."
            "recent_refunds",
            return_value=rows,
        )

    def test_empty_log_returns_zero_report(self):
        with self._stub_recent([]):
            report = get_refund_status()
        assert report.total_entries == 0
        assert report.applied_count == 0
        assert report.skipped_count == 0
        assert report.total_refunded == 0.0

    def test_counts_applied_vs_skipped(self):
        rows = [
            {
                "return_id": "r1", "order_id": "o1",
                "applied": True, "status": "recorded",
                "refund_amount": 25.0,
            },
            {
                "return_id": "r2", "order_id": "o2",
                "applied": True, "status": "recorded",
                "refund_amount": 50.0,
            },
            {
                "return_id": "r3", "order_id": "o3",
                "applied": False, "status": "exceeds_max_amount",
                "refund_amount": 999.0,
            },
        ]
        with self._stub_recent(rows):
            report = get_refund_status()
        assert report.applied_count == 2
        assert report.skipped_count == 1
        assert report.total_refunded == 75.0
        assert report.avg_refund_amount == 37.5
        assert report.by_status == {
            "recorded": 2, "exceeds_max_amount": 1,
        }

    def test_per_store_rollup_only_when_no_store_filter(self):
        rows = [
            {
                "return_id": "r1", "order_id": "o1",
                "store_id": "store_a",
                "applied": True, "status": "recorded",
                "refund_amount": 25.0,
            },
            {
                "return_id": "r2", "order_id": "o2",
                "store_id": "store_b",
                "applied": True, "status": "recorded",
                "refund_amount": 50.0,
            },
        ]
        with self._stub_recent(rows):
            report = get_refund_status()  # no store filter
        assert "store_a" in report.by_store
        assert "store_b" in report.by_store
        assert report.by_store["store_a"]["applied"] == 1
        assert report.by_store["store_b"]["total_refunded"] == 50.0

    def test_sample_skips_caps_at_five(self):
        # Build 10 skipped rows
        rows = [
            {
                "return_id": f"r{i}", "order_id": f"o{i}",
                "applied": False, "status": "fraud_risk_too_high",
                "refund_amount": 10.0,
            }
            for i in range(10)
        ]
        with self._stub_recent(rows):
            report = get_refund_status()
        assert len(report.sample_skips) == 5

    def test_status_filter_passthrough(self):
        """get_refund_status with store_id filter scopes
        recent_refunds correctly."""
        captured = {}

        def fake_recent(*, window_hours, store_id=None):
            captured["window_hours"] = window_hours
            captured["store_id"] = store_id
            return []

        with patch(
            "engines.returns_management.refund_status."
            "recent_refunds",
            side_effect=fake_recent,
        ):
            get_refund_status(
                window_hours=24.0, store_id="store_a",
            )
        assert captured["window_hours"] == 24.0
        assert captured["store_id"] == "store_a"
