"""Tests for cohort_analysis's Shopify hydrator (customers + orders)."""
from __future__ import annotations

from unittest.mock import patch

from engines.cohort_analysis.shopify_hydrator import (
    hydrate_customers,
    hydrate_orders,
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

    def test_supplied_customers_pass_through(self):
        supplied = [{"id": "gid://shopify/Customer/1"}]
        with patch(
            "engines.cohort_analysis.shopify_hydrator._get_router",
        ) as mock_router:
            result = hydrate_customers(supplied)
        assert result is supplied
        mock_router.assert_not_called()

    def test_supplied_orders_pass_through(self):
        supplied = [{"id": "gid://shopify/Order/1"}]
        with patch(
            "engines.cohort_analysis.shopify_hydrator._get_router",
        ) as mock_router:
            result = hydrate_orders(supplied)
        assert result is supplied
        mock_router.assert_not_called()


# ─── Empty input → fetch ──────────────────────────────────────────


class TestHydrateHappyPath:

    def test_customers_routed_to_fetch_customers_capability(self):
        from core.adapters.base import Capability

        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={
                "customers": [
                    {
                        "id": "gid://shopify/Customer/1",
                        "created_at": "2025-09-01",
                    },
                ],
            },
        ))
        with patch(
            "engines.cohort_analysis.shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_customers([])

        cap, _ = stub.calls[0]
        assert cap == Capability.SHOPIFY_FETCH_CUSTOMERS
        assert len(result) == 1

    def test_orders_routed_to_fetch_orders_capability(self):
        from core.adapters.base import Capability

        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={
                "orders": [
                    {
                        "id": "gid://shopify/Order/1",
                        "created_at": "2025-09-15",
                    },
                ],
            },
        ))
        with patch(
            "engines.cohort_analysis.shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_orders([])

        cap, _ = stub.calls[0]
        assert cap == Capability.SHOPIFY_FETCH_ORDERS
        assert len(result) == 1

    def test_query_filter_passed_through_for_customers(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"customers": []},
        ))
        with patch(
            "engines.cohort_analysis.shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate_customers(
                [], query="created_at:>2025-01-01",
            )
        _, params = stub.calls[0]
        assert params["query"] == "created_at:>2025-01-01"

    def test_query_filter_passed_through_for_orders(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"orders": []},
        ))
        with patch(
            "engines.cohort_analysis.shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate_orders(
                [], query="created_at:>2025-01-01",
            )
        _, params = stub.calls[0]
        assert params["query"] == "created_at:>2025-01-01"

    def test_blank_query_dropped(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"customers": []},
        ))
        with patch(
            "engines.cohort_analysis.shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate_customers([], query="   ")
        _, params = stub.calls[0]
        assert "query" not in params

    def test_non_dict_items_filtered(self):
        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={
                "customers": [
                    {"id": "gid://shopify/Customer/1"},
                    "garbage",
                    None,
                ],
            },
        ))
        with patch(
            "engines.cohort_analysis.shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_customers([])
        assert len(result) == 1


# ─── Limit clamp ──────────────────────────────────────────────────


class TestLimitClamp:

    def test_limit_clamp_matrix(self):
        for raw, expected in [
            (-1, 1), (0, 1), (1000, 250), ("garbage", 250),
            (75, 75),
        ]:
            stub = _StubRouter(result=_StubResult(
                ok=True, data={"customers": []},
            ))
            with patch(
                "engines.cohort_analysis.shopify_hydrator._get_router",
                return_value=stub,
            ):
                hydrate_customers([], limit=raw)
            _, params = stub.calls[0]
            assert params["limit"] == expected


# ─── Failure modes ────────────────────────────────────────────────


class TestGracefulFallbacks:

    def test_router_unavailable_returns_empty_for_customers(self):
        with patch(
            "engines.cohort_analysis.shopify_hydrator._get_router",
            return_value=None,
        ):
            assert hydrate_customers([]) == []

    def test_router_unavailable_returns_empty_for_orders(self):
        with patch(
            "engines.cohort_analysis.shopify_hydrator._get_router",
            return_value=None,
        ):
            assert hydrate_orders([]) == []

    def test_adapter_returns_failure_returns_empty(self):
        stub = _StubRouter(result=_StubResult(
            ok=False, error="scope missing",
        ))
        with patch(
            "engines.cohort_analysis.shopify_hydrator._get_router",
            return_value=stub,
        ):
            assert hydrate_customers([]) == []
            assert hydrate_orders([]) == []

    def test_adapter_raises_returns_empty(self):
        class _ExplodingRouter:
            def execute(self, capability, params):
                raise RuntimeError("network down")

        with patch(
            "engines.cohort_analysis.shopify_hydrator._get_router",
            return_value=_ExplodingRouter(),
        ):
            assert hydrate_customers([]) == []
            assert hydrate_orders([]) == []


# ─── Flow integration ────────────────────────────────────────────


class TestFlowIntegration:

    def test_flow_hydrates_both_when_empty(self):
        from engines.cohort_analysis.flow import (
            CohortAnalysisEngine,
        )

        with patch(
            "engines.cohort_analysis.flow.hydrate_customers",
            return_value=[
                {
                    "id": "cust_1",
                    "created_at": "2025-09-01T00:00:00Z",
                },
            ],
        ), patch(
            "engines.cohort_analysis.flow.hydrate_orders",
            return_value=[
                {
                    "id": "order_1",
                    "customer_id": "cust_1",
                    "created_at": "2025-10-01T00:00:00Z",
                    "total": 100.0,
                },
            ],
        ):
            output = CohortAnalysisEngine().run({
                "data": {
                    "customers": [],
                    "orders": [],
                    "cohort_type": "monthly",
                },
            })

        # Hydrators filled in data, so the "Customers or orders
        # list is required" error must NOT be the failure reason.
        if output["status"] == "error":
            assert "Customers or orders list is required" not in (
                output.get("error") or ""
            )

    def test_flow_falls_back_to_standard_error_when_both_empty(self):
        from engines.cohort_analysis.flow import (
            CohortAnalysisEngine,
        )

        with patch(
            "engines.cohort_analysis.flow.hydrate_customers",
            return_value=[],
        ), patch(
            "engines.cohort_analysis.flow.hydrate_orders",
            return_value=[],
        ):
            output = CohortAnalysisEngine().run({
                "data": {"customers": [], "orders": []},
            })
        assert output["status"] == "error"
        assert "Customers or orders list is required" in output["error"]

    def test_flow_passes_kwargs_through(self):
        from engines.cohort_analysis.flow import (
            CohortAnalysisEngine,
        )

        captured: dict[str, dict] = {
            "customers": {}, "orders": {},
        }

        def _record_customers(supplied, *, limit=None, query=None):
            captured["customers"]["limit"] = limit
            captured["customers"]["query"] = query
            return [
                {"id": "c1", "created_at": "2025-09-01"},
            ]

        def _record_orders(supplied, *, limit=None, query=None):
            captured["orders"]["limit"] = limit
            captured["orders"]["query"] = query
            return [
                {
                    "id": "o1",
                    "customer_id": "c1",
                    "created_at": "2025-10-01",
                },
            ]

        with patch(
            "engines.cohort_analysis.flow.hydrate_customers",
            side_effect=_record_customers,
        ), patch(
            "engines.cohort_analysis.flow.hydrate_orders",
            side_effect=_record_orders,
        ):
            CohortAnalysisEngine().run({
                "data": {
                    "customers": [],
                    "orders": [],
                    "hydrate_limit": 100,
                    "hydrate_query": "created_at:>2025-01-01",
                },
            })

        assert captured["customers"]["limit"] == 100
        assert captured["customers"]["query"] == \
            "created_at:>2025-01-01"
        assert captured["orders"]["limit"] == 100
        assert captured["orders"]["query"] == \
            "created_at:>2025-01-01"

    def test_flow_skips_hydrate_when_caller_supplies_data(self):
        from engines.cohort_analysis.flow import (
            CohortAnalysisEngine,
        )

        # Supplied non-empty → hydrators are still called but
        # short-circuit because the supplied list is truthy.
        called = {"customers": 0, "orders": 0}

        def _spy_customers(supplied, **kwargs):
            called["customers"] += 1
            return supplied

        def _spy_orders(supplied, **kwargs):
            called["orders"] += 1
            return supplied

        with patch(
            "engines.cohort_analysis.flow.hydrate_customers",
            side_effect=_spy_customers,
        ), patch(
            "engines.cohort_analysis.flow.hydrate_orders",
            side_effect=_spy_orders,
        ):
            CohortAnalysisEngine().run({
                "data": {
                    "customers": [
                        {
                            "id": "c1",
                            "created_at": "2025-09-01",
                        },
                    ],
                    "orders": [
                        {
                            "id": "o1",
                            "customer_id": "c1",
                            "created_at": "2025-10-01",
                        },
                    ],
                },
            })

        # Both hydrators called once each (the flow always invokes
        # them); they short-circuit internally when supplied is
        # non-empty (verified by the unit tests above).
        assert called["customers"] == 1
        assert called["orders"] == 1
