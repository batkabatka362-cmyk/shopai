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
        # W963-166: dispatcher now also defaults inventory_policy
        # to CONTINUE (dropshipping-safe) so customers can order
        # even when stock=0.
        assert update_params["variants"] == [{
            "id": "gid://shopify/ProductVariant/100",
            "price": "19.99",
            "inventory_policy": "CONTINUE",
        }]
        assert result["inventory_policy"] == "CONTINUE"

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

    def test_inventory_policy_override_deny(self):
        """Operator can opt into DENY via _metadata."""
        captured: list[dict] = []

        def fake_router_call(cap, params):
            captured.append(dict(params))
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
            ok, result = _create_draft_product_dispatch({
                "title": "Own Inventory Product",
                "_metadata": {
                    "suggested_price": 25.00,
                    "inventory_policy": "DENY",
                },
            })

        assert ok is True
        update_params = captured[1]
        assert update_params["variants"][0][
            "inventory_policy"
        ] == "DENY"
        assert result["inventory_policy"] == "DENY"

    def test_invalid_inventory_policy_falls_back_to_continue(self):
        captured: list[dict] = []

        def fake_router_call(cap, params):
            captured.append(dict(params))
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
            ok, result = _create_draft_product_dispatch({
                "title": "Bad Policy Product",
                "_metadata": {
                    "suggested_price": 10.00,
                    "inventory_policy": "garbage",
                },
            })

        assert ok is True
        assert result["inventory_policy"] == "CONTINUE"

    def test_missing_title_rejects(self):
        ok, result = _create_draft_product_dispatch({})
        assert ok is False
        assert result == {"error": "missing_title"}


class TestImageAttachment:
    """W963-167: media attachment via _metadata.image_urls /
    _metadata.images."""

    def _setup_fake_router(self, captured):
        def fake(cap, params):
            captured.append((cap, dict(params)))
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
            if cap == "SHOPIFY_UPDATE_VARIANTS":
                return True, {}
            if cap == "SHOPIFY_CREATE_PRODUCT_MEDIA":
                return True, {
                    "attached_count": len(
                        params.get("media") or [],
                    ),
                    "media": params.get("media") or [],
                }
            return False, {"error": "unexpected"}

        return fake

    def test_image_urls_attached(self):
        captured: list[tuple[str, dict]] = []
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=self._setup_fake_router(captured),
        ):
            ok, result = _create_draft_product_dispatch({
                "title": "With Images",
                "_metadata": {
                    "suggested_price": 12.0,
                    "image_urls": [
                        "https://images.pexels.com/a.jpg",
                        "https://images.pexels.com/b.jpg",
                    ],
                },
            })

        assert ok is True
        assert result["images_attached"] == 2
        caps = [c for c, _ in captured]
        # Order: create -> update variants -> create media
        assert caps == [
            "SHOPIFY_CREATE_PRODUCT",
            "SHOPIFY_UPDATE_VARIANTS",
            "SHOPIFY_CREATE_PRODUCT_MEDIA",
        ]
        media_params = captured[2][1]
        assert media_params["product_id"] == "gid://x/1"
        assert media_params["media"] == [
            {"url": "https://images.pexels.com/a.jpg"},
            {"url": "https://images.pexels.com/b.jpg"},
        ]

    def test_images_dicts_with_alt(self):
        captured: list[tuple[str, dict]] = []
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=self._setup_fake_router(captured),
        ):
            _create_draft_product_dispatch({
                "title": "With Alts",
                "_metadata": {
                    "suggested_price": 12.0,
                    "images": [
                        {
                            "url": "https://x.com/a.jpg",
                            "alt": "front view",
                        },
                        {"url": "https://x.com/b.jpg"},
                    ],
                },
            })

        media_params = captured[2][1]
        assert media_params["media"][0] == {
            "url": "https://x.com/a.jpg",
            "alt": "front view",
        }
        assert media_params["media"][1] == {
            "url": "https://x.com/b.jpg",
        }

    def test_no_image_metadata_skips_attach(self):
        captured: list[tuple[str, dict]] = []
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=self._setup_fake_router(captured),
        ):
            ok, result = _create_draft_product_dispatch({
                "title": "No Images",
                "_metadata": {"suggested_price": 12.0},
            })

        assert ok is True
        # No CREATE_PRODUCT_MEDIA call
        caps = [c for c, _ in captured]
        assert "SHOPIFY_CREATE_PRODUCT_MEDIA" not in caps
        assert "images_attached" not in result

    def test_image_attach_failure_doesnt_crash_create(self):
        """Image attach is best-effort. If it fails the product
        + price still landed; result surfaces the error
        details for observability."""
        def fake(cap, params):
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
            if cap == "SHOPIFY_UPDATE_VARIANTS":
                return True, {}
            if cap == "SHOPIFY_CREATE_PRODUCT_MEDIA":
                return False, {"error": "invalid_url"}
            return False, {}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake,
        ):
            ok, result = _create_draft_product_dispatch({
                "title": "Bad URL",
                "_metadata": {
                    "suggested_price": 10.0,
                    "image_urls": ["not a url"],
                },
            })

        assert ok is True
        assert result["images_attached"] == 0
        assert (
            result["images_attach_error"] == "invalid_url"
        )
