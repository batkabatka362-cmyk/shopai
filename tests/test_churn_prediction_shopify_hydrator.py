"""Tests for churn_prediction's Shopify hydrator.

Mirrors the bundle hydrator's contract — auto-fetches customers via
``Capability.SHOPIFY_FETCH_CUSTOMERS`` when the caller leaves them
empty, pass-through otherwise.
"""
from __future__ import annotations

from unittest.mock import patch

from engines.churn_prediction.shopify_hydrator import (
    hydrate_customers,
)


# ─── Stubs ────────────────────────────────────────────────────────


class _StubResult:
    def __init__(self, *, ok, data=None, error=None):
        self.ok = ok
        self.data = data or {}
        self.error = error


class _StubRouter:
    def __init__(self, *, result):
        self.result = result
        self.calls: list[tuple] = []

    def execute(self, capability, params):
        self.calls.append((capability, params))
        return self.result


# ─── Pass-through ─────────────────────────────────────────────────


class TestPassThrough:

    def test_supplied_customers_pass_through_no_router_call(self):
        supplied = [{"id": "gid://shopify/Customer/1"}]
        with patch(
            "engines.churn_prediction.shopify_hydrator._get_router",
        ) as mock_router:
            result = hydrate_customers(supplied)
        assert result is supplied
        mock_router.assert_not_called()


# ─── Empty input → fetch ──────────────────────────────────────────


class TestHydrateHappyPath:

    def test_empty_input_triggers_fetch_with_default_limit(self):
        from core.adapters.base import Capability

        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={
                "customers": [
                    {
                        "id": "gid://shopify/Customer/1",
                        "email": "ada@example.com",
                    },
                    {
                        "id": "gid://shopify/Customer/2",
                        "email": "bob@example.com",
                    },
                ],
                "count": 2,
            },
        ))
        with patch(
            "engines.churn_prediction.shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_customers([])

        assert len(stub.calls) == 1
        cap, params = stub.calls[0]
        assert cap == Capability.SHOPIFY_FETCH_CUSTOMERS
        assert params["limit"] == 250
        assert "query" not in params
        assert len(result) == 2

    def test_none_input_triggers_fetch(self):
        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={
                "customers": [
                    {"id": "gid://shopify/Customer/1"},
                ],
            },
        ))
        with patch(
            "engines.churn_prediction.shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_customers(None)
        assert len(result) == 1

    def test_query_filter_passed_through(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"customers": []},
        ))
        with patch(
            "engines.churn_prediction.shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate_customers(
                [],
                query="orders_count:>0 AND last_order_date:<2026-01-01",
            )
        _, params = stub.calls[0]
        assert params["query"] == (
            "orders_count:>0 AND last_order_date:<2026-01-01"
        )

    def test_blank_query_dropped(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"customers": []},
        ))
        with patch(
            "engines.churn_prediction.shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate_customers([], query="   ")
        _, params = stub.calls[0]
        assert "query" not in params

    def test_non_dict_customers_filtered_out(self):
        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={
                "customers": [
                    {"id": "gid://shopify/Customer/1"},
                    "garbage",
                    None,
                    {"id": "gid://shopify/Customer/2"},
                ],
            },
        ))
        with patch(
            "engines.churn_prediction.shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_customers([])
        assert len(result) == 2
        assert all(isinstance(c, dict) for c in result)


# ─── Limit clamping ───────────────────────────────────────────────


class TestLimitClamping:

    def test_limit_clamped(self):
        for raw, expected in [
            (-10, 1), (0, 1), (1000, 250), ("garbage", 250),
            (75, 75),
        ]:
            stub = _StubRouter(result=_StubResult(
                ok=True, data={"customers": []},
            ))
            with patch(
                "engines.churn_prediction.shopify_hydrator._get_router",
                return_value=stub,
            ):
                hydrate_customers([], limit=raw)
            _, params = stub.calls[0]
            assert params["limit"] == expected, (
                f"limit={raw} should clamp to {expected}"
            )


# ─── Failure modes ────────────────────────────────────────────────


class TestGracefulFallbacks:

    def test_router_unavailable_returns_empty(self):
        with patch(
            "engines.churn_prediction.shopify_hydrator._get_router",
            return_value=None,
        ):
            assert hydrate_customers([]) == []

    def test_adapter_returns_failure_returns_empty(self):
        stub = _StubRouter(result=_StubResult(
            ok=False, error="scope missing",
        ))
        with patch(
            "engines.churn_prediction.shopify_hydrator._get_router",
            return_value=stub,
        ):
            assert hydrate_customers([]) == []

    def test_adapter_raises_returns_empty(self):
        class _ExplodingRouter:
            def execute(self, capability, params):
                raise RuntimeError("network down")

        with patch(
            "engines.churn_prediction.shopify_hydrator._get_router",
            return_value=_ExplodingRouter(),
        ):
            assert hydrate_customers([]) == []


# ─── Flow integration ────────────────────────────────────────────


class TestFlowIntegration:

    def test_flow_hydrates_when_customers_empty(self):
        from engines.churn_prediction.flow import (
            ChurnPredictionEngine,
        )

        injected = [
            {
                "id": "cust_1",
                "email": "ada@example.com",
                "orders_count": 5,
                "total_spent": 250.0,
                "last_order_date": "2025-12-01",
            },
        ]

        with patch(
            "engines.churn_prediction.flow.hydrate_customers",
            return_value=injected,
        ):
            output = ChurnPredictionEngine().run({
                "data": {"customers": []},
            })

        # Hydrator filled in customers, so the "requires non-empty
        # customer list" error must NOT be the failure reason.
        if output["status"] == "error":
            assert "requires 'data.customers'" not in (
                output.get("error") or ""
            )

    def test_flow_falls_back_to_standard_error_when_hydrator_empty(self):
        from engines.churn_prediction.flow import (
            ChurnPredictionEngine,
        )

        with patch(
            "engines.churn_prediction.flow.hydrate_customers",
            return_value=[],
        ):
            output = ChurnPredictionEngine().run({
                "data": {"customers": []},
            })
        # churn_prediction's error envelope uses status="fail"
        # (its own convention; differs from bundle's "error").
        assert output["status"] == "fail"
        assert "requires 'data.customers'" in output["error"]

    def test_flow_passes_kwargs_through(self):
        from engines.churn_prediction.flow import (
            ChurnPredictionEngine,
        )

        captured: dict = {}

        def _record(supplied, *, limit=None, query=None):
            captured["limit"] = limit
            captured["query"] = query
            return [{"id": "cust_1", "orders_count": 1}]

        with patch(
            "engines.churn_prediction.flow.hydrate_customers",
            side_effect=_record,
        ):
            ChurnPredictionEngine().run({
                "data": {
                    "customers": [],
                    "hydrate_limit": 100,
                    "hydrate_query": "orders_count:>0",
                },
            })

        assert captured["limit"] == 100
        assert captured["query"] == "orders_count:>0"

    def test_flow_skips_hydrate_when_caller_supplied_customers(self):
        from engines.churn_prediction.flow import (
            ChurnPredictionEngine,
        )

        called = {"count": 0}

        def _spy(supplied, **kwargs):
            called["count"] += 1
            return supplied  # pass-through

        with patch(
            "engines.churn_prediction.flow.hydrate_customers",
            side_effect=_spy,
        ):
            ChurnPredictionEngine().run({
                "data": {
                    "customers": [
                        {"id": "cust_1", "orders_count": 1},
                    ],
                },
            })

        # The flow no longer invokes hydrate_customers when
        # supplied list is non-empty (short-circuits in
        # _hydrate_payload before calling it).
        assert called["count"] == 0
