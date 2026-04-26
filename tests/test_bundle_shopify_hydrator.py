"""Tests for bundle's Shopify hydrator — auto-fetches products /
orders when the caller leaves them empty.

Different shape from cart_recovery / browse_recovery wire-ups: this
is the READ side. Engines wire SHOPIFY_LIST_PRODUCTS +
SHOPIFY_FETCH_ORDERS as input-data sources, not output writes.
"""
from __future__ import annotations

from unittest.mock import patch

from engines.bundle.shopify_hydrator import (
    hydrate_orders,
    hydrate_products,
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


# ─── Pass-through (no fetch) ──────────────────────────────────────


class TestPassThroughWhenSupplied:

    def test_supplied_products_pass_through_without_router_call(self):
        supplied = [
            {"id": "gid://shopify/Product/1", "title": "Widget"},
        ]
        with patch(
            "engines._shopify_hydrator._get_router",
        ) as mock_router:
            result = hydrate_products(supplied)
        assert result is supplied  # same object, no copy
        mock_router.assert_not_called()

    def test_supplied_orders_pass_through_without_router_call(self):
        supplied = [{"id": "gid://shopify/Order/1"}]
        with patch(
            "engines._shopify_hydrator._get_router",
        ) as mock_router:
            result = hydrate_orders(supplied)
        assert result is supplied
        mock_router.assert_not_called()


# ─── Empty supplied → fetch (happy path) ──────────────────────────


class TestHydrateProductsHappyPath:

    def test_empty_input_triggers_fetch(self):
        from core.adapters.base import Capability

        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={
                "products": [
                    {
                        "id": "gid://shopify/Product/1",
                        "title": "Widget",
                    },
                    {
                        "id": "gid://shopify/Product/2",
                        "title": "Gadget",
                    },
                ],
                "count": 2,
                "has_next_page": False,
            },
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_products([])

        assert len(stub.calls) == 1
        cap, params = stub.calls[0]
        assert cap == Capability.SHOPIFY_LIST_PRODUCTS
        # Default limit applied.
        assert params["limit"] == 250
        assert "query" not in params
        # Returns the fetched products.
        assert len(result) == 2
        assert result[0]["title"] == "Widget"

    def test_none_input_triggers_fetch(self):
        # ``None`` is a valid input shape (caller didn't even
        # supply the key).
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"products": [{"id": "gid://x"}]},
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_products(None)
        assert len(stub.calls) == 1
        assert len(result) == 1

    def test_query_filter_passed_through(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"products": []},
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate_products(
                [],
                query="status:active AND tag:bestseller",
            )
        _, params = stub.calls[0]
        assert params["query"] == "status:active AND tag:bestseller"

    def test_blank_query_dropped(self):
        # Blank / whitespace-only query string is NOT passed to the
        # API (Shopify rejects empty queries).
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"products": []},
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate_products([], query="   ")
        _, params = stub.calls[0]
        assert "query" not in params

    def test_non_dict_products_filtered_out(self):
        # Defensive: if the adapter returns garbage in the products
        # list, we filter to dicts only so downstream pipeline
        # doesn't choke.
        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={
                "products": [
                    {"id": "gid://shopify/Product/1"},
                    "garbage",
                    None,
                    {"id": "gid://shopify/Product/2"},
                ],
            },
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_products([])
        assert len(result) == 2
        assert all(isinstance(p, dict) for p in result)


class TestHydrateOrdersHappyPath:

    def test_empty_input_triggers_fetch(self):
        from core.adapters.base import Capability

        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={
                "orders": [
                    {"id": "gid://shopify/Order/1"},
                    {"id": "gid://shopify/Order/2"},
                ],
            },
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_orders([])

        assert len(stub.calls) == 1
        cap, _ = stub.calls[0]
        assert cap == Capability.SHOPIFY_FETCH_ORDERS
        assert len(result) == 2


# ─── Limit clamping ───────────────────────────────────────────────


