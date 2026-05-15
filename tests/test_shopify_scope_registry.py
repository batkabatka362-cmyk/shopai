"""Tests for the Shopify OAuth scope registry + CLI.

The registry aggregates ``required_scopes`` across every
registered Shopify adapter so operators can answer "which OAuth
scopes does this app need at install time?" without reading
every adapter file's docstring.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

import pytest

from core.adapters.shopify._base import ShopifyBaseAdapter


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
    defaults = dict(per_adapter=False, show_gaps=False, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Test fixtures: synthetic adapter classes ───────────────────


class _FakeOrdersAdapter(ShopifyBaseAdapter):
    """Synthetic adapter for testing the registry without
    triggering live adapter constructor logic."""
    name = "fake_orders"
    required_scopes = frozenset({"read_orders", "write_orders"})

    def __init__(self) -> None:  # noqa: D401 — bypass parent init
        pass


class _FakeProductsAdapter(ShopifyBaseAdapter):
    name = "fake_products"
    required_scopes = frozenset({"read_products"})

    def __init__(self) -> None:
        pass


class _FakeUndeclaredAdapter(ShopifyBaseAdapter):
    """No required_scopes declared — surfaces in the gap list."""
    name = "fake_undeclared"

    def __init__(self) -> None:
        pass


# ─── collect_manifest() ────────────────────────────────────────


class TestCollectManifest:

    def test_unions_scopes_across_adapters(self):
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest(
            adapter_classes=(
                _FakeOrdersAdapter, _FakeProductsAdapter,
            ),
        )
        assert manifest.all_scopes == frozenset({
            "read_orders", "write_orders", "read_products",
        })

    def test_by_scope_reverse_index(self):
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest(
            adapter_classes=(
                _FakeOrdersAdapter, _FakeProductsAdapter,
            ),
        )
        # read_orders → just orders
        assert manifest.by_scope["read_orders"] == ["fake_orders"]
        # read_products → just products
        assert manifest.by_scope["read_products"] == ["fake_products"]

    def test_by_scope_collapses_multi_adapter(self):
        """If two adapters claim the same scope, both names
        appear sorted in the reverse index."""
        from core.adapters.shopify.scope_registry import collect_manifest

        class _A(ShopifyBaseAdapter):
            name = "z_adapter"
            required_scopes = frozenset({"read_orders"})

            def __init__(self):
                pass

        class _B(ShopifyBaseAdapter):
            name = "a_adapter"
            required_scopes = frozenset({"read_orders"})

            def __init__(self):
                pass

        manifest = collect_manifest(adapter_classes=(_A, _B))
        # Sorted alphabetically
        assert manifest.by_scope["read_orders"] == [
            "a_adapter", "z_adapter",
        ]

    def test_by_adapter_per_adapter_scope_list(self):
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest(
            adapter_classes=(_FakeOrdersAdapter,),
        )
        assert manifest.by_adapter["fake_orders"] == [
            "read_orders", "write_orders",
        ]

    def test_undeclared_adapter_in_gap_list(self):
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest(
            adapter_classes=(
                _FakeOrdersAdapter, _FakeUndeclaredAdapter,
            ),
        )
        assert "fake_undeclared" in manifest.undeclared_adapters
        assert "fake_orders" not in manifest.undeclared_adapters

    def test_undeclared_adapter_empty_in_by_adapter(self):
        """Undeclared adapter still gets a key — value is empty
        list. Lets callers distinguish 'declared zero scopes'
        from 'not declared at all' via the gap list."""
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest(
            adapter_classes=(_FakeUndeclaredAdapter,),
        )
        assert manifest.by_adapter["fake_undeclared"] == []

    def test_total_adapters_count(self):
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest(
            adapter_classes=(
                _FakeOrdersAdapter, _FakeProductsAdapter,
                _FakeUndeclaredAdapter,
            ),
        )
        assert manifest.total_adapters == 3

    def test_non_shopify_class_skipped(self):
        """Classes that aren't ShopifyBaseAdapter subclasses are
        silently skipped (defensive — the tuple might include
        wrapper types or other surprises)."""
        from core.adapters.shopify.scope_registry import collect_manifest

        class _NotAShopifyAdapter:
            name = "intruder"
            required_scopes = frozenset({"read_oops"})

        manifest = collect_manifest(
            adapter_classes=(
                _FakeOrdersAdapter, _NotAShopifyAdapter,
            ),
        )
        assert "read_oops" not in manifest.all_scopes


# ─── scope_independent sentinel ────────────────────────────────


class _FakeScopeIndependentAdapter(ShopifyBaseAdapter):
    """Synthetic adapter declaring it needs no extra OAuth
    scope (app-level feature)."""

    name = "fake_independent"
    scope_independent = True

    def __init__(self) -> None:
        pass


class TestScopeIndependentSentinel:

    def test_independent_adapter_not_in_undeclared(self):
        """An adapter that sets ``scope_independent = True``
        with empty ``required_scopes`` is treated as declared,
        not as a rollout gap."""
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest(
            adapter_classes=(_FakeScopeIndependentAdapter,),
        )
        assert "fake_independent" not in manifest.undeclared_adapters

    def test_independent_adapter_listed(self):
        """The manifest exposes the independent list so the CLI
        can surface it distinctly from the undeclared list."""
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest(
            adapter_classes=(_FakeScopeIndependentAdapter,),
        )
        assert "fake_independent" in manifest.scope_independent_adapters

    def test_independent_adapter_empty_in_by_adapter(self):
        """Independent adapters appear in by_adapter with an
        empty scope list — same shape as 'declared zero scopes'."""
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest(
            adapter_classes=(_FakeScopeIndependentAdapter,),
        )
        assert manifest.by_adapter["fake_independent"] == []

    def test_independent_doesnt_add_phantom_scopes(self):
        """An independent adapter doesn't contribute any scopes
        to the all_scopes union."""
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest(
            adapter_classes=(_FakeScopeIndependentAdapter,),
        )
        assert manifest.all_scopes == frozenset()

    def test_normal_undeclared_still_in_gap_list(self):
        """An adapter with neither scopes nor the sentinel
        still surfaces as undeclared."""
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest(
            adapter_classes=(
                _FakeUndeclaredAdapter,
                _FakeScopeIndependentAdapter,
            ),
        )
        assert "fake_undeclared" in manifest.undeclared_adapters
        assert (
            "fake_independent"
            not in manifest.undeclared_adapters
        )

    def test_base_class_default_is_false(self):
        """The base class default is False so adapters that
        don't override require explicit declaration."""
        assert ShopifyBaseAdapter.scope_independent is False


