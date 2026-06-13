"""Tests for engines.customer_effort_score.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.customer_effort_score.tag_applier import apply_high_effort_tags


def _score(cid="c1", effort=6.0, **extra):
    return {
        "customer_id": cid,
        "effort_score": effort,
        **extra,
    }


def _ok_router():
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": "c1", "tags": []}, error=None,
    )
    return router


class TestThreshold:

    def test_high_effort_tagged(self):
        with patch(
            "engines.customer_effort_score.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.customer_effort_score.tag_applier.record_writeback",
        ):
            results = apply_high_effort_tags([
                _score(cid="c1", effort=6.0),
            ])
        assert len(results) == 1
        assert results[0]["applied"] is True

    def test_low_effort_skipped(self):
        with patch(
            "engines.customer_effort_score.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.customer_effort_score.tag_applier.record_writeback",
        ):
            results = apply_high_effort_tags([
                _score(cid="c1", effort=2.0),
            ])
        assert results == []

    def test_boundary_5(self):
        # exactly 5 should fire (>= threshold)
        with patch(
            "engines.customer_effort_score.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.customer_effort_score.tag_applier.record_writeback",
        ):
            results = apply_high_effort_tags([
                _score(cid="c1", effort=5.0),
            ])
        assert len(results) == 1


class TestAggregation:

    def test_avg_across_interactions(self):
        # c1: avg=6 (qualifies), c2: avg=2 (skipped)
        router = _ok_router()
        with patch(
            "engines.customer_effort_score.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.customer_effort_score.tag_applier.record_writeback",
        ):
            results = apply_high_effort_tags([
                _score(cid="c1", effort=5.0),
                _score(cid="c1", effort=7.0),
                _score(cid="c2", effort=2.0),
            ])
        assert len(results) == 1
        assert results[0]["customer_id"] == "c1"
        assert results[0]["avg_effort_score"] == 6.0

    def test_mixed_interactions_avg_below_threshold(self):
        # avg = (3+4)/2 = 3.5, below threshold
        with patch(
            "engines.customer_effort_score.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.customer_effort_score.tag_applier.record_writeback",
        ):
            results = apply_high_effort_tags([
                _score(cid="c1", effort=3.0),
                _score(cid="c1", effort=4.0),
            ])
        assert results == []


class TestTagFormat:

    def test_tag_emitted(self):
        router = _ok_router()
        with patch(
            "engines.customer_effort_score.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.customer_effort_score.tag_applier.record_writeback",
        ):
            apply_high_effort_tags([_score(cid="c1", effort=6.0)])
        params = router.execute.call_args.args[1]
        assert params["tags"] == ["ces:high_effort"]
        assert params["id"] == "c1"


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.customer_effort_score.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.customer_effort_score.tag_applier.record_writeback",
        ) as record_mock:
            apply_high_effort_tags([_score(cid="c1", effort=6.0)])
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "customer_effort_score"
        assert kw["action_type"] == "apply_high_effort_tags"
        assert kw["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "interactions": [
                    {
                        "customer_id": "c1", "touchpoint": "checkout",
                        "steps_taken": 12, "time_spent": 500,
                        "resolved": False,
                    },
                ],
                "apply_high_effort_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.customer_effort_score.flow import CustomerEffortScoreEngine
        with patch(
            "engines.customer_effort_score.tag_applier.apply_high_effort_tags",
        ) as apply_mock:
            result = CustomerEffortScoreEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_high_effort"] == []

    def test_opt_in_invokes_applier(self):
        from engines.customer_effort_score.flow import CustomerEffortScoreEngine
        with patch(
            "engines.customer_effort_score.tag_applier.apply_high_effort_tags",
            return_value=[
                {
                    "customer_id": "c1", "avg_effort_score": 6.5,
                    "applied": True, "error": None,
                },
            ],
        ) as apply_mock:
            result = CustomerEffortScoreEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_high_effort"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.customer_effort_score.flow import CustomerEffortScoreEngine
        with patch(
            "engines.customer_effort_score.tag_applier.apply_high_effort_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = CustomerEffortScoreEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_high_effort"] == []
