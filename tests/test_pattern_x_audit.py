"""Tests for engines._pattern_x_audit (Wave 226-228)."""
from __future__ import annotations

from pathlib import Path

from engines._pattern_x_audit import (
    PatternXReport,
    PatternXViolation,
    _DOMAIN_SUMMARY_FUNCS,
    _get_autonomy_status_body,
    _has_function_def,
    _parse_module,
    run_pattern_x_audit,
)


class TestDomainCatalog:

    def test_all_8_domains_present(self):
        assert set(_DOMAIN_SUMMARY_FUNCS.keys()) == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
            "customer_outreach",
        }

    def test_summary_func_names_match_convention(self):
        for domain, fn in _DOMAIN_SUMMARY_FUNCS.items():
            assert fn.startswith("_"), domain
            assert fn.endswith("_summary"), domain


class TestHelpers:

    def test_has_function_def_finds_present(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text("def my_func():\n    pass\n", encoding="utf-8")
        tree = _parse_module(src)
        assert tree is not None
        assert _has_function_def(tree, "my_func")
        assert not _has_function_def(tree, "absent")

    def test_get_autonomy_status_body_extracts(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def get_autonomy_status():\n"
            "    return _customer_support_summary()\n",
            encoding="utf-8",
        )
        tree = _parse_module(src)
        body = _get_autonomy_status_body(tree)
        assert body is not None
        assert "_customer_support_summary" in body

    def test_get_autonomy_status_body_absent_returns_none(
        self, tmp_path,
    ):
        src = tmp_path / "fake.py"
        src.write_text("def other(): pass\n", encoding="utf-8")
        tree = _parse_module(src)
        assert _get_autonomy_status_body(tree) is None

    def test_parse_module_missing_returns_none(self, tmp_path):
        assert _parse_module(tmp_path / "nope.py") is None

    def test_parse_module_broken_returns_none(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        assert _parse_module(src) is None


class TestRunPatternXAudit:

    def test_returns_report(self):
        report = run_pattern_x_audit()
        assert isinstance(report, PatternXReport)

    def test_scans_all_8_domains(self):
        report = run_pattern_x_audit()
        assert len(report.domains_scanned) == 8

    def test_live_passes(self):
        report = run_pattern_x_audit()
        assert not report.has_violations, report.violations
        assert len(report.clean_domains) == 8

    def test_missing_module_flags_every_domain(self, tmp_path):
        report = run_pattern_x_audit(
            autonomy_status_path=tmp_path / "missing.py",
        )
        assert report.has_violations
        assert len(report.violations) == 8

    def test_module_with_no_summary_funcs_flags_all(
        self, tmp_path,
    ):
        src = tmp_path / "stub.py"
        src.write_text(
            "def get_autonomy_status():\n    pass\n",
            encoding="utf-8",
        )
        report = run_pattern_x_audit(autonomy_status_path=src)
        assert len(report.violations) == 8
        for v in report.violations:
            assert "not defined" in v.reason

    def test_module_with_defs_but_no_invocations_flags(
        self, tmp_path,
    ):
        src = tmp_path / "stub.py"
        funcs = "\n".join(
            f"def {fn}():\n    pass\n"
            for fn in _DOMAIN_SUMMARY_FUNCS.values()
        )
        src.write_text(
            funcs + "\ndef get_autonomy_status():\n    pass\n",
            encoding="utf-8",
        )
        report = run_pattern_x_audit(autonomy_status_path=src)
        assert len(report.violations) == 8
        for v in report.violations:
            assert "not invoked" in v.reason


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternXViolation(
            domain="x", expected_func="_x_summary",
        )
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_report_clean(self):
        assert not PatternXReport().has_violations
