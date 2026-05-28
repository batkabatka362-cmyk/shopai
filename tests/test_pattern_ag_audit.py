"""Tests for engines._pattern_ag_audit (Wave 273-275)."""
from __future__ import annotations

from engines._pattern_ag_audit import (
    PatternAGReport,
    PatternAGViolation,
    _DOMAIN_ANALYZE_EXPORTS,
    _module_exports_callable,
    run_pattern_ag_audit,
)


class TestCatalog:

    def test_all_8_domains(self):
        assert set(_DOMAIN_ANALYZE_EXPORTS.keys()) == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
            "customer_outreach",
        }

    def test_analyze_fn_names_follow_convention(self):
        for d, (_, fn) in _DOMAIN_ANALYZE_EXPORTS.items():
            assert fn.startswith("analyze_"), (d, fn)
            assert fn.endswith("_health"), (d, fn)


class TestModuleExportsCallable:

    def test_function_def(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def analyze_x_health():\n    return None\n",
            encoding="utf-8",
        )
        assert _module_exports_callable(
            src, "analyze_x_health",
        )

    def test_assign(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "from somewhere import f\n"
            "analyze_x_health = f\n",
            encoding="utf-8",
        )
        assert _module_exports_callable(
            src, "analyze_x_health",
        )

    def test_ann_assign(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "from typing import Callable\n"
            "analyze_x_health: Callable = lambda: None\n",
            encoding="utf-8",
        )
        assert _module_exports_callable(
            src, "analyze_x_health",
        )

    def test_nested_not_counted(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def outer():\n"
            "    def analyze_x_health():\n        pass\n",
            encoding="utf-8",
        )
        assert not _module_exports_callable(
            src, "analyze_x_health",
        )

    def test_missing_file_false(self, tmp_path):
        assert not _module_exports_callable(
            tmp_path / "nope.py", "analyze_x_health",
        )

    def test_broken_file_false(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        assert not _module_exports_callable(
            src, "analyze_x_health",
        )

    def test_different_name_not_counted(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def some_other_function():\n    pass\n",
            encoding="utf-8",
        )
        assert not _module_exports_callable(
            src, "analyze_x_health",
        )


class TestRunPatternAGAudit:

    def test_returns_report(self):
        r = run_pattern_ag_audit()
        assert isinstance(r, PatternAGReport)

    def test_scans_all_8_domains(self):
        r = run_pattern_ag_audit()
        assert len(r.domains_scanned) == 8

    def test_live_passes(self):
        r = run_pattern_ag_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 8


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternAGViolation(
            domain="x",
            module_path="p.py",
            expected_function="analyze_x_health",
        )
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        assert not PatternAGReport().has_violations
