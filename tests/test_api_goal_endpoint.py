"""Tests for ``GET /api/goal`` — brain-stack goal state via HTTP.

Parity with the CLI's ``shopai goal show``. A future UI consuming
this endpoint can render the current goal + per-goal EMA without
shelling out to the CLI.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_handler():
    from api.server import ShopAIHandler
    handler = ShopAIHandler.__new__(ShopAIHandler)
    responses: list[tuple[int, dict]] = []
    handler._json_response = (
        lambda s, b: responses.append((s, b))
    )
    return handler, responses


# ─── happy path ───────────────────────────────────────────────────


class TestGoalEndpoint:

    def test_returns_current_goal(self):
        """Live call returns 200 with a current-goal string and
        a stats dict (possibly empty)."""
        handler, responses = _make_handler()
        handler._get_goal()
        status, body = responses[0]
        assert status == 200
        assert "current" in body
        assert "stats" in body

    def test_no_outcomes_returns_empty_stats(self):
        """Fresh manager without recorded outcomes yields
        ``stats: {}`` — callers distinguish 'not measured' from
        'measured at neutral'."""
        mock_mgr = MagicMock()
        mock_mgr.get_current_goal.return_value = "maximize_profit"
        mock_mgr.get_effectiveness_stats.return_value = {}
        with patch(
            "core.goals.goal_feedback._default_manager",
            return_value=mock_mgr,
        ):
            handler, responses = _make_handler()
            handler._get_goal()
        status, body = responses[0]
        assert status == 200
        assert body["current"] == "maximize_profit"
        assert body["stats"] == {}

    def test_stats_payload_round_trips(self):
        """When the manager has recorded outcomes, the per-goal
        effectiveness + sample counts surface verbatim."""
        mock_mgr = MagicMock()
        mock_mgr.get_current_goal.return_value = "grow_customers"
        mock_mgr.get_effectiveness_stats.return_value = {
            "grow_customers": {"effectiveness": 0.72, "n": 14},
            "maximize_profit": {"effectiveness": 0.45, "n": 5},
        }
        with patch(
            "core.goals.goal_feedback._default_manager",
            return_value=mock_mgr,
        ):
            handler, responses = _make_handler()
            handler._get_goal()
        status, body = responses[0]
        assert status == 200
        assert body["current"] == "grow_customers"
        assert body["stats"]["grow_customers"]["effectiveness"] == 0.72
        assert body["stats"]["grow_customers"]["n"] == 14
        assert body["stats"]["maximize_profit"]["n"] == 5


# ─── resilience ──────────────────────────────────────────────────


class TestResilience:

    def test_no_manager_returns_200_with_null(self):
        """If goal_feedback's default manager is None, return 200
        with explicit null + error string. NOT 500 — a missing
        manager is a config issue, not a server fault."""
        with patch(
            "core.goals.goal_feedback._default_manager",
            return_value=None,
        ):
            handler, responses = _make_handler()
            handler._get_goal()
        status, body = responses[0]
        assert status == 200
        assert body["current"] is None
        assert body["stats"] == {}
        assert "error" in body

    def test_manager_raise_safe(self):
        """get_current_goal raising → current=None but stats still
        returned (the failures are scoped per call)."""
        mock_mgr = MagicMock()
        mock_mgr.get_current_goal.side_effect = RuntimeError("crash")
        mock_mgr.get_effectiveness_stats.return_value = {
            "maximize_profit": {"effectiveness": 0.5, "n": 0},
        }
        with patch(
            "core.goals.goal_feedback._default_manager",
            return_value=mock_mgr,
        ):
            handler, responses = _make_handler()
            handler._get_goal()
        status, body = responses[0]
        assert status == 200
        assert body["current"] is None
        # Stats still came through
        assert "maximize_profit" in body["stats"]

    def test_stats_raise_safe(self):
        """get_effectiveness_stats raising → stats={} but current
        still returned."""
        mock_mgr = MagicMock()
        mock_mgr.get_current_goal.return_value = "grow_customers"
        mock_mgr.get_effectiveness_stats.side_effect = RuntimeError(
            "stats DB down",
        )
        with patch(
            "core.goals.goal_feedback._default_manager",
            return_value=mock_mgr,
        ):
            handler, responses = _make_handler()
            handler._get_goal()
        status, body = responses[0]
        assert status == 200
        assert body["current"] == "grow_customers"
        assert body["stats"] == {}


# ─── route registration ──────────────────────────────────────────


class TestRouteRegistration:

    def test_goal_route_in_get_table(self):
        """The endpoint is listed in do_GET's route map so dispatch
        finds it."""
        import inspect

        from api.server import ShopAIHandler

        src = inspect.getsource(ShopAIHandler.do_GET)
        assert '"/api/goal"' in src
        assert "_get_goal" in src
