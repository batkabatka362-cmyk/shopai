"""Tests for ``shopai store audit`` CLI command.

Thin wrapper around
``engines.store_setup.launch_audit.audit_store``. Renders the
per-check completion table + exits 1 when not ready to launch.

Coverage:
  1. JSON envelope shape.
  2. Text render: ready / not-ready states.
  3. Exit code matches ready_to_launch.
  4. Store ID from CLI arg or active store fallback.
  5. Thresholds (--expected-collections / --expected-discounts)
     propagate to audit_store kwargs.
  6. ImportError surfaces clean error + exit 1.
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
    defaults = dict(
        store_id=None,
        json=False,
        expected_collections=1,
        expected_discounts=1,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _ready_result():
    return {
        "checks": [
            {"key": "legal_policies", "ok": True,
             "applied": 5, "expected": 5, "missing": []},
            {"key": "standard_pages", "ok": True,
             "applied": 4, "expected": 4, "missing": []},
            {"key": "active_discounts", "ok": True,
             "applied": 1, "expected": 1, "missing": []},
            {"key": "curated_collections", "ok": True,
             "applied": 1, "expected": 1, "missing": []},
            {"key": "design_tokens", "ok": True,
             "applied": 1, "expected": 1, "missing": []},
        ],
        "ready_to_launch": True,
        "completion_pct": 100,
        "missing_summary": "all checks passed",
    }


def _not_ready_result():
    return {
        "checks": [
            {"key": "legal_policies", "ok": False,
             "applied": 3, "expected": 5,
             "missing": ["TERMS_OF_SERVICE", "SHIPPING_POLICY"]},
            {"key": "standard_pages", "ok": True,
             "applied": 4, "expected": 4, "missing": []},
            {"key": "active_discounts", "ok": False,
             "applied": 0, "expected": 1,
             "missing": ["need 1 more"]},
            {"key": "curated_collections", "ok": True,
             "applied": 1, "expected": 1, "missing": []},
            {"key": "design_tokens", "ok": True,
             "applied": 1, "expected": 1, "missing": []},
        ],
        "ready_to_launch": False,
        "completion_pct": 60,
        "missing_summary": (
            "legal_policies: TERMS_OF_SERVICE, SHIPPING_POLICY; "
            "active_discounts: need 1 more"
        ),
    }


class TestReady:

    def test_text_says_ready(self, cli):
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_ready_result(),
        ):
            out, code = _capture(
                cli._cmd_store_audit,
                _ns(store_id="store-a"),
            )
        assert code == 0
        assert "READY" in out
        assert "100%" in out
        assert "store-a" in out
        # Each check rendered
        for key in (
            "legal_policies", "standard_pages",
            "active_discounts", "curated_collections",
            "design_tokens",
        ):
            assert key in out

    def test_json_envelope(self, cli):
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_ready_result(),
        ):
            out, code = _capture(
                cli._cmd_store_audit,
                _ns(store_id="store-a", json=True),
            )
        data = json.loads(out)
        assert data["ready_to_launch"] is True
        assert data["completion_pct"] == 100
        assert len(data["checks"]) == 5
        assert code == 0


class TestNotReady:

    def test_text_says_not_ready_exit_1(self, cli):
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_not_ready_result(),
        ):
            out, code = _capture(
                cli._cmd_store_audit,
                _ns(store_id="store-a"),
            )
        assert code == 1
        assert "NOT READY" in out
        assert "60%" in out
        # Missing summary rendered
        assert "TERMS_OF_SERVICE" in out

    def test_json_not_ready_exit_1(self, cli):
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_not_ready_result(),
        ):
            out, code = _capture(
                cli._cmd_store_audit,
                _ns(store_id="store-a", json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["ready_to_launch"] is False


class TestActiveStoreFallback:

    def test_no_store_id_uses_active_store(self, cli):
        with patch.object(
            cli, "_get_store_manager",
        ) as sm_factory, patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_ready_result(),
        ) as audit_mock:
            sm = sm_factory.return_value
            sm.active_store_id = "active-store"
            _capture(
                cli._cmd_store_audit,
                _ns(store_id=None),
            )
        assert (
            audit_mock.call_args.kwargs["store_id"]
            == "active-store"
        )

    def test_explicit_store_id_overrides_active(self, cli):
        with patch.object(
            cli, "_get_store_manager",
        ) as sm_factory, patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_ready_result(),
        ) as audit_mock:
            sm = sm_factory.return_value
            sm.active_store_id = "active-store"
            _capture(
                cli._cmd_store_audit,
                _ns(store_id="explicit-store"),
            )
        assert (
            audit_mock.call_args.kwargs["store_id"]
            == "explicit-store"
        )


class TestThresholdPropagation:

    def test_expected_collections_flag(self, cli):
        with patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=_ready_result(),
        ) as audit_mock:
            _capture(
                cli._cmd_store_audit,
                _ns(
                    store_id="s",
                    expected_collections=5,
                    expected_discounts=3,
                ),
            )
        kw = audit_mock.call_args.kwargs
        assert kw["expected_collections"] == 5
        assert kw["expected_discounts"] == 3


class TestErrorPath:

    def test_import_failure_clean_error(self, cli):
        # Force the import inside the handler to fail
        import builtins
        real_import = builtins.__import__

        def _raise(name, *a, **kw):
            if name == "engines.store_setup.launch_audit":
                raise ImportError("module missing")
            return real_import(name, *a, **kw)

        with patch(
            "builtins.__import__", side_effect=_raise,
        ):
            out, code = _capture(
                cli._cmd_store_audit,
                _ns(store_id="s"),
            )
        assert code == 1
        assert "launch_audit unavailable" in out

    def test_import_failure_json_envelope(self, cli):
        import builtins
        real_import = builtins.__import__

        def _raise(name, *a, **kw):
            if name == "engines.store_setup.launch_audit":
                raise ImportError("module missing")
            return real_import(name, *a, **kw)

        with patch(
            "builtins.__import__", side_effect=_raise,
        ):
            out, code = _capture(
                cli._cmd_store_audit,
                _ns(store_id="s", json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
