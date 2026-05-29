"""Tests for engines._pattern_ak_audit (Wave 308-310)."""
from __future__ import annotations

from engines._pattern_ak_audit import (
    PatternAKReport,
    PatternAKViolation,
    _DOMAIN_BRIDGES,
    _cycle_run_func,
    _has_invocation,
    run_pattern_ak_audit,
)


class TestCatalog:

    def test_all_10_domains(self):
        assert set(_DOMAIN_BRIDGES.keys()) == {
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

    def test_bridge_names_use_maybe_auto_pause_prefix(self):
        for d, fn in _DOMAIN_BRIDGES.items():
            assert fn.startswith("maybe_auto_pause_"), (d, fn)


class TestCycleRunFunc:

    def test_finds_function(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def _cmd_cycle_run(args):\n    pass\n",
            encoding="utf-8",
        )
        f = _cycle_run_func(src)
        assert f is not None
        assert f.name == "_cmd_cycle_run"

    def test_missing_file_none(self, tmp_path):
        assert _cycle_run_func(tmp_path / "nope.py") is None

    def test_broken_file_none(self, tmp_path):
        src = tmp_path / "broken.py"
        src.write_text("def: oops\n", encoding="utf-8")
        assert _cycle_run_func(src) is None

    def test_no_cycle_run_returns_none(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def other_func():\n    pass\n",
            encoding="utf-8",
        )
        assert _cycle_run_func(src) is None


class TestHasInvocation:

    def test_direct_call(self, tmp_path):
        import ast
        src = tmp_path / "fake.py"
        src.write_text(
            "def _cmd_cycle_run():\n"
            "    maybe_auto_pause_x()\n",
            encoding="utf-8",
        )
        f = _cycle_run_func(src)
        assert _has_invocation(f, "maybe_auto_pause_x")

    def test_string_only_reference_not_invocation(
        self, tmp_path,
    ):
        src = tmp_path / "fake.py"
        src.write_text(
            "def _cmd_cycle_run():\n"
            "    '''docstring mentions maybe_auto_pause_x'''\n"
            "    s = 'maybe_auto_pause_x'\n",
            encoding="utf-8",
        )
        f = _cycle_run_func(src)
        # Symbol referenced but never invoked
        assert not _has_invocation(f, "maybe_auto_pause_x")

    def test_unrelated_call_not_counted(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def _cmd_cycle_run():\n"
            "    something_else()\n",
            encoding="utf-8",
        )
        f = _cycle_run_func(src)
        assert not _has_invocation(f, "maybe_auto_pause_x")

    def test_nested_call_counted(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def _cmd_cycle_run():\n"
            "    try:\n"
            "        maybe_auto_pause_x()\n"
            "    except Exception:\n"
            "        pass\n",
            encoding="utf-8",
        )
        f = _cycle_run_func(src)
        assert _has_invocation(f, "maybe_auto_pause_x")


class TestRunPatternAKAudit:

    def test_returns_report(self):
        r = run_pattern_ak_audit()
        assert isinstance(r, PatternAKReport)

    def test_scans_all_10_domains(self):
        r = run_pattern_ak_audit()
        assert len(r.domains_scanned) == 10

    def test_live_passes(self):
        r = run_pattern_ak_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 10

    def test_missing_cli_flags_all_domains(self, tmp_path):
        r = run_pattern_ak_audit(
            cli_path=tmp_path / "missing.py",
        )
        assert len(r.violations) == 10

    def test_string_only_references_caught_as_violations(
        self, tmp_path,
    ):
        """The whole point of AK over U: string-only mentions
        should flag as violations."""
        src = tmp_path / "fake_cli.py"
        # cycle_run mentions all 7 bridges as strings only
        all_bridges = "\n    ".join(
            f"s = '{fn}'"
            for fn in _DOMAIN_BRIDGES.values()
        )
        src.write_text(
            "def _cmd_cycle_run():\n    " + all_bridges + "\n",
            encoding="utf-8",
        )
        r = run_pattern_ak_audit(cli_path=src)
        # All 7 bridges referenced as strings, none called
        assert len(r.violations) == 10


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternAKViolation(
            domain="x", bridge_name="maybe_auto_pause_x",
        )
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        assert not PatternAKReport().has_violations
