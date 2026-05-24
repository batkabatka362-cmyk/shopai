"""Tests for engines.warranty.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.warranty.tag_applier import apply_warranty_risk_tags


def _risk(pid="p1", level="high", rate=15.0, **extra):
    return {
        "product_id": pid,
        "risk_level": level,
        "claim_rate_pct": rate,
        "claim_count": extra.pop("claim_count", 3),
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


class TestLevelFilter:

    def test_high_tagged(self):
        with patch(
            "engines.warranty.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.warranty.tag_applier.record_writeback",
        ):
            results = apply_warranty_risk_tags(
                [_risk(pid="p1", level="high")],
                [_product("p1")],
            )
        assert len(results) == 1
        assert results[0]["applied"] is True

    def test_medium_tagged(self):
        with patch(
            "engines.warranty.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.warranty.tag_applier.record_writeback",
        ):
            results = apply_warranty_risk_tags(
                [_risk(pid="p1", level="medium")],
                [_product("p1")],
            )
        assert len(results) == 1
        assert results[0]["applied"] is True

    def test_low_skipped(self):
        with patch(
            "engines.warranty.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.warranty.tag_applier.record_writeback",
        ):
            results = apply_warranty_risk_tags(
                [_risk(pid="p1", level="low", rate=2.0)],
                [_product("p1")],
            )
        assert results == []


class TestTagFormat:

    def test_high_format(self):
        router = _ok_router("p1")
        with patch(
            "engines.warranty.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.warranty.tag_applier.record_writeback",
        ):
            apply_warranty_risk_tags(
                [_risk(pid="p1", level="high")],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "warranty:high_risk" in params["tags"]

    def test_medium_format(self):
        router = _ok_router("p1")
        with patch(
            "engines.warranty.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.warranty.tag_applier.record_writeback",
        ):
            apply_warranty_risk_tags(
                [_risk(pid="p1", level="medium")],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "warranty:medium_risk" in params["tags"]


class TestMerge:

    def test_existing_tags_preserved(self):
        router = _ok_router("p1")
        with patch(
            "engines.warranty.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.warranty.tag_applier.record_writeback",
        ):
            apply_warranty_risk_tags(
                [_risk(pid="p1", level="high")],
                [_product("p1", tags=["existing"])],
            )
        params = router.execute.call_args.args[1]
        assert "existing" in params["tags"]
        assert "warranty:high_risk" in params["tags"]


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.warranty.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.warranty.tag_applier.record_writeback",
        ) as record_mock:
            apply_warranty_risk_tags(
                [_risk(pid="p1", level="high")],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "warranty"
        assert kw["action_type"] == "apply_warranty_risk_tags"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "products": [
                    {"id": "p1", "title": "Widget", "tags": [], "quantity_sold": 100},
                ],
                "claims": [
                    {"id": f"cl{i}", "product_id": "p1", "status": "approved"}
                    for i in range(15)
                ],
                "policies": [],
                "apply_warranty_risk_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.warranty.flow import WarrantyEngine
        with patch(
            "engines.warranty.tag_applier.apply_warranty_risk_tags",
        ) as apply_mock:
            result = WarrantyEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_warranty_risks"] == []

    def test_opt_in_invokes_applier(self):
        from engines.warranty.flow import WarrantyEngine
        with patch(
            "engines.warranty.tag_applier.apply_warranty_risk_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 1, "merged_tags": [],
                    "risk_level": "high", "claim_rate_pct": 15.0,
                    "error": None,
                },
            ],
        ) as apply_mock:
            result = WarrantyEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_warranty_risks"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.warranty.flow import WarrantyEngine
        with patch(
            "engines.warranty.tag_applier.apply_warranty_risk_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = WarrantyEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_warranty_risks"] == []
