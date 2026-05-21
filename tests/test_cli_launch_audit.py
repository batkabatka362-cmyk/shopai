"""Tests for ``shopai launch-audit``.

Wraps the existing ``engines.store_setup.launch_audit.audit_store``
in a CLI surface so operators can gate "is this store ready?"
the same way they gate scope drift.

Coverage:
  - Healthy audit -> exit 0 + "OK" message
  - Failing audit -> exit 1 + per-check breakdown of failures
  - JSON output (success and failure)
  - Audit-internal exception -> friendly unavailable message,
    no crash
  - ``--store`` arg propagates to audit_store
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
    defaults = dict(json=False, store=None)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _result(*, ready, completion_pct, checks=None, missing="-"):
    return {
        "ready_to_launch": ready,
        "completion_pct": completion_pct,
        "checks": checks or [],
        "missing_summary": missing,
    }


class TestHealthyAudit:

    def test_ready_to_launch_text_exits_0(self, cli):
        report = _result(
            ready=True,
            completion_pct=100,
            checks=[
                {"key": "legal_policies", "ok": True,
                 "applied": 5, "expected": 5, "missing": []},
                {"key": "active_products", "ok": True,
                 "applied": 10, "expected": 1, "missing": []},
            ],
            missing="all checks passed",
        )
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_launch_audit, _ns(),
            )
        assert code == 0
        assert "OK" in out
        assert "2/2" in out
        assert "100%" in out
        assert "ready to take orders" in out.lower()

    def test_ready_to_launch_json_exits_0(self, cli):
        report = _result(
            ready=True,
            completion_pct=100,
            checks=[{
                "key": "legal_policies", "ok": True,
                "applied": 5, "expected": 5, "missing": [],
            }],
        )
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_launch_audit, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["ready_to_launch"] is True
        assert data["completion_pct"] == 100
        assert isinstance(data["checks"], list)


class TestFailingAudit:

    def test_failing_audit_text_exits_1(self, cli):
        report = _result(
            ready=False,
            completion_pct=66,
            checks=[
                {"key": "legal_policies", "ok": True,
                 "applied": 5, "expected": 5, "missing": []},
                {"key": "standard_pages", "ok": False,
                 "applied": 3, "expected": 4,
                 "missing": ["faq"]},
                {"key": "active_products", "ok": False,
                 "applied": 0, "expected": 1,
                 "missing": ["need 1 more"]},
            ],
            missing="standard_pages: faq; active_products: need 1 more",
        )
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_launch_audit, _ns(),
            )
        assert code == 1
        assert "FAILED" in out
        assert "standard_pages" in out
        assert "active_products" in out
        # The passing check stays out of the failure breakdown
        assert "[FAIL] legal_policies" not in out
        # Fix instruction surfaces
        assert "launch_orchestrator" in out

    def test_failing_audit_json_exits_1(self, cli):
        report = _result(
            ready=False,
            completion_pct=50,
            checks=[
                {"key": "active_products", "ok": False,
                 "applied": 0, "expected": 1,
                 "missing": ["need 1 more"]},
                {"key": "legal_policies", "ok": True,
                 "applied": 5, "expected": 5, "missing": []},
            ],
            missing="active_products: need 1 more",
        )
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=report,
        ):
            out, code = _capture(
                cli._cmd_launch_audit, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["ok"] is False
        assert data["ready_to_launch"] is False
        assert data["completion_pct"] == 50
        # Failing check round-trips through JSON intact
        active = next(
            c for c in data["checks"]
            if c["key"] == "active_products"
        )
        assert active["ok"] is False
        assert active["missing"] == ["need 1 more"]


class TestResilience:

    def test_audit_raise_renders_unavailable(self, cli):
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            side_effect=RuntimeError("boom"),
        ):
            out, code = _capture(
                cli._cmd_launch_audit, _ns(),
            )
        # Unavailable is exit 0 (matches scopes-live-check
        # convention) -- we don't want a transient probe failure
        # to look like a launch-readiness failure
        assert code == 0
        assert "unavailable" in out.lower()

    def test_audit_raise_json_emits_error(self, cli):
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            side_effect=RuntimeError("boom"),
        ):
            out, code = _capture(
                cli._cmd_launch_audit, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is None
        assert data["error"] == "audit_unavailable"
        assert "boom" in data["message"]


class TestStorePropagation:

    def test_store_arg_passed_to_audit(self, cli):
        report = _result(ready=True, completion_pct=100)
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=report,
        ) as mock_audit:
            _capture(cli._cmd_launch_audit, _ns(store="store-a"))
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["store_id"] == "store-a"

    def test_no_store_passes_none(self, cli):
        report = _result(ready=True, completion_pct=100)
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=report,
        ) as mock_audit:
            _capture(cli._cmd_launch_audit, _ns())
        kwargs = mock_audit.call_args.kwargs
        # None / empty string both normalize to None so Pattern Z
        # records a fleet-wide event instead of a sentinel string.
        assert kwargs["store_id"] is None
