"""Tests for engines._pattern_ai_audit (Wave 286-288)."""
from __future__ import annotations

from engines._pattern_ai_audit import (
    PatternAIReport,
    PatternAIViolation,
    _DOMAIN_STATUS_EXPORTS,
    _has_top_level_function,
    run_pattern_ai_audit,
)


class TestCatalog:

    def test_all_7_domains(self):
        assert set(_DOMAIN_STATUS_EXPORTS.keys()) == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
        }

    def test_status_fn_names_follow_convention(self):
        for d, (_, fn) in _DOMAIN_STATUS_EXPORTS.items():
            assert fn.startswith("get_"), (d, fn)
            assert fn.endswith("_status"), (d, fn)

    def test_paths_end_with_status_py(self):
        for path, _ in _DOMAIN_STATUS_EXPORTS.values():
            assert path.endswith("_status.py"), path


class TestHasTopLevelFunction:

    def test_finds_top_level(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def get_x_status():\n    return {}\n",
            encoding="utf-8",
        )
        assert _has_top_level_function(src, "get_x_status")

    def test_misses_nested(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def outer():\n"
            "    def get_x_status():\n        pass\n",
            encoding="utf-8",
        )
        assert not _has_top_level_function(
            src, "get_x_status",
        )

    def test_misses_assign_alias(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "from somewhere import f\n"
            "get_x_status = f\n",
            encoding="utf-8",
        )
        # Strict: Assign aliases not counted
        assert not _has_top_level_function(
            src, "get_x_status",
        )

    def test_missing_file_false(self, tmp_path):
        assert not _has_top_level_function(
            tmp_path / "nope.py", "get_x_status",
        )

    def test_broken_file_false(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        assert not _has_top_level_function(
            src, "get_x_status",
        )


class TestRunPatternAIAudit:

    def test_returns_report(self):
        r = run_pattern_ai_audit()
        assert isinstance(r, PatternAIReport)

    def test_scans_all_7_domains(self):
        r = run_pattern_ai_audit()
        assert len(r.domains_scanned) == 7

    def test_live_passes(self):
        r = run_pattern_ai_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 7


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternAIViolation(
            domain="x",
            module_path="p.py",
            expected_function="get_x_status",
        )
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        assert not PatternAIReport().has_violations
