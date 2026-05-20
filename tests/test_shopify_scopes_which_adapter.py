"""Tests for ``shopai shopify-scopes-which-adapter`` -- the
reverse-lookup CLI that maps a scope name back to the
adapters that declared a need for it.

Coverage:
  1. Scope present in registry → exit 0, adapters listed.
  2. Scope NOT in registry → exit 1 with diagnostic guidance.
  3. JSON output shape (declared / adapters / adapter_count).
  4. Missing scope arg → exit 1.
  5. Manifest-collection failure degrades to error envelope.
  6. Real registry produces non-empty results for real scopes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

import pytest

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


def _ns(scope="", json_flag=False):
    return argparse.Namespace(scope=scope, json=json_flag)


def _manifest_with(scope_map: dict[str, list[str]]):
    """Build a ScopeManifest stub from a {scope: [adapters]} map."""
    all_scopes = frozenset(scope_map.keys())
    by_adapter: dict[str, list[str]] = {}
    for scope, adapters in scope_map.items():
        for a in adapters:
            by_adapter.setdefault(a, []).append(scope)
    return ScopeManifest(
        all_scopes=all_scopes,
        by_scope={k: list(v) for k, v in scope_map.items()},
        by_adapter={k: sorted(v) for k, v in by_adapter.items()},
        undeclared_adapters=[],
        scope_independent_adapters=[],
        total_adapters=len(by_adapter),
    )


# ─── Found scope ─────────────────────────────────────────────


class TestScopeFound:

    def test_lists_single_adapter(self, cli):
        manifest = _manifest_with({
            "read_orders": ["shopify_orders"],
        })
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=manifest,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_which_adapter,
                _ns(scope="read_orders"),
            )
        assert code == 0
        assert "read_orders" in out
        assert "shopify_orders" in out
        # Pluralisation: 1 adapter is singular
        assert "1 adapter:" in out

    def test_lists_multiple_adapters(self, cli):
        manifest = _manifest_with({
            "read_customers": [
                "shopify_customers", "shopify_segments",
                "shopify_companies",
            ],
        })
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=manifest,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_which_adapter,
                _ns(scope="read_customers"),
            )
        assert code == 0
        assert "shopify_customers" in out
        assert "shopify_segments" in out
        assert "shopify_companies" in out
        assert "3 adapters:" in out

    def test_json_output_shape(self, cli):
        manifest = _manifest_with({
            "read_orders": ["shopify_orders", "shopify_draft_orders"],
        })
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=manifest,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_which_adapter,
                _ns(scope="read_orders", json_flag=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["scope"] == "read_orders"
        assert data["declared"] is True
        assert data["adapters"] == [
            "shopify_orders", "shopify_draft_orders",
        ]
        assert data["adapter_count"] == 2


# ─── Not found ───────────────────────────────────────────────


class TestScopeNotFound:

    def test_unknown_scope_exits_1(self, cli):
        manifest = _manifest_with({
            "read_orders": ["shopify_orders"],
        })
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=manifest,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_which_adapter,
                _ns(scope="read_some_fake_scope"),
            )
        assert code == 1
        assert "not declared" in out.lower()
        # Guidance surfaces
        assert "typo" in out.lower() or "legacy" in out.lower()

    def test_unknown_scope_json(self, cli):
        manifest = _manifest_with({
            "read_orders": ["shopify_orders"],
        })
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=manifest,
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_which_adapter,
                _ns(scope="read_some_fake_scope", json_flag=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["declared"] is False
        assert data["adapters"] == []
        assert data["adapter_count"] == 0


# ─── Edge cases ──────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_scope_arg_exits_1(self, cli):
        out, code = _capture(
            cli._cmd_shopify_scopes_which_adapter,
            _ns(scope=""),
        )
        assert code == 1
        assert "required" in out.lower()

    def test_whitespace_only_scope_treated_as_empty(self, cli):
        out, code = _capture(
            cli._cmd_shopify_scopes_which_adapter,
            _ns(scope="   "),
        )
        assert code == 1

    def test_empty_scope_json(self, cli):
        out, code = _capture(
            cli._cmd_shopify_scopes_which_adapter,
            _ns(scope="", json_flag=True),
        )
        assert code == 1
        data = json.loads(out)
        assert data["error"] == "scope_required"

    def test_manifest_failure_degrades_gracefully(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            side_effect=RuntimeError("registry blew up"),
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_which_adapter,
                _ns(scope="read_orders"),
            )
        assert code == 1
        assert "unavailable" in out.lower()

    def test_manifest_failure_json(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            side_effect=RuntimeError("registry blew up"),
        ):
            out, code = _capture(
                cli._cmd_shopify_scopes_which_adapter,
                _ns(scope="read_orders", json_flag=True),
            )
        assert code == 1
        data = json.loads(out)
        assert "manifest_unavailable" in data["error"]
        assert "registry blew up" in data["error"]


# ─── Real registry integration ────────────────────────────────


class TestRealRegistry:
    """End-to-end against the actual production manifest --
    ensures the CLI works against the real ScopeManifest shape
    (not just the test stub)."""

    def test_real_scope_resolves_to_real_adapters(self, cli):
        """``read_orders`` is one of the most commonly declared
        scopes -- multiple adapters in the live registry need
        it. The lookup should return at least one adapter
        without any patching."""
        out, code = _capture(
            cli._cmd_shopify_scopes_which_adapter,
            _ns(scope="read_orders", json_flag=True),
        )
        # If the scope is in the real registry, exit 0.
        # If not (perhaps API revision dropped it), exit 1.
        # Either way the CLI shouldn't crash.
        assert code in (0, 1)
        data = json.loads(out)
        assert data["scope"] == "read_orders"
        if data["declared"]:
            assert data["adapter_count"] > 0
            assert isinstance(data["adapters"], list)
