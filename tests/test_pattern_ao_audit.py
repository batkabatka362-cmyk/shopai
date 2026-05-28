"""Tests for engines._pattern_ao_audit (Wave 338-340)."""
from __future__ import annotations

from engines._pattern_ao_audit import (
    PatternAOReport,
    PatternAOViolation,
    _DOMAIN_APPLIERS,
    _MIN_GATES,
    _count_gates,
    run_pattern_ao_audit,
)


class TestCatalog:

    def test_all_9_domains(self):
        assert set(_DOMAIN_APPLIERS.keys()) == {
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

    def test_floor_is_4(self):
        assert _MIN_GATES == 4

    def test_paths_end_with_applier_py(self):
        for path in _DOMAIN_APPLIERS.values():
            assert path.endswith("_applier.py"), path


class TestCountGates:

    def test_counts_numbered_items(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            '"""\n'
            "Module docstring.\n\n"
            "Safety gates:\n"
            "  1. first\n"
            "  2. second\n"
            "  3. third\n"
            '"""\n',
            encoding="utf-8",
        )
        assert _count_gates(src) == 3

    def test_zero_when_no_numbered_list(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            '"""Module docstring with no numbered list."""\n',
            encoding="utf-8",
        )
        assert _count_gates(src) == 0

    def test_zero_when_no_docstring(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "x = 1\n",
            encoding="utf-8",
        )
        assert _count_gates(src) == 0

    def test_missing_file_zero(self, tmp_path):
        assert _count_gates(tmp_path / "nope.py") == 0

    def test_broken_file_zero(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        assert _count_gates(src) == 0

    def test_counts_indented_numbered_items(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            '"""\n'
            "Doc with indented gates:\n\n"
            "      1. one\n"
            "      2. two\n"
            "      3. three\n"
            "      4. four\n"
            '"""\n',
            encoding="utf-8",
        )
        assert _count_gates(src) == 4


class TestRunPatternAOAudit:

    def test_returns_report(self):
        r = run_pattern_ao_audit()
        assert isinstance(r, PatternAOReport)

    def test_scans_all_9_domains(self):
        r = run_pattern_ao_audit()
        assert len(r.domains_scanned) == 8

    def test_live_passes(self):
        r = run_pattern_ao_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 8

    def test_gates_by_domain_populated(self):
        r = run_pattern_ao_audit()
        assert len(r.gates_by_domain) == 8
        for domain, n in r.gates_by_domain.items():
            assert n >= _MIN_GATES, (domain, n)


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternAOViolation(
            domain="x", applier_path="p.py",
        )
        assert v.gates_found == 0
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        r = PatternAOReport()
        assert not r.has_violations
        assert r.gates_by_domain == {}
