"""Tests for engines.review_management.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.review_management.tag_applier import apply_review_health_tags


def _ok_router(applied_pid):
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": applied_pid, "tags": []},
        error=None,
    )
    return router


class TestSignalCollection:

    def test_poor_rating_fires_with_enough_reviews(self):
        with patch(
            "engines.review_management.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.review_management.tag_applier.record_writeback",
        ):
            r = apply_review_health_tags(
                product_id="p1",
                summary={"avg_rating": 2.5, "total_reviews": 10},
                sentiment={},
                trend={},
            )
        assert r["applied"] is True
        assert "poor_rating" in r["signals"]
        assert "reviews:poor_rating" in r["merged_tags"]

    def test_poor_rating_blocked_by_min_reviews(self):
        # Only 2 reviews -> no poor_rating signal
        with patch(
            "engines.review_management.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.review_management.tag_applier.record_writeback",
        ):
            r = apply_review_health_tags(
                product_id="p1",
                summary={"avg_rating": 1.5, "total_reviews": 2},
                sentiment={},
                trend={},
            )
        assert r["applied"] is False
        assert r["error"] == "no_health_signals"

    def test_negative_sentiment_fires(self):
        with patch(
            "engines.review_management.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.review_management.tag_applier.record_writeback",
        ):
            r = apply_review_health_tags(
                product_id="p1",
                summary={},
                sentiment={"negative_pct": 60.0},
                trend={},
            )
        assert "negative_sentiment" in r["signals"]
        assert "reviews:negative_sentiment" in r["merged_tags"]

    def test_declining_fires(self):
        with patch(
            "engines.review_management.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.review_management.tag_applier.record_writeback",
        ):
            r = apply_review_health_tags(
                product_id="p1",
                summary={},
                sentiment={},
                trend={"direction": "declining"},
            )
        assert "declining" in r["signals"]
        assert "reviews:declining" in r["merged_tags"]

    def test_signals_stack(self):
        with patch(
            "engines.review_management.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.review_management.tag_applier.record_writeback",
        ):
            r = apply_review_health_tags(
                product_id="p1",
                summary={"avg_rating": 2.0, "total_reviews": 20},
                sentiment={"negative_pct": 70.0},
                trend={"direction": "declining"},
            )
        assert set(r["signals"]) == {
            "poor_rating", "negative_sentiment", "declining",
        }
        assert r["tags_added"] == 3


class TestNoSignalsSkipped:

    def test_healthy_product_skipped(self):
        with patch(
            "engines.review_management.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ):
            r = apply_review_health_tags(
                product_id="p1",
                summary={"avg_rating": 4.5, "total_reviews": 50},
                sentiment={"negative_pct": 5.0},
                trend={"direction": "improving"},
            )
        assert r["applied"] is False
        assert r["error"] == "no_health_signals"


class TestMerge:

    def test_existing_tags_preserved(self):
        router = _ok_router("p1")
        with patch(
            "engines.review_management.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.review_management.tag_applier.record_writeback",
        ):
            apply_review_health_tags(
                product_id="p1",
                summary={"avg_rating": 2.0, "total_reviews": 10},
                sentiment={},
                trend={},
                existing_tags=["best_seller"],
            )
        params = router.execute.call_args.args[1]
        assert "best_seller" in params["tags"]
        assert "reviews:poor_rating" in params["tags"]


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.review_management.tag_applier._get_router",
            return_value=_ok_router("p1"),
        ), patch(
            "engines.review_management.tag_applier.record_writeback",
        ) as record_mock:
            apply_review_health_tags(
                product_id="p1",
                summary={"avg_rating": 2.0, "total_reviews": 10},
                sentiment={},
                trend={},
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "review_management"
        assert kw["action_type"] == "apply_review_health_tags"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        reviews = [
            {"id": f"r{i}", "rating": 1, "text": "terrible", "date": "2026-05-01"}
            for i in range(8)
        ]
        return {
            "status": "success",
            "data": {
                "product_id": "p1",
                "reviews": reviews,
                "apply_review_health_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.review_management.flow import ReviewManagementEngine
        with patch(
            "engines.review_management.tag_applier.apply_review_health_tags",
        ) as apply_mock:
            result = ReviewManagementEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_review_health"] == {}

    def test_opt_in_invokes_applier(self):
        from engines.review_management.flow import ReviewManagementEngine
        with patch(
            "engines.review_management.tag_applier.apply_review_health_tags",
            return_value={
                "product_id": "p1", "applied": True,
                "tags_added": 1, "merged_tags": [],
                "signals": ["poor_rating"], "error": None,
            },
        ) as apply_mock:
            result = ReviewManagementEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_review_health"]["applied"] is True

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.review_management.flow import ReviewManagementEngine
        with patch(
            "engines.review_management.tag_applier.apply_review_health_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = ReviewManagementEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_review_health"] == {}
