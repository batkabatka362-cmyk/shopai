"""Tests for engines._pattern_am_audit (Wave 322-324)."""
from __future__ import annotations

from engines._pattern_am_audit import (
    PatternAMReport,
    PatternAMViolation,
    _DOMAIN_TEST_KEYWORDS,
    _matching_test_files,
    run_pattern_am_audit,
)


class TestCatalog:

    def test_all_8_domains(self):
        assert set(_DOMAIN_TEST_KEYWORDS.keys()) == {
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
            "customer_outreach",
        }

    def test_every_domain_has_keywords(self):
        for d, kws in _DOMAIN_TEST_KEYWORDS.items():
            assert len(kws) >= 1, d


class TestMatchingTestFiles:

    def test_finds_keyword_match(self, tmp_path):
        (tmp_path / "test_foo_health.py").write_text("")
        (tmp_path / "test_other.py").write_text("")
        matches = _matching_test_files(tmp_path, ("foo",))
        assert "test_foo_health.py" in matches
        assert "test_other.py" not in matches

    def test_matches_any_keyword(self, tmp_path):
        (tmp_path / "test_alpha.py").write_text("")
        (tmp_path / "test_beta.py").write_text("")
        matches = _matching_test_files(
            tmp_path, ("alpha", "beta"),
        )
        assert "test_alpha.py" in matches
        assert "test_beta.py" in matches

    def test_skips_non_test_files(self, tmp_path):
        (tmp_path / "foo_test.py").write_text("")
        (tmp_path / "conftest.py").write_text("")
        matches = _matching_test_files(tmp_path, ("foo",))
        assert matches == []

    def test_skips_non_py_files(self, tmp_path):
        (tmp_path / "test_foo.txt").write_text("")
        matches = _matching_test_files(tmp_path, ("foo",))
        assert matches == []

    def test_missing_dir_returns_empty(self, tmp_path):
        matches = _matching_test_files(
            tmp_path / "nope", ("foo",),
        )
        assert matches == []

    def test_sorted_output(self, tmp_path):
        (tmp_path / "test_z_foo.py").write_text("")
        (tmp_path / "test_a_foo.py").write_text("")
        matches = _matching_test_files(tmp_path, ("foo",))
        assert matches == [
            "test_a_foo.py", "test_z_foo.py",
        ]


class TestRunPatternAMAudit:

    def test_returns_report(self):
        r = run_pattern_am_audit()
        assert isinstance(r, PatternAMReport)

    def test_scans_all_8_domains(self):
        r = run_pattern_am_audit()
        assert len(r.domains_scanned) == 8

    def test_live_passes(self):
        r = run_pattern_am_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 8

    def test_test_files_by_domain_populated(self):
        r = run_pattern_am_audit()
        for domain, files in r.test_files_by_domain.items():
            assert len(files) >= 1, (
                f"{domain} has zero test files"
            )

    def test_missing_dir_flags_all(self, tmp_path):
        r = run_pattern_am_audit(
            tests_dir=tmp_path / "nope",
        )
        assert len(r.violations) == 8


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternAMViolation(domain="x")
        assert v.keywords == ()
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        r = PatternAMReport()
        assert not r.has_violations
        assert r.test_files_by_domain == {}
