"""Tests for engines._pattern_yprime_audit (Wave 229-231)."""
from __future__ import annotations

from engines._pattern_yprime_audit import (
    PatternYPrimeReport,
    PatternYPrimeViolation,
    _DOMAIN_TEMPLATE,
    _TEMPLATE_ROLES,
    run_pattern_yprime_audit,
)


class TestDomainCatalog:

    def test_all_9_domains_present(self):
        assert set(_DOMAIN_TEMPLATE.keys()) == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
            "customer_outreach",
            "catalog_quality",
        }

    def test_every_domain_has_all_5_roles(self):
        for domain, (_, roles) in _DOMAIN_TEMPLATE.items():
            assert set(roles.keys()) == set(_TEMPLATE_ROLES), (
                domain
            )

    def test_every_filename_ends_with_py(self):
        for domain, (_, roles) in _DOMAIN_TEMPLATE.items():
            for role, fname in roles.items():
                assert fname.endswith(".py"), (
                    domain, role, fname,
                )

    def test_template_roles_count_is_5(self):
        assert len(_TEMPLATE_ROLES) == 5


class TestRunPatternYPrimeAudit:

    def test_returns_report(self):
        report = run_pattern_yprime_audit()
        assert isinstance(report, PatternYPrimeReport)

    def test_scans_all_9_domains(self):
        report = run_pattern_yprime_audit()
        assert len(report.domains_scanned) == 8

    def test_live_passes(self):
        report = run_pattern_yprime_audit()
        assert not report.has_violations, report.violations
        assert len(report.clean_domains) == 8


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternYPrimeViolation(domain="x")
        assert v.missing_roles == []
        assert v.package_dir == ""
        assert v.reason == ""

    def test_with_fields(self):
        v = PatternYPrimeViolation(
            domain="x",
            missing_roles=["log", "applier"],
            package_dir="engines/x",
            reason="2 role(s) missing",
        )
        assert v.missing_roles == ["log", "applier"]
        assert v.package_dir == "engines/x"


class TestReportDataclass:

    def test_empty_clean(self):
        assert not PatternYPrimeReport().has_violations

    def test_with_violation(self):
        r = PatternYPrimeReport()
        r.violations.append(PatternYPrimeViolation(domain="x"))
        assert r.has_violations
