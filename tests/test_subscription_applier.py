"""Tests for engines.subscription.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.subscription.tag_applier import apply_churn_risk_tags


def _risk(sid="c1", level="high", **extra):
    return {"subscriber_id": sid, "risk_level": level, **extra}


def _ok_router():
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": "c1", "tags": []}, error=None,
    )
    return router


class TestLevelFilter:

    def test_high_tagged(self):
        with patch(
            "engines.subscription.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.subscription.tag_applier.record_writeback",
        ):
            results = apply_churn_risk_tags([_risk(level="high")])
        assert len(results) == 1
        assert results[0]["applied"] is True

    def test_medium_tagged(self):
        with patch(
            "engines.subscription.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.subscription.tag_applier.record_writeback",
        ):
            results = apply_churn_risk_tags([_risk(level="medium")])
        assert len(results) == 1
        assert results[0]["applied"] is True

    def test_low_skipped(self):
        with patch(
            "engines.subscription.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.subscription.tag_applier.record_writeback",
        ):
            results = apply_churn_risk_tags([_risk(level="low")])
        assert results == []

    def test_minimal_skipped(self):
        with patch(
            "engines.subscription.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.subscription.tag_applier.record_writeback",
        ):
            results = apply_churn_risk_tags([_risk(level="minimal")])
        assert results == []


class TestTagFormat:

    def test_high_tag_format(self):
        router = _ok_router()
        with patch(
            "engines.subscription.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.subscription.tag_applier.record_writeback",
        ):
            apply_churn_risk_tags([_risk(sid="c1", level="high")])
        params = router.execute.call_args.args[1]
        assert params["tags"] == ["subscription:churn_high"]
        assert params["id"] == "c1"

    def test_medium_tag_format(self):
        router = _ok_router()
        with patch(
            "engines.subscription.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.subscription.tag_applier.record_writeback",
        ):
            apply_churn_risk_tags([_risk(sid="c2", level="medium")])
        params = router.execute.call_args.args[1]
        assert params["tags"] == ["subscription:churn_medium"]


class TestEmpty:

    def test_empty_list_returns_empty(self):
        assert apply_churn_risk_tags([]) == []

    def test_all_low_returns_empty(self):
        with patch(
            "engines.subscription.tag_applier._get_router",
            return_value=_ok_router(),
        ):
            results = apply_churn_risk_tags([
                _risk(sid="c1", level="low"),
                _risk(sid="c2", level="minimal"),
            ])
        assert results == []


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.subscription.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.subscription.tag_applier.record_writeback",
        ) as record_mock:
            apply_churn_risk_tags([_risk(sid="c1", level="high")])
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "subscription"
        assert kw["action_type"] == "apply_churn_risk_tags"
        assert kw["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "subscribers": [
                    {
                        "id": "c1", "status": "past_due",
                        "join_date": "2026-04-01",
                    },
                ],
                "plans": [{"id": "plan1", "name": "Basic", "price": 10}],
                "billing_history": [
                    {"subscriber_id": "c1", "status": "failed"},
                    {"subscriber_id": "c1", "status": "failed"},
                ],
                "products": [],
                "apply_churn_risk_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.subscription.flow import SubscriptionEngine
        with patch(
            "engines.subscription.tag_applier.apply_churn_risk_tags",
        ) as apply_mock:
            result = SubscriptionEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_churn_risks"] == []

    def test_opt_in_invokes_applier(self):
        from engines.subscription.flow import SubscriptionEngine
        with patch(
            "engines.subscription.tag_applier.apply_churn_risk_tags",
            return_value=[
                {
                    "subscriber_id": "c1", "risk_level": "high",
                    "applied": True, "error": None,
                },
            ],
        ) as apply_mock:
            result = SubscriptionEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_churn_risks"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.subscription.flow import SubscriptionEngine
        with patch(
            "engines.subscription.tag_applier.apply_churn_risk_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = SubscriptionEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_churn_risks"] == []
