"""Tests for ``shopai launch-audit``.

Operator surface for the read-only launch-readiness audit.

Coverage:
  - All checks pass -> READY header, exit 0
  - At least one check fails -> MISS line + fix_hint shown
  - --strict + not ready -> exit 1
  - --strict + ready -> exit 0
  - --json -> raw audit dict on stdout
  - audit raises -> friendly text + exit 0 (probe failure
    isn't an audit failure)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import MagicMock, patch

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
    defaults = dict(
        store=None,
        expected_products=1,
        expected_collections=1,
        expected_discounts=1,
        strict=False,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm():
    sm = MagicMock()
    sm.active_store_id = None
    return sm


def _all_pass_result():
    """Synthetic 'launchable store' audit result."""
    return {
        "checks": [
            {"key": "legal_policies", "ok": True,
             "applied": 5, "expected": 5, "missing": [],
             "fix_hint": "Run: shopai launch ..."},
            {"key": "standard_pages", "ok": True,
             "applied": 4, "expected": 4, "missing": [],
             "fix_hint": "Run: shopai launch ..."},
            {"key": "active_discounts", "ok": True,
             "applied": 1, "expected": 1, "missing": [],
             "fix_hint": "Run: shopai launch ..."},
            {"key": "curated_collections", "ok": True,
             "applied": 1, "expected": 1, "missing": [],
             "fix_hint": "Run: shopai launch ..."},
            {"key": "design_tokens", "ok": True,
             "applied": 1, "expected": 1, "missing": [],
             "fix_hint": "Run: shopai launch ..."},
            {"key": "active_products", "ok": True,
             "applied": 1, "expected": 1, "missing": [],
             "fix_hint": "Add ACTIVE products ..."},
            {"key": "shipping_zones", "ok": True,
             "applied": 1, "expected": 1, "missing": [],
             "fix_hint": "Manual: configure at "
                         "admin.shopify.com/settings/shipping"},
            {"key": "fulfillable_locations", "ok": True,
             "applied": 1, "expected": 1, "missing": [],
             "fix_hint": "Manual: activate at "
                         "admin.shopify.com/settings/locations"},
        ],
        "ready_to_launch": True,
        "completion_pct": 100,
        "missing_summary": "all checks passed",
    }


def _partial_fail_result():
    res = _all_pass_result()
    res["checks"][1] = {
        "key": "standard_pages", "ok": False,
        "applied": 2, "expected": 4,
        "missing": ["faq", "shipping-returns"],
        "fix_hint": (
            "Run: shopai launch --store-name <NAME> "
            "--niche <NICHE>"
        ),
    }
    res["ready_to_launch"] = False
    res["completion_pct"] = 88
    res["missing_summary"] = (
        "standard_pages: faq, shipping-returns"
    )
    return res


class TestAllPass:

    def test_ready_header_exit_0(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_all_pass_result(),
        ):
            out, code = _capture(
                cli._cmd_launch_audit, _ns(),
            )
        assert code == 0
        assert "READY" in out
        assert "100%" in out
        assert "launchable" in out.lower()

    def test_json_output(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_all_pass_result(),
        ):
            out, code = _capture(
                cli._cmd_launch_audit, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["ready_to_launch"] is True
        # Every check carries fix_hint in JSON too
        assert all("fix_hint" in c for c in data["checks"])


class TestPartialFail:

    def test_miss_lines_include_fix_hint(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_partial_fail_result(),
        ):
            out, code = _capture(
                cli._cmd_launch_audit, _ns(),
            )
        # Default behaviour: informational exit 0
        assert code == 0
        assert "NOT READY" in out
        assert "[MISS] standard_pages" in out
        assert "missing: faq, shipping-returns" in out
        # The fix hint shows up on the MISS line
        assert "fix:" in out
        assert "shopai launch" in out

    def test_strict_partial_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_partial_fail_result(),
        ):
            out, code = _capture(
                cli._cmd_launch_audit, _ns(strict=True),
            )
        assert code == 1

    def test_strict_ready_exits_0(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_all_pass_result(),
        ):
            out, code = _capture(
                cli._cmd_launch_audit, _ns(strict=True),
            )
        assert code == 0

    def test_strict_json_partial_exits_1(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_partial_fail_result(),
        ):
            out, code = _capture(
                cli._cmd_launch_audit,
                _ns(strict=True, json=True),
            )
        assert code == 1
        # JSON still emitted before exit
        data = json.loads(out)
        assert data["ready_to_launch"] is False


class TestResilience:

    def test_audit_raise_friendly(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            side_effect=RuntimeError("network"),
        ):
            out, code = _capture(
                cli._cmd_launch_audit, _ns(),
            )
        # Probe failure isn't a launch failure -- exit 0
        assert code == 0
        assert "failed" in out.lower()


class TestKwargPropagation:

    def test_expected_counts_forwarded(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_all_pass_result(),
        ) as audit_mock:
            _capture(
                cli._cmd_launch_audit,
                _ns(
                    expected_products=5,
                    expected_collections=3,
                    expected_discounts=2,
                ),
            )
        kwargs = audit_mock.call_args.kwargs
        assert kwargs["expected_products"] == 5
        assert kwargs["expected_collections"] == 3
        assert kwargs["expected_discounts"] == 2
