"""Tests for ``GET /api/engines?by_goal=1`` and ``?unmapped=1``.

Parity with the CLI's ``shopai engines --by-goal`` / ``--unmapped``
(PR #116). A future UI consuming `/api/engines` should be able to
render the same grouped view without re-implementing the
ENGINE_GOAL_MAP attribution.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _make_handler(query: str = ""):
    from api.server import ShopAIHandler
    handler = ShopAIHandler.__new__(ShopAIHandler)
    handler.path = f"/api/engines{query}"
    responses: list[tuple[int, dict]] = []
    handler._json_response = (
        lambda s, b: responses.append((s, b))
    )
    return handler, responses


# ─── _truthy_param ────────────────────────────────────────────────


class TestTruthyParam:

    def test_truthy_values(self):
        from api.server import _truthy_param
        for v in ["1", "true", "yes", "on", "TRUE"]:
            assert _truthy_param([v]) is True, v

    def test_falsy_values(self):
        from api.server import _truthy_param
        for v in ["0", "false", "no", "off", "anything"]:
            assert _truthy_param([v]) is False, v

    def test_missing_inputs(self):
        from api.server import _truthy_param
        assert _truthy_param(None) is False
        assert _truthy_param([]) is False


# ─── default behavior (no flag) ────────────────────────────────────


class TestFlatListing:

    def test_default_no_grouping(self):
        handler, responses = _make_handler()
        handler._list_engines()
        status, body = responses[0]
        assert status == 200
        assert "count" in body
        assert "engines" in body
        # Default response shape unchanged — no by_goal field
        assert "by_goal" not in body
        assert isinstance(body["engines"], list)


# ─── by_goal=1 ────────────────────────────────────────────────────


class TestByGoal:

    def test_by_goal_groups_engines(self):
        handler, responses = _make_handler("?by_goal=1")
        handler._list_engines()
        status, body = responses[0]
        assert status == 200
        assert "by_goal" in body
        # All canonical goals + unmapped bucket
        for goal in (
            "capture_opportunity", "grow_customers",
            "increase_aov", "maximize_profit", "unmapped",
        ):
            assert goal in body["by_goal"], (
                f"missing goal bucket: {goal}"
            )

    def test_cart_recovery_under_grow_customers(self):
        handler, responses = _make_handler("?by_goal=1")
        handler._list_engines()
        body = responses[0][1]
        assert "cart_recovery" in body["by_goal"]["grow_customers"]

    def test_unmapped_engines_in_unmapped_bucket(self):
        """Pick an unmapped engine dynamically -- the
        engine-goal map evolves; hardcoding a specific engine
        name caused drift (cohort_analysis was unmapped when
        this test was written but later mapped)."""
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP
        from engines.registry import list_engines
        unmapped = sorted(
            e for e in list_engines() if e not in ENGINE_GOAL_MAP
        )
        assert unmapped, "expected at least one unmapped engine"
        handler, responses = _make_handler("?by_goal=1")
        handler._list_engines()
        body = responses[0][1]
        # Every unmapped engine should land in the "unmapped"
        # bucket -- verify on the dynamically-picked sample.
        assert unmapped[0] in body["by_goal"]["unmapped"]

    def test_engines_within_group_sorted(self):
        handler, responses = _make_handler("?by_goal=1")
        handler._list_engines()
        body = responses[0][1]
        for goal, engines_in_goal in body["by_goal"].items():
            assert engines_in_goal == sorted(engines_in_goal), (
                f"goal {goal} not sorted: {engines_in_goal[:3]}"
            )

    def test_total_count_matches_full_list(self):
        handler, responses = _make_handler("?by_goal=1")
        handler._list_engines()
        body = responses[0][1]
        total_across_groups = sum(
            len(v) for v in body["by_goal"].values()
        )
        assert total_across_groups == body["count"]

    def test_flat_engines_field_still_present(self):
        """The ``engines`` array is preserved alongside ``by_goal``
        so existing flat-list consumers keep working."""
        handler, responses = _make_handler("?by_goal=1")
        handler._list_engines()
        body = responses[0][1]
        assert "engines" in body
        assert isinstance(body["engines"], list)


# ─── unmapped=1 ───────────────────────────────────────────────────


class TestUnmapped:

    def test_unmapped_only(self):
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP

        handler, responses = _make_handler("?unmapped=1")
        handler._list_engines()
        status, body = responses[0]
        assert status == 200
        # Every returned engine is unmapped
        for engine in body["engines"]:
            assert engine not in ENGINE_GOAL_MAP

    def test_response_carries_total(self):
        """The endpoint surfaces both the unmapped count AND the
        full registry count, so a UI can render '97 of 131'."""
        handler, responses = _make_handler("?unmapped=1")
        handler._list_engines()
        body = responses[0][1]
        assert "count" in body
        assert "total" in body
        assert body["count"] <= body["total"]


# ─── resilience ──────────────────────────────────────────────────


class TestResilience:

    def test_goal_map_failure_still_returns_engines(self):
        """If ENGINE_GOAL_MAP can't load, by_goal returns engines
        grouped under 'unmapped' rather than 500ing."""
        with patch.dict(
            "sys.modules",
            {"core.goals.engine_goal_map": None},
        ):
            handler, responses = _make_handler("?by_goal=1")
            handler._list_engines()
        status, body = responses[0]
        assert status == 200
        # All engines fell to the unmapped bucket
        assert "by_goal" in body
        assert "unmapped" in body["by_goal"]
