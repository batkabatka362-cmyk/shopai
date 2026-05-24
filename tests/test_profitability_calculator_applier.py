"""Tests for engines.profitability_calculator.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.profitability_calculator.tag_applier import apply_roi_tags


def _p(pid="p1", roi=250.0, **extra):
    return {
        "product_id": pid,
        "roi": roi,
        "revenue": extra.pop("revenue", 100.0),
        "total_cost": extra.pop("total_cost", 30.0),
        "net_margin": extra.pop("net_margin", 70.0),
        "break_even_units": extra.pop("break_even_units", 5),
        **extra,
    }


def _product(pid, tags=None):
    return {"id": pid, "tags": list(tags or [])}


def _ok_router(applied_pid):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": applied_pid, "tags": []},
        error=None,
    )
    return router


class TestThreshold:

    def test_high_roi_tagged(self):
        router = _ok_router("p1")
        with patch(
            "engines.profitability_calculator.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.profitability_calculator.tag_applier.record_writeback",
        ):
            apply_roi_tags(
                [_p(pid="p1", roi=300.0)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "profit:high_roi" in params["tags"]

    def test_low_roi_tagged(self):
        router = _ok_router("p1")
        with patch(
            "engines.profitability_calculator.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.profitability_calculator.tag_applier.record_writeback",
        ):
            apply_roi_tags(
                [_p(pid="p1", roi=20.0)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "profit:low_roi" in params["tags"]

    def test_midband_skipped(self):
        with patch(
            "engines.profitability_calculator.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.profitability_calculator.tag_applier.record_writeback",
        ):
            results = apply_roi_tags(
                [_p(pid="p1", roi=100.0)],
                [_product("p1")],
            )
        assert results == []


class TestBoundaries:

    def test_boundary_200_high(self):
        # >= 200 fires
        router = _ok_router("p1")
        with patch(
            "engines.profitability_calculator.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.profitability_calculator.tag_applier.record_writeback",
        ):
            apply_roi_tags(
                [_p(pid="p1", roi=200.0)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "profit:high_roi" in params["tags"]

    def test_boundary_30_low(self):
        # <= 30 fires
        router = _ok_router("p1")
        with patch(
            "engines.profitability_calculator.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.profitability_calculator.tag_applier.record_writeback",
        ):
            apply_roi_tags(
                [_p(pid="p1", roi=30.0)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "profit:low_roi" in params["tags"]


class TestMerge:

    def test_existing_tags_preserved(self):
        router = _ok_router("p1")
        with patch(
            "engines.profitability_calculator.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.profitability_calculator.tag_applier.record_writeback",
        ):
            apply_roi_tags(
                [_p(pid="p1", roi=300.0)],
                [_product("p1", tags=["best_seller"])],
            )
        params = router.execute.call_args.args[1]
        assert "best_seller" in params["tags"]
        assert "profit:high_roi" in params["tags"]


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.profitability_calculator.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.profitability_calculator.tag_applier.record_writeback",
        ) as record_mock:
            apply_roi_tags(
                [_p(pid="p1", roi=300.0)],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "profitability_calculator"
        assert kw["action_type"] == "apply_roi_tags"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "products": [
                    {
                        "id": "p1", "title": "Widget", "tags": [],
                        "units_sold": 100, "price": 100.0,
                    },
                ],
                "costs": [
                    {"product_id": "p1", "category": "cogs", "amount": 30.0},
                ],
                "pricing": [
                    {"product_id": "p1", "price": 100.0},
                ],
                "apply_roi_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.profitability_calculator.flow import ProfitabilityCalculatorEngine
        with patch(
            "engines.profitability_calculator.tag_applier.apply_roi_tags",
        ) as apply_mock:
            result = ProfitabilityCalculatorEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_roi"] == []

    def test_opt_in_invokes_applier(self):
        from engines.profitability_calculator.flow import ProfitabilityCalculatorEngine
        with patch(
            "engines.profitability_calculator.tag_applier.apply_roi_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 1, "merged_tags": [],
                    "roi": 300.0, "tag": "profit:high_roi",
                    "error": None,
                },
            ],
        ) as apply_mock:
            result = ProfitabilityCalculatorEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_roi"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.profitability_calculator.flow import ProfitabilityCalculatorEngine
        with patch(
            "engines.profitability_calculator.tag_applier.apply_roi_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = ProfitabilityCalculatorEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_roi"] == []
