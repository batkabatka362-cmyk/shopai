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
        depth=2,
        args="{}",
        yes=False,
        window_days=30,
        min_sample_size=2,
        top=20,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestReliability:
    """``shopai capabilities reliability`` renders the
    per-capability success-rate leaderboard."""

    def test_empty_leaderboard_friendly(self, cli):
        with patch(
            "core.capability_planner."
            "capability_leaderboard",
            return_value=[],
        ):
            out, code = _capture(
                cli._cmd_capabilities,
                _ns(capability_action="reliability"),
            )
        assert code == 0
        assert "No capability reliability data" in out

    def test_renders_rows_sorted(self, cli):
        rows = [
            {"capability": "high_cap",
             "executed_count": 5,
             "success_count": 5, "success_rate": 1.0},
            {"capability": "mid_cap",
             "executed_count": 4,
             "success_count": 2, "success_rate": 0.5},
        ]
        with patch(
            "core.capability_planner."
            "capability_leaderboard",
            return_value=rows,
        ):
            out, code = _capture(
                cli._cmd_capabilities,
                _ns(capability_action="reliability"),
            )
        assert code == 0
        # Header + each row's percentage + ratio rendered
        # (the ratio is padded for alignment so we don't
        # match strict "(5/5)" -- substring search).
        assert "Capability reliability" in out
        assert "100.0%" in out
        assert "5/5" in out
        assert "high_cap" in out
        assert "50.0%" in out
        assert "2/4" in out
        assert "mid_cap" in out

    def test_json_output(self, cli):
        rows = [{
            "capability": "x", "executed_count": 3,
            "success_count": 2, "success_rate": 0.667,
        }]
        with patch(
            "core.capability_planner."
            "capability_leaderboard",
            return_value=rows,
        ):
            out, code = _capture(
                cli._cmd_capabilities,
                _ns(
                    capability_action="reliability",
                    json=True,
                ),
            )
        assert code == 0
        data = json.loads(out)
        assert data["rows"] == rows
        assert data["window_days"] == 30

    def test_args_propagate(self, cli):
        with patch(
            "core.capability_planner."
            "capability_leaderboard",
            return_value=[],
        ) as mock_lb:
            _capture(
                cli._cmd_capabilities,
                _ns(
                    capability_action="reliability",
                    window_days=7,
                    min_sample_size=5,
                    top=10,
                ),
            )
        kwargs = mock_lb.call_args.kwargs
        assert kwargs["since_seconds"] == 7 * 86400
        assert kwargs["min_sample_size"] == 5
        assert kwargs["top_n"] == 10


class TestRun:
    """``shopai capabilities run <name>`` invokes a
    registered capability in-process. Default dry-run;
    --yes opts in to actual execution."""

    def test_dry_run_resolves_real_function(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="run",
                name="generate_starter_products",
                args='{"niche": "beauty"}',
            ),
        )
        assert code == 0
        assert "DRY-RUN" in out
        assert "generate_starter_products" in out
        assert "Dry-run only" in out
        assert "Pass --yes" in out

    def test_yes_executes_real_function(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="run",
                name="generate_starter_products",
                args='{"niche": "beauty"}',
                yes=True,
                json=True,
            ),
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        # Real generator returned 4 starter products
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 4
        assert (
            data["data"][0]["title"]
            == "Hydrating Vitamin C Serum"
        )

    def test_unknown_capability_exits_1(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="run",
                name="ghost",
            ),
        )
        assert code == 1
        assert "unknown_capability" in out

    def test_invalid_args_json_exits_1(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="run",
                name="generate_starter_products",
                args="not valid json",
            ),
        )
        assert code == 1
        assert "invalid --args JSON" in out

    def test_cli_handler_capability_refused(self, cli):
        """post_launch_enrich's module_path is ``cli:_cmd...``
        -- can't be invoked in-process, returns a friendly
        error."""
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="run",
                name="post_launch_enrich",
                yes=True,
            ),
        )
        assert code == 1
        assert "cli_handler_not_in_process" in out


class TestTree:
    """``shopai capabilities tree <name>`` renders the
    composition graph from a root capability as an indented
    ASCII tree."""

    def test_tree_renders_launch_store(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="tree",
                name="launch_store",
            ),
        )
        assert code == 0
        # Root header + kind
        assert "launch_store [orchestrator]" in out
        # composes_with peers as children
        assert "audit_store" in out
        # ASCII connectors (not Unicode)
        assert "`--" in out or "|--" in out

    def test_tree_audit_all_shows_full_audit_suite(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="tree",
                name="audit_all",
                depth=1,
            ),
        )
        assert code == 0
        # All 9 audits appear as children
        for audit_name in (
            "pattern_k_audit", "pattern_y_audit",
            "pattern_i_audit", "pattern_j_audit",
            "pattern_z_audit", "pattern_q_audit",
            "pattern_s_audit", "oauth_audit",
            "scope_health_check",
        ):
            assert audit_name in out

    def test_tree_unknown_exits_1(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="tree",
                name="ghost",
            ),
        )
        assert code == 1

    def test_tree_json(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="tree",
                name="launch_store",
                depth=1,
                json=True,
            ),
        )
        assert code == 0
        data = json.loads(out)
        assert data["name"] == "launch_store"
        assert data["kind"] == "orchestrator"
        assert isinstance(data["children"], list)

    def test_tree_depth_zero_no_children(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(
                capability_action="tree",
                name="launch_store",
                depth=0,
                json=True,
            ),
        )
        assert code == 0
        data = json.loads(out)
        assert data["children"] == []


class TestStats:

    def test_stats_text_renders_kind_and_tag_breakdown(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(capability_action="stats"),
        )
        assert code == 0
        # Header + kind + tag breakdown
        assert "Substrate registry:" in out
        assert "By kind:" in out
        assert "Top tags:" in out
        # The post-launch tag dominates (>50% of registry)
        assert "post-launch" in out
        # Audit coverage block
        assert "Audit checks with at least one closer" in out
        assert "active_products" in out
        assert "apply_starter_products" in out

    def test_stats_json_carries_full_breakdown(self, cli):
        out, code = _capture(
            cli._cmd_capabilities,
            _ns(capability_action="stats", json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert data["total"] >= 80
        # by_kind has engine + applier + ...
        assert data["by_kind"]["engine"] > 0
        assert data["by_kind"]["applier"] > 0
        # Audit coverage maps each check to its closers
        assert "active_products" in data["audit_coverage"]
        assert (
            "apply_starter_products"
            in data["audit_coverage"]["active_products"]
        )
        # CLI count is reasonable (a few -- mostly orchestrators)
        assert data["with_cli_count"] >= 1


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
