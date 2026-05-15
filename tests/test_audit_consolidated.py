"""Tests for ``shopai audit`` -- the consolidated audit command
that runs all five institutional gates in one shot.

Verifies:
  - Default mode runs every audit + a unified verdict
  - --only NAME restricts to one audit
  - --json emits a structured envelope
  - A failure in any audit flips overall_ok to False + exits 1
  - Module exceptions in one audit don't crash the others
  - All five named audits are runnable individually
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(json=False, only=None)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Default mode ─────────────────────────────────────────────


class TestDefaultMode:

    def test_runs_all_five_audits(self, cli):
        out, code = _capture(cli._cmd_audit_all, _ns())
        assert code == 0
        # All five labels appear
        assert "Pattern K" in out
        assert "OAuth scope" in out
        assert "Pattern Y" in out
        assert "Pattern I" in out
        assert "Pattern J" in out
        assert "Audit OK" in out

    def test_unified_verdict_on_pass(self, cli):
        out, code = _capture(cli._cmd_audit_all, _ns())
        assert code == 0
        # Each audit shows [pass] (7 audits total)
        passes = out.count("[pass]")
        assert passes == 7


# ─── --only NAME ──────────────────────────────────────────────


class TestOnly:

    @pytest.mark.parametrize("audit_name", [
        "pattern_k", "oauth", "pattern_y",
        "pattern_i", "pattern_j",
    ])
    def test_each_audit_runs_individually(self, cli, audit_name):
        out, code = _capture(
            cli._cmd_audit_all, _ns(only=audit_name),
        )
        assert code == 0
        # Only one [pass] line because only one audit ran
        assert out.count("[pass]") == 1
        # Single-audit verdict line
        assert audit_name in out

    def test_unknown_audit_name_caught_by_argparse(self, cli):
        # argparse rejects bad --only values before _cmd is
        # called; the function itself doesn't need to validate.
        # But _run_one_audit is defensive; this test confirms
        # the helper's fallback.
        result = cli._run_one_audit("not_a_real_audit")
        assert result["ok"] is False
        assert "unknown audit" in result["error"]


# ─── JSON envelope ────────────────────────────────────────────


class TestJson:

    def test_json_emits_structured_envelope(self, cli):
        out, code = _capture(cli._cmd_audit_all, _ns(json=True))
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert set(data["audits"].keys()) == {
            "pattern_k", "oauth", "pattern_y",
            "pattern_i", "pattern_j", "pattern_z",
            "pattern_q",
        }
        # Each audit has at least an ok field
        for audit in data["audits"].values():
            assert "ok" in audit

    def test_json_only_filter_emits_one_audit(self, cli):
        out, _ = _capture(
            cli._cmd_audit_all, _ns(json=True, only="pattern_k"),
        )
        data = json.loads(out)
        assert set(data["audits"].keys()) == {"pattern_k"}


# ─── Failure propagation ──────────────────────────────────────


class TestFailurePropagation:

    def test_pattern_k_failure_flips_overall(self, cli):
        from core.approval.coverage_audit import AuditReport
        bad = AuditReport(
            enqueued=[],
            registered=[],
            missing={"missing_action"},
            orphaned=set(),
        )
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            return_value=bad,
        ):
            out, code = _capture(cli._cmd_audit_all, _ns())
        assert code == 1
        assert "Audit FAILED" in out
        # The failing audit's label surfaces in the summary
        assert "Pattern K" in out

    def test_pattern_j_failure_flips_overall(self, cli):
        from engines._pattern_j_audit import (
            PatternJReport,
            WriteSite,
        )
        bad = PatternJReport(
            recorder_sites=[],
            guarded_sites=[],
            unguarded_sites=[
                WriteSite(
                    file="engines/x/flow.py",
                    lineno=42,
                    method="create_from_decision",
                    receiver_expr="mi",
                    module_path="/abs/x/flow.py",
                ),
            ],
            scanned_modules=10,
        )
        with patch(
            "engines._pattern_j_audit.audit_pattern_j",
            return_value=bad,
        ):
            out, code = _capture(cli._cmd_audit_all, _ns())
        assert code == 1
        assert "[FAIL] Pattern J" in out


# ─── Resilience ───────────────────────────────────────────────


class TestResilience:

    def test_one_audit_exception_doesnt_block_others(self, cli):
        """If Pattern K's module raises, the other six still
        run and the overall doctor flips to FAILED on its [??]."""
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            side_effect=RuntimeError("module broken"),
        ):
            out, code = _capture(cli._cmd_audit_all, _ns())
        # Pattern K renders as [??] (error/unavailable)
        assert "[??]" in out
        assert "module broken" in out
        # Other six still passed (they ran)
        assert out.count("[pass]") == 6
        # Overall flipped to FAILED
        assert code == 1

    def test_json_includes_error_string_on_exception(self, cli):
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            side_effect=RuntimeError("module broken"),
        ):
            out, _ = _capture(
                cli._cmd_audit_all, _ns(json=True),
            )
        data = json.loads(out)
        assert data["audits"]["pattern_k"]["ok"] is False
        assert "module broken" in data["audits"]["pattern_k"]["error"]
