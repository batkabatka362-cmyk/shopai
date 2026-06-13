"""Tests for engines.behavioral_data.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.behavioral_data.tag_applier import apply_engagement_tags


def _summary(pid="p1", views=200, ctr=0.15, **extra):
    clicks = int(views * ctr) if views > 0 else 0
    return {
        "product_id": pid,
        "views": views,
        "clicks": extra.pop("clicks", clicks),
        "click_through_rate": ctr,
        **extra,
    }


def _ok_router(applied_pid):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": applied_pid, "tags": []},
        error=None,
    )
    return router


class TestThreshold:

    def test_low_views_skipped(self):
        with patch(
            "engines.behavioral_data.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.behavioral_data.tag_applier.record_writeback",
        ):
            results = apply_engagement_tags(
                [_summary(views=50, ctr=0.20)],
            )
        assert results == []


class TestTagComposition:

    def test_hot_above_high_ctr(self):
        router = _ok_router("p1")
        with patch(
            "engines.behavioral_data.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.behavioral_data.tag_applier.record_writeback",
        ):
            apply_engagement_tags(
                [_summary(views=200, ctr=0.15)],
            )
        params = router.execute.call_args.args[1]
        assert "engagement:hot" in params["tags"]
        assert "engagement:high_view_low_ctr" not in params["tags"]

    def test_low_ctr_with_high_views(self):
        router = _ok_router("p1")
        with patch(
            "engines.behavioral_data.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.behavioral_data.tag_applier.record_writeback",
        ):
            apply_engagement_tags(
                [_summary(views=500, ctr=0.02)],
            )
        params = router.execute.call_args.args[1]
        assert "engagement:high_view_low_ctr" in params["tags"]
        assert "engagement:hot" not in params["tags"]

    def test_midband_ctr_skipped(self):
        # ctr=0.07 is between low (0.05) and hot (0.10)
        with patch(
            "engines.behavioral_data.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.behavioral_data.tag_applier.record_writeback",
        ):
            results = apply_engagement_tags(
                [_summary(views=200, ctr=0.07)],
            )
        assert results == []


class TestMerge:

    def test_existing_tags_preserved(self):
        router = _ok_router("p1")
        with patch(
            "engines.behavioral_data.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.behavioral_data.tag_applier.record_writeback",
        ):
            apply_engagement_tags(
                [_summary(pid="p1", views=200, ctr=0.15)],
                product_views=[
                    {"product_id": "p1", "tags": ["best_seller"]},
                ],
            )
        params = router.execute.call_args.args[1]
        assert "best_seller" in params["tags"]
        assert "engagement:hot" in params["tags"]


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.behavioral_data.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.behavioral_data.tag_applier.record_writeback",
        ) as record_mock:
            apply_engagement_tags(
                [_summary(views=200, ctr=0.15)],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "behavioral_data"
        assert kw["action_type"] == "apply_engagement_tags"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "sessions": [{"id": "s1", "duration": 120}],
                "events": [
                    {"product_id": "p1", "type": "click"}
                    for _ in range(50)
                ] + [
                    {"product_id": "p1", "type": "add_to_cart"}
                    for _ in range(20)
                ],
                "product_views": [
                    {"product_id": "p1"} for _ in range(200)
                ],
                "apply_engagement_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.behavioral_data.flow import BehavioralDataEngine
        with patch(
            "engines.behavioral_data.tag_applier.apply_engagement_tags",
        ) as apply_mock:
            result = BehavioralDataEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_engagement"] == []

    def test_opt_in_invokes_applier(self):
        from engines.behavioral_data.flow import BehavioralDataEngine
        with patch(
            "engines.behavioral_data.tag_applier.apply_engagement_tags",
            return_value=[
                {
                    "product_id": "p1", "applied": True,
                    "tags_added": 1, "merged_tags": [],
                    "views": 200, "ctr": 0.15, "tag": "engagement:hot",
                    "error": None,
                },
            ],
        ) as apply_mock:
            result = BehavioralDataEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_engagement"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.behavioral_data.flow import BehavioralDataEngine
        with patch(
            "engines.behavioral_data.tag_applier.apply_engagement_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = BehavioralDataEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_engagement"] == []
