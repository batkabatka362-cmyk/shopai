"""Tests for the brain_stack field on ``GET /api/engine/<name>``.

The endpoint pre-PR returned name/class/inputs/outputs — the
mechanical contract. PR #117 added the same brain-stack section
to the CLI's ``shopai engine-info``; this PR brings the API up
to parity so a future UI gets the same view.

Also fixes a latent bug: the endpoint crashed with 500 on engines
that didn't expose ``engine_name`` (most of them — they use
``ENGINE_NAME`` or no attribute at all). The new fallback chain
matches the CLI's ``getattr(engine, "ENGINE_NAME", ...)``.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _make_handler():
    from api.server import ShopAIHandler
    handler = ShopAIHandler.__new__(ShopAIHandler)
    responses: list[tuple[int, dict]] = []
    handler._json_response = (
        lambda s, b: responses.append((s, b))
    )
    return handler, responses


# ─── existing-bug fix (no engine_name attribute) ─────────────────


class TestEngineNameFallback:

    def test_engine_without_engine_name_attr_returns_200(self):
        """Pre-PR: CartRecoveryEngine has no engine_name attribute
        → 500. Post-PR: falls back to ENGINE_NAME / registry name."""
        handler, responses = _make_handler()
        handler._engine_info("cart_recovery")
        status, body = responses[0]
        assert status == 200
        assert body["name"]  # whatever fallback fired
        assert "class" in body

    def test_unknown_engine_still_404(self):
        handler, responses = _make_handler()
        handler._engine_info("definitely_not_a_real_engine")
        status, body = responses[0]
        assert status == 404
        assert "error" in body


# ─── brain_stack field shape ──────────────────────────────────────


class TestBrainStackField:

    def test_mapped_engine_carries_goal(self):
        """cart_recovery → grow_customers per ENGINE_GOAL_MAP."""
        handler, responses = _make_handler()
        handler._engine_info("cart_recovery")
        status, body = responses[0]
        assert status == 200
        assert "brain_stack" in body
        assert body["brain_stack"]["goal"] == "grow_customers"

    def test_unmapped_engine_has_null_goal(self):
        """cohort_analysis is not in ENGINE_GOAL_MAP (per
        ``shopai engines --unmapped`` output)."""
        handler, responses = _make_handler()
        handler._engine_info("cohort_analysis")
        status, body = responses[0]
        assert status == 200
        assert body["brain_stack"]["goal"] is None
        assert body["brain_stack"]["effectiveness"] is None
        assert body["brain_stack"]["samples"] == 0

    def test_effectiveness_default_null_when_no_outcomes(self):
        """No EMA recorded yet → null, not 0.50. Callers
        distinguish 'never measured' from 'measured at neutral.'"""
        handler, responses = _make_handler()
        handler._engine_info("cart_recovery")
        status, body = responses[0]
        assert status == 200
        assert body["brain_stack"]["effectiveness"] is None

    def test_effectiveness_surfaces_when_recorded(self):
        """When the GoalManager has stats for the engine's goal,
        the EMA + sample count appear on the response."""
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP
        goal = ENGINE_GOAL_MAP["cart_recovery"]
        fake_stats = {goal: {"effectiveness": 0.71, "n": 9}}
        with patch(
            "core.goals.goal_manager.GoalManager.get_effectiveness_stats",
            return_value=fake_stats,
        ):
            handler, responses = _make_handler()
            handler._engine_info("cart_recovery")
        status, body = responses[0]
        assert status == 200
        assert body["brain_stack"]["effectiveness"] == 0.71
        assert body["brain_stack"]["samples"] == 9


# ─── failure resilience ──────────────────────────────────────────


class TestResilience:

    def test_goal_manager_failure_doesnt_500(self):
        """If GoalManager raises, the endpoint still returns 200
        with brain_stack.goal populated from the static map and
        effectiveness/samples falling back to defaults."""
        with patch(
            "core.goals.goal_manager.GoalManager",
            side_effect=RuntimeError("manager broken"),
        ):
            handler, responses = _make_handler()
            handler._engine_info("cart_recovery")
        status, body = responses[0]
        assert status == 200
        # Goal still resolved (uses static map, not manager)
        assert body["brain_stack"]["goal"] == "grow_customers"
        # Effectiveness gracefully defaults
        assert body["brain_stack"]["effectiveness"] is None

    def test_goal_map_failure_doesnt_500(self):
        """If ENGINE_GOAL_MAP can't load (broken module),
        brain_stack still appears with all-None values rather
        than crashing the endpoint."""
        with patch(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            side_effect=ImportError,
        ):
            handler, responses = _make_handler()
            handler._engine_info("cart_recovery")
        status, body = responses[0]
        assert status == 200
        assert "brain_stack" in body


# ─── helper function direct ──────────────────────────────────────


class TestEngineBrainStackHelper:

    def test_returns_dict_shape(self):
        from api.server import _engine_brain_stack
        result = _engine_brain_stack("cart_recovery")
        assert set(result.keys()) == {"goal", "effectiveness", "samples"}

    def test_unknown_engine_safe(self):
        """The helper doesn't validate the engine name itself —
        unknown engines just resolve to unmapped (goal=None)."""
        from api.server import _engine_brain_stack
        result = _engine_brain_stack("totally_made_up_engine_xyz")
        assert result["goal"] is None
        assert result["effectiveness"] is None
