"""Tests for engines._pattern_o_audit (Wave 122)."""
from __future__ import annotations

from pathlib import Path

from engines._pattern_o_audit import (
    PatternOReport,
    PatternOViolation,
    _has_apply_gate,
    run_pattern_o_audit,
)


class TestHasApplyGate:

    def test_detects_data_get_apply_x_call(self, tmp_path):
        """The AST scanner must catch
        ``data.get("apply_refunds")`` regardless of comparison
        form."""
        src = (
            "def flow(input_data):\n"
            "    data = input_data['data']\n"
            "    if data.get('apply_refunds') is True:\n"
            "        pass\n"
        )
        p = tmp_path / "fake_flow.py"
        p.write_text(src, encoding="utf-8")
        assert _has_apply_gate(p) is True

    def test_no_apply_call_returns_false(self, tmp_path):
        src = (
            "def flow():\n"
            "    return 42\n"
        )
        p = tmp_path / "fake.py"
        p.write_text(src, encoding="utf-8")
        assert _has_apply_gate(p) is False

    def test_other_get_calls_not_apply_dont_match(
        self, tmp_path,
    ):
        src = (
            "def flow():\n"
            "    val = data.get('something_else')\n"
        )
        p = tmp_path / "fake.py"
        p.write_text(src, encoding="utf-8")
        assert _has_apply_gate(p) is False

    def test_syntax_error_returns_false(self, tmp_path):
        src = "def f(\n   # missing close paren\n"
        p = tmp_path / "broken.py"
        p.write_text(src, encoding="utf-8")
        assert _has_apply_gate(p) is False


class TestPatternOAuditLive:
    """Audit must pass on the current codebase."""

    def test_audit_finds_no_violations(self):
        report = run_pattern_o_audit()
        assert isinstance(report, PatternOReport)
        assert report.has_violations is False, (
            f"Pattern O regression: "
            f"{[(v.engine, v.writer_module) for v in report.violations]}"
        )

    def test_scans_known_wired_engines(self):
        report = run_pattern_o_audit()
        # Known wired engines from Wave 6/7 onward
        scanned = set(report.scanned_engines)
        for engine in (
            "loyalty", "dynamic_pricing", "returns_management",
            "customer_support",
        ):
            assert engine in scanned, (
                f"{engine} expected in scanned list"
            )


class TestViolationDataclass:

    def test_report_has_violations_property(self):
        r = PatternOReport()
        assert r.has_violations is False
        r.violations.append(PatternOViolation(
            engine="x", writer_module="x/y.py", reason="...",
        ))
        assert r.has_violations is True


class TestExemptionList:
    """Legitimate exemptions don't show up as violations."""

    def test_store_setup_writers_exempt(self):
        report = run_pattern_o_audit()
        # store_setup/page_applier + policy_applier are called
        # from launch_orchestrator, not gated via flow.py
        violation_paths = {
            v.writer_module for v in report.violations
        }
        assert (
            "store_setup/page_applier.py"
            not in violation_paths
        )
        assert (
            "store_setup/policy_applier.py"
            not in violation_paths
        )
