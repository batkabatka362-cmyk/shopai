"""Tests for engines.order_quality.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.order_quality.tag_applier import apply_defect_rate_tags


def _rate(pid="p1", rate=0.12, entity_type="product", **extra):
    return {
        "entity": pid,
        "entity_type": entity_type,
        "defect_rate": rate,
        "defect_count": extra.pop("defect_count", 1),
        "total_orders": extra.pop("total_orders", 10),
        **extra,
    }


def _order(items=None):
    return {"id": "o1", "items": items or []}


def _ok_router(applied_pid):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": applied_pid, "tags": []},
        error=None,
    )
    return router


class TestEntityTypeFilter:

    def test_supplier_entries_skipped(self):
        with patch(
            "engines.order_quality.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.order_quality.tag_applier.record_writeback",
        ):
            results = apply_defect_rate_tags(
                [_rate(pid="sup1", entity_type="supplier", rate=0.30)],
                [_order()],
            )
        assert results == []

    def test_product_entries_tagged(self):
        with patch(
            "engines.order_quality.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.order_quality.tag_applier.record_writeback",
        ):
            results = apply_defect_rate_tags(
                [_rate(pid="p1", entity_type="product", rate=0.12)],
                [_order()],
            )
        assert len(results) == 1
        assert results[0]["applied"] is True


class TestThreshold:

    def test_high_defect_tagged(self):
        router = _ok_router("p1")
        with patch(
            "engines.order_quality.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.order_quality.tag_applier.record_writeback",
        ):
            apply_defect_rate_tags(
                [_rate(pid="p1", rate=0.15)],
                [_order()],
            )
        params = router.execute.call_args.args[1]
        assert "quality:high_defect" in params["tags"]

    def test_medium_defect_tagged(self):
        router = _ok_router("p1")
        with patch(
            "engines.order_quality.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.order_quality.tag_applier.record_writeback",
        ):
            apply_defect_rate_tags(
                [_rate(pid="p1", rate=0.07)],
                [_order()],
            )
        params = router.execute.call_args.args[1]
        assert "quality:medium_defect" in params["tags"]

    def test_low_defect_skipped(self):
        with patch(
            "engines.order_quality.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.order_quality.tag_applier.record_writeback",
        ):
            results = apply_defect_rate_tags(
                [_rate(pid="p1", rate=0.02)],
                [_order()],
            )
        assert results == []


class TestMerge:

    def test_existing_tags_preserved(self):
        router = _ok_router("p1")
        with patch(
            "engines.order_quality.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.order_quality.tag_applier.record_writeback",
        ):
            apply_defect_rate_tags(
                [_rate(pid="p1", rate=0.12)],
                [_order(items=[
                    {"product_id": "p1", "tags": ["best_seller"]},
                ])],
            )
        params = router.execute.call_args.args[1]
        assert "best_seller" in params["tags"]
        assert "quality:high_defect" in params["tags"]


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.order_quality.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.order_quality.tag_applier.record_writeback",
        ) as record_mock:
            apply_defect_rate_tags(
                [_rate(pid="p1", rate=0.12)],
                [_order()],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "order_quality"
        assert kw["action_type"] == "apply_defect_rate_tags"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "orders": [
                    {
                        "id": "o1", "supplier_id": "sup1",
                        "items": [{"product_id": "p1", "tags": []}],
                    },
                    {
                        "id": "o2", "supplier_id": "sup1",
                        "items": [{"product_id": "p1", "tags": []}],
                    },
                ],
                "defects": [
                    {"order_id": "o1", "product_id": "p1", "type": "broken"},
                    {"order_id": "o2", "product_id": "p1", "type": "missing"},
                ],
                "suppliers": [],
                "apply_defect_rate_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.order_quality.flow import OrderQualityEngine
        with patch(
            "engines.order_quality.tag_applier.apply_defect_rate_tags",
        ) as apply_mock:
            result = OrderQualityEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_defect_rates"] == []

    def test_opt_in_invokes_applier(self):
        from engines.order_quality.flow import OrderQualityEngine
        with patch(
            "engines.order_quality.tag_applier.apply_defect_rate_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 1, "merged_tags": [],
                    "defect_rate": 1.0, "error": None,
                },
            ],
        ) as apply_mock:
            result = OrderQualityEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_defect_rates"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.order_quality.flow import OrderQualityEngine
        with patch(
            "engines.order_quality.tag_applier.apply_defect_rate_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = OrderQualityEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_defect_rates"] == []
