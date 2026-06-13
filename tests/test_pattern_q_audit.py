"""Tests for the Pattern Q engine envelope audit + CLI.

Pattern Q catches a regression class the AST-based audits
can't: an engine refactored to drop one of the canonical
``{status, data, meta, error}`` keys would ship silently
because the envelope dict is computed dynamically.

This audit RUNS each engine with empty input and verifies the
result has all four keys + a valid status value.

Tests cover:
  - Live baseline: every registered engine returns the
    canonical envelope (regression guard).
  - Each violation class detected (missing_keys, not_a_dict,
    bad_status, raised).
  - CLI text + JSON + remediation hint.
  - Consolidated-audit integration.
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


# ─── Live baseline ────────────────────────────────────────────


class TestLiveBaseline:

    def test_every_engine_returns_canonical_envelope(self):
        """Regression guard: a refactor that drops one of the
        four keys lands here as a failure."""
        from engines._output_schema_audit import (
            audit_engine_output_schema,
        )
        report = audit_engine_output_schema()
        assert report.has_violations is False, (
            f"violations: "
            f"{[(v.engine, v.reason) for v in report.violations]}"
        )
        # The audit actually exercised every engine
        assert report.scanned_engines > 100
        assert len(report.clean_engines) > 100


# ─── Violation classes (synthetic fixtures) ──────────────────


class TestViolationClasses:

    def _mock_engine(self, run_result):
        """Build a tiny engine-like object whose run() returns
        a specified value."""
        class _FakeEngine:
            def run(self, _input):
                return run_result
        return _FakeEngine()

    def _audit_one(self, name, engine):
        """Run the audit against a single synthetic engine."""
        from engines._output_schema_audit import (
            audit_engine_output_schema,
        )
        with patch(
            "engines.registry.list_engines",
            return_value=[name],
        ), patch(
            "engines.registry.get_engine",
            return_value=engine,
        ):
            return audit_engine_output_schema()

    def test_missing_keys_detected(self):
        engine = self._mock_engine({"status": "success", "data": {}})
        report = self._audit_one("incomplete", engine)
        assert len(report.violations) == 1
        v = report.violations[0]
        assert v.reason == "missing_keys"
        assert "error" in v.detail or "meta" in v.detail

    def test_not_a_dict_detected(self):
        engine = self._mock_engine("just a string")
        report = self._audit_one("bad_return", engine)
        assert len(report.violations) == 1
        assert report.violations[0].reason == "not_a_dict"
        assert "str" in report.violations[0].detail

    def test_bad_status_detected(self):
        engine = self._mock_engine({
            "status": "weird",  # not in {success, error, fail}
            "data": {},
            "meta": {},
            "error": None,
        })
        report = self._audit_one("weird_status", engine)
        assert len(report.violations) == 1
        assert report.violations[0].reason == "bad_status"
        assert "weird" in report.violations[0].detail

    def test_raised_detected(self):
        class _BoomEngine:
            def run(self, _input):
                raise RuntimeError("kaboom")
        report = self._audit_one("boomer", _BoomEngine())
        assert len(report.violations) == 1
        assert report.violations[0].reason == "raised"
        assert "kaboom" in report.violations[0].detail

    def test_missing_engine_skipped(self):
        """An engine the registry can't instantiate is recorded
        as skipped, not a violation."""
        from engines._output_schema_audit import (
            audit_engine_output_schema,
        )
        with patch(
            "engines.registry.list_engines",
            return_value=["ghost"],
        ), patch(
            "engines.registry.get_engine",
            side_effect=KeyError("ghost"),
        ):
            report = audit_engine_output_schema()
        assert report.violations == []
        assert "ghost" in report.skipped_engines

    def test_clean_engine_classified_correctly(self):
        engine = self._mock_engine({
            "status": "success",
            "data": {"foo": "bar"},
            "meta": {"engine": "fine", "timestamp": "t"},
            "error": None,
        })
        report = self._audit_one("fine", engine)
        assert report.violations == []
        assert "fine" in report.clean_engines


# ─── W962-33: strict probe (malformed input) ─────────────────


class TestStrictMode:
    """Strict probes replay each engine with malformed input
    shapes; engines missing a top-level try/except surface as
    raised_on_malformed."""

    def _audit_strict(self, name, engine):
        from engines._output_schema_audit import (
            audit_engine_output_schema,
        )
        from unittest.mock import patch
        with patch(
            "engines.registry.list_engines",
            return_value=[name],
        ), patch(
            "engines.registry.get_engine",
            return_value=engine,
        ):
            return audit_engine_output_schema(strict=True)

    def test_raises_on_malformed_caught(self):
        """An engine that passes the empty probe but raises on
        malformed input is flagged."""
        clean_envelope = {
            "status": "success", "data": {}, "meta": {},
            "error": None,
        }

        class _Fragile:
            def run(self, inp):
                # Passes empty probe (returns canonical envelope)
                # but raises when data is a string.
                if not isinstance(inp.get("data"), dict):
                    raise TypeError(
                        "data must be a dict",
                    )
                return clean_envelope

        report = self._audit_strict("fragile", _Fragile())
        assert len(report.violations) == 1
        v = report.violations[0]
        assert v.reason == "raised_on_malformed"
        assert "TypeError" in v.detail

    def test_robust_engine_passes_strict(self):
        """An engine with a top-level try/except (W962-13/14
        pattern) passes strict probes."""
        clean_envelope = {
            "status": "success", "data": {}, "meta": {},
            "error": None,
        }
        error_envelope = {
            "status": "error", "data": {}, "meta": {},
            "error": "bad input",
        }

        class _Robust:
            def run(self, inp):
                try:
                    if not isinstance(inp.get("data"), dict):
                        return error_envelope
                    return clean_envelope
                except Exception as exc:  # noqa: BLE001
                    return {
                        **error_envelope,
                        "error": str(exc),
                    }

        report = self._audit_strict("robust", _Robust())
        assert report.violations == []
        assert "robust" in report.clean_engines

    def test_strict_only_runs_when_requested(self):
        """Default audit (strict=False) skips the malformed
        probes -- a fragile engine still classifies as clean."""
        clean_envelope = {
            "status": "success", "data": {}, "meta": {},
            "error": None,
        }

        class _Fragile:
            def run(self, inp):
                if not isinstance(inp.get("data"), dict):
                    raise TypeError("data must be a dict")
                return clean_envelope

        from engines._output_schema_audit import (
            audit_engine_output_schema,
        )
        from unittest.mock import patch
        with patch(
            "engines.registry.list_engines",
            return_value=["fragile"],
        ), patch(
            "engines.registry.get_engine",
            return_value=_Fragile(),
        ):
            # strict=False (default) -- fragile passes
            report = audit_engine_output_schema()
        assert report.violations == []
        assert "fragile" in report.clean_engines

    def test_strict_live_baseline_clean(self):
        """W962-33 regression guard: every production engine
        already passes the strict probe (no top-level except
        gaps after W962-13/14)."""
        from engines._output_schema_audit import (
            audit_engine_output_schema,
        )
        report = audit_engine_output_schema(strict=True)
        assert report.has_violations is False, (
            f"strict violations: "
            f"{[(v.engine, v.reason) for v in report.violations]}"
        )


# ─── CLI ──────────────────────────────────────────────────────


class TestCli:

    def test_live_audit_passes(self, cli):
        out, code = _capture(cli._cmd_pattern_q_audit, _ns())
        assert code == 0
        assert "Pattern Q OK" in out
        assert "envelope" in out

    def test_json_envelope_shape(self, cli):
        out, code = _capture(
            cli._cmd_pattern_q_audit, _ns(json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["violations"] == []
        assert data["scanned_engines"] > 100

    def test_failure_renders_remediation(self, cli):
        from engines._output_schema_audit import (
            EngineSchemaReport,
            EngineSchemaViolation,
        )
        bad = EngineSchemaReport(
            scanned_engines=2,
            clean_engines=["fine"],
            violations=[
                EngineSchemaViolation(
                    engine="broken",
                    reason="missing_keys",
                    detail="missing ['error']",
                ),
            ],
        )
        with patch(
            "engines._output_schema_audit.audit_engine_output_schema",
            return_value=bad,
        ):
            out, code = _capture(cli._cmd_pattern_q_audit, _ns())
        assert code == 1
        assert "FAILED" in out
        assert "broken" in out
        assert "missing_keys" in out
        # Remediation hint
        assert "engines/loyalty/flow.py" in out

    def test_module_failure_is_resilient(self, cli):
        with patch(
            "engines._output_schema_audit.audit_engine_output_schema",
            side_effect=RuntimeError("module broken"),
        ):
            out, code = _capture(cli._cmd_pattern_q_audit, _ns())
        assert "unavailable" in out.lower()
        assert code == 0  # unavailable is not fatal


# ─── Consolidated-audit integration ──────────────────────────


class TestConsolidatedIntegration:

    def test_pattern_q_runs_in_audit_all(self, cli):
        out, _ = _capture(
            cli._cmd_audit_all, _ns(json=True),
        )
        data = json.loads(out)
        assert "pattern_q" in data["audits"]
        assert data["audits"]["pattern_q"]["ok"] is True

    def test_pattern_q_only_filter(self, cli):
        out, code = _capture(
            cli._cmd_audit_all, _ns(only="pattern_q"),
        )
        assert code == 0
        assert "Pattern Q" in out

    def test_pattern_q_failure_fails_audit_all(self, cli):
        from engines._output_schema_audit import (
            EngineSchemaReport,
            EngineSchemaViolation,
        )
        bad = EngineSchemaReport(
            scanned_engines=1,
            clean_engines=[],
            violations=[
                EngineSchemaViolation(
                    engine="x", reason="raised",
                    detail="KeyError: foo",
                ),
            ],
        )
        with patch(
            "engines._output_schema_audit.audit_engine_output_schema",
            return_value=bad,
        ):
            out, code = _capture(cli._cmd_audit_all, _ns())
        assert code == 1
        assert "[FAIL] Pattern Q" in out
