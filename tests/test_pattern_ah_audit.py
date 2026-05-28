"""Tests for engines._pattern_ah_audit (Wave 277-279)."""
from __future__ import annotations

from engines._pattern_ah_audit import (
    PatternAHReport,
    PatternAHViolation,
    _DOMAIN_APPLY_EXPORTS,
    _has_top_level_function,
    run_pattern_ah_audit,
)


class TestCatalog:

    def test_all_7_domains(self):
        assert set(_DOMAIN_APPLY_EXPORTS.keys()) == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
        }

    def test_apply_fn_names_start_with_apply(self):
        for d, (_, fn) in _DOMAIN_APPLY_EXPORTS.items():
            assert fn.startswith("apply_"), (d, fn)


class TestHasTopLevelFunction:

    def test_finds_top_level(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def apply_x():\n    return []\n",
            encoding="utf-8",
        )
        assert _has_top_level_function(src, "apply_x")

    def test_misses_nested(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def outer():\n"
            "    def apply_x():\n        pass\n",
            encoding="utf-8",
        )
        assert not _has_top_level_function(src, "apply_x")

    def test_misses_assign_alias(self, tmp_path):
        """Pattern AH is strict: only FunctionDef counts.
        Aliases via Assign won't be importable via from-import
        in some edge cases."""
        src = tmp_path / "fake.py"
        src.write_text(
            "from somewhere import f\n"
            "apply_x = f\n",
            encoding="utf-8",
        )
        assert not _has_top_level_function(src, "apply_x")

    def test_missing_file_false(self, tmp_path):
        assert not _has_top_level_function(
            tmp_path / "nope.py", "apply_x",
        )

    def test_broken_file_false(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        assert not _has_top_level_function(src, "apply_x")


class TestRunPatternAHAudit:

    def test_returns_report(self):
        r = run_pattern_ah_audit()
        assert isinstance(r, PatternAHReport)

    def test_scans_all_7_domains(self):
        r = run_pattern_ah_audit()
        assert len(r.domains_scanned) == 7

    def test_live_passes(self):
        r = run_pattern_ah_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 7


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternAHViolation(
            domain="x",
            module_path="p.py",
            expected_function="apply_x",
        )
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        assert not PatternAHReport().has_violations
