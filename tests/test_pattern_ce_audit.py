"""W963-155: Pattern CE audit tests."""
from __future__ import annotations

import pytest

from engines._pattern_ce_audit import (
    PatternCEReport,
    audit_vendor_handler_parity,
)


class TestRuns:
    def test_audit_runs_clean(self):
        report = audit_vendor_handler_parity()
        # All 7 current vendor handlers must register
        # cleanly. If a future commit adds an 8th handler
        # without wiring, this fails.
        assert isinstance(report, PatternCEReport)
        if report.has_violations:
            details = "\n".join(
                f"  {v.handler_class}: "
                f"{', '.join(v.missing)}"
                for v in report.violations
            )
            pytest.fail(
                f"Pattern CE clean expected, found "
                f"{len(report.violations)} violation(s):\n"
                f"{details}"
            )
        # Sanity: at least the 7 known handlers
        assert len(report.vendors_checked) >= 7

    def test_known_handlers_present(self):
        report = audit_vendor_handler_parity()
        expected = {
            "AfterShipVendorHandler",
            "GA4VendorHandler",
            "GorgiasVendorHandler",
            "KlarnaVendorHandler",
            "KlaviyoVendorHandler",
            "LooxVendorHandler",
            "PayPalVendorHandler",
            "StripeVendorHandler",
        }
        assert expected <= set(report.vendors_checked)
