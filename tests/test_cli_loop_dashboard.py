"""Tests for ``shopai loop`` — single-screen autonomous-loop dashboard.

The dashboard aggregates the live state of every moving part the
autonomous loop touches into one operator-friendly view. Five
panels: approval queue, recent decisions, active goal + EMA,
top recommended engines, webhook stats + engine→goal coverage.

Tests cover:
  - ``_build_loop_dict`` returns the full shape, even when some
    subsystems are unavailable (each panel is best-effort)
  - text view renders each panel and degrades gracefully
  - JSON view round-trips cleanly (monitoring-tool consumable)
  - subsystem failures don't crash the dashboard
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


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ─── _build_loop_dict shape ──────────────────────────────────────


class TestBuildLoopDict:

    def test_returns_full_shape(self, cli):
        payload = cli._build_loop_dict(top_n=3)
        assert set(payload.keys()) == {
            "approval_queue",
            "recent_executed",
            "goal",
            "recommendations",
            "webhook_stats",
            "engine_coverage",
        }

    def test_goal_section_has_current_and_stats(self, cli):
        payload = cli._build_loop_dict()
        assert "current" in payload["goal"]
        assert "stats" in payload["goal"]

    def test_engine_coverage_includes_ratio(self, cli):
        payload = cli._build_loop_dict()
        cov = payload["engine_coverage"]
        assert "total" in cov
        assert "mapped" in cov
        assert "ratio" in cov
        # ratio is a number between 0 and 1
        assert 0.0 <= cov["ratio"] <= 1.0

    def test_recent_executed_capped_by_top_n(self, cli):
        payload = cli._build_loop_dict(top_n=2)
        assert len(payload["recent_executed"]) <= 2

    def test_recommendations_capped_by_top_n(self, cli):
        payload = cli._build_loop_dict(top_n=3)
        assert len(payload["recommendations"]) <= 3


# ─── text view ───────────────────────────────────────────────────


class TestTextView:

    def test_default_render_has_all_sections(self, cli):
        out = _capture(
            cli._cmd_loop,
            argparse.Namespace(json=False, top=5),
        )
        assert "ShopAI Autonomous Loop" in out
        assert "Approval Queue:" in out
        assert "Active Goal:" in out
        assert "Top Picks" in out or "recommender unavailable" in out
        assert "Webhook bridge" in out
        assert "Engine coverage" in out

    def test_no_args_uses_default_top(self, cli):
        """Calling without args still works (default top=5)."""
        out = _capture(cli._cmd_loop)
        assert "Approval Queue:" in out


# ─── JSON view ───────────────────────────────────────────────────


class TestJsonView:

    def test_json_view_valid_json(self, cli):
        out = _capture(
            cli._cmd_loop,
            argparse.Namespace(json=True, top=5),
        )
        data = json.loads(out)
        assert "approval_queue" in data

    def test_json_view_no_text_prefix(self, cli):
        """First non-whitespace char is ``{`` — jq-friendly."""
        out = _capture(
            cli._cmd_loop,
            argparse.Namespace(json=True, top=5),
        )
        assert out.strip()[0] == "{"
        assert "ShopAI Autonomous Loop" not in out


# ─── resilience: subsystem failures don't crash ──────────────────


class TestResilience:

    def test_approval_queue_failure_renders_unavailable(self, cli):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            out = _capture(
                cli._cmd_loop,
                argparse.Namespace(json=False, top=5),
            )
        # Dashboard still renders, queue line says unavailable
        assert "ShopAI Autonomous Loop" in out
        assert "unavailable" in out.lower()

    def test_recommender_failure_renders_unavailable(self, cli):
        with patch(
            "core.brain.engine_recommender.recommend_engines",
            side_effect=RuntimeError("recommender down"),
        ):
            out = _capture(
                cli._cmd_loop,
                argparse.Namespace(json=False, top=5),
            )
        assert "ShopAI Autonomous Loop" in out
        assert "Top Picks:" in out
        assert "recommender unavailable" in out

    def test_goal_manager_failure_renders_unknown(self, cli):
        with patch(
            "core.goals.goal_feedback._default_manager",
            return_value=None,
        ):
            out = _capture(
                cli._cmd_loop,
                argparse.Namespace(json=False, top=5),
            )
        # Active Goal still rendered, just as (unknown)
        assert "Active Goal:" in out

    def test_all_subsystems_failed_no_crash(self, cli):
        """Multiple subsystem failures stacked — dashboard
        still completes."""
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("x"),
        ), patch(
            "core.goals.goal_feedback._default_manager",
            return_value=None,
        ), patch(
            "core.brain.engine_recommender.recommend_engines",
            side_effect=RuntimeError("x"),
        ):
            out = _capture(
                cli._cmd_loop,
                argparse.Namespace(json=False, top=5),
            )
        # Header still present
        assert "ShopAI Autonomous Loop" in out


# ─── --watch refresh loop ────────────────────────────────────────


class TestWatchMode:

    def test_watch_zero_renders_once(self, cli):
        """watch=0 (default) is a one-shot render, not a loop."""
        out = _capture(
            cli._cmd_loop,
            argparse.Namespace(json=False, top=5, watch=0),
        )
        # Header appears exactly once
        assert out.count("ShopAI Autonomous Loop") == 1

    def test_watch_exits_on_keyboard_interrupt(self, cli):
        """The watch loop catches Ctrl+C and returns cleanly
        rather than propagating the KeyboardInterrupt."""
        # Patch sleep to raise immediately — simulates Ctrl+C on
        # the first iteration.
        with patch(
            "time.sleep", side_effect=KeyboardInterrupt,
        ):
            out = _capture(
                cli._cmd_loop,
                argparse.Namespace(json=False, top=3, watch=2),
            )
        # Header rendered once (the loop drew once then the
        # KeyboardInterrupt during sleep broke out)
        assert "ShopAI Autonomous Loop" in out
        assert "refreshing every 2s" in out

    def test_watch_renders_repeatedly(self, cli):
        """After 3 iterations (3rd sleep raises), the dashboard
        has rendered 3 times."""
        call_count = {"n": 0}

        def _fake_sleep(_):
            call_count["n"] += 1
            if call_count["n"] >= 3:
                raise KeyboardInterrupt

        with patch("time.sleep", side_effect=_fake_sleep):
            out = _capture(
                cli._cmd_loop,
                argparse.Namespace(json=False, top=2, watch=1),
            )
        assert out.count("ShopAI Autonomous Loop") == 3

    def test_watch_json_falls_through_to_oneshot(self, cli):
        """--watch + --json together: json takes priority (watching
        a json stream isn't useful; callers scripting a live feed
        write their own polling loop)."""
        with patch("time.sleep", side_effect=AssertionError(
            "sleep should not be called when json=True"
        )):
            out = _capture(
                cli._cmd_loop,
                argparse.Namespace(json=True, top=3, watch=5),
            )
        # Output is pure JSON, no watch-loop header text
        data = json.loads(out)
        assert "approval_queue" in data


# ─── _render_loop_text extracted helper ──────────────────────────


class TestRenderLoopText:

    def test_render_helper_returns_full_dashboard(self, cli):
        """``_render_loop_text(payload)`` works standalone for
        callers that build the payload separately (the watch
        loop, future test harnesses)."""
        payload = cli._build_loop_dict(top_n=3)
        out = _capture(cli._render_loop_text, payload)
        assert "ShopAI Autonomous Loop" in out
        assert "Approval Queue:" in out
        assert "Active Goal:" in out
