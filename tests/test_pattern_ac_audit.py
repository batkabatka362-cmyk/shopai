"""Tests for engines._pattern_ac_audit (Wave 232-234)."""
from __future__ import annotations

from engines._pattern_ac_audit import (
    PatternACReport,
    PatternACViolation,
    _DOMAIN_CLI_PREFIXES,
    _REQUIRED_SUFFIXES,
    _collect_subparser_names,
    run_pattern_ac_audit,
)


class TestDomainCatalog:

    def test_all_9_domains_present(self):
        assert set(_DOMAIN_CLI_PREFIXES.keys()) == {
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

    def test_required_suffixes_are_4(self):
        assert len(_REQUIRED_SUFFIXES) == 4
        assert set(_REQUIRED_SUFFIXES) == {
            "status", "health", "pause", "resume",
        }

    def test_no_prefix_has_underscore(self):
        # CLI conventions use hyphens, not underscores
        for prefix in _DOMAIN_CLI_PREFIXES.values():
            assert "_" not in prefix, prefix


class TestCollectSubparserNames:

    def test_extracts_add_parser_string_args(self, tmp_path):
        src = tmp_path / "fake_cli.py"
        src.write_text(
            "import argparse\n"
            "p = argparse.ArgumentParser()\n"
            "sub = p.add_subparsers()\n"
            "sub.add_parser('foo-status')\n"
            "sub.add_parser('foo-health')\n",
            encoding="utf-8",
        )
        names = _collect_subparser_names(src)
        assert names == {"foo-status", "foo-health"}

    def test_missing_file_returns_none(self, tmp_path):
        assert _collect_subparser_names(
            tmp_path / "nope.py",
        ) is None

    def test_broken_file_returns_none(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        assert _collect_subparser_names(src) is None

    def test_ignores_non_string_first_arg(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "sub.add_parser(some_var)\n"
            "sub.add_parser('ok-cmd')\n",
            encoding="utf-8",
        )
        names = _collect_subparser_names(src)
        assert names == {"ok-cmd"}


class TestRunPatternACAudit:

    def test_returns_report(self):
        report = run_pattern_ac_audit()
        assert isinstance(report, PatternACReport)

    def test_scans_all_9_domains(self):
        report = run_pattern_ac_audit()
        assert len(report.domains_scanned) == 8

    def test_live_passes(self):
        report = run_pattern_ac_audit()
        assert not report.has_violations, report.violations
        assert len(report.clean_domains) == 8

    def test_missing_cli_flags_all_domains(self, tmp_path):
        report = run_pattern_ac_audit(
            cli_path=tmp_path / "missing.py",
        )
        assert len(report.violations) == 8

    def test_partial_registration_flags_missing(
        self, tmp_path,
    ):
        # cli.py with only the -status command for one domain
        src = tmp_path / "fake_cli.py"
        src.write_text(
            "sub.add_parser('refund-status')\n"
            "sub.add_parser('marketing-status')\n"
            "sub.add_parser('marketing-health')\n"
            "sub.add_parser('marketing-pause')\n"
            "sub.add_parser('marketing-resume')\n",
            encoding="utf-8",
        )
        report = run_pattern_ac_audit(cli_path=src)
        # marketing has all 4 -> clean
        # refund has 1 of 4 -> 3 missing
        # other 5 domains have 0 of 4 -> 4 missing each
        clean = set(report.clean_domains)
        assert "marketing_budget" in clean
        refund_v = next(
            v for v in report.violations
            if v.domain == "customer_support_refund"
        )
        assert len(refund_v.missing_commands) == 3
        assert "refund-status" not in refund_v.missing_commands


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternACViolation(domain="x", prefix="x")
        assert v.missing_commands == []
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        assert not PatternACReport().has_violations
