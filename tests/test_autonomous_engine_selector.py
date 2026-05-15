"""Tests for the AutonomousController's analysis-engine selector.

Before PR #108, ``_phase_analyze`` hardcoded the same 5 engines every
cycle, regardless of which goal was active or which engines the EMA
loop currently prioritized. All the goal_feedback / engine_recommender
work (PR #90/#91/#92) emitted signals nothing consumed.

The selector closes that gap with an opt-in path:

  - ``use_engine_recommender=False`` (default) → legacy 5-engine list
    (no behavior change for existing callers).
  - ``use_engine_recommender=True`` → top picks from
    core.brain.engine_recommender.

Recommender failure or empty picks fall back to the legacy list — the
autonomous loop must never silently run zero engines if the brain
stack hiccups.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def make_controller():
    from core.autonomous.controller import AutonomousController

    def _make(**kwargs):
        return AutonomousController(store_manager=None, **kwargs)
    return _make


# ─── default behavior (backward compat) ───────────────────────────


class TestLegacyDefault:

    def test_default_is_legacy_list(self, make_controller):
        controller = make_controller()
        picks = controller._select_analysis_engines()
        assert picks == [
            "pricing", "inventory", "product_ranking",
            "customer_segmentation", "product_research",
        ]

    def test_explicit_false_is_legacy_list(self, make_controller):
        controller = make_controller(use_engine_recommender=False)
        assert controller._select_analysis_engines() == list(
            type(controller)._LEGACY_ANALYSIS_ENGINES
        )

    def test_default_never_calls_recommender(self, make_controller):
        controller = make_controller()
        with patch(
            "core.brain.engine_recommender.recommend_engines"
        ) as mock_rec:
            controller._select_analysis_engines()
        mock_rec.assert_not_called()


# ─── opt-in recommender path ──────────────────────────────────────


class TestRecommenderEnabled:

    def test_uses_recommender_picks(self, make_controller):
        from core.brain.engine_recommender import (
            EngineRecommendation, RecommendationResult,
        )

        result = RecommendationResult(
            active_goal="maximize_profit",
            primary=[
                EngineRecommendation(
                    engine="dynamic_pricing", goal="maximize_profit",
                    alignment=1.0, effectiveness=0.7, priority=0.85,
                    reason="",
                ),
                EngineRecommendation(
                    engine="content_generation", goal="maximize_profit",
                    alignment=1.0, effectiveness=0.6, priority=0.80,
                    reason="",
                ),
            ],
            alternatives=[], source="rules",
        )
        controller = make_controller(use_engine_recommender=True)
        with patch(
            "core.brain.engine_recommender.recommend_engines",
            return_value=result,
        ):
            picks = controller._select_analysis_engines()
        assert picks == ["dynamic_pricing", "content_generation"]

    def test_empty_picks_falls_back_to_legacy(
        self, make_controller,
    ):
        from core.brain.engine_recommender import RecommendationResult

        empty = RecommendationResult(
            active_goal="x", primary=[], alternatives=[],
            source="rules",
        )
        controller = make_controller(use_engine_recommender=True)
        with patch(
            "core.brain.engine_recommender.recommend_engines",
            return_value=empty,
        ):
            picks = controller._select_analysis_engines()
        # Falls back so the loop never runs zero engines
        assert picks == list(
            type(controller)._LEGACY_ANALYSIS_ENGINES
        )

    def test_recommender_exception_falls_back_to_legacy(
        self, make_controller,
    ):
        controller = make_controller(use_engine_recommender=True)
        with patch(
            "core.brain.engine_recommender.recommend_engines",
            side_effect=RuntimeError("brain stack broken"),
        ):
            picks = controller._select_analysis_engines()
        assert picks == list(
            type(controller)._LEGACY_ANALYSIS_ENGINES
        )

    def test_recommender_called_with_correct_args(
        self, make_controller,
    ):
        controller = make_controller(use_engine_recommender=True)
        with patch(
            "core.brain.engine_recommender.recommend_engines"
        ) as mock_rec:
            from core.brain.engine_recommender import RecommendationResult
            mock_rec.return_value = RecommendationResult(
                active_goal="x", primary=[], alternatives=[],
                source="rules",
            )
            controller._select_analysis_engines()
        mock_rec.assert_called_once_with(
            limit=5, include_alternatives=False,
        )
