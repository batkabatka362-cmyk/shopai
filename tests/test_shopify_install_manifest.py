"""Tests for ``shopai shopify-install-manifest`` — generates a
Shopify app install manifest from the OAuth scope registry.

Closes the loop from the registry (PRs #173-#177) to a
deployable ``shopify.app.toml`` fragment. Three output formats:

  - ``toml`` (default): ready to paste, with optional
    per-scope adapter-usage comments
  - ``json``: raw scope list for programmatic consumption
  - ``csv``: comma-separated one-liner for Shopify CLI tools
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


def _ns(**kw):
    defaults = dict(format="toml", with_comments=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fixture_manifest():
    """A small manifest fixture exercising the format paths."""
    return ScopeManifest(
        all_scopes=frozenset({
            "read_orders", "write_orders", "read_products",
        }),
        by_scope={
            "read_orders": ["shopify_orders", "shopify_refunds"],
            "write_orders": ["shopify_orders"],
            "read_products": ["shopify_products"],
        },
        by_adapter={
            "shopify_orders": ["read_orders", "write_orders"],
            "shopify_refunds": ["read_orders"],
            "shopify_products": ["read_products"],
            "shopify_shop": [],
        },
        undeclared_adapters=[],
        scope_independent_adapters=["shopify_shop"],
        total_adapters=4,
    )


# ─── TOML format (default) ─────────────────────────────────────


class TestToml:

    def test_default_format_is_toml(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_fixture_manifest(),
        ):
            out, code = _capture(
                cli._cmd_shopify_install_manifest, _ns(),
            )
        assert code == 0
        assert "[access_scopes]" in out
        assert "scopes =" in out

    def test_toml_scopes_in_alphabetical_order(self, cli):
        """The csv line in the toml output must be sorted so
        regenerations produce diffable output."""
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_fixture_manifest(),
        ):
            out, _ = _capture(
                cli._cmd_shopify_install_manifest, _ns(),
            )
        # Find the scopes = "..." line
        for line in out.splitlines():
            if line.startswith("scopes ="):
                csv = line.split('"')[1]
                items = csv.split(",")
                assert items == sorted(items)
                break
        else:
            raise AssertionError("scopes line not found")

    def test_toml_header_includes_counts(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_fixture_manifest(),
        ):
            out, _ = _capture(
                cli._cmd_shopify_install_manifest, _ns(),
            )
        # 3 scopes, 3 declared + 1 independent
        assert "Scopes: 3" in out
        assert "3 adapters" in out
        assert "1 scope-independent" in out

    def test_toml_with_comments(self, cli):
        """--with-comments adds the per-scope adapter-usage
        lines so readers can trace each scope back to which
        adapters need it."""
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_fixture_manifest(),
        ):
            out, _ = _capture(
                cli._cmd_shopify_install_manifest,
                _ns(with_comments=True),
            )
        # Per-scope usage comments appear
        assert "# used by shopify_orders" in out
        # Scope name comments appear
        assert "# read_orders" in out

    def test_with_comments_truncates_long_adapter_lists(self, cli):
        """When a scope has many users, the comment truncates
        with a `... +N more` suffix so the line stays readable."""
        many_adapters = [f"adapter_{i}" for i in range(10)]
        manifest = ScopeManifest(
            all_scopes=frozenset({"read_orders"}),
            by_scope={"read_orders": many_adapters},
            by_adapter={a: ["read_orders"] for a in many_adapters},
            undeclared_adapters=[],
            scope_independent_adapters=[],
            total_adapters=10,
        )
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=manifest,
        ):
            out, _ = _capture(
                cli._cmd_shopify_install_manifest,
                _ns(with_comments=True),
            )
        assert "more" in out


# ─── JSON format ───────────────────────────────────────────────


class TestJson:

    def test_json_outputs_list(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_fixture_manifest(),
        ):
            out, code = _capture(
                cli._cmd_shopify_install_manifest,
                _ns(format="json"),
            )
        assert code == 0
        data = json.loads(out)
        assert isinstance(data, list)

    def test_json_is_sorted(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_fixture_manifest(),
        ):
            out, _ = _capture(
                cli._cmd_shopify_install_manifest,
                _ns(format="json"),
            )
        data = json.loads(out)
        assert data == sorted(data)

    def test_json_jq_friendly_leading_bracket(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_fixture_manifest(),
        ):
            out, _ = _capture(
                cli._cmd_shopify_install_manifest,
                _ns(format="json"),
            )
        assert out.strip()[0] == "["


# ─── CSV format ────────────────────────────────────────────────


class TestCsv:

    def test_csv_is_single_line(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_fixture_manifest(),
        ):
            out, _ = _capture(
                cli._cmd_shopify_install_manifest,
                _ns(format="csv"),
            )
        # One non-blank line (print adds a trailing newline)
        non_blank = [
            line for line in out.splitlines() if line.strip()
        ]
        assert len(non_blank) == 1

    def test_csv_no_quotes(self, cli):
        """The csv form is the raw scope names — no quoting,
        no headers, just `a,b,c`."""
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_fixture_manifest(),
        ):
            out, _ = _capture(
                cli._cmd_shopify_install_manifest,
                _ns(format="csv"),
            )
        line = out.strip()
        assert '"' not in line
        assert "=" not in line
        assert "[" not in line

    def test_csv_sorted(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            return_value=_fixture_manifest(),
        ):
            out, _ = _capture(
                cli._cmd_shopify_install_manifest,
                _ns(format="csv"),
            )
        items = out.strip().split(",")
        assert items == sorted(items)


# ─── Live coverage ─────────────────────────────────────────────


class TestLive:

    def test_live_toml_contains_known_scopes(self, cli):
        """The live registry includes (at minimum) the standard
        product/order/customer scopes from PR #173."""
        out, _ = _capture(
            cli._cmd_shopify_install_manifest, _ns(),
        )
        for scope in [
            "read_orders", "write_orders",
            "read_products", "write_products",
            "read_customers", "write_customers",
        ]:
            assert scope in out

    def test_live_csv_parses_back_to_scope_set(self, cli):
        """Round-trip: emit csv, split back into a set,
        compare to all_required_scopes()."""
        from core.adapters.shopify.scope_registry import (
            all_required_scopes,
        )
        out, _ = _capture(
            cli._cmd_shopify_install_manifest,
            _ns(format="csv"),
        )
        emitted = set(out.strip().split(","))
        assert emitted == set(all_required_scopes())


# ─── Resilience ────────────────────────────────────────────────


class TestResilience:

    def test_registry_failure_renders_text(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            side_effect=RuntimeError("registry broken"),
        ):
            out, code = _capture(
                cli._cmd_shopify_install_manifest, _ns(),
            )
        # Doesn't exit 1 — the manifest generator is read-only
        # and a failure here doesn't warrant blocking the
        # operator's workflow.
        assert code == 0
        assert "unavailable" in out.lower()

    def test_registry_failure_renders_json_error(self, cli):
        with patch(
            "core.adapters.shopify.scope_registry.collect_manifest",
            side_effect=RuntimeError("registry broken"),
        ):
            out, _ = _capture(
                cli._cmd_shopify_install_manifest,
                _ns(format="json"),
            )
        data = json.loads(out)
        assert "error" in data
