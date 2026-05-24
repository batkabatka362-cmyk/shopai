"""Tests for engines.product_risk.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engines.product_risk.tag_applier import apply_risk_tags


def _risk(pid="p1", level="high", **extra):
    return {"product_id": pid, "risk_level": level, **extra}


def _product(pid, tags=None):
    return {"id": pid, "tags": list(tags or [])}


def _ok_router(applied_pid):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": applied_pid, "tags": []},
        error=None,
    )
    return router


class TestRiskFilter:

    @pytest.mark.parametrize("level", ["high", "critical"])
    def test_taggable_levels(self, level):
        with patch(
            "engines.product_risk.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_risk.tag_applier.record_writeback",
        ):
            results = apply_risk_tags(
                [_risk(pid="p1", level=level)],
                [_product("p1")],
            )
        assert results[0]["applied"] is True
        assert results[0]["risk_level"] == level

    @pytest.mark.parametrize("level", ["low", "moderate", "", "unknown"])
    def test_safe_levels_silently_skipped(self, level):
        with patch(
            "engines.product_risk.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_risk.tag_applier.record_writeback",
        ):
            results = apply_risk_tags(
                [_risk(pid="p1", level=level)],
                [_product("p1")],
            )
        assert results == []


class TestTagComposition:

    def test_high_risk_tag_composition(self):
        router = _ok_router("p1")
        with patch(
            "engines.product_risk.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_risk.tag_applier.record_writeback",
        ):
            apply_risk_tags(
                [_risk(pid="p1", level="high")],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert set(params["tags"]) == {"risk:high", "risk:high"} or set(params["tags"]) == {"risk:high"}
        # The generic "risk:high" tag + level-specific "risk:high"
        # collapse to one when level == "high"
        assert "risk:high" in params["tags"]

    def test_critical_risk_tag_composition(self):
        router = _ok_router("p1")
        with patch(
            "engines.product_risk.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.product_risk.tag_applier.record_writeback",
        ):
            apply_risk_tags(
                [_risk(pid="p1", level="critical")],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "risk:high" in params["tags"]
        assert "risk:critical" in params["tags"]


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.product_risk.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.product_risk.tag_applier.record_writeback",
        ) as record_mock:
            apply_risk_tags(
                [_risk(pid="p1", level="critical")],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "product_risk"
        assert kw["action_type"] == "apply_risk_tags"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "products": [
                    {
                        "id": "p1", "title": "Widget",
                        "price": 100, "tags": [],
                    },
                ],
                "apply_risk_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.product_risk.flow import ProductRiskEngine
        with patch(
            "engines.product_risk.tag_applier.apply_risk_tags",
        ) as apply_mock:
            result = ProductRiskEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_high_risk"] == []

    def test_opt_in_invokes_applier(self):
        from engines.product_risk.flow import ProductRiskEngine
        with patch(
            "engines.product_risk.tag_applier.apply_risk_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 2, "merged_tags": [],
                    "risk_level": "high", "error": None,
                },
            ],
        ) as apply_mock:
            result = ProductRiskEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_high_risk"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.product_risk.flow import ProductRiskEngine
        with patch(
            "engines.product_risk.tag_applier.apply_risk_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = ProductRiskEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_high_risk"] == []
