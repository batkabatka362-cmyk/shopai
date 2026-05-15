"""Tests for ``shopai catalog`` and the underlying
``core.approval.catalog.build_catalog()`` builder.

The catalog cross-references every registered dispatcher with its
capability (AST-walked from dispatchers source), claiming adapter
(scope registry), and emitting engine (AST scan of engines/).

Tests cover:
  - Builder happy path on the live registry
  - AST capability extraction for direct ``_router_call`` and
    delegated mint dispatchers
  - Adapter aggregation across capabilities
  - Emitting-engine resolution per action_type
  - CLI text + JSON output, plus --engine and --action-type
    filters
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from pathlib import Path
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
    defaults = dict(json=False, engine=None, action_type=None)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Builder happy path ───────────────────────────────────────


class TestBuilder:

    def test_live_catalog_resolves_every_dispatcher(self):
        """The full registered catalog must have NO unknown
        dispatchers — every dispatcher's source matches a known
        router pattern (_router_call or mint delegation)."""
        from core.approval.catalog import build_catalog
        report = build_catalog()
        assert report.unknown_dispatchers == ()
        assert len(report.entries) > 0

    def test_apply_tags_routes_to_products(self):
        from core.approval.catalog import build_catalog
        report = build_catalog()
        entry = next(
            (e for e in report.entries if e.action_type == "apply_tags"),
            None,
        )
        assert entry is not None
        # Routes through SHOPIFY_UPDATE_PRODUCT
        assert "SHOPIFY_UPDATE_PRODUCT" in entry.capabilities
        # Products adapter claims it
        assert any(
            a.name == "shopify_products" for a in entry.adapters
        )
        # Has the expected scopes
        assert "write_products" in entry.aggregate_scopes
        # tag_management is the emitting engine
        assert "tag_management" in entry.emitting_engines

    def test_mint_dispatchers_resolve_to_create_discount(self):
        """The 6 mint dispatchers all delegate to
        mint_recovery_code or _generic_mint_dispatch and route
        through SHOPIFY_CREATE_DISCOUNT — verify the catalog
        picks that up."""
        from core.approval.catalog import build_catalog
        report = build_catalog()
        mints = [
            e for e in report.entries
            if e.action_type.startswith("mint_")
        ]
        assert len(mints) >= 4
        for e in mints:
            assert "SHOPIFY_CREATE_DISCOUNT" in e.capabilities, (
                f"{e.action_type} did not resolve to "
                f"SHOPIFY_CREATE_DISCOUNT: {e.capabilities}"
            )
            assert any(
                a.name == "shopify_discount" for a in e.adapters
            )


# ─── Synthetic dispatcher source ──────────────────────────────


class TestSyntheticDispatchers:
    """AST walk against a small synthetic dispatchers source so
    the failure / edge cases can be exercised without modifying
    the production dispatchers.py."""

    def test_direct_router_call_extracted(self, tmp_path):
        from core.approval.catalog import (
            _walk_dispatcher_capabilities,
        )
        src = tmp_path / "fake_disp.py"
        src.write_text(
            "def register_dispatcher(x):\n"
            "    def deco(f):\n"
            "        return f\n"
            "    return deco\n"
            "\n"
            "def _router_call(name, params):\n"
            "    return True, {}\n"
            "\n"
            "@register_dispatcher('apply_thing')\n"
            "def _x(params):\n"
            "    return _router_call('SHOPIFY_THING', {'id': 1})\n",
            encoding="utf-8",
        )
        result = _walk_dispatcher_capabilities(src)
        assert result == {"apply_thing": ("SHOPIFY_THING",)}

    def test_multiple_router_calls_in_branches(self, tmp_path):
        """A dispatcher with two _router_call branches returns
        BOTH capabilities."""
        from core.approval.catalog import (
            _walk_dispatcher_capabilities,
        )
        src = tmp_path / "fake_disp.py"
        src.write_text(
            "def register_dispatcher(x):\n"
            "    def deco(f):\n"
            "        return f\n"
            "    return deco\n"
            "\n"
            "@register_dispatcher('branchy')\n"
            "def _x(params):\n"
            "    if params['mode'] == 'a':\n"
            "        return _router_call('SHOPIFY_A', {})\n"
            "    return _router_call('SHOPIFY_B', {})\n",
            encoding="utf-8",
        )
        result = _walk_dispatcher_capabilities(src)
        caps = set(result["branchy"])
        assert caps == {"SHOPIFY_A", "SHOPIFY_B"}

    def test_dispatcher_without_router_call(self, tmp_path):
        from core.approval.catalog import (
            _walk_dispatcher_capabilities,
        )
        src = tmp_path / "fake_disp.py"
        src.write_text(
            "def register_dispatcher(x):\n"
            "    def deco(f):\n"
            "        return f\n"
            "    return deco\n"
            "\n"
            "@register_dispatcher('mystery')\n"
            "def _x(params):\n"
            "    return False, {'error': 'nyi'}\n",
            encoding="utf-8",
        )
        result = _walk_dispatcher_capabilities(src)
        # action_type registered but caps empty — surfaces as
        # 'unknown_dispatchers' upstream
        assert result == {"mystery": ()}

    def test_mint_delegation_resolves(self, tmp_path):
        from core.approval.catalog import (
            _walk_dispatcher_capabilities,
        )
        src = tmp_path / "fake_disp.py"
        src.write_text(
            "def register_dispatcher(x):\n"
            "    def deco(f):\n"
            "        return f\n"
            "    return deco\n"
            "\n"
            "@register_dispatcher('mint_x')\n"
            "def _x(params):\n"
            "    return _generic_mint_dispatch(params, "
            "default_ttl_days=7)\n",
            encoding="utf-8",
        )
        result = _walk_dispatcher_capabilities(src)
        assert result["mint_x"] == ("SHOPIFY_CREATE_DISCOUNT",)

    def test_engine_action_emitters_picks_up_kwarg(self, tmp_path):
        """The engine-emitter AST scan finds any Call with an
        ``action_type='X'`` keyword arg, regardless of which
        function is being called."""
        from core.approval.catalog import _walk_engine_action_emitters
        eng = tmp_path / "fake_engine"
        eng.mkdir()
        (eng / "__init__.py").write_text("", encoding="utf-8")
        (eng / "flow.py").write_text(
            "def f():\n"
            "    return q.enqueue(action_type='apply_x')\n",
            encoding="utf-8",
        )
        result = _walk_engine_action_emitters(tmp_path)
        assert result == {"apply_x": ["fake_engine"]}


# ─── CLI ─────────────────────────────────────────────────────


class TestCli:

    def test_default_render_lists_every_entry(self, cli):
        out, code = _capture(cli._cmd_catalog, _ns())
        assert code == 0
        assert "action catalog" in out
        # Sample of well-known action_types
        assert "apply_tags" in out
        assert "apply_price_change" in out
        assert "mint_loyalty_code" in out

    def test_engine_filter(self, cli):
        out, code = _capture(
            cli._cmd_catalog, _ns(engine="loyalty"),
        )
        assert code == 0
        assert "mint_loyalty_code" in out
        # Other engines' entries should not appear
        assert "apply_tags" not in out
        assert "filtered to engine=loyalty" in out

    def test_action_type_filter(self, cli):
        out, code = _capture(
            cli._cmd_catalog, _ns(action_type="apply_tags"),
        )
        assert code == 0
        assert "apply_tags" in out
        assert "tag_management" in out
        # The mint entries should not appear
        assert "mint_loyalty_code" not in out

    def test_json_envelope_shape(self, cli):
        out, _ = _capture(cli._cmd_catalog, _ns(json=True))
        data = json.loads(out)
        assert "summary" in data
        assert "entries" in data
        assert data["summary"]["total_dispatchers"] > 0
        assert data["summary"]["unknown_dispatchers"] == []
        # Each entry has the expected keys
        e = data["entries"][0]
        assert {
            "action_type",
            "dispatcher",
            "capabilities",
            "adapters",
            "aggregate_scopes",
            "emitting_engines",
        }.issubset(e.keys())

    def test_unknown_engine_filter_renders_empty(self, cli):
        out, code = _capture(
            cli._cmd_catalog, _ns(engine="not_a_real_engine"),
        )
        assert code == 0
        assert "No catalog entries match the filter" in out

    def test_builder_failure_renders_unavailable(self, cli):
        with patch(
            "core.approval.catalog.build_catalog",
            side_effect=RuntimeError("catalog broken"),
        ):
            out, code = _capture(cli._cmd_catalog, _ns())
        assert "unavailable" in out.lower()
