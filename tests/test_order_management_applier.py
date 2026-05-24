"""Tests for engines.order_management.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.order_management.tag_applier import apply_fraud_tags


def _ok_router():
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": "o1", "tags": []}, error=None,
    )
    return router


class TestLevelMapping:

    def test_high_to_high_risk(self):
        router = _ok_router()
        with patch(
            "engines.order_management.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.order_management.tag_applier.record_writeback",
        ):
            r = apply_fraud_tags(
                order_id="o1",
                fraud_screen={"risk_level": "high", "recommendation": "review"},
            )
        assert r["applied"] is True
        assert r["tag"] == "fraud:high_risk"
        params = router.execute.call_args.args[1]
        assert params["tags"] == ["fraud:high_risk"]
        assert params["id"] == "o1"

    def test_medium_to_review(self):
        router = _ok_router()
        with patch(
            "engines.order_management.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.order_management.tag_applier.record_writeback",
        ):
            r = apply_fraud_tags(
                order_id="o1",
                fraud_screen={"risk_level": "medium", "recommendation": "review"},
            )
        assert r["applied"] is True
        assert r["tag"] == "fraud:review"

    def test_low_skipped(self):
        with patch(
            "engines.order_management.tag_applier._get_router",
            return_value=_ok_router(),
        ):
            r = apply_fraud_tags(
                order_id="o1",
                fraud_screen={"risk_level": "low", "recommendation": "approve"},
            )
        assert r["applied"] is False
        assert r["error"] == "low_or_unknown_risk"

    def test_unknown_skipped(self):
        with patch(
            "engines.order_management.tag_applier._get_router",
            return_value=_ok_router(),
        ):
            r = apply_fraud_tags(
                order_id="o1",
                fraud_screen={"risk_level": "unknown"},
            )
        assert r["applied"] is False
        assert r["error"] == "low_or_unknown_risk"


class TestEmptyOrderId:

    def test_empty_oid_returns_skip(self):
        r = apply_fraud_tags(
            order_id="",
            fraud_screen={"risk_level": "high"},
        )
        assert r["applied"] is False
        assert r["error"] == "no_order_id"


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.order_management.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.order_management.tag_applier.record_writeback",
        ) as record_mock:
            apply_fraud_tags(
                order_id="o1",
                fraud_screen={"risk_level": "high"},
            )
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "order_management"
        assert kw["action_type"] == "apply_fraud_tags"
        assert kw["capability"] == "SHOPIFY_TAG_ORDER"
        assert kw["success"] is True


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False, reject=False):
        # An order that triggers medium-risk: new customer + free
        # email + total > $500. Must pass validation first.
        order: dict = {
            "id": "o1",
            "email": "test@gmail.com",
            "total_price": 800,
            "customer": {"id": "c1", "orders_count": 0},
            "shipping_address": {
                "address1": "123 Main St",
                "city": "Springfield",
                "country": "US",
                "country_code": "US",
            },
            "billing_address": {
                "address1": "123 Main St",
                "city": "Springfield",
                "country": "US",
                "country_code": "US",
            },
            "line_items": [
                {"product_id": "p1", "quantity": 1, "price": 800},
            ],
        }
        return {
            "status": "success",
            "data": {
                "order": order,
                "apply_fraud_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.order_management.flow import OrderManagementEngine
        with patch(
            "engines.order_management.tag_applier.apply_fraud_tags",
        ) as apply_mock:
            result = OrderManagementEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        # tagged_fraud key exists; value may be {} or missing
        assert result["data"].get("tagged_fraud", {}) == {}

    def test_opt_in_invokes_applier(self):
        from engines.order_management.flow import OrderManagementEngine
        with patch(
            "engines.order_management.tag_applier.apply_fraud_tags",
            return_value={
                "order_id": "o1", "applied": True,
                "tag": "fraud:review", "risk_level": "medium",
                "error": None,
            },
        ) as apply_mock:
            result = OrderManagementEngine().run(self._seed(apply_tags=True))
        # Engine reaches non-reject path -> applier called once
        apply_mock.assert_called_once()
        assert result["data"]["tagged_fraud"]["applied"] is True

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.order_management.flow import OrderManagementEngine
        with patch(
            "engines.order_management.tag_applier.apply_fraud_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = OrderManagementEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"].get("tagged_fraud", {}) == {}