class TestLimitClamping:

    def test_default_limit_250(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"products": []},
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate_products([])
        _, params = stub.calls[0]
        assert params["limit"] == 250

    def test_explicit_limit_respected(self):
        stub = _StubRouter(result=_StubResult(
            ok=True, data={"products": []},
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate_products([], limit=50)
        _, params = stub.calls[0]
        assert params["limit"] == 50

    def test_limit_clamped(self):
        for raw, expected in [
            (-10, 1),     # below floor → 1
            (0, 1),       # below floor → 1
            (1000, 250),  # above ceiling → 250
            ("garbage", 250),  # non-numeric → default
        ]:
            stub = _StubRouter(result=_StubResult(
                ok=True, data={"products": []},
            ))
            with patch(
                "engines._shopify_hydrator._get_router",
                return_value=stub,
            ):
                hydrate_products([], limit=raw)
            _, params = stub.calls[0]
            assert params["limit"] == expected, (
                f"limit={raw} should clamp to {expected}"
            )


# ─── Failure modes ────────────────────────────────────────────────


class TestGracefulFallbacks:

    def test_router_unavailable_returns_empty_products(self):
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=None,
        ):
            result = hydrate_products([])
        assert result == []

    def test_router_unavailable_returns_empty_orders(self):
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=None,
        ):
            result = hydrate_orders([])
        assert result == []

    def test_adapter_returns_failure_returns_empty(self):
        stub = _StubRouter(result=_StubResult(
            ok=False, error="scope missing",
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_products([])
        assert result == []

    def test_adapter_raises_returns_empty(self):
        class _ExplodingRouter:
            def execute(self, capability, params):
                raise RuntimeError("network down")

        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=_ExplodingRouter(),
        ):
            result = hydrate_products([])
        assert result == []


# ─── Flow integration ─────────────────────────────────────────────


class TestFlowIntegration:
    """Verifies the bundle pipeline calls the hydrator and the
    auto-fetched products feed downstream stages correctly."""

    def _input_with_no_products(self):
        return {
            "data": {
                "products": [],
                "orders": [],
                "constraints": {"max_bundle_size": 3},
            },
        }

    def test_flow_uses_hydrator_to_fill_empty_products(self):
        from engines.bundle.flow import BundleEngine

        # Caller passes no products. Hydrator auto-fetches a few.
        # The downstream pipeline should accept them and run to
        # completion (or fail downstream — either way the
        # "Product list is required" guard does NOT fire).
        injected_products = [
            {"id": "gid://shopify/Product/1", "title": "A"},
            {"id": "gid://shopify/Product/2", "title": "B"},
            {"id": "gid://shopify/Product/3", "title": "C"},
        ]

        with patch(
            "engines.bundle.flow.hydrate_products",
            return_value=injected_products,
        ), patch(
            "engines.bundle.flow.hydrate_orders",
            return_value=[],
        ):
            output = BundleEngine().run(
                self._input_with_no_products(),
            )

        # The hydrator filled in products, so the "Product list
        # is required" error must NOT be the failure reason.
        if output["status"] == "error":
            assert "Product list is required" not in (
                output.get("error") or ""
            )

    def test_flow_fails_when_hydrator_returns_empty(self):
        from engines.bundle.flow import BundleEngine

        # No supplied products + hydrator returns nothing → the
        # standard "Product list is required" guard fires (same
        # behavior as before this wire-up — graceful degradation).
        with patch(
            "engines.bundle.flow.hydrate_products",
            return_value=[],
        ), patch(
            "engines.bundle.flow.hydrate_orders",
            return_value=[],
        ):
            output = BundleEngine().run(
                self._input_with_no_products(),
            )
        assert output["status"] == "error"
        assert "Product list is required" in output["error"]

    def test_flow_passes_hydrate_kwargs_through(self):
        from engines.bundle.flow import BundleEngine

        captured: dict = {}

        def _record(supplied, *, limit=None, query=None):
            captured["limit"] = limit
            captured["query"] = query
            return [
                {"id": "gid://shopify/Product/1", "title": "A"},
            ]

        with patch(
            "engines.bundle.flow.hydrate_products",
            side_effect=_record,
        ), patch(
            "engines.bundle.flow.hydrate_orders",
            return_value=[],
        ):
            BundleEngine().run({
                "data": {
                    "products": [],
                    "hydrate_limit": 75,
                    "hydrate_query": "tag:bundle-eligible",
                },
            })

        assert captured["limit"] == 75
        assert captured["query"] == "tag:bundle-eligible"

    def test_flow_skips_hydrate_when_caller_supplied_products(self):
        from engines.bundle.flow import BundleEngine

        # Caller pre-fetched products. Hydrator gets called but
        # MUST be a no-op pass-through. Spy via a fake.
        called = {"count": 0}

        def _spy(supplied, **kwargs):
            called["count"] += 1
            return supplied  # pass-through

        with patch(
            "engines.bundle.flow.hydrate_products",
            side_effect=_spy,
        ), patch(
            "engines.bundle.flow.hydrate_orders",
            side_effect=lambda s, **k: s,
        ):
            BundleEngine().run({
                "data": {
                    "products": [
                        {
                            "id": "gid://shopify/Product/1",
                            "title": "Widget",
                        },
                    ],
                },
            })

        # Hydrator was called once (every run calls it), but with
        # the supplied list it short-circuits. The actual pass-
        # through is verified by the function's own unit tests
        # above; here we just confirm the flow invokes it.
        assert called["count"] == 1
