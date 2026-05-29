"""Tests for engines._pattern_ap_audit (Wave 353-357)."""
from __future__ import annotations

from engines._pattern_ap_audit import (
    PatternAPReport,
    PatternAPViolation,
    _DOMAIN_BRIDGES,
    _bridges_inside_try_blocks,
    _cycle_run_func,
    run_pattern_ap_audit,
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


class TestBridgesInsideTryBlocks:

    def test_call_inside_try_counted(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def _cmd_cycle_run():\n"
            "    try:\n"
            "        maybe_auto_pause_x()\n"
            "    except Exception:\n"
            "        pass\n",
            encoding="utf-8",
        )
        func = _cycle_run_func(src)
        inside = _bridges_inside_try_blocks(func)
        assert "maybe_auto_pause_x" in inside

    def test_call_outside_try_not_counted(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def _cmd_cycle_run():\n"
            "    maybe_auto_pause_x()\n",
            encoding="utf-8",
        )
        func = _cycle_run_func(src)
        inside = _bridges_inside_try_blocks(func)
        assert "maybe_auto_pause_x" not in inside

    def test_string_only_reference_not_counted(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def _cmd_cycle_run():\n"
            "    try:\n"
            "        s = 'maybe_auto_pause_x'\n"
            "    except Exception:\n"
            "        pass\n",
            encoding="utf-8",
        )
        func = _cycle_run_func(src)
        inside = _bridges_inside_try_blocks(func)
        assert "maybe_auto_pause_x" not in inside

    def test_multiple_bridges_in_separate_trys(self, tmp_path):
        src = tmp_path / "fake.py"
        src.write_text(
            "def _cmd_cycle_run():\n"
            "    try:\n"
            "        maybe_auto_pause_a()\n"
            "    except Exception:\n"
            "        pass\n"
            "    try:\n"
            "        maybe_auto_pause_b()\n"
            "    except Exception:\n"
            "        pass\n",
            encoding="utf-8",
        )
        func = _cycle_run_func(src)
        inside = _bridges_inside_try_blocks(func)
        assert "maybe_auto_pause_a" in inside
        assert "maybe_auto_pause_b" in inside


class TestRunPatternAPAudit:

    def test_returns_report(self):
        r = run_pattern_ap_audit()
        assert isinstance(r, PatternAPReport)

    def test_scans_all_10_domains(self):
        r = run_pattern_ap_audit()
        assert len(r.domains_scanned) == 10

    def test_live_passes(self):
        r = run_pattern_ap_audit()
        assert not r.has_violations, r.violations
        assert len(r.clean_domains) == 10

    def test_missing_cli_flags_all_domains(self, tmp_path):
        r = run_pattern_ap_audit(
            cli_path=tmp_path / "missing.py",
        )
        assert len(r.violations) == 10

    def test_unwrapped_bridge_flags_violation(self, tmp_path):
        """The whole point of AP: bridges OUTSIDE try blocks
        get flagged."""
        src = tmp_path / "fake_cli.py"
        # All 7 bridges invoked but ZERO wrapped in try
        bridges_calls = "\n    ".join(
            f"{fn}()"
            for fn in _DOMAIN_BRIDGES.values()
        )
        src.write_text(
            "def _cmd_cycle_run():\n    "
            + bridges_calls + "\n",
            encoding="utf-8",
        )
        r = run_pattern_ap_audit(cli_path=src)
        assert len(r.violations) == 10


class TestViolationDataclass:

    def test_defaults(self):
        v = PatternAPViolation(
            domain="x", bridge_name="maybe_auto_pause_x",
        )
        assert v.reason == ""


class TestReportDataclass:

    def test_empty_clean(self):
        assert not PatternAPReport().has_violations
