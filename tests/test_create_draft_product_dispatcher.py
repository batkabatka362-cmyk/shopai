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
        # W963-168: Pexels URLs auto-resized to <=1500px wide
        assert media_params["media"] == [
            {
                "url": (
                    "https://images.pexels.com/a.jpg"
                    "?auto=compress&cs=tinysrgb&w=1500"
                ),
            },
            {
                "url": (
                    "https://images.pexels.com/b.jpg"
                    "?auto=compress&cs=tinysrgb&w=1500"
                ),
            },
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

    def test_image_query_triggers_stock_search(self):
        """W963-169: _metadata.image_query -> IMAGE_STOCK_SEARCH
        fan-out -> first photo attached as hero image."""
        captured: list[tuple[str, dict]] = []

        def fake_router_call(cap, params):
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
            if cap == "IMAGE_STOCK_SEARCH":
                return True, {
                    "photo_count": 2,
                    "photos": [
                        {
                            "url_large2x": (
                                "https://pexels.com/p1.jpg"
                                "?w=1500"
                            ),
                            "alt": "matching photo",
                        },
                        {
                            "url_large2x": (
                                "https://pexels.com/p2.jpg"
                            ),
                            "alt": "second photo",
                        },
                    ],
                }
            if cap == "SHOPIFY_CREATE_PRODUCT_MEDIA":
                return True, {
                    "attached_count": len(
                        params.get("media") or [],
                    ),
                }
            return False, {"error": "unexpected"}

        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake_router_call,
        ):
            ok, result = _create_draft_product_dispatch({
                "title": "Autonomous Image Test",
                "_metadata": {
                    "suggested_price": 15.0,
                    "image_query": "vitamin c serum",
                    "image_count": 1,
                },
            })

        assert ok is True
        assert result["images_attached"] == 1
        assert (
            result["images_discovered_from"]
            == "stock_search"
        )
        # Capability chain: create -> update -> search -> media
        caps = [c for c, _ in captured]
        assert caps == [
            "SHOPIFY_CREATE_PRODUCT",
            "SHOPIFY_UPDATE_VARIANTS",
            "IMAGE_STOCK_SEARCH",
            "SHOPIFY_CREATE_PRODUCT_MEDIA",
        ]
        # The search params carried the query + clamped limit
        search_params = captured[2][1]
        assert search_params["query"] == "vitamin c serum"
        assert search_params["limit"] == 1

    def test_publish_on_approve_fires_publish_chain(self):
        """W963-170: _metadata.publish_on_approve=True chains
        create + price + image attach + status flip + publish
        into a single dispatcher call."""
        captured: list[str] = []

        def fake(cap, params):
            captured.append(cap)
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
            if cap == "SHOPIFY_UPDATE_PRODUCT":
                return True, {}
            if cap == "SHOPIFY_LIST_PUBLICATIONS":
                return True, {
                    "publications": [{
                        "id": "gid://shopify/Publication/1",
                        "name": "Online Store",
                    }],
                }
            if cap == "SHOPIFY_PUBLISH_RESOURCE":
                return True, {
                    "id": params["id"],
                    "publication_count": 1,
                }
            return True, {}

        from core.approval.dispatchers import (
            _ONLINE_STORE_PUB_CACHE,
        )
        _ONLINE_STORE_PUB_CACHE.clear()
        with patch(
            "core.approval.dispatchers._router_call",
            side_effect=fake,
        ):
            ok, result = _create_draft_product_dispatch({
                "title": "Single-Step Launch",
                "_metadata": {
                    "suggested_price": 10.0,
                    "publish_on_approve": True,
                },
            })

        assert ok is True
        assert result["published"] is True
        # Full chain fired in order:
        # CREATE_PRODUCT, UPDATE_VARIANTS, UPDATE_PRODUCT,
        # LIST_PUBLICATIONS, PUBLISH_RESOURCE
        assert captured == [
            "SHOPIFY_CREATE_PRODUCT",
            "SHOPIFY_UPDATE_VARIANTS",
            "SHOPIFY_UPDATE_PRODUCT",
            "SHOPIFY_LIST_PUBLICATIONS",
            "SHOPIFY_PUBLISH_RESOURCE",
        ]

    def test_no_publish_on_approve_stays_draft(self):
        """Default behavior: no publish step fires."""
        captured: list[str] = []

        def fake(cap, params):
            captured.append(cap)
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
            side_effect=fake,
        ):
            ok, result = _create_draft_product_dispatch({
                "title": "Stay Draft",
                "_metadata": {"suggested_price": 10.0},
            })

        assert ok is True
        assert "SHOPIFY_PUBLISH_RESOURCE" not in captured
        assert "published" not in result

    def test_publish_on_approve_string_truthy(self):
        """String '1' / 'true' / 'yes' also enable publish."""
        for raw in ("1", "true", "yes", "TRUE"):
            captured: list[str] = []

            def fake(cap, params):
                captured.append(cap)
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
                if cap == "SHOPIFY_LIST_PUBLICATIONS":
                    return True, {
                        "publications": [{
                            "id": "gid://shopify/Publication/1",
                            "name": "Online Store",
                        }],
                    }
                return True, {}

            from core.approval.dispatchers import (
                _ONLINE_STORE_PUB_CACHE,
            )
            _ONLINE_STORE_PUB_CACHE.clear()
            with patch(
                "core.approval.dispatchers._router_call",
                side_effect=fake,
            ):
                _, result = _create_draft_product_dispatch({
                    "title": "X",
                    "_metadata": {
                        "suggested_price": 10.0,
                        "publish_on_approve": raw,
                    },
                })
            assert result.get("published") is True, (
                f"publish_on_approve={raw!r} should enable"
            )

    def test_explicit_urls_skip_stock_search(self):
        """When image_urls is provided, no IMAGE_STOCK_SEARCH
        call should fire even if image_query is also set."""
        captured: list[str] = []

        def fake(cap, params):
            captured.append(cap)
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
            side_effect=fake,
        ):
            _create_draft_product_dispatch({
                "title": "Has URLs",
                "_metadata": {
                    "suggested_price": 10.0,
                    "image_urls": [
                        "https://images.pexels.com/a.jpg",
                    ],
                    "image_query": "fallback query",
                },
            })

        assert "IMAGE_STOCK_SEARCH" not in captured

    def test_pexels_urls_resized(self):
        """W963-168: Pexels URLs must be sized to avoid
        Shopify's 25MP limit triggering FAILED media uploads."""
        from core.approval.dispatchers import (
            _normalise_image_url,
        )
        raw = (
            "https://images.pexels.com/photos/"
            "34939693/pexels-photo-34939693.jpeg"
        )
        sized = _normalise_image_url(raw)
        assert "?auto=compress" in sized
        assert "w=1500" in sized
        # Already-sized URL stays unchanged
        already = raw + "?w=600"
        assert _normalise_image_url(already) == already
        # Non-Pexels URL passes through
        other = "https://cdn.example.com/image.jpg"
        assert _normalise_image_url(other) == other

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
