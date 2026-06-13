"""Tests for engines.customer_support.support_status."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from engines.customer_support.support_status import (
    SupportStatusReport,
    _aggregate_verdict,
    _ticket_tag_activity,
    get_support_status,
)
from engines.returns_management.refund_health import (
    RefundHealthReport,
)
from engines.returns_management.refund_state import (
    RefundPauseState,
)
from engines.returns_management.refund_status import (
    RefundStatusReport,
)


def _stub_refund_status(*, total=0, applied=0, skipped=0,
                         amount=0.0, avg=0.0):
    return RefundStatusReport(
        window_hours=168.0,
        total_entries=total,
        applied_count=applied,
        skipped_count=skipped,
        total_refunded=amount,
        avg_refund_amount=avg,
    )


def _stub_health(*, verdict="healthy", ratio=0.0):
    return RefundHealthReport(
        window_hours=168.0,
        verdict=verdict,
        failure_ratio=ratio,
    )


def _patch_support_substrate(
    *,
    refund_status,
    health,
    pause_state,
    ticket_tag_counts=(0, 0, 0),
):
    """Compose patches for support_status's 4 inputs."""
    return [
        patch(
            "engines.customer_support.support_status."
            "get_refund_status",
            return_value=refund_status,
        ),
        patch(
            "engines.customer_support.support_status."
            "analyze_refund_health",
            return_value=health,
        ),
        patch(
            "engines.customer_support.support_status."
            "get_state",
            return_value=pause_state,
        ),
        patch(
            "engines.customer_support.support_status."
            "_ticket_tag_activity",
            return_value=ticket_tag_counts,
        ),
    ]


def _apply_patches(patchers, fn):
    """Helper to apply nested patches."""
    entered = [p.__enter__() for p in patchers]
    try:
        return fn()
    finally:
        for p in reversed(patchers):
            p.__exit__(None, None, None)


class TestAggregateVerdict:

    def _build(self, **kw):
        defaults = dict(
            window_hours=168.0,
            refund_total_entries=0,
            refund_applied_count=0,
            refund_skipped_count=0,
            refund_total_amount=0.0,
            refund_verdict="healthy",
            refund_failure_ratio=0.0,
            refund_paused=False,
            ticket_tag_total=0,
            ticket_tag_applied=0,
            ticket_tag_failed=0,
        )
        defaults.update(kw)
        return SupportStatusReport(**defaults)

    def test_paused_takes_priority(self):
        report = self._build(
            refund_paused=True,
            refund_pause_reason="threshold breach",
        )
        verdict, reasons, na = _aggregate_verdict(report)
        assert verdict == "paused"
        assert "auto-pause" in reasons[0]
        assert "refund-resume" in na

    def test_critical_refund_health_is_degraded(self):
        report = self._build(
            refund_verdict="critical",
            refund_failure_ratio=0.5,
        )
        verdict, reasons, na = _aggregate_verdict(report)
        assert verdict == "degraded"
        assert "critical threshold" in reasons[0]
        assert "refund-health --apply-bridge" in na

    def test_zero_activity_is_quiet(self):
        report = self._build()
        verdict, reasons, na = _aggregate_verdict(report)
        assert verdict == "quiet"
        assert "no refund or ticket-tag activity" in reasons[0]

    def test_healthy_when_activity_present(self):
        report = self._build(
            refund_total_entries=5,
            refund_applied_count=4,
            refund_total_amount=100.0,
        )
        verdict, _, _ = _aggregate_verdict(report)
        assert verdict == "healthy"

    def test_ticket_tag_failure_ratio_degraded(self):
        report = self._build(
            ticket_tag_total=10,
            ticket_tag_applied=5,
            ticket_tag_failed=5,
        )
        verdict, reasons, na = _aggregate_verdict(report)
        assert verdict == "degraded"
        assert "ticket-tag failure ratio" in reasons[0]

    def test_low_sample_ticket_tag_failures_not_degraded(self):
        """ticket_tag_total < 5 -> ratio check skipped."""
        report = self._build(
            ticket_tag_total=3,
            ticket_tag_failed=3,
            ticket_tag_applied=0,
            refund_applied_count=1,  # so it's not quiet
            refund_total_entries=1,
        )
        verdict, _, _ = _aggregate_verdict(report)
        assert verdict == "healthy"

    def test_degraded_refund_only(self):
        report = self._build(
            refund_verdict="degraded",
            refund_failure_ratio=0.2,
            refund_total_entries=10,
            refund_applied_count=8,
        )
        verdict, reasons, na = _aggregate_verdict(report)
        assert verdict == "degraded"
        assert "warn threshold" in reasons[0]


class TestGetSupportStatusComposition:
    """get_support_status correctly pulls from all 4 inputs."""

    def test_populates_all_fields(self):
        patches = _patch_support_substrate(
            refund_status=_stub_refund_status(
                total=10, applied=8, skipped=2,
                amount=200.0, avg=25.0,
            ),
            health=_stub_health(
                verdict="healthy", ratio=0.05,
            ),
            pause_state=RefundPauseState(),
            ticket_tag_counts=(5, 4, 1),
        )

        def call():
            return get_support_status(window_hours=24.0)

        report = _apply_patches(patches, call)
        assert report.refund_applied_count == 8
        assert report.refund_total_amount == 200.0
        assert report.refund_verdict == "healthy"
        assert report.refund_paused is False
        assert report.ticket_tag_total == 5
        assert report.ticket_tag_applied == 4
        assert report.ticket_tag_failed == 1
        # Aggregate verdict computed
        assert report.verdict in (
            "healthy", "quiet", "degraded", "paused",
        )
        assert len(report.verdict_reasons) >= 1

    def test_paused_state_propagates(self):
        patches = _patch_support_substrate(
            refund_status=_stub_refund_status(),
            health=_stub_health(),
            pause_state=RefundPauseState(
                paused=True,
                reason="manual pause",
                paused_at=12345.0,
            ),
        )
        report = _apply_patches(
            patches, lambda: get_support_status(),
        )
        assert report.refund_paused is True
        assert report.refund_pause_reason == "manual pause"
        assert report.verdict == "paused"

    def test_store_filter_passes_through(self):
        captured = {}
        patches = _patch_support_substrate(
            refund_status=_stub_refund_status(),
            health=_stub_health(),
            pause_state=RefundPauseState(),
        )

        def call():
            return get_support_status(store_id="store_a")

        # Override one patch to capture the call
        with patch(
            "engines.customer_support.support_status."
            "get_refund_status",
            side_effect=lambda **kw: (
                captured.update(kw) or _stub_refund_status()
            ),
        ), patch(
            "engines.customer_support.support_status."
            "analyze_refund_health",
            return_value=_stub_health(),
        ), patch(
            "engines.customer_support.support_status."
            "get_state",
            return_value=RefundPauseState(),
        ), patch(
            "engines.customer_support.support_status."
            "_ticket_tag_activity",
            return_value=(0, 0, 0),
        ):
            get_support_status(
                window_hours=24.0, store_id="store_a",
            )
        # store_id reached the refund_status call
        assert captured.get("store_id") == "store_a"


class TestTicketTagActivity:
    """The queue-reading helper handles missing API gracefully."""

    def test_queue_unavailable_returns_zeros(self):
        # Patch the import inside the helper
        with patch.dict(
            "sys.modules",
            {"core.approval.queue": None},
        ):
            total, applied, failed = _ticket_tag_activity(
                window_hours=24.0, store_id=None,
            )
        # When the import fails, returns (0, 0, 0)
        assert (total, applied, failed) == (0, 0, 0)
