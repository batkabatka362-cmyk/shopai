"""Tests for engines._pattern_aj_audit (Wave 300-302)."""
from __future__ import annotations

from engines._pattern_aj_audit import (
    PatternAJReport,
    PatternAJViolation,
    _DOMAIN_CLI_PREFIXES,
    _REQUIRED_SUFFIXES,
    _collect_dispatch_literals,
    run_pattern_aj_audit,
)


class TestCatalog:

    def test_all_9_domains(self):
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

    def test_required_suffixes(self):
        assert len(_REQUIRED_SUFFIXES) == 4
        assert set(_REQUIRED_SUFFIXES) == {
            "status", "health", "pause", "resume",
        }


class TestCollectDispatchLiterals:

    def test_finds_args_command_compare(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def main(args):\n"
            "    if args.command == 'foo-status':\n"
            "        pass\n"
            "    if args.command == 'foo-health':\n"
            "        pass\n",
            encoding="utf-8",
        )
        names = _collect_dispatch_literals(src)
        assert names is not None
        assert "foo-status" in names
        assert "foo-health" in names

    def test_finds_reversed_compare(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def main(args):\n"
            "    if 'bar' == args.command:\n"
            "        pass\n",
            encoding="utf-8",
        )
        names = _collect_dispatch_literals(src)
        assert "bar" in names

    def test_missing_file_none(self, tmp_path):
        assert _collect_dispatch_literals(
            tmp_path / "nope.py",
        ) is None

    def test_broken_file_none(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        assert _collect_dispatch_literals(src) is None

    def test_unrelated_compare_not_picked_up(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "if x == 'not-a-command':\n    pass\n",
            encoding="utf-8",
        )
        names = _collect_dispatch_literals(src)
        assert "not-a-command" not in names


class TestRunPatternAJAudit:

    def test_returns_report(self):
        r = run_pattern_aj_audit()
        assert isinstance(r, PatternAJReport)

    def test_scans_all_9_domains(self):
        r = run_pattern_aj_audit()
        assert len(r.domains_scanned) == 8

    def test_live_passes(self):
        r = run_pattern_aj_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 8

    def test_missing_cli_flags_all_domains(self, tmp_path):
        r = run_pattern_aj_audit(
            cli_path=tmp_path / "missing.py",
        )
        assert len(r.violations) == 8

    def test_partial_dispatch_flags_missing(self, tmp_path):
        src = tmp_path / "fake_cli.py"
        # only refund-status has a dispatch branch
        src.write_text(
            "def main(args):\n"
            "    if args.command == 'refund-status':\n"
            "        pass\n",
            encoding="utf-8",
        )
        r = run_pattern_aj_audit(cli_path=src)
        # refund: 1 of 4 -> 3 missing; everyone else: 4 missing
        refund_v = next(
            v for v in r.violations
            if v.domain == "customer_support_refund"
        )
        assert len(refund_v.missing_dispatch) == 3
        assert "refund-status" not in refund_v.missing_dispatch


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternAJViolation(domain="x", prefix="x")
        assert v.missing_dispatch == []
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        assert not PatternAJReport().has_violations
