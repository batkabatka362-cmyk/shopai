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
        history=False,
        history_window=86400 * 7,
        recommend=False,
        recommend_window=86400 * 30,
        recommend_top=10,
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


class TestRecommend:
    """``shopai plan --recommend`` surfaces successful past
    plans from peer stores. Empire-AGI cross-store learning
    primitive."""

    def test_empty_recommendations_friendly(self, cli):
        with patch(
            "core.capability_planner.successful_plans",
            return_value=[],
        ), patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(),
        ):
            out, code = _capture(
                cli._cmd_plan, _ns(recommend=True),
            )
        assert code == 0
        assert "No successful peer-store plans" in out

    def test_recommendations_render_with_capabilities(
        self, cli,
    ):
        rows = [{
            "goal": "launch store",
            "capabilities": [
                "launch_store", "audit_store",
            ],
            "cli_sequence": ["shopai launch <name>"],
            "success_count": 5,
            "last_success": 1234567890.0,
            "stores": ["store-a", "store-b", "store-c"],
        }]
        with patch(
            "core.capability_planner.successful_plans",
            return_value=rows,
        ), patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(),
        ):
            out, code = _capture(
                cli._cmd_plan, _ns(recommend=True),
            )
        assert code == 0
        assert "Cross-store plan recommendations" in out
        assert "launch store" in out
        assert "succeeded 5x" in out
        assert "3 store(s)" in out
        assert "launch_store, audit_store" in out
        assert "shopai launch <name>" in out

    def test_recommend_json_envelope(self, cli):
        rows = [{
            "goal": "x", "capabilities": ["y"],
            "cli_sequence": ["shopai x"],
            "success_count": 2, "last_success": 0.0,
            "stores": ["a"],
        }]
        sm = _fake_sm()
        sm.active_store_id = "current-store"
        with patch(
            "core.capability_planner.successful_plans",
            return_value=rows,
        ) as mock_sp, patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(
                cli._cmd_plan,
                _ns(recommend=True, json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["exclude_store"] == "current-store"
        assert data["recommendations"] == rows
        # Active store passed as exclude filter
        kwargs = mock_sp.call_args.kwargs
        assert (
            kwargs["exclude_store_id"] == "current-store"
        )

    def test_recommend_window_and_top_propagate(self, cli):
        with patch(
            "core.capability_planner.successful_plans",
            return_value=[],
        ) as mock_sp, patch.object(
            cli, "_get_store_manager",
            return_value=_fake_sm(),
        ):
            _capture(
                cli._cmd_plan,
                _ns(
                    recommend=True,
                    recommend_window=86400 * 7,
                    recommend_top=5,
                ),
            )
        kwargs = mock_sp.call_args.kwargs
        assert kwargs["since_seconds"] == 86400 * 7
        assert kwargs["top_n"] == 5


class TestHistory:
    """``shopai plan --history`` reads plan_history.json
    and renders recent invocations."""

    def test_empty_history_friendly(self, cli):
        with patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ), patch(
            "core.capability_planner.outcome_breakdown",
            return_value={
                "total": 0, "executed_total": 0,
                "by_outcome": {}, "success_rate": 0.0,
            },
        ), patch(
            "core.capability_planner.goal_breakdown",
            return_value=[],
        ):
            out, code = _capture(
                cli._cmd_plan, _ns(history=True),
            )
        assert code == 0
        assert "No plan invocations" in out

    def test_recent_events_render(self, cli):
        import time as _time
        events = [
            {
                "event_id": "plan_a",
                "timestamp": _time.time() - 3600,
                "goal": "mobile design",
                "store_id": "store-a",
                "executed": True,
                "outcome": "success",
                "notes": "closed 3 of 5 gaps",
            },
            {
                "event_id": "plan_b",
                "timestamp": _time.time() - 7200,
                "goal": "launch store",
                "store_id": "store-b",
                "executed": False,
                "outcome": "skipped",
                "notes": "",
            },
        ]
        breakdown = {
            "total": 2, "executed_total": 1,
            "by_outcome": {"success": 1, "skipped": 1},
            "success_rate": 1.0,
        }
        goals = [
            {"goal": "mobile design", "count": 1,
             "success": 1, "executed": 1,
             "success_rate": 1.0},
        ]
        with patch(
            "core.capability_planner.recent_history",
            return_value=events,
        ), patch(
            "core.capability_planner.outcome_breakdown",
            return_value=breakdown,
        ), patch(
            "core.capability_planner.goal_breakdown",
            return_value=goals,
        ):
            out, code = _capture(
                cli._cmd_plan, _ns(history=True),
            )
        assert code == 0
        assert "Plan history -- 2 invocation(s)" in out
        assert "mobile design" in out
        assert "launch store" in out
        assert "success" in out
        assert "skipped" in out
        assert "closed 3 of 5 gaps" in out
        # Aggregate footer
        assert "Outcomes (1 executed)" in out
        assert "Success rate: 100.0%" in out
        assert "Top goals" in out

    def test_history_json_passthrough(self, cli):
        events = [{
            "event_id": "x", "timestamp": 0,
            "goal": "g", "store_id": "s",
            "executed": True, "outcome": "success",
            "notes": "",
        }]
        breakdown = {
            "total": 1, "executed_total": 1,
            "by_outcome": {"success": 1},
            "success_rate": 1.0,
        }
        goals = [{
            "goal": "g", "count": 1, "executed": 1,
            "success": 1, "success_rate": 1.0,
        }]
        with patch(
            "core.capability_planner.recent_history",
            return_value=events,
        ), patch(
            "core.capability_planner.outcome_breakdown",
            return_value=breakdown,
        ), patch(
            "core.capability_planner.goal_breakdown",
            return_value=goals,
        ):
            out, code = _capture(
                cli._cmd_plan,
                _ns(history=True, json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["events"] == events
        assert data["outcome_breakdown"] == breakdown
        assert data["top_goals"] == goals


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


class TestExecutePiping:
    """End-to-end composition piping: when a downstream
    applier's pipe_from points at an upstream peer in the
    plan, the executor replaces suggested_args[pipe_as]
    with the upstream step's actual result.data."""

    def test_pipe_replaces_arg_at_runtime(self, cli):
        """A goal that pulls in a generator + applier pair
        runs through the executor with the generator's output
        flowing into the applier's pipe_as kwarg."""
        # We use the real launch-chain registry. The pair
        # we exercise: generate_policies + apply_policies
        # (composes_input='policies').
        # Mocking: replace both module-level functions so we
        # don't touch Shopify.
        captured: dict = {}

        def fake_gen(**kw):
            return {"REFUND_POLICY": "<p>r</p>"}

        def fake_apply(policies=None, **kw):
            captured["policies"] = policies
            captured["other"] = kw
            return {"applied_count": 1, "results": []}

        with patch(
            "engines.store_setup.policy_generator."
            "generate_policies",
            side_effect=fake_gen,
        ), patch(
            "engines.store_setup.policy_applier.apply_policies",
            side_effect=fake_apply,
        ):
            out, code = _capture(
                cli._cmd_plan,
                _ns(
                    goal="policies",
                    execute=True,
                    yes=True,
                    json=True,
                ),
            )
        assert code == 0
        # apply_policies was called with policies kwarg piped
        # from the generator's return value
        assert captured["policies"] == {
            "REFUND_POLICY": "<p>r</p>",
        }


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