# ─── Live coverage now at 100% ─────────────────────────────────


class TestLiveCoverage:

    def test_no_remaining_undeclared(self):
        """After the sentinel + 7 straggler wireups, every
        registered adapter is either scope-declared or
        scope-independent."""
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest()
        assert manifest.undeclared_adapters == []

    def test_live_independents(self):
        """The 7 known scope-independent adapters all surface."""
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest()
        expected = {
            "shopify_app_billing",
            "shopify_app_subscriptions",
            "shopify_mobile_platform_app",
            "shopify_bulk",
            "shopify_bulk_mutations",
            "shopify_generic_tags",
            "shopify_shop",
        }
        assert expected.issubset(
            set(manifest.scope_independent_adapters),
        )


# ─── Helper aliases ────────────────────────────────────────────


class TestHelpers:

    def test_all_required_scopes(self):
        """The flat helper returns a frozenset."""
        from core.adapters.shopify.scope_registry import all_required_scopes
        scopes = all_required_scopes()
        assert isinstance(scopes, frozenset)
        # The live wireups include orders + products at minimum
        assert "read_orders" in scopes
        assert "write_orders" in scopes

    def test_scopes_by_adapter(self):
        from core.adapters.shopify.scope_registry import scopes_by_adapter
        by_adapter = scopes_by_adapter()
        assert isinstance(by_adapter, dict)
        # shopify_orders wired in this PR
        assert "shopify_orders" in by_adapter
        assert "read_orders" in by_adapter["shopify_orders"]


# ─── Live registry verification ────────────────────────────────


class TestLiveRegistry:

    def test_orders_adapter_declares_scopes(self):
        from core.adapters.shopify.orders import ShopifyOrdersAdapter
        assert "read_orders" in ShopifyOrdersAdapter.required_scopes
        assert "write_orders" in ShopifyOrdersAdapter.required_scopes

    def test_products_adapter_declares_scopes(self):
        from core.adapters.shopify.products import ShopifyProductsAdapter
        assert (
            "read_products" in ShopifyProductsAdapter.required_scopes
        )
        assert (
            "write_products" in ShopifyProductsAdapter.required_scopes
        )

    def test_base_adapter_default_is_empty(self):
        """ShopifyBaseAdapter ships with an empty default so
        unwired subclasses don't break — they just surface in
        the gap list."""
        assert ShopifyBaseAdapter.required_scopes == frozenset()


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_default_flat_union(self, cli):
        out, code = _capture(cli._cmd_shopify_scopes, _ns())
        assert code == 0
        assert "Shopify OAuth scope manifest" in out
        # Live wireups appear
        assert "read_orders" in out
        assert "write_orders" in out
        # Co-use count surfaces
        assert "used by" in out

    def test_per_adapter_mode(self, cli):
        out, code = _capture(
            cli._cmd_shopify_scopes, _ns(per_adapter=True),
        )
        assert code == 0
        # Adapter names appear as group headers
        assert "shopify_orders:" in out
        assert "shopify_products:" in out

    def test_show_gaps_lists_undeclared(self, cli):
        out, code = _capture(
            cli._cmd_shopify_scopes, _ns(show_gaps=True),
        )
        assert code == 0
        assert "Adapters without declared scopes" in out

    def test_json_envelope_shape(self, cli):
        out, _ = _capture(cli._cmd_shopify_scopes, _ns(json=True))
        data = json.loads(out)
        assert set(data.keys()) >= {
            "all_scopes", "by_scope", "by_adapter",
            "undeclared_adapters", "total_adapters",
            "declared_adapter_count",
        }

    def test_json_show_gaps_includes_list(self, cli):
        out, _ = _capture(
            cli._cmd_shopify_scopes,
            _ns(json=True, show_gaps=True),
        )
        data = json.loads(out)
        # Without --show-gaps it's None; with it's a list
        assert isinstance(data["undeclared_adapters"], list)

    def test_json_omits_gaps_by_default(self, cli):
        out, _ = _capture(cli._cmd_shopify_scopes, _ns(json=True))
        data = json.loads(out)
        # None when --show-gaps not passed (keeps the operator
        # install manifest clean)
        assert data["undeclared_adapters"] is None

    def test_json_first_char_is_brace(self, cli):
        out, _ = _capture(cli._cmd_shopify_scopes, _ns(json=True))
        assert out.strip()[0] == "{"

    def test_registry_failure_renders_text_unavailable(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            side_effect=RuntimeError("scan broken"),
        ):
            out, code = _capture(cli._cmd_shopify_scopes, _ns())
        assert code == 0
        assert "unavailable" in out.lower()

    def test_registry_failure_renders_json_error(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            side_effect=RuntimeError("scan broken"),
        ):
            out, _ = _capture(
                cli._cmd_shopify_scopes, _ns(json=True),
            )
        data = json.loads(out)
        assert "error" in data
