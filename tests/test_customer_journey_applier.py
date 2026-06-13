"""Tests for engines.customer_journey.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.customer_journey.tag_applier import apply_journey_tags


def _journey(cid="c1", stage="purchase", **extra):
    return {
        "customer_id": cid,
        "furthest_stage": stage,
        **extra,
    }


def _ok_router():
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": "c1", "tags": []},
        error=None,
    )
    return router


class TestBasic:

    def test_each_valid_stage_tagged(self):
        router = _ok_router()
        with patch(
            "engines.customer_journey.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.customer_journey.tag_applier.record_writeback",
        ):
            results = apply_journey_tags([
                _journey(cid="c1", stage="awareness"),
                _journey(cid="c2", stage="consideration"),
                _journey(cid="c3", stage="purchase"),
                _journey(cid="c4", stage="retention"),
            ])
        assert len(results) == 4
        assert all(r["applied"] for r in results)
        assert {r["stage"] for r in results} == {
            "awareness", "consideration", "purchase", "retention",
        }

    def test_tag_format(self):
        router = _ok_router()
        with patch(
            "engines.customer_journey.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.customer_journey.tag_applier.record_writeback",
        ):
            apply_journey_tags([_journey(cid="c1", stage="retention")])
        params = router.execute.call_args.args[1]
        assert params["tags"] == ["journey:retention"]
        assert params["id"] == "c1"

    def test_none_stage_skipped(self):
        with patch(
            "engines.customer_journey.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.customer_journey.tag_applier.record_writeback",
        ):
            results = apply_journey_tags([
                _journey(cid="c1", stage="none"),
                _journey(cid="c2", stage="purchase"),
            ])
        assert len(results) == 1
        assert results[0]["customer_id"] == "c2"

    def test_invalid_stage_skipped(self):
        with patch(
            "engines.customer_journey.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.customer_journey.tag_applier.record_writeback",
        ):
            results = apply_journey_tags([
                _journey(cid="c1", stage="nonsense"),
                _journey(cid="c2", stage="awareness"),
            ])
        assert len(results) == 1
        assert results[0]["customer_id"] == "c2"

    def test_blank_customer_id_skipped(self):
        with patch(
            "engines.customer_journey.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.customer_journey.tag_applier.record_writeback",
        ):
            results = apply_journey_tags([
                _journey(cid="", stage="purchase"),
                _journey(cid="c1", stage="purchase"),
            ])
        assert len(results) == 1
        assert results[0]["customer_id"] == "c1"

    def test_empty_returns_empty(self):
        assert apply_journey_tags([]) == []


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.customer_journey.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.customer_journey.tag_applier.record_writeback",
        ) as record_mock:
            apply_journey_tags([_journey(cid="c1", stage="retention")])
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "customer_journey"
        assert kw["action_type"] == "apply_journey_tags"
        assert kw["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kw["success"] is True


class TestRouterUnavailable:

    def test_router_none_emits_skip_results(self):
        with patch(
            "engines.customer_journey.tag_applier._get_router",
            return_value=None,
        ):
            results = apply_journey_tags([
                _journey(cid="c1", stage="awareness"),
                _journey(cid="c2", stage="purchase"),
                _journey(cid="c3", stage="none"),  # filtered out
            ])
        # Only the two with valid stages
        assert len(results) == 2
        assert all(r["error"] == "router_unavailable" for r in results)


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        # Events that drive each customer through stages
        events = [
            {"customer_id": "c1", "event_type": "page_view", "timestamp": 1.0},
            {"customer_id": "c1", "event_type": "order_complete", "timestamp": 2.0},
            {"customer_id": "c2", "event_type": "product_view", "timestamp": 3.0},
        ]
        return {
            "status": "success",
            "data": {
                "customers": [{"id": "c1"}, {"id": "c2"}],
                "events": events,
                "touchpoints": [],
                "conversions": [],
                "apply_journey_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.customer_journey.flow import CustomerJourneyEngine
        with patch(
            "engines.customer_journey.tag_applier.apply_journey_tags",
        ) as apply_mock:
            result = CustomerJourneyEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_journey"] == []

    def test_opt_in_invokes_applier(self):
        from engines.customer_journey.flow import CustomerJourneyEngine
        with patch(
            "engines.customer_journey.tag_applier.apply_journey_tags",
            return_value=[
                {
                    "customer_id": "c1", "stage": "purchase",
                    "applied": True, "error": None,
                },
            ],
        ) as apply_mock:
            result = CustomerJourneyEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_journey"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.customer_journey.flow import CustomerJourneyEngine
        with patch(
            "engines.customer_journey.tag_applier.apply_journey_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = CustomerJourneyEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_journey"] == []
