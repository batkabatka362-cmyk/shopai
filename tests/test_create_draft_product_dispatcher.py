"""W963-164: create_draft_product dispatcher tests.

The dispatcher creates a product via SHOPIFY_CREATE_PRODUCT then
threads ``_metadata.suggested_price`` into a follow-up
SHOPIFY_UPDATE_VARIANTS call so the new product has a real
price + customers can actually buy it.
"""
from __future__ import annotations

from unittest.mock import patch

from core.approval.dispatchers import (
    _create_draft_product_dispatch,
)


class TestPriceThreading:
    def test_suggested_price_set_on_variant(self):
        """Happy path: create succeeds + variant id returned +
        price-set follow-up fires."""
        calls: list[tuple[str, dict]] = []

        def fake_router_call(cap, params):
            calls.append((cap, dict(params)))
            if cap == "SHOPIFY_CREATE_PRODUCT":
                return True, {
                    "product": {
                        "id": "gid://shopify/Product/1",
                        "variants": [
                            {
                                "id": (
                                    "gid://shopify/"
                                    "ProductVariant/100"
                                ),
                                "price": "0.0",
                                "sku": "",
                            },
                        ],
                    },
                }
            if cap == "SHOPIFY_UPDATE_VARIANTS":
                return True, {"updated": True}
            return False, {"error": "unexpected"}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake_router_call,
        ):
            ok, result = _create_draft_product_dispatch({
                "title": "Test Serum",
                "description": "<p>test</p>",
                "status": "DRAFT",
                "_metadata": {"suggested_price": 19.99},
            })

        assert ok is True
        assert result["price_set"] is True
        assert result["price_set_value"] == "19.99"
        # Two router calls fired: create + update_variants
        assert len(calls) == 2
        assert calls[0][0] == "SHOPIFY_CREATE_PRODUCT"
        assert calls[1][0] == "SHOPIFY_UPDATE_VARIANTS"
        update_params = calls[1][1]
        assert update_params["product_id"] == (
            "gid://shopify/Product/1"
        )
        assert update_params["variants"] == [{
            "id": "gid://shopify/ProductVariant/100",
            "price": "19.99",
        }]

    def test_no_suggested_price_skips_variant_update(self):
        """No _metadata.suggested_price -> only create
        fires; no follow-up."""
        calls: list[tuple[str, dict]] = []

        def fake_router_call(cap, params):
            calls.append((cap, dict(params)))
            return True, {"product": {"id": "gid://x/1"}}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake_router_call,
        ):
            ok, result = _create_draft_product_dispatch({
                "title": "No Price Product",
                "status": "DRAFT",
            })

        assert ok is True
        assert len(calls) == 1
        assert calls[0][0] == "SHOPIFY_CREATE_PRODUCT"
        assert "price_set" not in result

    def test_metadata_stripped_from_create_params(self):
        """_metadata key (and any underscore-prefixed key)
        must NOT reach the Shopify create call."""
        captured_params: list[dict] = []

        def fake_router_call(cap, params):
            captured_params.append(dict(params))
            if cap == "SHOPIFY_CREATE_PRODUCT":
                return True, {
                    "product": {
                        "id": "gid://x/1",
                        "variants": [{
                            "id": "gid://x/v1",
                            "price": "0.0",
                            "sku": "",
                        }],
                    },
                }
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake_router_call,
        ):
            _create_draft_product_dispatch({
                "title": "X",
                "status": "DRAFT",
                "_metadata": {"suggested_price": 10.0},
                "_internal": "private",
            })

        create_params = captured_params[0]
        assert "_metadata" not in create_params
        assert "_internal" not in create_params

    def test_variant_id_missing_surfaces_skip_reason(self):
        """Create succeeded but variant id not in response ->
        success returned BUT price_set=False + skip_reason."""
        def fake_router_call(cap, params):
            if cap == "SHOPIFY_CREATE_PRODUCT":
                return True, {
                    "product": {"id": "gid://x/1"},
                }
            return True, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake_router_call,
        ):
            ok, result = _create_draft_product_dispatch({
                "title": "X",
                "_metadata": {"suggested_price": 5.0},
            })

        assert ok is True
        assert result["price_set"] is False
        assert "variant" in result["price_set_skip_reason"]

    def test_create_failure_short_circuits(self):
        """Create fails -> dispatcher returns immediately
        without trying to set variant price."""
        calls: list[str] = []

        def fake_router_call(cap, params):
            calls.append(cap)
            return False, {"error": "scope_missing"}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake_router_call,
        ):
            ok, result = _create_draft_product_dispatch({
                "title": "X",
                "_metadata": {"suggested_price": 9.99},
            })

        assert ok is False
        # Only ONE call (the create) fired
        assert calls == ["SHOPIFY_CREATE_PRODUCT"]

    def test_invalid_suggested_price_skips(self):
        """Non-numeric / zero / negative suggested_price ->
        no follow-up call, no error."""
        calls: list[str] = []

        def fake_router_call(cap, params):
            calls.append(cap)
            return True, {
                "product": {
                    "id": "gid://x/1",
                    "variants": [{
                        "id": "gid://x/v1",
                        "price": "0.0",
                        "sku": "",
                    }],
                },
            }

        for bad in ["abc", 0, -5, None]:
            calls.clear()
            with patch(
                "core.approval.dispatchers._router_call",
                side_effect=fake_router_call,
            ):
                ok, _ = _create_draft_product_dispatch({
                    "title": "X",
                    "_metadata": {"suggested_price": bad},
                })
            assert ok is True
            assert calls == ["SHOPIFY_CREATE_PRODUCT"]

    def test_missing_title_rejects(self):
        ok, result = _create_draft_product_dispatch({})
        assert ok is False
        assert result == {"error": "missing_title"}
