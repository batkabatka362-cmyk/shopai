"""Tests for engines.returns_management.refund_state + refund_health."""
from __future__ import annotations

import time
from unittest.mock import patch

from engines.returns_management.refund_state import (
    RefundPauseState,
    get_state,
    is_paused,
    pause,
    resume,
)
from engines.returns_management.refund_health import (
    RefundHealthReport,
    analyze_refund_health,
    maybe_auto_pause_refunds,
)


# ─── refund_state ────────────────────────────────────────


class TestRefundPauseStateRoundTrip:

    def test_save_skipped_under_pytest(self):
        """Pattern J: _save no-ops under PYTEST_CURRENT_TEST so
        tests don't pollute the production refund_state.json."""
        with patch(
            "engines.returns_management.refund_state."
            "_STATE_PATH"
        ) as mock_path:
            pause(reason="test")
            # _save short-circuits -> the path's .open()
            # is never reached
            mock_path.open.assert_not_called()

    def test_load_returns_default_when_missing(
        self, monkeypatch, tmp_path,
    ):
        """When the state file doesn't exist, load returns an
        unpaused default RefundPauseState."""
        # Point _STATE_PATH at a non-existent file
        fake_path = tmp_path / "no_such_file.json"
        monkeypatch.setattr(
            "engines.returns_management.refund_state."
            "_STATE_PATH",
            fake_path,
        )
        state = get_state()
        assert state.paused is False
        assert state.reason == ""


class TestPauseResume:

    def test_pause_then_resume(self, monkeypatch, tmp_path):
        # Disable the Pattern J guard so writes happen
        monkeypatch.setattr(
            "engines.returns_management.refund_state."
            "_is_test_environment",
            lambda: False,
        )
        fake_path = tmp_path / "refund_state.json"
        monkeypatch.setattr(
            "engines.returns_management.refund_state."
            "_STATE_PATH",
            fake_path,
        )
        state = pause(reason="threshold breach")
        assert state.paused is True
        assert is_paused() is True
        state2 = resume()
        assert state2.paused is False
        assert is_paused() is False

    def test_auto_resume_after_deadline(
        self, monkeypatch, tmp_path,
    ):
        """When auto_resume_after has passed, get_state
        transparently flips the flag back to unpaused +
        persists the cleared state."""
        monkeypatch.setattr(
            "engines.returns_management.refund_state."
            "_is_test_environment",
            lambda: False,
        )
        fake_path = tmp_path / "refund_state.json"
        monkeypatch.setattr(
            "engines.returns_management.refund_state."
            "_STATE_PATH",
            fake_path,
        )
        # Pause with an already-elapsed auto_resume_after
        pause(
            reason="test", auto_resume_after=time.time() - 60,
        )
        state = get_state()
        assert state.paused is False  # auto-resumed


# ─── refund_health ───────────────────────────────────────


def _row(*, applied=True, status="recorded", amount=10.0):
    return {
        "return_id": "r",
        "order_id": "o",
        "applied": applied,
        "status": status,
        "refund_amount": amount,
        "recorded_at": time.time(),
    }


class TestAnalyzeRefundHealth:

    def _stub_recent(self, rows):
        return patch(
            "engines.returns_management.refund_health."
            "recent_refunds",
            return_value=rows,
        )

    def test_small_sample_returns_healthy(self):
        """Below min_sample (default 5) -> healthy regardless
        of failure ratio."""
        rows = [
            _row(applied=False, status="adapter_failed"),
            _row(applied=False, status="adapter_failed"),
        ]
        with self._stub_recent(rows), patch(
            "engines.returns_management.refund_health."
            "is_paused", return_value=False,
        ):
            report = analyze_refund_health()
        assert report.verdict == "healthy"
        assert "insufficient data" in report.reasons[0]

    def test_low_failure_ratio_healthy(self):
        rows = [
            _row(applied=True),
            _row(applied=True),
            _row(applied=True),
            _row(applied=True),
            _row(applied=True),
            _row(applied=False, status="adapter_failed"),
        ]
        with self._stub_recent(rows), patch(
            "engines.returns_management.refund_health."
            "is_paused", return_value=False,
        ):
            report = analyze_refund_health()
        # 1/6 = ~17% which is >= 15% warn threshold -> degraded
        assert report.verdict == "degraded"

    def test_high_failure_ratio_critical(self):
        rows = [
            _row(applied=False, status="adapter_failed"),
            _row(applied=False, status="adapter_failed"),
            _row(applied=False, status="adapter_failed"),
            _row(applied=False, status="adapter_failed"),
            _row(applied=True),
            _row(applied=True),
        ]
        with self._stub_recent(rows), patch(
            "engines.returns_management.refund_health."
            "is_paused", return_value=False,
        ):
            report = analyze_refund_health()
        # 4/6 = 67% >> 30% pause threshold
        assert report.verdict == "critical"

    def test_already_paused_field_populated(self):
        rows = [_row(applied=True) for _ in range(10)]
        with self._stub_recent(rows), patch(
            "engines.returns_management.refund_health."
            "is_paused", return_value=True,
        ):
            report = analyze_refund_health()
        assert report.already_paused is True


