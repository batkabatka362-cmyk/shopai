"""Tests for engines._pattern_ae_audit (Wave 261-263)."""
from __future__ import annotations

from engines._pattern_ae_audit import (
    PatternAEReport,
    PatternAEViolation,
    _DOMAIN_STATE_MODULES,
    _EXPECTED_SYMBOL,
    _module_exports_symbol,
    run_pattern_ae_audit,
)


class TestCatalog:

    def test_all_10_domains(self):
        assert set(_DOMAIN_STATE_MODULES.keys()) == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
            "customer_outreach",
            "catalog_quality",
            "shipping_alert",
        }

    def test_paths_end_with_state_py(self):
        for path in _DOMAIN_STATE_MODULES.values():
            assert path.endswith("_state.py"), path

    def test_expected_symbol(self):
        assert _EXPECTED_SYMBOL == "is_paused"


class TestModuleExportsSymbol:

    def test_function_def_form(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def is_paused():\n    return False\n",
            encoding="utf-8",
        )
        assert _module_exports_symbol(src, "is_paused")

    def test_assign_form(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "from somewhere import f\n"
            "is_paused = f\n",
            encoding="utf-8",
        )
        assert _module_exports_symbol(src, "is_paused")

    def test_ann_assign_form(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "from typing import Callable\n"
            "is_paused: Callable = lambda: False\n",
            encoding="utf-8",
        )
        assert _module_exports_symbol(src, "is_paused")

    def test_missing_symbol(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def other_function():\n    pass\n",
            encoding="utf-8",
        )
        assert not _module_exports_symbol(src, "is_paused")

    def test_nested_function_not_counted(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def outer():\n"
            "    def is_paused():\n        return False\n",
            encoding="utf-8",
        )
        # Nested function -- intentionally NOT counted
        assert not _module_exports_symbol(src, "is_paused")

    def test_missing_file_false(self, tmp_path):
        assert not _module_exports_symbol(
            tmp_path / "nope.py", "is_paused",
        )

    def test_broken_file_false(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        assert not _module_exports_symbol(src, "is_paused")


class TestRunPatternAEAudit:

    def test_returns_report(self):
        r = run_pattern_ae_audit()
        assert isinstance(r, PatternAEReport)

    def test_scans_all_10_domains(self):
        r = run_pattern_ae_audit()
        assert len(r.domains_scanned) == 10

    def test_live_passes(self):
        r = run_pattern_ae_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 10


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternAEViolation(domain="x", module_path="p.py")
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        assert not PatternAEReport().has_violations
