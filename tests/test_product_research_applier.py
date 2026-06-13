"""Tests for engines.product_research.winner_applier +
the Phase 7 opt-in path in flow.py.

Coverage:
  1. Verdict filter: strong_buy/buy tag, hold/avoid skip.
  2. Existing-tags merge (case-insensitive dedup; nothing
     duplicated).
  3. Tag composition: each winner gets research:winner +
     research:<verdict>.
  4. Pattern Z recording (success + failure paths).
  5. Engine flow opt-in: no flag = no tags applied; flag =
     apply loop fires.
  6. Output contains tagged_winners list.
  7. Apply raise inside flow doesn't break the envelope.
  8. Router/capability unavailable = all-skipped uniform
     result shape.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engines.product_research.winner_applier import (
    apply_winner_tags,
)


def _winner(
    *,
    pid="gid://shopify/Product/1",
    verdict="strong_buy",
    **extra,
):
    return {
        "product_id": pid,
        "verdict": verdict,
        **extra,
    }


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
        ok=False,
        data=None,
        error=error,
    )
    return router


# ─── Verdict filter ───────────────────────────────────────────


class TestVerdictFilter:

    def test_strong_buy_gets_tagged(self):
        with patch(
            "engines.product_research.winner_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_research.winner_applier."
            "record_writeback",
        ):
            results = apply_winner_tags(
                [_winner(pid="p1", verdict="strong_buy")],
                [_product("p1")],
            )
        assert len(results) == 1
        assert results[0]["applied"] is True

    def test_buy_gets_tagged(self):
        with patch(
            "engines.product_research.winner_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_research.winner_applier."
            "record_writeback",
        ):
            results = apply_winner_tags(
                [_winner(pid="p1", verdict="buy")],
                [_product("p1")],
            )
        assert len(results) == 1
        assert results[0]["applied"] is True

    @pytest.mark.parametrize("verdict", [
        "hold", "avoid", "neutral", "", "unscored",
    ])
    def test_non_taggable_verdicts_silently_skip(self, verdict):
        """Hold / avoid / unscored don't produce a result row
        -- not just `applied: False`, but ABSENT from output."""
        with patch(
            "engines.product_research.winner_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_research.winner_applier."
            "record_writeback",
        ):
            results = apply_winner_tags(
                [_winner(pid="p1", verdict=verdict)],
                [_product("p1")],
            )
        assert results == []


# ─── Tag composition + merge ─────────────────────────────────


class TestTagComposition:

    def test_strong_buy_winner_gets_two_tags(self):
        router = _ok_router("p1")
        with patch(
            "engines.product_research.winner_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_research.winner_applier."
            "record_writeback",
        ):
            apply_winner_tags(
                [_winner(pid="p1", verdict="strong_buy")],
                [_product("p1", tags=["existing"])],
            )
        # The adapter call should have received the merged
        # tag list: existing + research:winner + research:strong_buy
        kwargs = router.execute.call_args.args
        capability_arg, params = kwargs
        assert params["id"] == "p1"
        assert set(params["tags"]) == {
            "existing", "research:winner", "research:strong_buy",
        }

    def test_existing_tag_not_duplicated(self):
        """If research:winner already exists, only the
        verdict-specific tag is added."""
        router = _ok_router("p1")
        with patch(
            "engines.product_research.winner_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_research.winner_applier."
            "record_writeback",
        ):
            results = apply_winner_tags(
                [_winner(pid="p1", verdict="buy")],
                [_product("p1", tags=["research:winner"])],
            )
        assert results[0]["tags_added"] == 1
        params = router.execute.call_args.args[1]
        # research:winner appears once even though we tried
        # to add it
        assert params["tags"].count("research:winner") == 1

    def test_all_tags_already_exist_no_op(self):
        """When everything is already tagged, return
        applied=False with no_new_tags marker -- no API call."""
        router = _ok_router("p1")
        with patch(
            "engines.product_research.winner_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_research.winner_applier."
            "record_writeback",
        ):
            results = apply_winner_tags(
                [_winner(pid="p1", verdict="buy")],
                [_product("p1", tags=[
                    "research:winner", "research:buy",
                ])],
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "no_new_tags"
        # No API call when nothing to add
        router.execute.assert_not_called()


# ─── Pattern Z recording ─────────────────────────────────────


class TestPatternZRecording:

    def test_success_records_writeback(self):
        with patch(
            "engines.product_research.winner_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_research.winner_applier."
            "record_writeback",
        ) as record_mock:
            apply_winner_tags(
                [_winner(pid="p1", verdict="strong_buy")],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "product_research"
        assert kwargs["action_type"] == "apply_winner_tags"
        assert kwargs["capability"] == "SHOPIFY_UPDATE_PRODUCT"
        assert kwargs["success"] is True

    def test_adapter_rejection_records_failure(self):
        with patch(
            "engines.product_research.winner_applier._get_router",
            return_value=_fail_router("scope_missing"),
        ), patch(
            "engines.product_research.winner_applier."
            "record_writeback",
        ) as record_mock:
            results = apply_winner_tags(
                [_winner(pid="p1", verdict="buy")],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False
        assert (
            "scope_missing"
            in record_mock.call_args.kwargs["error"]
        )
        assert results[0]["applied"] is False


# ─── Router unavailability ───────────────────────────────────


class TestRouterUnavailable:

    def test_no_router_returns_skipped_for_each_winner(self):
        with patch(
            "engines.product_research.winner_applier._get_router",
            return_value=None,
        ), patch(
            "engines.product_research.winner_applier."
            "record_writeback",
        ):
            results = apply_winner_tags(
                [
                    _winner(pid="p1", verdict="strong_buy"),
                    _winner(pid="p2", verdict="buy"),
                    # Skipped (hold) - shouldn't appear in
                    # results at all.
                    _winner(pid="p3", verdict="hold"),
                ],
                [
                    _product("p1"), _product("p2"),
                    _product("p3"),
                ],
            )
        assert len(results) == 2  # Only taggable winners
        for r in results:
            assert r["applied"] is False
            assert r["error"] == "router_unavailable"


# ─── Empty inputs ────────────────────────────────────────────


class TestEmptyInputs:

    def test_empty_winners_returns_empty(self):
        assert apply_winner_tags([], []) == []

    def test_non_list_winners_returns_empty(self):
        assert apply_winner_tags(None, []) == []  # type: ignore

    def test_winner_without_pid_skipped(self):
        with patch(
            "engines.product_research.winner_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_research.winner_applier."
            "record_writeback",
        ):
            results = apply_winner_tags(
                [{"verdict": "buy"}],  # no product_id
                [_product("p1")],
            )
        assert results == []


# ─── Engine flow opt-in ──────────────────────────────────────


class TestFlowOptIn:

    def _seed_input(self, *, apply_tags=False):
        # product_research.run() takes a flat dict (NOT wrapped
        # under data). Match that shape.
        return {
            "products": [
                {
                    "id": "p1",
                    "name": "Acme T-Shirt",
                    "price": 30,
                    "cost": 8,
                    "tags": [],
                },
            ],
            "niche": "apparel",
            "apply_winner_tags": apply_tags,
        }

    def test_no_flag_no_apply(self):
        from engines.product_research.flow import run
        with patch(
            "engines.product_research.winner_applier."
            "apply_winner_tags",
        ) as apply_mock:
            result = run(self._seed_input(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_winners"] == []

    def test_opt_in_invokes_applier(self):
        from engines.product_research.flow import run
        with patch(
            "engines.product_research.winner_applier."
            "apply_winner_tags",
            return_value=[
                {
                    "product_id": "p1",
                    "applied": True,
                    "tags_added": 2,
                    "merged_tags": [
                        "research:winner", "research:buy",
                    ],
                    "verdict": "buy",
                    "error": None,
                },
            ],
        ) as apply_mock:
            result = run(self._seed_input(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_winners"]
        assert (
            result["data"]["tagged_winners"][0]["applied"]
            is True
        )

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.product_research.flow import run
        with patch(
            "engines.product_research.winner_applier."
            "apply_winner_tags",
            side_effect=RuntimeError("router boom"),
        ):
            result = run(self._seed_input(apply_tags=True))
        # Engine still emits a clean envelope; tagged_winners
        # is empty.
        assert result["status"] == "success"
        assert result["data"]["tagged_winners"] == []
