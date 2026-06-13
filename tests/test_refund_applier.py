"""Tests for engines.returns_management.refund_applier."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.returns_management.refund_applier import (
    _fraud_risk_by_return,
    _lookup_parent_transaction,
    apply_refunds,
)


def _ok(data=None):
    return SimpleNamespace(ok=True, data=data or {}, error=None)


def _fail(error="adapter said no"):
    return SimpleNamespace(ok=False, data=None, error=error)


class TestFraudRiskIndex:

    def test_indexes_by_return_id(self):
        flags = [
            {"return_id": "r1", "risk_score": 0.7},
            {"return_id": "r2", "risk_score": 0.2},
        ]
        idx = _fraud_risk_by_return(flags)
        assert idx["r1"] == 0.7
        assert idx["r2"] == 0.2

    def test_tolerates_missing_or_bad_rows(self):
        flags = [
            {"return_id": "r1", "risk_score": "not_a_number"},
            "not_a_dict",
            {"risk_score": 0.5},  # missing return_id
            {"return_id": "r3", "risk_score": 0.4},
        ]
        idx = _fraud_risk_by_return(flags)
        # Bad rows skipped; r1 falls to 0 on parse error
        assert idx["r1"] == 0.0
        assert idx["r3"] == 0.4
        assert len(idx) == 2


class TestParentTransactionLookup:

    def test_picks_first_non_refund_transaction(self):
        router = MagicMock()
        router.execute.return_value = _ok({
            "transactions": [
                {
                    "id": "gid://shopify/OrderTransaction/T1",
                    "kind": "SALE",
                },
                {
                    "id": "gid://shopify/OrderTransaction/T2",
                    "kind": "REFUND",
                },
            ],
        })
        cap = object()  # opaque sentinel; never inspected
        parent, err = _lookup_parent_transaction(
            router, cap, "o1",
        )
        assert parent == (
            "gid://shopify/OrderTransaction/T1"
        )
        assert err == ""

    def test_skips_refund_and_void_kinds(self):
        router = MagicMock()
        router.execute.return_value = _ok({
            "transactions": [
                {"id": "T1", "kind": "REFUND"},
                {"id": "T2", "kind": "VOID"},
                {"id": "T3", "kind": "CAPTURE"},
            ],
        })
        parent, err = _lookup_parent_transaction(
            router, object(), "o1",
        )
        assert parent == "T3"

    def test_no_transactions_returns_error(self):
        router = MagicMock()
        router.execute.return_value = _ok({"transactions": []})
        parent, err = _lookup_parent_transaction(
            router, object(), "o1",
        )
        assert parent is None
        assert err == "no_parent_transaction"

    def test_router_failure_returns_error(self):
        router = MagicMock()
        router.execute.return_value = _fail()
        parent, err = _lookup_parent_transaction(
            router, object(), "o1",
        )
        assert parent is None
        assert err == "order_lookup_failed"

    def test_router_raises_returns_error(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("net down")
        parent, err = _lookup_parent_transaction(
            router, object(), "o1",
        )
        assert parent is None
        assert err == "order_lookup_failed"

    def test_router_or_cap_none_returns_router_unavailable(
        self,
    ):
        parent, err = _lookup_parent_transaction(
            None, object(), "o1",
        )
        assert parent is None
        assert err == "router_unavailable"


class TestSafetyGates:

    def _processed(
        self,
        *,
        status="approved",
        refund_amount=50.0,
        order_id="o1",
        return_id="r1",
    ):
        return [{
            "return_id": return_id,
            "order_id": order_id,
            "status": status,
            "refund_amount": refund_amount,
        }]

    def test_skips_when_not_approved(self):
        out = apply_refunds(
            self._processed(status="rejected"),
            fraud_flags=[],
        )
        assert out[0]["applied"] is False
        assert out[0]["status"] == "not_approved"

    def test_skips_when_zero_refund_amount(self):
        out = apply_refunds(
            self._processed(refund_amount=0),
            fraud_flags=[],
        )
        assert out[0]["status"] == "zero_refund_amount"

    def test_skips_when_exceeds_max_amount(self):
        out = apply_refunds(
            self._processed(refund_amount=1000.0),
            fraud_flags=[],
            max_amount=500.0,
        )
        assert out[0]["status"] == "exceeds_max_amount"
        assert "1000" in out[0]["error"]
        assert "500" in out[0]["error"]

    def test_skips_when_fraud_risk_too_high(self):
        out = apply_refunds(
            self._processed(),
            fraud_flags=[
                {"return_id": "r1", "risk_score": 0.8},
            ],
            max_fraud_risk=0.5,
        )
        assert out[0]["status"] == "fraud_risk_too_high"

    def test_skips_when_no_order_id(self):
        out = apply_refunds(
            self._processed(order_id=""),
            fraud_flags=[],
        )
        assert out[0]["status"] == "no_order_id"


class TestHappyPath:

    def test_refund_applied_when_all_gates_pass(self):
        processed = [{
            "return_id": "r1",
            "order_id": "o1",
            "status": "approved",
            "refund_amount": 25.0,
        }]
        # Patch router + capability resolution
        fake_router = MagicMock()
        # First call (GET_ORDER) returns transactions; second
        # call (CREATE_REFUND) returns OK
        fake_router.execute.side_effect = [
            _ok({
                "transactions": [
                    {"id": "gid://T1", "kind": "SALE"},
                ],
            }),
            _ok({"refund_id": "gid://R1"}),
        ]
        with patch(
            "engines.returns_management.refund_applier._get_router",
            return_value=fake_router,
        ), patch(
            "engines.returns_management.refund_applier._capability",
            return_value=object(),
        ), patch(
            "engines.returns_management.refund_applier.record_writeback",
        ) as rec_mock:
            out = apply_refunds(processed, fraud_flags=[])
        assert out[0]["applied"] is True
        assert out[0]["status"] == "recorded"
        # Recorder fired
        rec_mock.assert_called_once()
        # Two router calls -- order lookup + refund issue
        assert fake_router.execute.call_count == 2

    def test_adapter_failure_records_skip(self):
        processed = [{
            "return_id": "r1",
            "order_id": "o1",
            "status": "approved",
            "refund_amount": 25.0,
        }]
        fake_router = MagicMock()
        fake_router.execute.side_effect = [
            _ok({
                "transactions": [
                    {"id": "gid://T1", "kind": "SALE"},
                ],
            }),
            _fail("userError: amount mismatch"),
        ]
        with patch(
            "engines.returns_management.refund_applier._get_router",
            return_value=fake_router,
        ), patch(
            "engines.returns_management.refund_applier._capability",
            return_value=object(),
        ):
            out = apply_refunds(processed, fraud_flags=[])
        assert out[0]["applied"] is False
        assert out[0]["status"] == "adapter_failed"
        assert "amount mismatch" in out[0]["error"]


class TestPerRowIsolation:
    """A bad row must not stop the applier from processing the
    rest."""

    def test_mixed_rows_each_get_their_own_outcome(self):
        processed = [
            {  # gate fail: zero amount
                "return_id": "r0",
                "order_id": "o0",
                "status": "approved",
                "refund_amount": 0,
            },
            {  # gate fail: above cap
                "return_id": "r1",
                "order_id": "o1",
                "status": "approved",
                "refund_amount": 9999.0,
            },
            {  # would-succeed, but no router
                "return_id": "r2",
                "order_id": "o2",
                "status": "approved",
                "refund_amount": 25.0,
            },
        ]
        with patch(
            "engines.returns_management.refund_applier._get_router",
            return_value=None,  # no router -> last row hits
        ):
            out = apply_refunds(
                processed, fraud_flags=[], max_amount=500.0,
            )
        assert len(out) == 3
        assert out[0]["status"] == "zero_refund_amount"
        assert out[1]["status"] == "exceeds_max_amount"
        assert out[2]["status"] == "router_unavailable"
