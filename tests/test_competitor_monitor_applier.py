"""Tests for engines.competitor_monitor.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.competitor_monitor.tag_applier import apply_undercut_tags


def _change(pid="p1", pct=-10.0, direction="competitor_lower", **extra):
    return {
        "product_id": pid,
        "change_pct": pct,
        "direction": direction,
        "competitor": extra.pop("competitor", "comp1"),
        **extra,
    }


def _product(pid, tags=None):
    return {"product_id": pid, "tags": list(tags or [])}


def _ok_router(applied_pid):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": applied_pid, "tags": []},
        error=None,
    )
    return router


class TestDirectionFilter:

    def test_competitor_lower_tagged(self):
        with patch(
            "engines.competitor_monitor.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.competitor_monitor.tag_applier.record_writeback",
        ):
            results = apply_undercut_tags(
                [_change(pid="p1", pct=-10.0)],
                [_product("p1")],
            )
        assert len(results) == 1
        assert results[0]["applied"] is True

    def test_competitor_higher_skipped(self):
        with patch(
            "engines.competitor_monitor.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.competitor_monitor.tag_applier.record_writeback",
        ):
            results = apply_undercut_tags(
                [_change(pid="p1", pct=10.0, direction="competitor_higher")],
                [_product("p1")],
            )
        assert results == []


class TestThreshold:

    def test_below_threshold_skipped(self):
        with patch(
            "engines.competitor_monitor.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.competitor_monitor.tag_applier.record_writeback",
        ):
            results = apply_undercut_tags(
                [_change(pid="p1", pct=-3.0)],
                [_product("p1")],
            )
        assert results == []

    def test_dedup_worst_per_product(self):
        router = _ok_router("p1")
        with patch(
            "engines.competitor_monitor.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.competitor_monitor.tag_applier.record_writeback",
        ):
            results = apply_undercut_tags(
                [
                    _change(pid="p1", pct=-8.0, competitor="a"),
                    _change(pid="p1", pct=-20.0, competitor="b"),
                    _change(pid="p1", pct=-12.0, competitor="c"),
                ],
                [_product("p1")],
            )
        # only one Shopify call
        assert router.execute.call_count == 1
        assert len(results) == 1
        # severe threshold (20%) applies
        assert results[0]["undercut_pct"] == 20.0


class TestTagComposition:

    def test_severe_only_above_threshold(self):
        router = _ok_router("p1")
        with patch(
            "engines.competitor_monitor.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.competitor_monitor.tag_applier.record_writeback",
        ):
            apply_undercut_tags(
                [_change(pid="p1", pct=-20.0)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "competitor:undercut" in params["tags"]
        assert "competitor:severe_undercut" in params["tags"]

    def test_undercut_only_below_severe(self):
        router = _ok_router("p1")
        with patch(
            "engines.competitor_monitor.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.competitor_monitor.tag_applier.record_writeback",
        ):
            apply_undercut_tags(
                [_change(pid="p1", pct=-8.0)],
                [_product("p1")],
            )
        params = router.execute.call_args.args[1]
        assert "competitor:undercut" in params["tags"]
        assert "competitor:severe_undercut" not in params["tags"]


class TestPatternZ:

    def test_success_records_with_competitor(self):
        with patch(
            "engines.competitor_monitor.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.competitor_monitor.tag_applier.record_writeback",
        ) as record_mock:
            apply_undercut_tags(
                [_change(pid="p1", pct=-10.0, competitor="big_box")],
                [_product("p1")],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "competitor_monitor"
        assert kw["action_type"] == "apply_undercut_tags"
        assert kw["success"] is True
        assert kw["params"]["competitor"] == "big_box"


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "competitors": [
                    {
                        "name": "comp1",
                        "products": [
                            {"product_id": "p1", "title": "Widget", "price": 80.0},
                        ],
                    },
                ],
                "our_products": [
                    {"product_id": "p1", "title": "Widget", "price": 100.0, "tags": []},
                ],
                "apply_undercut_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.competitor_monitor.flow import CompetitorMonitorEngine
        with patch(
            "engines.competitor_monitor.tag_applier.apply_undercut_tags",
        ) as apply_mock:
            result = CompetitorMonitorEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_undercut"] == []

    def test_opt_in_invokes_applier(self):
        from engines.competitor_monitor.flow import CompetitorMonitorEngine
        with patch(
            "engines.competitor_monitor.tag_applier.apply_undercut_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 1, "merged_tags": [],
                    "undercut_pct": 20.0, "error": None,
                },
            ],
        ) as apply_mock:
            result = CompetitorMonitorEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_undercut"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.competitor_monitor.flow import CompetitorMonitorEngine
        with patch(
            "engines.competitor_monitor.tag_applier.apply_undercut_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = CompetitorMonitorEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_undercut"] == []
