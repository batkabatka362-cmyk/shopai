"""Tests for engines.audience_targeting.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.audience_targeting.tag_applier import apply_audience_tags


def _match(seg_id="high_value", customer_ids=None, **extra):
    return {
        "segment_id": seg_id,
        "matched_customer_ids": list(customer_ids or []),
        **extra,
    }


def _ok_router():
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": "c1", "tags": []}, error=None,
    )
    return router


class TestBasic:

    def test_each_customer_per_segment_tagged(self):
        router = _ok_router()
        with patch(
            "engines.audience_targeting.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.audience_targeting.tag_applier.record_writeback",
        ):
            results = apply_audience_tags([
                _match(seg_id="high_value", customer_ids=["c1", "c2"]),
                _match(seg_id="frequent_buyers", customer_ids=["c1"]),
            ])
        assert len(results) == 3
        # c1 appears twice (matches both segments)
        c1_matches = [r for r in results if r["customer_id"] == "c1"]
        assert len(c1_matches) == 2
        assert {r["segment_id"] for r in c1_matches} == {
            "high_value", "frequent_buyers",
        }

    def test_tag_format(self):
        router = _ok_router()
        with patch(
            "engines.audience_targeting.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.audience_targeting.tag_applier.record_writeback",
        ):
            apply_audience_tags([
                _match(seg_id="at_risk", customer_ids=["c1"]),
            ])
        params = router.execute.call_args.args[1]
        assert params["tags"] == ["audience:at_risk"]
        assert params["id"] == "c1"

    def test_empty_returns_empty(self):
        assert apply_audience_tags([]) == []

    def test_blank_segment_id_skipped(self):
        with patch(
            "engines.audience_targeting.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.audience_targeting.tag_applier.record_writeback",
        ):
            results = apply_audience_tags([
                _match(seg_id="", customer_ids=["c1"]),
                _match(seg_id="vip", customer_ids=["c2"]),
            ])
        assert len(results) == 1
        assert results[0]["segment_id"] == "vip"

    def test_blank_customer_id_skipped(self):
        with patch(
            "engines.audience_targeting.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.audience_targeting.tag_applier.record_writeback",
        ):
            results = apply_audience_tags([
                _match(seg_id="vip", customer_ids=["", "c1"]),
            ])
        assert len(results) == 1
        assert results[0]["customer_id"] == "c1"


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.audience_targeting.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.audience_targeting.tag_applier.record_writeback",
        ) as record_mock:
            apply_audience_tags([_match(seg_id="vip", customer_ids=["c1"])])
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "audience_targeting"
        assert kw["action_type"] == "apply_audience_tags"
        assert kw["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kw["success"] is True

    def test_failure_records(self):
        router = MagicMock()
        router.execute.return_value = SimpleNamespace(
            ok=False, data=None, error="adapter_rejected",
        )
        with patch(
            "engines.audience_targeting.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.audience_targeting.tag_applier.record_writeback",
        ) as record_mock:
            results = apply_audience_tags(
                [_match(seg_id="vip", customer_ids=["c1"])],
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["success"] is False
        assert results[0]["applied"] is False


class TestRouterUnavailable:

    def test_router_none_emits_skip_results(self):
        with patch(
            "engines.audience_targeting.tag_applier._get_router",
            return_value=None,
        ):
            results = apply_audience_tags([
                _match(seg_id="vip", customer_ids=["c1", "c2"]),
            ])
        assert len(results) == 2
        assert all(r["error"] == "router_unavailable" for r in results)


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "customers": [
                    {
                        "id": "c1", "total_spent": 5000, "total_orders": 5,
                        "last_order_date": "2026-05-15",
                    },
                    {
                        "id": "c2", "total_spent": 500, "total_orders": 1,
                        "last_order_date": "2026-05-10",
                    },
                ],
                "orders": [],
                "segments": [],  # use defaults
                "campaign_goal": "conversion",
                "apply_audience_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.audience_targeting.flow import AudienceTargetingEngine
        with patch(
            "engines.audience_targeting.tag_applier.apply_audience_tags",
        ) as apply_mock:
            result = AudienceTargetingEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_audiences"] == []

    def test_opt_in_invokes_applier(self):
        from engines.audience_targeting.flow import AudienceTargetingEngine
        with patch(
            "engines.audience_targeting.tag_applier.apply_audience_tags",
            return_value=[
                {
                    "customer_id": "c1", "segment_id": "high_value",
                    "applied": True, "error": None,
                },
            ],
        ) as apply_mock:
            result = AudienceTargetingEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_audiences"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.audience_targeting.flow import AudienceTargetingEngine
        with patch(
            "engines.audience_targeting.tag_applier.apply_audience_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = AudienceTargetingEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_audiences"] == []