class TestAutoPauseBridge:
    """maybe_auto_pause_refunds: opt-in, idempotent, condition-
    gated."""

    def _critical_rows(self):
        return [
            _row(applied=False, status="adapter_failed")
            for _ in range(8)
        ]

    def test_bridge_off_by_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_PAUSE_REFUNDS_ON_FAILURE",
            raising=False,
        )
        with patch(
            "engines.returns_management.refund_health."
            "recent_refunds",
            return_value=self._critical_rows(),
        ), patch(
            "engines.returns_management.refund_health."
            "is_paused", return_value=False,
        ), patch(
            "engines.returns_management.refund_health.pause",
        ) as pause_mock:
            report = maybe_auto_pause_refunds()
        # Verdict is critical but bridge didn't fire
        assert report.verdict == "critical"
        assert report.bridge_fired is False
        assert "env-gate OFF" in report.bridge_reason
        pause_mock.assert_not_called()

    def test_bridge_fires_when_gated_and_critical(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_PAUSE_REFUNDS_ON_FAILURE", "1",
        )
        with patch(
            "engines.returns_management.refund_health."
            "recent_refunds",
            return_value=self._critical_rows(),
        ), patch(
            "engines.returns_management.refund_health."
            "is_paused", return_value=False,
        ), patch(
            "engines.returns_management.refund_health.pause",
        ) as pause_mock:
            report = maybe_auto_pause_refunds()
        assert report.bridge_fired is True
        pause_mock.assert_called_once()

    def test_bridge_idempotent_when_already_paused(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_PAUSE_REFUNDS_ON_FAILURE", "1",
        )
        with patch(
            "engines.returns_management.refund_health."
            "recent_refunds",
            return_value=self._critical_rows(),
        ), patch(
            "engines.returns_management.refund_health."
            "is_paused", return_value=True,
        ), patch(
            "engines.returns_management.refund_health.pause",
        ) as pause_mock:
            report = maybe_auto_pause_refunds()
        assert report.bridge_fired is False
        assert report.bridge_reason == "already_paused"
        pause_mock.assert_not_called()

    def test_bridge_does_not_fire_when_only_degraded(
        self, monkeypatch,
    ):
        """degraded verdict should NOT auto-pause -- only
        critical."""
        monkeypatch.setenv(
            "SHOPAI_AUTO_PAUSE_REFUNDS_ON_FAILURE", "1",
        )
        degraded_rows = [
            _row(applied=True), _row(applied=True),
            _row(applied=True), _row(applied=True),
            _row(applied=True),
            _row(applied=False, status="adapter_failed"),
        ]
        with patch(
            "engines.returns_management.refund_health."
            "recent_refunds",
            return_value=degraded_rows,
        ), patch(
            "engines.returns_management.refund_health."
            "is_paused", return_value=False,
        ), patch(
            "engines.returns_management.refund_health.pause",
        ) as pause_mock:
            report = maybe_auto_pause_refunds()
        assert report.verdict == "degraded"
        assert report.bridge_fired is False
        pause_mock.assert_not_called()


class TestApplierRespectsPauseFlag:
    """When refund_state.is_paused() returns True, every row
    in apply_refunds() skips with status='paused'."""

    def test_paused_skips_every_row(self):
        from engines.returns_management.refund_applier import (
            apply_refunds,
        )
        processed = [
            {
                "return_id": "r1", "order_id": "o1",
                "status": "approved",
                "refund_amount": 25.0,
            },
            {
                "return_id": "r2", "order_id": "o2",
                "status": "approved",
                "refund_amount": 50.0,
            },
        ]
        with patch(
            "engines.returns_management.refund_applier."
            "is_paused",
            return_value=True,
        ):
            out = apply_refunds(processed, fraud_flags=[])
        assert len(out) == 2
        for row in out:
            assert row["applied"] is False
            assert row["status"] == "paused"
            assert (
                "auto-pause flag" in row["error"]
            )
