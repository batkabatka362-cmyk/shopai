"""Tests for ``shopai capabilities`` subcommands.

The CLI is the operator (and Claude) entry point into the
capability registry. These tests confirm:

  - ``list`` enumerates + filters
  - ``show <name>`` prints the full record + exits 1 on
    unknown
  - ``find <query>`` substring-matches the LLM-readable
    fields
  - --json output is parseable + carries the same shape
    as the dataclass
  - The launch-chain registration set is reachable
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


@pytest.fixture(autouse=True)
def _isolate_registry():
    from core.capability_registry.bootstrap import (
        reset_for_tests,
    )
    reset_for_tests()
    yield
    reset_for_tests()


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
        capability_action="list",
        kind=None,
        tag=None,
        closes_audit=None,
        name=None,
        query=None,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestList:

    def test_default_list_renders_all(self, cli):
        out, code = _capture(cli._cmd_capabilities, _ns())
        assert code == 0
        assert "Capabilities" in out
        # Launch chain auto-bootstraps
        assert "launch_store" in out
        assert "audit_store" in out

    def test_filter_by_kind(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(kind="orchestrator"),
        )
        assert code == 0
        assert "launch_store" in out
        # Generators / appliers shouldn't be in the
        # orchestrator filter
        assert "generate_policies" not in out

    def test_filter_by_tag(self, cli):
        out, code = _capture(
            cli._cmd_capabilities, _ns(tag="design"),
        )
        assert code == 0
        assert "store_design_engine" in out
        assert "apply_design" in out

    def test_filter_by_closes_audit(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(closes_audit="active_products"),
        )
        assert code == 0
        assert "apply_starter_products" in out

    def test_json_list_parseable(self, cli):
        out, code = _capture(
            cli._cmd_capabilities, _ns(json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert isinstance(data, list)
        names = {c["name"] for c in data}
        assert "launch_store" in names

    def test_filter_with_no_matches_text(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(tag="nonsense-tag"),
        )
        assert code == 0
        assert "No capabilities" in out


class TestShow:

    def test_show_known_capability(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="show",
                name="launch_store",
            ),
        )
        assert code == 0
        assert "launch_store" in out
        assert "orchestrator" in out
        assert "when to use" in out
        # Audit checks listed
        assert "legal_policies" in out

    def test_show_unknown_exits_1(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="show",
                name="ghost_capability",
            ),
        )
        assert code == 1
        assert "Unknown capability" in out

    def test_show_unknown_suggests_similar(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="show",
                name="launch",  # partial match
            ),
        )
        # Exits 1 but surfaces "Did you mean" hint with at
        # least one launch-related suggestion (alphabetical
        # order means apply_* hits land first).
        assert code == 1
        assert "Did you mean" in out
        assert "apply_" in out

    def test_show_json(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="show",
                name="launch_store",
                json=True,
            ),
        )
        assert code == 0
        data = json.loads(out)
        assert data["name"] == "launch_store"
        assert data["kind"] == "orchestrator"
        # JSON carries every dataclass field
        assert "audit_checks_closed" in data
        assert "composes_with" in data
        assert "example_input" in data

    def test_show_json_unknown(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="show",
                name="ghost",
                json=True,
            ),
        )
        assert code == 1
        data = json.loads(out)
        assert data["ok"] is False
        assert data["error"] == "not_found"


class TestFind:

    def test_find_mobile_returns_design_engine(self, cli):
        """The mobile-app design example from the north-star
        bible: 'mobile' as a free-form query should surface
        the store_design_engine because its when_to_use
        mentions mobile."""
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="find",
                query="mobile",
            ),
        )
        assert code == 0
        assert "store_design_engine" in out

    def test_find_discount_returns_writers(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="find",
                query="discount",
            ),
        )
        assert code == 0
        assert "apply_welcome_discount" in out
        # find returns the when_to_use as the one-liner
        assert "generate_welcome_discount" in out

    def test_find_no_match(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="find",
                query="cryptocurrency_mining",
            ),
        )
        assert code == 0
        assert "No capabilities match" in out

    def test_find_json(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="find",
                query="policies",
                json=True,
            ),
        )
        assert code == 0
        data = json.loads(out)
        assert any(
            c["name"] == "apply_policies" for c in data
        )


class TestEndToEnd:
    """End-to-end: the registry catalog is reachable through
    the CLI surface AI / operators actually use."""

    def test_launch_chain_inventory_through_list(self, cli):
        out, code = _capture(
            cli._cmd_capabilities, _ns(json=True),
        )
        data = json.loads(out)
        names = {c["name"] for c in data}
        # The 7-step orchestrator + the audit + the
        # post-launch flow all surface together
        assert {
            "launch_store",
            "audit_store",
            "post_launch_enrich",
            "apply_starter_products",
            "upload_brand_assets",
            "apply_design",
        }.issubset(names)

    def test_audit_to_writer_link_visible(self, cli):
        """Operator workflow: 'audit shows active_products
        gap -> which writer closes it?' -- the CLI gives a
        one-command answer."""
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(closes_audit="active_products"),
        )
        assert code == 0
        assert "apply_starter_products" in out
