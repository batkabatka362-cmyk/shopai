"""Tests for ``shopai shopify-scopes-audit`` — the CI gate
that fails the build when any Shopify adapter is missing a
scope declaration.

Mirrors the Pattern K dispatcher coverage audit (PR #157,
``shopai approvals audit``). Same shape: exit 0 = clean,
exit 1 = at least one gap. Plus a --json mode for automation.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

import pytest

from core.adapters.shopify._base import ShopifyBaseAdapter
from core.adapters.shopify.scope_registry import ScopeManifest


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
    defaults = dict(json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _clean_manifest():
    """All adapters declared — audit should pass."""
    return ScopeManifest(
        all_scopes=frozenset({"read_orders", "write_orders"}),
        by_scope={"read_orders": ["a"], "write_orders": ["a"]},
        by_adapter={"a": ["read_orders", "write_orders"]},
        undeclared_adapters=[],
        scope_independent_adapters=["b"],
        total_adapters=2,
    )


def _gappy_manifest():
    """Two undeclared — audit should fail."""
    return ScopeManifest(
        all_scopes=frozenset({"read_orders"}),
        by_scope={"read_orders": ["a"]},
        by_adapter={"a": ["read_orders"], "b": [], "c": []},
        undeclared_adapters=["b", "c"],
        scope_independent_adapters=[],
        total_adapters=3,
    )


# ─── Pass case ─────────────────────────────────────────────────


class TestPassCase:

    def test_exit_0_when_no_gaps(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_clean_manifest(),
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_audit, _ns(),
            )
        assert code == 0
        assert "Scope coverage OK" in out

    def test_summary_includes_independent_count(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_clean_manifest(),
        ):
            out, _ = _capture(
                cli._cmd_shopify_scopes_audit, _ns(),
            )
        # "1 scope-independent" from the clean manifest fixture
        assert "1 scope-independent" in out

    def test_json_pass_envelope(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_clean_manifest(),
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_audit, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data == {
            "ok": True,
            "undeclared_count": 0,
            "undeclared_adapters": [],
            "total_adapters": 2,
        }


# ─── Fail case ─────────────────────────────────────────────────


class TestFailCase:

    def test_exit_1_when_gaps(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_gappy_manifest(),
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_audit, _ns(),
            )
        assert code == 1
        assert "Scope coverage FAILED" in out

    def test_gap_list_in_output(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_gappy_manifest(),
        ):
            out, _ = _capture(
                cli._cmd_shopify_scopes_audit, _ns(),
            )
        # Both undeclared adapters surface so the CI log is
        # actionable
        assert "b" in out
        assert "c" in out

    def test_remediation_hint_in_output(self, cli):
        """The error message tells operators how to fix it —
        actionable CI output beats opaque exit codes."""
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_gappy_manifest(),
        ):
            out, _ = _capture(
                cli._cmd_shopify_scopes_audit, _ns(),
            )
        assert "required_scopes" in out
        assert "scope_independent" in out

    def test_json_fail_envelope_exits_1(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_gappy_manifest(),
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_audit, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["ok"] is False
        assert data["undeclared_count"] == 2
        assert set(data["undeclared_adapters"]) == {"b", "c"}
        assert data["total_adapters"] == 3


# ─── Live coverage ─────────────────────────────────────────────


class TestLiveCoverage:

    def test_live_audit_passes(self, cli):
        """After PR #176 the live registry is at 100% coverage —
        the audit MUST pass against the real adapter set."""
        out, code = _capture(
            cli._cmd_shopify_scopes_audit, _ns(),
        )
        assert code == 0
        assert "Scope coverage OK" in out


# ─── Registry failure resilience ───────────────────────────────


class TestRegistryFailure:

    def test_registry_exception_doesnt_exit_1(self, cli):
        """A broken registry import is a different bug class
        from a missing scope. The audit surfaces the failure but
        doesn't fail the build — the test suite catches registry
        breakage directly."""
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            side_effect=RuntimeError("registry broken"),
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_audit, _ns(),
            )
        assert code == 0
        assert "unavailable" in out.lower()

    def test_registry_exception_json_mode(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            side_effect=RuntimeError("registry broken"),
        ):
            out, _ = _capture(
                cli._cmd_shopify_scopes_audit, _ns(json=True),
            )
        data = json.loads(out)
        assert "error" in data


# ─── New-adapter regression scenario ───────────────────────────


class _UnwiredAdapter(ShopifyBaseAdapter):
    """Mimics a future PR adding an adapter without declaring
    scopes — the gate should fail on this."""

    name = "fake_unwired"

    def __init__(self) -> None:
        pass


class TestNewAdapterRegression:

    def test_synthetic_unwired_adapter_fails_audit(self, cli):
        """The gate's whole purpose: catch new adapters that
        forget to declare scopes. Patch the bootstrap tuple to
        include a synthetic undeclared adapter and confirm the
        audit fails. ``collect_manifest`` reads the bootstrap
        constant lazily on each call so the patch lands."""
        from core.adapters.shopify import bootstrap
        patched_classes = (
            *bootstrap._SHOPIFY_ADAPTER_CLASSES, _UnwiredAdapter,
        )
        with patch.object(
            bootstrap, "_SHOPIFY_ADAPTER_CLASSES",
            patched_classes,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_audit, _ns(),
            )
        assert code == 1
        assert "fake_unwired" in out
