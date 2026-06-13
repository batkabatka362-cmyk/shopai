"""Tests for engines.stock_prediction.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engines.stock_prediction.tag_applier import (
    apply_restock_tags,
)


def _pred(pid="p1", restock_qty=10, **extra):
    return {"product_id": pid, "restock_qty": restock_qty, **extra}


def _product(pid, tags=None):
    return {"id": pid, "tags": list(tags or [])}


def _ok_router(applied_pid):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": applied_pid, "tags": []},
        error=None,
    )
    return router


class TestRestockFilter:

    def test_restock_qty_positive_tagged(self):
        with patch(
            "engines.stock_prediction.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.stock_prediction.tag_applier.record_writeback",
        ):
            results = apply_restock_tags(
                [_pred(pid="p1", restock_qty=20)],
                [_product("p1")],
            )
        assert results[0]["applied"] is True

    @pytest.mark.parametrize("qty", [0, -5, "invalid"])
    def test_no_restock_silently_skipped(self, qty):
        with patch(
            "engines.stock_prediction.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.stock_prediction.tag_applier.record_writeback",
        ):
            results = apply_restock_tags(
                [_pred(pid="p1", restock_qty=qty)],
                [_product("p1")],
            )
        assert results == []


class TestTagComposition:

    def test_single_restock_tag(self):
        router = _ok_router("p1")
        with patch(
            "engines.stock_prediction.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.stock_prediction.tag_applier.record_writeback",
        ):
            apply_restock_tags(
                [_pred(pid="p1", restock_qty=5)],
                [_product("p1", tags=["existing"])],
            )
        params = router.execute.call_args.args[1]
        assert set(params["tags"]) == {
            "existing", "stock:restock_recommended",
        }


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.stock_prediction.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.stock_prediction.tag_applier.record_writeback",
        ) as record_mock:
            apply_restock_tags(
                [_pred(pid="p1", restock_qty=10)],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "stock_prediction"
        assert kw["action_type"] == "apply_restock_tags"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "products": [
                    {
                        "id": "p1", "title": "Widget",
                        "current_stock": 5,
                        "sales_history": [
                            {"date": "2026-05-01", "qty": 2},
                            {"date": "2026-05-02", "qty": 3},
                        ],
                        "tags": [],
                    },
                ],
                "apply_restock_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.stock_prediction.flow import (
            StockPredictionEngine,
        )
        with patch(
            "engines.stock_prediction.tag_applier.apply_restock_tags",
        ) as apply_mock:
            result = StockPredictionEngine().run(
                self._seed(apply_tags=False),
            )
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_restock"] == []

    def test_opt_in_invokes_applier(self):
        from engines.stock_prediction.flow import (
            StockPredictionEngine,
        )
        with patch(
            "engines.stock_prediction.tag_applier.apply_restock_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 1, "merged_tags": [],
                    "error": None,
                },
            ],
        ) as apply_mock:
            result = StockPredictionEngine().run(
                self._seed(apply_tags=True),
            )
        apply_mock.assert_called_once()
        assert result["data"]["tagged_restock"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.stock_prediction.flow import (
            StockPredictionEngine,
        )
        with patch(
            "engines.stock_prediction.tag_applier.apply_restock_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = StockPredictionEngine().run(
                self._seed(apply_tags=True),
            )
        assert result["status"] == "success"
        assert result["data"]["tagged_restock"] == []
