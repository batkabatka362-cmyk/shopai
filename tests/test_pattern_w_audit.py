"""Tests for engines._pattern_w_audit (Wave 223-225)."""
from __future__ import annotations

from pathlib import Path

from engines._pattern_w_audit import (
    PatternWReport,
    PatternWViolation,
    _DOMAIN_HEALTH_MODULES,
    _module_references_prefix,
    run_pattern_w_audit,
)


class TestDomainCatalog:

    def test_all_7_domains_present(self):
        assert set(_DOMAIN_HEALTH_MODULES.keys()) == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
        }

    def test_every_domain_has_module_path_and_prefix(self):
        for domain, (path, prefix) in (
            _DOMAIN_HEALTH_MODULES.items()
        ):
            assert path.endswith(".py"), domain
            assert prefix.isupper(), domain
            assert prefix.replace("_", "").isalpha(), domain


class TestModuleReferencesPrefix:

    def test_exact_prefix_literal_matches(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "PREFIX = 'FULFILLMENT'\n", encoding="utf-8",
        )
        assert _module_references_prefix(src, "FULFILLMENT")

    def test_inline_env_var_matches(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "X = os.environ.get('SHOPAI_REFUND_MAX_AMOUNT')\n",
            encoding="utf-8",
        )
        assert _module_references_prefix(src, "REFUND")

    def test_plural_form_matches(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "Y = 'SHOPAI_AUTO_PAUSE_REFUNDS_ON_FAILURE'\n",
            encoding="utf-8",
        )
        assert _module_references_prefix(src, "REFUND")

    def test_unrelated_module_does_not_match(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "Z = 'SOMETHING_ELSE'\n", encoding="utf-8",
        )
        assert not _module_references_prefix(src, "REFUND")

    def test_missing_file_returns_false(self, tmp_path):
        missing = tmp_path / "nope.py"
        assert not _module_references_prefix(missing, "X")

    def test_unparseable_file_returns_false(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        assert not _module_references_prefix(src, "REFUND")


class TestRunPatternWAudit:

    def test_returns_report(self):
        report = run_pattern_w_audit()
        assert isinstance(report, PatternWReport)

    def test_scans_all_7_domains(self):
        report = run_pattern_w_audit()
        assert len(report.domains_scanned) == 7

    def test_live_passes(self):
        report = run_pattern_w_audit()
        assert not report.has_violations, report.violations
        assert len(report.clean_domains) == 7


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternWViolation(
            domain="x", expected_prefix="X",
        )
        assert v.reason == ""

    def test_reason_carried(self):
        v = PatternWViolation(
            domain="x",
            expected_prefix="X",
            reason="missing literal",
        )
        assert v.reason == "missing literal"


class TestReportDataclass:

    def test_empty_report_has_no_violations(self):
        r = PatternWReport()
        assert not r.has_violations

    def test_with_violation(self):
        r = PatternWReport()
        r.violations.append(PatternWViolation(
            domain="x", expected_prefix="X",
        ))
        assert r.has_violations
