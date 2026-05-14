"""Tests for the expanded ``shopai status`` output.

The base ``_cmd_status`` still prints engines/stores/sync (covered
implicitly by the smoke test in commit). This file exercises the
two helpers added in PR #103+ that surface the *autonomous loop*
state — approval queue depth + last few decisions, and active
goal + top recommended engines.

Both helpers are best-effort: an unavailable approval queue or
recommender must not crash ``status`` — the smoke test for that
behavior is included via the ``_unavailable`` cases.
"""
from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "shopai_cli", "cli.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    """Each test gets a fresh approval queue with no rows."""
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _capture(fn, *args, **kwargs) -> str:
    buf = StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ─── _format_age ─────────────────────────────────────────────────


class TestFormatAge:

    def test_seconds(self, cli):
        assert cli._format_age(5) == "5s ago"
        assert cli._format_age(59) == "59s ago"

    def test_minutes(self, cli):
        assert cli._format_age(60) == "1m ago"
        assert cli._format_age(3599) == "59m ago"

    def test_hours(self, cli):
        assert cli._format_age(3600) == "1h ago"
        assert cli._format_age(86399) == "23h ago"

    def test_days(self, cli):
        assert cli._format_age(86400) == "1d ago"
        assert cli._format_age(86400 * 7) == "7d ago"


# ─── _print_approval_status ──────────────────────────────────────


class TestApprovalStatus:

    def test_empty_queue_prints_zeros(self, cli, isolated_queue):
        out = _capture(cli._print_approval_status)
        assert "Approval Queue:" in out
        assert "pending: 0" in out
        assert "executed: 0" in out
        # No "Recent decisions:" section when nothing is executed
        assert "Recent decisions:" not in out

    def test_counts_render(self, cli, isolated_queue):
        a = isolated_queue.enqueue(
            engine="cart_recovery", action_type="mint_x",
            capability="SHOPIFY_CREATE_DISCOUNT", params={},
            narrative="",
        )
        isolated_queue.enqueue(
            engine="loyalty", action_type="mint_y",
            capability="SHOPIFY_CREATE_DISCOUNT", params={},
            narrative="",
        )
        isolated_queue.approve(a.id)
        out = _capture(cli._print_approval_status)
        assert "pending: 1" in out
        assert "approved: 1" in out

    def test_recent_decisions_listed(self, cli, isolated_queue):
        a = isolated_queue.enqueue(
            engine="loyalty", action_type="mint_code",
            capability="SHOPIFY_CREATE_DISCOUNT", params={},
            narrative="",
        )
        isolated_queue.approve(a.id)
        # Force-execute by direct state push (simulates dispatcher)
        from core.approval.queue import ApprovalStatus
        isolated_queue._transition(
            a.id,
            from_status=ApprovalStatus.APPROVED,
            to_status=ApprovalStatus.EXECUTED,
            decided_by="test",
            reason="",
        )
        out = _capture(cli._print_approval_status)
        assert "Recent decisions:" in out
        assert a.id[:18] in out
        # Short engine/action_type stays untruncated
        assert "loyalty/mint_code" in out
        assert "EXECUTED" in out

    def test_long_engine_label_truncated(
        self, cli, isolated_queue,
    ):
        """A very long engine/action_type combo gets ...-truncated."""
        a = isolated_queue.enqueue(
            engine="some_extremely_long_engine_name",
            action_type="and_its_action_type_is_also_long",
            capability="X", params={}, narrative="",
        )
        isolated_queue.approve(a.id)
        from core.approval.queue import ApprovalStatus
        isolated_queue._transition(
            a.id,
            from_status=ApprovalStatus.APPROVED,
            to_status=ApprovalStatus.EXECUTED,
            decided_by="test", reason="",
        )
        out = _capture(cli._print_approval_status)
        # Truncation appended
        assert "..." in out

    def test_unavailable_queue_no_crash(self, cli):
        """If the approval queue import fails, status keeps printing."""
        with patch(
            "core.approval.queue.get_approval_queue",
            side_effect=RuntimeError("db locked"),
        ):
            # Must NOT raise — best-effort surface
            cli._print_approval_status()


# ─── _print_goal_status ──────────────────────────────────────────


class TestGoalStatus:

    def test_renders_active_goal_and_picks(self, cli):
        out = _capture(cli._print_goal_status)
        assert "Active Goal:" in out
        assert "Top picks:" in out
        # Format: "1. engine_name           priority X.XX"
        assert "priority" in out
        assert "effectiveness" in out

    def test_recommender_failure_no_crash(self, cli):
        """recommend_engines raising must not bring status down."""
        with patch(
            "core.brain.engine_recommender.recommend_engines",
            side_effect=RuntimeError("boom"),
        ):
            cli._print_goal_status()  # no raise

    def test_empty_recommendation_shows_hint(self, cli):
        from core.brain.engine_recommender import RecommendationResult

        empty = RecommendationResult(
            active_goal="unknown_goal",
            primary=[], alternatives=[], source="rules",
        )
        with patch(
            "core.brain.engine_recommender.recommend_engines",
            return_value=empty,
        ):
            out = _capture(cli._print_goal_status)
        assert "unknown_goal" in out
        assert "no engines mapped" in out.lower()
