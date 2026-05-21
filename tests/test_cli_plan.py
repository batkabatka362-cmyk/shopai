"""Tests for ``shopai plan``.

The operator (and Claude) entry point into the deterministic
substrate planner. These tests verify:

  - ``shopai plan "<goal>"`` resolves the goal via the
    registry and emits a step sequence + CLI list.
  - ``shopai plan --close-audit-gaps`` runs the audit,
    extracts failing keys, and plans against them.
  - JSON output is parseable.
  - Empty goal exits 1 with a usage hint.
  - The bible's "mobile design" example works end-to-end.
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


@pytest.fixture(autouse=True)
def _registry_isolation():
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
        goal="",
        close_audit_gaps=False,
        store=None,
        as_context=False,
        execute=False,
        yes=False,
        llm=False,
        llm_model="qwen2.5",
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm():
    sm = MagicMock()
    sm.active_store_id = None
    return sm


class TestGoalPath:

    def test_mobile_design_goal(self, cli):
        """The bible's example -- the planner resolves 'mobile
        design' to store_design_engine + apply_design +
        audit_store via the registry, and renders the
        operator-runnable command sequence."""
        out, code = _capture(
            cli._cmd_plan, _ns(goal="mobile design"),
        )
        assert code == 0
        assert "Plan for: mobile design" in out
        assert "store_design_engine" in out
        assert "apply_design" in out
        assert "audit_store" in out
        # Run section + audit coverage rendered
        assert "Run:" in out
        assert "design_tokens" in out

    def test_launch_goal_uses_orchestrator(self, cli):
        out, code = _capture(
            cli._cmd_plan, _ns(goal="launch store"),
        )
        assert code == 0
        assert "launch_store" in out
        # The orchestrator CLI is emitted, not per-step sub-CLIs
        assert "shopai launch" in out

    def test_unrecognised_goal_renders_note(self, cli):
        out, code = _capture(
            cli._cmd_plan,
            _ns(goal="cryptocurrency_mining"),
        )
        assert code == 0
        assert "no plan" in out.lower() or "No registered" in out

    def test_empty_goal_exits_1_with_usage(self, cli):
        out, code = _capture(cli._cmd_plan, _ns())
        assert code == 1
        assert "Usage" in out

    def test_json_output_parseable(self, cli):
        out, code = _capture(
            cli._cmd_plan,
            _ns(goal="mobile design", json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert data["goal"] == "mobile design"
        names = {s["capability_name"] for s in data["steps"]}
        assert "store_design_engine" in names
        assert "apply_design" in names
        assert isinstance(data["cli_sequence"], list)
        assert isinstance(data["audit_coverage"], list)


class TestLlmFlag:
    """``shopai plan <goal> --llm`` opts in to LLM-driven
    seed selection. Falls back to deterministic when Ollama
    isn't reachable -- and the operator-visible output
    looks identical."""

    def test_llm_unavailable_falls_back_silently(self, cli):
        # No real Ollama in test env -> LLMPlanner returns
        # a deterministic plan with a note.
        out, code = _capture(
            cli._cmd_plan,
            _ns(goal="mobile design", llm=True),
        )
        # Output renders normally; LLM flag is graceful.
        assert code == 0
        assert "Plan for: mobile design" in out
        # Substring match still found store_design_engine
        assert "store_design_engine" in out

    def test_llm_with_json_carries_note(self, cli):
        out, code = _capture(
            cli._cmd_plan,
            _ns(
                goal="mobile design",
                llm=True,
                json=True,
            ),
        )
        assert code == 0
        data = json.loads(out)
        # Falls back to deterministic; the note explains
        # LLM was unavailable (Ollama not running in tests).
        assert any(
            "LLM" in n or "llm" in n
            for n in data["notes"]
        )


class TestExecute:
    """--execute runs each plan step via the in-process
    capability executor. Default dry-run; --yes invokes."""

    def test_execute_dry_run_resolves_each_step(self, cli):
        out, code = _capture(
            cli._cmd_plan,
            _ns(goal="mobile design", execute=True),
        )
        assert code == 0
        assert "Plan DRY-RUN" in out
        # All steps resolved as OK (or SKIP for cli_handler)
        # No real invocation happened.
        assert "Dry-run only" in out
        assert "store_design_engine" in out

    def test_execute_json_output(self, cli):
        out, code = _capture(
            cli._cmd_plan,
            _ns(
                goal="mobile design",
                execute=True,
                json=True,
            ),
        )
        assert code == 0
        data = json.loads(out)
        assert data["goal"] == "mobile design"
        assert data["executed"] is False  # no --yes
        assert isinstance(data["steps"], list)
        assert all("capability" in s for s in data["steps"])

    def test_execute_yes_invokes_each_step(self, cli):
        """With --yes, the executor actually invokes each
        step. The launch_store orchestrator returns its
        usual dict result (with empty-router degradation),
        not a crash."""
        out, code = _capture(
            cli._cmd_plan,
            _ns(
                goal="launch store",
                execute=True,
                yes=True,
            ),
        )
        # No real Shopify -> launch_store degrades to empty
        # but doesn't fail catastrophically.
        assert "Plan EXECUTED" in out
        # Either OK (graceful) or FAIL (raised); both
        # surface a per-step line. Importantly, the plan
        # rendered without crashing.
        assert "launch_store" in out


class TestAsContext:
    """--as-context emits LLM-ready markdown so operators
    can pipe the plan into any downstream LLM (Claude API,
    ChatGPT, sub-agent) for further reasoning."""

    def test_as_context_emits_markdown_headers(self, cli):
        out, code = _capture(
            cli._cmd_plan,
            _ns(goal="mobile design", as_context=True),
        )
        assert code == 0
        # Markdown headers
        assert "# Plan for: mobile design" in out
        assert "## Steps" in out
        # Per-step h3 header with backticked capability name
        assert "### 1. `store_design_engine`" in out
        # Sections that LLM consumers need
        assert "**When to use:**" in out
        assert "**CLI:** `shopai store design-apply`" in out
        assert "**Closes audit checks:** design_tokens" in out
        assert "**Shopify scopes:**" in out

    def test_as_context_includes_run_block(self, cli):
        out, code = _capture(
            cli._cmd_plan,
            _ns(goal="launch store", as_context=True),
        )
        assert code == 0
        # Bash fenced block for run-it instructions
        assert "## Run" in out
        assert "```bash" in out
        assert "shopai launch" in out

    def test_as_context_no_steps_renders_note(self, cli):
        out, code = _capture(
            cli._cmd_plan,
            _ns(
                goal="cryptocurrency_mining",
                as_context=True,
            ),
        )
        assert code == 0
        assert "No matching capabilities" in out


class TestAuditGapPath:

    def test_close_gaps_planner_consumes_audit(self, cli):
        """--close-audit-gaps runs the audit, extracts
        failing keys, and routes them into the planner."""
        audit_result = {
            "checks": [
                {"key": "legal_policies", "ok": False,
                 "applied": 0, "expected": 5,
                 "missing": ["x"], "fix_hint": "..."},
                {"key": "standard_pages", "ok": True,
                 "applied": 4, "expected": 4,
                 "missing": [], "fix_hint": ""},
                {"key": "active_products", "ok": False,
                 "applied": 0, "expected": 1,
                 "missing": ["y"], "fix_hint": "..."},
            ],
            "ready_to_launch": False,
            "completion_pct": 33,
            "missing_summary": "...",
            "next_action": "shopai launch ...",
        }
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ):
            out, code = _capture(
                cli._cmd_plan,
                _ns(close_audit_gaps=True),
            )
        assert code == 0
        # The planner should recommend launch_store (closes
        # both gaps in one shot)
        assert "launch_store" in out

    def test_close_gaps_json(self, cli):
        audit_result = {
            "checks": [
                {"key": "legal_policies", "ok": False,
                 "applied": 0, "expected": 5,
                 "missing": [], "fix_hint": ""},
            ],
            "ready_to_launch": False,
            "completion_pct": 0,
            "missing_summary": "",
            "next_action": "",
        }
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            return_value=audit_result,
        ):
            out, code = _capture(
                cli._cmd_plan,
                _ns(close_audit_gaps=True, json=True),
            )
        assert code == 0
        data = json.loads(out)
        # Goal field synthesised from failing keys
        assert "legal_policies" in data["goal"]

    def test_close_gaps_audit_failure_friendly(self, cli):
        with patch.object(
            cli, "_get_store_manager", return_value=_fake_sm(),
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            side_effect=RuntimeError("network"),
        ):
            out, code = _capture(
                cli._cmd_plan,
                _ns(close_audit_gaps=True),
            )
        # Failure surfaces as friendly text, doesn't crash
        assert code == 0
        assert "unavailable" in out.lower()


class TestEndToEnd:
    """Confirm the planner CLI is the registry+planner
    composed surface AI / operators actually use."""

    def test_mobile_design_full_run(self, cli):
        out, code = _capture(
            cli._cmd_plan,
            _ns(goal="mobile design", json=True),
        )
        assert code == 0
        data = json.loads(out)
        # End-to-end: goal -> registry -> plan -> JSON
        assert data["goal"] == "mobile design"
        # design_tokens audit check surfaces
        assert "design_tokens" in data["audit_coverage"]
        # CLI sequence has at least one runnable command
        assert data["cli_sequence"]
