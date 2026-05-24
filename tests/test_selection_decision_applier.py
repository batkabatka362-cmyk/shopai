"""Tests for engines.selection_decision.tag_applier + flow
opt-in path. Shape mirrors the other Phase 7 applier tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engines.selection_decision.tag_applier import (
    apply_selection_tags,
)


def _selected(pid="p1", **extra):
    return {"product_id": pid, **extra}


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


class TestBasicFlow:

    def test_selected_product_tagged(self):
        with patch(
            "engines.selection_decision.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.selection_decision.tag_applier."
            "record_writeback",
        ):
            results = apply_selection_tags(
                [_selected(pid="p1")],
                [_product("p1")],
            )
        assert len(results) == 1
        assert results[0]["applied"] is True

    def test_tag_composition(self):
        router = _ok_router("p1")
        with patch(
            "engines.selection_decision.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.selection_decision.tag_applier."
            "record_writeback",
        ):
            apply_selection_tags(
                [_selected(pid="p1")],
                [_product("p1", tags=["existing"])],
            )
        params = router.execute.call_args.args[1]
        assert set(params["tags"]) == {
            "existing", "selection:approved",
        }

    def test_no_pid_skipped(self):
        with patch(
            "engines.selection_decision.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.selection_decision.tag_applier."
            "record_writeback",
        ):
            results = apply_selection_tags(
                [{}],
                [_product("p1")],
            )
        assert results == []

    def test_all_tags_exist_no_op(self):
        router = _ok_router("p1")
        with patch(
            "engines.selection_decision.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.selection_decision.tag_applier."
            "record_writeback",
        ):
            results = apply_selection_tags(
                [_selected(pid="p1")],
                [_product("p1", tags=["selection:approved"])],
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "no_new_tags"
        router.execute.assert_not_called()


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.selection_decision.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.selection_decision.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_selection_tags(
                [_selected(pid="p1")],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "selection_decision"
        assert kw["action_type"] == "apply_selection_tags"
        assert kw["success"] is True

    def test_failure_records(self):
        with patch(
            "engines.selection_decision.tag_applier._get_router",
            return_value=_fail_router(),
        ), patch(
            "engines.selection_decision.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_selection_tags(
                [_selected(pid="p1")],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False


class TestRouterUnavailable:

    def test_returns_skipped_per_selected(self):
        with patch(
            "engines.selection_decision.tag_applier._get_router",
            return_value=None,
        ), patch(
            "engines.selection_decision.tag_applier."
            "record_writeback",
        ):
            results = apply_selection_tags(
                [_selected(pid="p1"), _selected(pid="p2")],
                [_product("p1"), _product("p2")],
            )
        assert len(results) == 2
        for r in results:
            assert r["applied"] is False
            assert r["error"] == "router_unavailable"


class TestFlowOptIn:

    def _seed_input(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "ranked_products": [
                    {
                        "product_id": "p1",
                        "id": "p1",
                        "title": "Widget",
                        "price": 50, "cost": 20,
                        "margin": 0.6,
                        "demand_score": 70,
                        "competition_score": 50,
                        "risk_level": "low",
                        "composite_score": 80,
                        "rank": 1,
                        "tags": [],
                    },
                ],
                "apply_selection_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.selection_decision.flow import (
            SelectionDecisionEngine,
        )
        with patch(
            "engines.selection_decision.tag_applier."
            "apply_selection_tags",
        ) as apply_mock:
            result = SelectionDecisionEngine().run(
                self._seed_input(apply_tags=False),
            )
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_selected"] == []

    def test_opt_in_invokes_applier(self):
        from engines.selection_decision.flow import (
            SelectionDecisionEngine,
        )
        with patch(
            "engines.selection_decision.tag_applier."
            "apply_selection_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 1, "merged_tags": [],
                    "error": None,
                },
            ],
        ) as apply_mock:
            result = SelectionDecisionEngine().run(
                self._seed_input(apply_tags=True),
            )
        apply_mock.assert_called_once()
        assert result["data"]["tagged_selected"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.selection_decision.flow import (
            SelectionDecisionEngine,
        )
        with patch(
            "engines.selection_decision.tag_applier."
            "apply_selection_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = SelectionDecisionEngine().run(
                self._seed_input(apply_tags=True),
            )
        assert result["status"] == "success"
        assert result["data"]["tagged_selected"] == []
