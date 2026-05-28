"""Tests for engines._pattern_af_audit (Wave 269-271)."""
from __future__ import annotations

from engines._pattern_af_audit import (
    PatternAFReport,
    PatternAFViolation,
    _DOMAIN_LOG_EXPORTS,
    _UNIVERSAL_EXPORT,
    _module_top_level_names,
    run_pattern_af_audit,
)


class TestCatalog:

    def test_all_8_domains(self):
        assert set(_DOMAIN_LOG_EXPORTS.keys()) == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
            "customer_outreach",
        }

    def test_universal_export_is_log_size(self):
        assert _UNIVERSAL_EXPORT == "log_size"

    def test_per_domain_record_fn_starts_with_record(self):
        for d, (_, record_fn, _) in _DOMAIN_LOG_EXPORTS.items():
            assert record_fn.startswith("record_"), (d, record_fn)

    def test_per_domain_recent_fn_starts_with_recent(self):
        for d, (_, _, recent_fn) in _DOMAIN_LOG_EXPORTS.items():
            assert recent_fn.startswith("recent_"), (d, recent_fn)


class TestModuleTopLevelNames:

    def test_collects_function_def(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def foo():\n    pass\n"
            "def bar():\n    pass\n",
            encoding="utf-8",
        )
        names = _module_top_level_names(src)
        assert names == {"foo", "bar"}

    def test_collects_assign(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "x = 1\ny: int = 2\n",
            encoding="utf-8",
        )
        names = _module_top_level_names(src)
        assert names == {"x", "y"}

    def test_skips_nested(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def outer():\n"
            "    def inner():\n        pass\n",
            encoding="utf-8",
        )
        assert _module_top_level_names(src) == {"outer"}

    def test_missing_file_none(self, tmp_path):
        assert _module_top_level_names(
            tmp_path / "nope.py",
        ) is None

    def test_broken_file_none(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        assert _module_top_level_names(src) is None


class TestRunPatternAFAudit:

    def test_returns_report(self):
        r = run_pattern_af_audit()
        assert isinstance(r, PatternAFReport)

    def test_scans_all_8_domains(self):
        r = run_pattern_af_audit()
        assert len(r.domains_scanned) == 8

    def test_live_passes(self):
        r = run_pattern_af_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 8


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternAFViolation(domain="x", module_path="p.py")
        assert v.missing_exports == []
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        assert not PatternAFReport().has_violations
