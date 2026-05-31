"""Tests for engines._pattern_qprime_audit (Wave 160)."""
from __future__ import annotations

from engines._pattern_qprime_audit import (
    PatternQPrimeReport,
    PatternQPrimeViolation,
    _CANONICAL_FIELDS,
    run_pattern_qprime_audit,
)


class TestPatternQPrimeLive:

    def test_audit_passes_on_current_codebase(self):
        report = run_pattern_qprime_audit()
        assert isinstance(report, PatternQPrimeReport)
        assert report.has_violations is False, (
            f"Pattern Q' regression: "
            f"{[(v.domain, v.missing_fields) for v in report.violations]}"
        )

    def test_probes_all_10_known_domains(self):
        """W937 bugfix: probe expanded from 7 to 10 domains
        (customer_outreach, catalog_quality, shipping_alert
        were previously silently skipped via getattr None)."""
        report = run_pattern_qprime_audit()
        assert set(report.domains_probed) == {
            "customer_support", "marketing",
            "fulfillment", "inventory",
            "discount_cleanup", "order_followup",
            "product_seo", "customer_outreach",
            "catalog_quality", "shipping_alert",
        }

    def test_canonical_fields_match_DomainSummary(self):
        """The canonical field set should match DomainSummary's
        fields (apart from internal __ defaults)."""
        from dataclasses import fields
        from core.automation.autonomy_status import (
            DomainSummary,
        )
        dsf = {f.name for f in fields(DomainSummary)}
        # Every canonical field must exist on DomainSummary
        for field_name in _CANONICAL_FIELDS:
            assert field_name in dsf, (
                f"_CANONICAL_FIELDS includes '{field_name}' "
                f"but DomainSummary doesn't have it"
            )


class TestPatternQPrimeReport:

    def test_report_has_violations_property(self):
        r = PatternQPrimeReport()
        assert r.has_violations is False
        r.violations.append(PatternQPrimeViolation(
            domain="foo", missing_fields=["verdict"],
        ))
        assert r.has_violations is True

    def test_violation_dataclass_defaults(self):
        v = PatternQPrimeViolation(domain="foo")
        assert v.missing_fields == []
        assert v.error == ""
