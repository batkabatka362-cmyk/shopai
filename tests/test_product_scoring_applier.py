"""Tests for engines.product_scoring.tag_applier +
the Phase 7 opt-in path in flow.py.

Coverage mirrors test_product_ranking_applier:
  1. Tier filter: A tagged; B/C/D silently skipped.
  2. Tag composition: scoring:tier_a + scoring:high_composite.
  3. Existing-tags merge (case-insensitive dedup).
  4. Pattern Z recording (success + failure).
  5. Engine flow opt-in: no flag = no tags; flag = apply.
  6. tagged_tier_a list in output.
  7. Apply raise doesn't break envelope.
  8. Router unavailable = all-skipped shape.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engines.product_scoring.tag_applier import apply_tier_tags


def _scored(pid="p1", tier="A", **extra):
    return {"id": pid, "tier": tier, **extra}


def _product(pid, tags=None):
    return {"id": pid, "tags": list(tags or [])}


def _ok_router(applied_pid):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True,
        data={"id": applied_pid, "tags": []},
        error=None,
    )
    return router


def _fail_router(error="adapter_rejected"):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=False, data=None, error=error,
    )
    return router


class TestTierFilter:

    def test_tier_a_tagged(self):
        with patch(
            "engines.product_scoring.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_scoring.tag_applier."
            "record_writeback",
        ):
            results = apply_tier_tags(
                [_scored(pid="p1", tier="A")],
                [_product("p1")],
            )
        assert len(results) == 1
        assert results[0]["applied"] is True
        assert results[0]["tier"] == "A"

    @pytest.mark.parametrize("tier", ["B", "C", "D", "", "Z"])
    def test_non_a_tier_silently_skipped(self, tier):
        with patch(
            "engines.product_scoring.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_scoring.tag_applier."
            "record_writeback",
        ):
            results = apply_tier_tags(
                [_scored(pid="p1", tier=tier)],
                [_product("p1")],
            )
        assert results == []


class TestTagComposition:

    def test_tier_a_gets_two_tags(self):
        router = _ok_router("p1")
        with patch(
            "engines.product_scoring.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_scoring.tag_applier."
            "record_writeback",
        ):
            apply_tier_tags(
                [_scored(pid="p1", tier="A")],
                [_product("p1", tags=["existing"])],
            )
        params = router.execute.call_args.args[1]
        assert set(params["tags"]) == {
            "existing",
            "scoring:tier_a",
            "scoring:high_composite",
        }

    def test_existing_tag_not_duplicated(self):
        router = _ok_router("p1")
        with patch(
            "engines.product_scoring.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_scoring.tag_applier."
            "record_writeback",
        ):
            results = apply_tier_tags(
                [_scored(pid="p1", tier="A")],
                [_product("p1", tags=["scoring:tier_a"])],
            )
        assert results[0]["tags_added"] == 1

    def test_all_tags_already_exist_no_op(self):
        router = _ok_router("p1")
        with patch(
            "engines.product_scoring.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_scoring.tag_applier."
            "record_writeback",
        ):
            results = apply_tier_tags(
                [_scored(pid="p1", tier="A")],
                [_product("p1", tags=[
                    "scoring:tier_a", "scoring:high_composite",
                ])],
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "no_new_tags"
        router.execute.assert_not_called()


class TestPatternZRecording:

    def test_success_records(self):
        with patch(
            "engines.product_scoring.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_scoring.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_tier_tags(
                [_scored(pid="p1", tier="A")],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "product_scoring"
        assert kw["action_type"] == "apply_tier_tags"
        assert kw["success"] is True

    def test_adapter_rejection_records_failure(self):
        with patch(
            "engines.product_scoring.tag_applier._get_router",
            return_value=_fail_router("scope_missing"),
        ), patch(
            "engines.product_scoring.tag_applier."
            "record_writeback",
        ) as record_mock:
            results = apply_tier_tags(
                [_scored(pid="p1", tier="A")],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False
        assert results[0]["applied"] is False


class TestEmptyAndRouter:

    def test_empty_returns_empty(self):
        assert apply_tier_tags([], []) == []

    def test_router_unavailable_all_skipped(self):
        with patch(
            "engines.product_scoring.tag_applier._get_router",
            return_value=None,
        ), patch(
            "engines.product_scoring.tag_applier."
            "record_writeback",
        ):
            results = apply_tier_tags(
                [
                    _scored(pid="p1", tier="A"),
                    _scored(pid="p2", tier="B"),  # skipped
                ],
                [_product("p1"), _product("p2")],
            )
        assert len(results) == 1
        assert results[0]["error"] == "router_unavailable"


class TestFlowOptIn:

    def _seed_input(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "products": [
                    {
                        "id": "p1", "title": "Widget A",
                        "price": 80, "cost": 20,
                        "tags": [],
                    },
                ],
                "apply_tier_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.product_scoring.flow import (
            ProductScoringEngine,
        )
        with patch(
            "engines.product_scoring.tag_applier."
            "apply_tier_tags",
        ) as apply_mock:
            result = ProductScoringEngine().run(
                self._seed_input(apply_tags=False),
            )
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_tier_a"] == []

    def test_opt_in_invokes_applier(self):
        from engines.product_scoring.flow import (
            ProductScoringEngine,
        )
        with patch(
            "engines.product_scoring.tag_applier."
            "apply_tier_tags",
            return_value=[
                {
                    "product_id": "p1",
                    "applied": True,
                    "tags_added": 2,
                    "tier": "A",
                    "merged_tags": [],
                    "error": None,
                },
            ],
        ) as apply_mock:
            result = ProductScoringEngine().run(
                self._seed_input(apply_tags=True),
            )
        apply_mock.assert_called_once()
        assert result["data"]["tagged_tier_a"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.product_scoring.flow import (
            ProductScoringEngine,
        )
        with patch(
            "engines.product_scoring.tag_applier."
            "apply_tier_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = ProductScoringEngine().run(
                self._seed_input(apply_tags=True),
            )
        assert result["status"] == "success"
        assert result["data"]["tagged_tier_a"] == []
