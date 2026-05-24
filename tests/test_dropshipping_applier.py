"""Tests for engines.dropshipping.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.dropshipping.tag_applier import apply_thin_margin_tags


def _m(pid="p1", pct=10.0, sup="sup1", **extra):
    return {
        "product_id": pid,
        "supplier_id": sup,
        "margin_pct": pct,
        "cost": extra.pop("cost", 5.0),
        "selling_price": extra.pop("selling_price", 10.0),
        "margin": extra.pop("margin", 5.0),
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

    def test_thin_below_15(self):
        router = _ok_router("p1")
        with patch(
            "engines.dropshipping.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.dropshipping.tag_applier.record_writeback",
        ):
            apply_thin_margin_tags(
                [_m(pid="p1", pct=10.0)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "margin:thin" in params["tags"]

    def test_tight_15_to_25(self):
        router = _ok_router("p1")
        with patch(
            "engines.dropshipping.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.dropshipping.tag_applier.record_writeback",
        ):
            apply_thin_margin_tags(
                [_m(pid="p1", pct=20.0)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "margin:tight" in params["tags"]

    def test_healthy_skipped(self):
        with patch(
            "engines.dropshipping.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.dropshipping.tag_applier.record_writeback",
        ):
            results = apply_thin_margin_tags(
                [_m(pid="p1", pct=30.0)],
                [_product("p1")],
            )
        assert results == []


class TestDedup:

    def test_worst_per_product_wins(self):
        # Product sourced from 2 suppliers: 22% and 10% -> tag with thin (worst)
        router = _ok_router("p1")
        with patch(
            "engines.dropshipping.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.dropshipping.tag_applier.record_writeback",
        ):
            results = apply_thin_margin_tags(
                [
                    _m(pid="p1", pct=22.0, sup="sup1"),
                    _m(pid="p1", pct=10.0, sup="sup2"),
                ],
                [_product("p1")],
            )
        # Only one Shopify call
        assert router.execute.call_count == 1
        assert len(results) == 1
        assert results[0]["margin_pct"] == 10.0
        params = router.execute.call_args.args[1]
        assert "margin:thin" in params["tags"]


class TestMerge:

    def test_existing_tags_preserved(self):
        router = _ok_router("p1")
        with patch(
            "engines.dropshipping.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.dropshipping.tag_applier.record_writeback",
        ):
            apply_thin_margin_tags(
                [_m(pid="p1", pct=10.0)],
                [_product("p1", tags=["best_seller"])],
            )
        params = router.execute.call_args.args[1]
        assert "best_seller" in params["tags"]
        assert "margin:thin" in params["tags"]


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.dropshipping.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.dropshipping.tag_applier.record_writeback",
        ) as record_mock:
            apply_thin_margin_tags(
                [_m(pid="p1", pct=10.0)],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "dropshipping"
        assert kw["action_type"] == "apply_thin_margin_tags"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "orders": [
                    {
                        "id": "o1", "items": [
                            {"product_id": "p1", "unit_cost": 8.0, "quantity": 1},
                        ],
                        "supplier_id": "sup1",
                    },
                ],
                "products": [
                    {"id": "p1", "title": "Widget", "tags": [], "price": 10.0},
                ],
                "suppliers": [
                    {"id": "sup1", "name": "S1", "products": ["p1"]},
                ],
                "tracking_data": [],
                "apply_thin_margin_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.dropshipping.flow import DropshippingEngine
        with patch(
            "engines.dropshipping.tag_applier.apply_thin_margin_tags",
        ) as apply_mock:
            result = DropshippingEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_thin_margin"] == []

    def test_opt_in_invokes_applier(self):
        from engines.dropshipping.flow import DropshippingEngine
        with patch(
            "engines.dropshipping.tag_applier.apply_thin_margin_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 1, "merged_tags": [],
                    "margin_pct": 10.0, "error": None,
                },
            ],
        ) as apply_mock:
            result = DropshippingEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_thin_margin"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.dropshipping.flow import DropshippingEngine
        with patch(
            "engines.dropshipping.tag_applier.apply_thin_margin_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = DropshippingEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_thin_margin"] == []
