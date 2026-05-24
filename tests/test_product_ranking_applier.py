"""Tests for engines.product_ranking.tag_applier +
the Phase 7 opt-in path in flow.py.

Coverage:
  1. Rank filter: 1..3 tagged; 4+ silently skipped.
  2. Tag composition: each top-tier gets ranking:top_tier
     + ranking:rank_<N>.
  3. Existing-tags merge (case-insensitive dedup).
  4. Pattern Z recording (success + failure paths).
  5. Engine flow opt-in: no flag = no tags; flag = apply
     loop fires.
  6. Output contains tagged_top_tier list.
  7. Apply raise doesn't break envelope.
  8. Router unavailable = all-skipped uniform shape.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engines.product_ranking.tag_applier import (
    apply_top_tier_tags,
)


def _ranked(pid="p1", rank=1, **extra):
    return {"product_id": pid, "rank": rank, **extra}


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


class TestRankFilter:

    @pytest.mark.parametrize("rank", [1, 2, 3])
    def test_top_tier_ranks_tagged(self, rank):
        with patch(
            "engines.product_ranking.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_ranking.tag_applier."
            "record_writeback",
        ):
            results = apply_top_tier_tags(
                [_ranked(pid="p1", rank=rank)],
                [_product("p1")],
            )
        assert len(results) == 1
        assert results[0]["applied"] is True
        assert results[0]["rank"] == rank

    @pytest.mark.parametrize("rank", [4, 5, 10, 0])
    def test_below_top_tier_silently_skipped(self, rank):
        """Rank > 3 produces no result row (not just
        applied=False)."""
        with patch(
            "engines.product_ranking.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_ranking.tag_applier."
            "record_writeback",
        ):
            results = apply_top_tier_tags(
                [_ranked(pid="p1", rank=rank)],
                [_product("p1")],
            )
        assert results == []


class TestTagComposition:

    def test_rank_1_gets_two_specific_tags(self):
        router = _ok_router("p1")
        with patch(
            "engines.product_ranking.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_ranking.tag_applier."
            "record_writeback",
        ):
            apply_top_tier_tags(
                [_ranked(pid="p1", rank=1)],
                [_product("p1", tags=["existing"])],
            )
        params = router.execute.call_args.args[1]
        assert params["id"] == "p1"
        assert set(params["tags"]) == {
            "existing",
            "ranking:top_tier",
            "ranking:rank_1",
        }

    def test_existing_tag_not_duplicated(self):
        router = _ok_router("p1")
        with patch(
            "engines.product_ranking.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_ranking.tag_applier."
            "record_writeback",
        ):
            results = apply_top_tier_tags(
                [_ranked(pid="p1", rank=2)],
                [_product("p1", tags=["ranking:top_tier"])],
            )
        # Only ranking:rank_2 is new
        assert results[0]["tags_added"] == 1

    def test_all_tags_already_exist_no_op(self):
        router = _ok_router("p1")
        with patch(
            "engines.product_ranking.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_ranking.tag_applier."
            "record_writeback",
        ):
            results = apply_top_tier_tags(
                [_ranked(pid="p1", rank=3)],
                [_product("p1", tags=[
                    "ranking:top_tier", "ranking:rank_3",
                ])],
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "no_new_tags"
        router.execute.assert_not_called()


class TestPatternZRecording:

    def test_success_records_writeback(self):
        with patch(
            "engines.product_ranking.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_ranking.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_top_tier_tags(
                [_ranked(pid="p1", rank=1)],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "product_ranking"
        assert kw["action_type"] == "apply_top_tier_tags"
        assert kw["capability"] == "SHOPIFY_UPDATE_PRODUCT"
        assert kw["success"] is True

    def test_adapter_rejection_records_failure(self):
        with patch(
            "engines.product_ranking.tag_applier._get_router",
            return_value=_fail_router("scope_missing"),
        ), patch(
            "engines.product_ranking.tag_applier."
            "record_writeback",
        ) as record_mock:
            results = apply_top_tier_tags(
                [_ranked(pid="p1", rank=1)],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False
        assert results[0]["applied"] is False


class TestRouterUnavailable:

    def test_returns_skipped_per_top_tier(self):
        with patch(
            "engines.product_ranking.tag_applier._get_router",
            return_value=None,
        ), patch(
            "engines.product_ranking.tag_applier."
            "record_writeback",
        ):
            results = apply_top_tier_tags(
                [
                    _ranked(pid="p1", rank=1),
                    _ranked(pid="p2", rank=2),
                    _ranked(pid="p3", rank=10),  # filtered
                ],
                [_product("p1"), _product("p2"), _product("p3")],
            )
        # Two top-tier (p1, p2); p3 silently skipped
        assert len(results) == 2
        for r in results:
            assert r["applied"] is False
            assert r["error"] == "router_unavailable"


class TestEmptyInputs:

    def test_empty_returns_empty(self):
        assert apply_top_tier_tags([], []) == []

    def test_non_list_returns_empty(self):
        assert apply_top_tier_tags(None, []) == []  # type: ignore

    def test_no_pid_skipped(self):
        with patch(
            "engines.product_ranking.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_ranking.tag_applier."
            "record_writeback",
        ):
            results = apply_top_tier_tags(
                [{"rank": 1}],  # no product_id
                [_product("p1")],
            )
        assert results == []


class TestFlowOptIn:

    def _seed_input(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "products": [
                    {
                        "id": "p1", "title": "Widget A",
                        "price": 50, "cost": 20,
                        "tags": [],
                        "margin": 0.6,
                        "demand_score": 80,
                        "competition_score": 70,
                    },
                ],
                "apply_top_tier_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.product_ranking.flow import (
            ProductRankingEngine,
        )
        with patch(
            "engines.product_ranking.tag_applier."
            "apply_top_tier_tags",
        ) as apply_mock:
            result = ProductRankingEngine().run(
                self._seed_input(apply_tags=False),
            )
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_top_tier"] == []

    def test_opt_in_invokes_applier(self):
        from engines.product_ranking.flow import (
            ProductRankingEngine,
        )
        with patch(
            "engines.product_ranking.tag_applier."
            "apply_top_tier_tags",
            return_value=[
                {
                    "product_id": "p1",
                    "applied": True,
                    "tags_added": 2,
                    "rank": 1,
                    "merged_tags": [],
                    "error": None,
                },
            ],
        ) as apply_mock:
            result = ProductRankingEngine().run(
                self._seed_input(apply_tags=True),
            )
        apply_mock.assert_called_once()
        assert result["data"]["tagged_top_tier"]
        assert (
            result["data"]["tagged_top_tier"][0]["applied"]
            is True
        )

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.product_ranking.flow import (
            ProductRankingEngine,
        )
        with patch(
            "engines.product_ranking.tag_applier."
            "apply_top_tier_tags",
            side_effect=RuntimeError("router boom"),
        ):
            result = ProductRankingEngine().run(
                self._seed_input(apply_tags=True),
            )
        assert result["status"] == "success"
        assert result["data"]["tagged_top_tier"] == []
