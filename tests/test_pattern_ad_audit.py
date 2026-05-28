"""Tests for engines._pattern_ad_audit (Wave 256-258)."""
from __future__ import annotations

from engines._pattern_ad_audit import (
    PatternADReport,
    PatternADViolation,
    _DOMAIN_BRIDGE_EXPORTS,
    _module_defines_function,
    run_pattern_ad_audit,
)


class TestCatalog:

    def test_all_9_domains_present(self):
        assert set(_DOMAIN_BRIDGE_EXPORTS.keys()) == {
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

    def test_bridge_fn_names_use_maybe_auto_pause_prefix(self):
        for domain, (_, fn) in _DOMAIN_BRIDGE_EXPORTS.items():
            assert fn.startswith("maybe_auto_pause_"), (
                domain, fn,
            )


class TestModuleDefinesFunction:

    def test_finds_top_level_function(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def maybe_auto_pause_x():\n    return None\n",
            encoding="utf-8",
        )
        assert _module_defines_function(
            src, "maybe_auto_pause_x",
        )

    def test_misses_nested_function(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def outer():\n"
            "    def maybe_auto_pause_x():\n"
            "        return None\n",
            encoding="utf-8",
        )
        # Nested function -- intentionally NOT counted
        assert not _module_defines_function(
            src, "maybe_auto_pause_x",
        )

    def test_missing_file_false(self, tmp_path):
        assert not _module_defines_function(
            tmp_path / "nope.py", "x",
        )

    def test_broken_file_false(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        assert not _module_defines_function(src, "x")

    def test_imported_symbol_not_counted(self, tmp_path):
        """Pattern AD requires the function to be DEFINED in
        the module, not re-exported via ``from x import y``."""
        src = tmp_path / "fake.py"
        src.write_text(
            "from somewhere import maybe_auto_pause_x\n",
            encoding="utf-8",
        )
        assert not _module_defines_function(
            src, "maybe_auto_pause_x",
        )


class TestRunPatternADAudit:

    def test_returns_report(self):
        r = run_pattern_ad_audit()
        assert isinstance(r, PatternADReport)

    def test_scans_all_9_domains(self):
        r = run_pattern_ad_audit()
        assert len(r.domains_scanned) == 8

    def test_live_passes(self):
        r = run_pattern_ad_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 8


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternADViolation(
            domain="x",
            expected_function="maybe_auto_pause_x",
            module_path="engines/x/x_health.py",
        )
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        assert not PatternADReport().has_violations
