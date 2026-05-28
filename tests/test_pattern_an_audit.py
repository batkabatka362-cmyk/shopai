"""Tests for engines._pattern_an_audit (Wave 327-329)."""
from __future__ import annotations

from engines._pattern_an_audit import (
    PatternANReport,
    PatternANViolation,
    _DOMAIN_ENGINE_NAMES,
    _extract_engine_constant,
    run_pattern_an_audit,
)


class TestCatalog:

    def test_all_7_domains(self):
        assert set(_DOMAIN_ENGINE_NAMES.keys()) == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
        }

    def test_all_engine_values_non_empty(self):
        for d, (_, eng) in _DOMAIN_ENGINE_NAMES.items():
            assert eng, d


class TestExtractEngineConstant:

    def test_finds_simple_constant(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "_ENGINE = 'returns_management'\n"
            "def apply():\n"
            "    record_writeback(engine=_ENGINE)\n",
            encoding="utf-8",
        )
        value, used = _extract_engine_constant(src)
        assert value == "returns_management"
        assert used

    def test_constant_only_no_usage(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "_ENGINE = 'x'\n"
            "def apply():\n"
            "    record_writeback(engine='hardcoded')\n",
            encoding="utf-8",
        )
        value, used = _extract_engine_constant(src)
        assert value == "x"
        assert not used

    def test_missing_constant(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def apply():\n    record_writeback()\n",
            encoding="utf-8",
        )
        value, used = _extract_engine_constant(src)
        assert value is None
        assert not used

    def test_missing_file(self, tmp_path):
        value, used = _extract_engine_constant(
            tmp_path / "nope.py",
        )
        assert value is None
        assert not used

    def test_broken_file(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        value, used = _extract_engine_constant(src)
        assert value is None
        assert not used

    def test_attribute_callee_recognized(self, tmp_path):
        """``recorder.record_writeback(engine=_ENGINE)`` should
        still register as used."""
        src = tmp_path / "fake.py"
        src.write_text(
            "_ENGINE = 'foo'\n"
            "def apply():\n"
            "    recorder.record_writeback(engine=_ENGINE)\n",
            encoding="utf-8",
        )
        value, used = _extract_engine_constant(src)
        assert used


class TestRunPatternANAudit:

    def test_returns_report(self):
        r = run_pattern_an_audit()
        assert isinstance(r, PatternANReport)

    def test_scans_all_7_domains(self):
        r = run_pattern_an_audit()
        assert len(r.domains_scanned) == 7

    def test_live_passes(self):
        r = run_pattern_an_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 7


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternANViolation(
            domain="x", expected_engine="y",
        )
        assert v.actual_engine == ""
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        assert not PatternANReport().has_violations
