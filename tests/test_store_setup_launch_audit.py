"""Tests for ``engines.store_setup.launch_audit``.

Read-only launch-readiness audit. Each per-check probe reads
the store's current state through the standard adapter layer
and reports completion vs expected baseline.

Coverage:
  1. All checks pass -> ready_to_launch=True, completion_pct=100.
  2. Missing policies -> legal_policies.ok=False with missing list.
  3. Missing pages -> standard_pages.ok=False.
  4. Discount count threshold.
  5. Collection count threshold.
  6. Design tokens probe (theme + filename roundtrip).
  7. Adapter probe raises -> degrade gracefully (item not OK,
     audit still completes).
  8. Pattern Z recording.
  9. store_id propagation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from engines.store_setup.launch_audit import audit_store


def _ok(data):
    return SimpleNamespace(ok=True, data=data, error=None)


def _fail():
    return SimpleNamespace(ok=False, data=None, error="x")


def _router_with(responses: dict):
    """Build a router-execute side_effect that maps a
    capability value (str) -> SimpleNamespace result."""
    def _exec(cap, params):
        # cap.value is the lowercase string Capability uses
        key = getattr(cap, "value", str(cap))
        return responses.get(key, _fail())
    return _exec


# Default "fully launched store" responses
_ALL_GOOD = {
    "shopify_get_shop_policies": _ok({
        "policies": [
            {"type": "REFUND_POLICY", "body": "<p>r</p>"},
            {"type": "PRIVACY_POLICY", "body": "<p>p</p>"},
            {"type": "TERMS_OF_SERVICE", "body": "<p>t</p>"},
            {"type": "SHIPPING_POLICY", "body": "<p>s</p>"},
            {"type": "CONTACT_INFORMATION",
             "body": "<p>c</p>"},
        ],
    }),
    "shopify_list_pages": _ok({
        "pages": [
            {"handle": "about"},
            {"handle": "contact"},
            {"handle": "faq"},
            {"handle": "shipping-returns"},
        ],
    }),
    "shopify_list_discounts": _ok({
        "discounts": [{"code": "WELCOME10"}],
    }),
    "shopify_list_collections": _ok({
        "collections": [{"title": "All"}],
    }),
    "shopify_list_products": _ok({
        "products": [
            {"id": "gid://shopify/Product/1",
             "title": "Camping Lantern", "status": "ACTIVE"},
        ],
    }),
    "shopify_list_delivery_profiles": _ok({
        "profiles": [{
            "id": "gid://shopify/DeliveryProfile/1",
            "name": "General",
            "location_groups": [{
                "location_group_id": "gid://shopify/DeliveryLocationGroup/1",
                "locations": [{"id": "loc1", "name": "Warehouse"}],
                "zones": [{
                    "id": "gid://shopify/DeliveryZone/1",
                    "name": "Domestic",
                }],
            }],
        }],
    }),
    "shopify_list_locations": _ok({
        "locations": [{
            "id": "gid://shopify/Location/1",
            "name": "Warehouse",
            "is_active": True,
            "fulfills_online_orders": True,
        }],
    }),
    "shopify_list_themes": _ok({
        "themes": [{
            "id": "gid://shopify/OnlineStoreTheme/1",
            "role": "MAIN",
        }],
    }),
    "shopify_list_theme_files": _ok({
        "files": [{
            "filename": "assets/shopai-design-tokens.json",
        }],
    }),
    "shopify_get_shop": _ok({
        "shop": {
            "name": "Test Store",
            "setup_required": False,
        },
    }),
}


class TestAllPass:

    def test_ready_to_launch(self):
        router = type("R", (), {})()
        router.execute = _router_with(_ALL_GOOD)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        assert result["ready_to_launch"] is True
        assert result["completion_pct"] == 100
        assert all(c["ok"] for c in result["checks"])

    def test_completion_pct_partial(self):
        # Drop the FAQ page -> standard_pages fails
        responses = dict(_ALL_GOOD)
        responses["shopify_list_pages"] = _ok({
            "pages": [
                {"handle": "about"},
                {"handle": "contact"},
                {"handle": "shipping-returns"},
            ],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        # 8 of 9 pass -> round(100 * 8/9) = 89
        assert result["completion_pct"] == 89
        assert result["ready_to_launch"] is False


class TestLegalPoliciesCheck:

    def test_all_policies_present(self):
        router = type("R", (), {})()
        router.execute = _router_with(_ALL_GOOD)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        legal = next(
            c for c in result["checks"]
            if c["key"] == "legal_policies"
        )
        assert legal["ok"] is True
        assert legal["applied"] == 5
        assert legal["missing"] == []

    def test_missing_policy_flagged(self):
        responses = dict(_ALL_GOOD)
        responses["shopify_get_shop_policies"] = _ok({
            "policies": [
                # Only refund + privacy
                {"type": "REFUND_POLICY", "body": "<p>r</p>"},
                {"type": "PRIVACY_POLICY", "body": "<p>p</p>"},
            ],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        legal = next(
            c for c in result["checks"]
            if c["key"] == "legal_policies"
        )
        assert legal["ok"] is False
        assert legal["applied"] == 2
        assert "TERMS_OF_SERVICE" in legal["missing"]
        assert "SHIPPING_POLICY" in legal["missing"]

    def test_empty_body_doesnt_count(self):
        """A policy row with empty body shouldn't count as
        applied -- empty policies are placeholders, not legal
        text."""
        responses = dict(_ALL_GOOD)
        responses["shopify_get_shop_policies"] = _ok({
            "policies": [
                {"type": "REFUND_POLICY", "body": "<p>r</p>"},
                {"type": "PRIVACY_POLICY", "body": "   "},
            ],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        legal = next(
            c for c in result["checks"]
            if c["key"] == "legal_policies"
        )
        assert "PRIVACY_POLICY" in legal["missing"]


class TestPagesCheck:

    def test_missing_page_flagged(self):
        responses = dict(_ALL_GOOD)
        responses["shopify_list_pages"] = _ok({
            "pages": [
                {"handle": "about"},
                {"handle": "contact"},
                # FAQ + shipping-returns missing
            ],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        pages = next(
            c for c in result["checks"]
            if c["key"] == "standard_pages"
        )
        assert pages["ok"] is False
        assert "faq" in pages["missing"]
        assert "shipping-returns" in pages["missing"]


class TestDiscountsCheck:

    def test_zero_discounts(self):
        responses = dict(_ALL_GOOD)
        responses["shopify_list_discounts"] = _ok({
            "discounts": [],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        discounts = next(
            c for c in result["checks"]
            if c["key"] == "active_discounts"
        )
        assert discounts["ok"] is False
        assert discounts["applied"] == 0

    def test_custom_expected_threshold(self):
        # 1 discount present, expect 3
        router = type("R", (), {})()
        router.execute = _router_with(_ALL_GOOD)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store(expected_discounts=3)
        discounts = next(
            c for c in result["checks"]
            if c["key"] == "active_discounts"
        )
        assert discounts["ok"] is False
        assert discounts["expected"] == 3


class TestDesignTokensCheck:

    def test_design_tokens_present(self):
        router = type("R", (), {})()
        router.execute = _router_with(_ALL_GOOD)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        tokens = next(
            c for c in result["checks"]
            if c["key"] == "design_tokens"
        )
        assert tokens["ok"] is True

    def test_no_themes_flagged(self):
        responses = dict(_ALL_GOOD)
        responses["shopify_list_themes"] = _ok({"themes": []})
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        tokens = next(
            c for c in result["checks"]
            if c["key"] == "design_tokens"
        )
        assert tokens["ok"] is False

    def test_design_tokens_missing_from_theme(self):
        responses = dict(_ALL_GOOD)
        responses["shopify_list_theme_files"] = _ok({
            "files": [],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        tokens = next(
            c for c in result["checks"]
            if c["key"] == "design_tokens"
        )
        assert tokens["ok"] is False
        assert (
            "assets/shopai-design-tokens.json"
            in tokens["missing"]
        )


class TestActiveProductsCheck:

    def test_one_active_product_passes(self):
        router = type("R", (), {})()
        router.execute = _router_with(_ALL_GOOD)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        products = next(
            c for c in result["checks"]
            if c["key"] == "active_products"
        )
        assert products["ok"] is True
        assert products["applied"] == 1
        assert products["expected"] == 1
        assert products["missing"] == []

    def test_zero_products_flagged(self):
        responses = dict(_ALL_GOOD)
        responses["shopify_list_products"] = _ok({
            "products": [],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        products = next(
            c for c in result["checks"]
            if c["key"] == "active_products"
        )
        assert products["ok"] is False
        assert products["applied"] == 0
        assert products["missing"] == ["need 1 more"]

    def test_draft_and_archived_dont_count(self):
        """A catalog full of DRAFT / ARCHIVED products still
        fails the check -- those aren't customer-visible."""
        responses = dict(_ALL_GOOD)
        responses["shopify_list_products"] = _ok({
            "products": [
                {"id": "p1", "title": "T1", "status": "DRAFT"},
                {"id": "p2", "title": "T2", "status": "ARCHIVED"},
                {"id": "p3", "title": "T3", "status": "draft"},
            ],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        products = next(
            c for c in result["checks"]
            if c["key"] == "active_products"
        )
        assert products["ok"] is False
        assert products["applied"] == 0

    def test_custom_expected_threshold(self):
        # 1 ACTIVE product present, but caller expects 5
        router = type("R", (), {})()
        router.execute = _router_with(_ALL_GOOD)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store(expected_products=5)
        products = next(
            c for c in result["checks"]
            if c["key"] == "active_products"
        )
        assert products["ok"] is False
        assert products["expected"] == 5
        assert products["missing"] == ["need 4 more"]

    def test_lowercase_active_normalises(self):
        """Normaliser uppercases status, but defensively accept
        lowercase from non-standard read paths."""
        responses = dict(_ALL_GOOD)
        responses["shopify_list_products"] = _ok({
            "products": [
                {"id": "p1", "title": "T1", "status": "active"},
                {"id": "p2", "title": "T2", "status": "ACTIVE"},
            ],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        products = next(
            c for c in result["checks"]
            if c["key"] == "active_products"
        )
        assert products["applied"] == 2
        assert products["ok"] is True


class TestShippingZonesCheck:

    def test_one_zone_passes(self):
        router = type("R", (), {})()
        router.execute = _router_with(_ALL_GOOD)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        zones = next(
            c for c in result["checks"]
            if c["key"] == "shipping_zones"
        )
        assert zones["ok"] is True
        assert zones["applied"] == 1
        assert zones["expected"] == 1
        assert zones["missing"] == []

    def test_zero_profiles_flagged(self):
        responses = dict(_ALL_GOOD)
        responses["shopify_list_delivery_profiles"] = _ok({
            "profiles": [],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        zones = next(
            c for c in result["checks"]
            if c["key"] == "shipping_zones"
        )
        assert zones["ok"] is False
        assert zones["applied"] == 0
        assert zones["missing"] == ["need 1 more"]

    def test_profile_with_no_zones_flagged(self):
        """A profile that exists but covers no zones is still
        a launch blocker -- nothing for the rate evaluator to
        match against at checkout."""
        responses = dict(_ALL_GOOD)
        responses["shopify_list_delivery_profiles"] = _ok({
            "profiles": [{
                "id": "p1",
                "name": "Empty",
                "location_groups": [{
                    "location_group_id": "g1",
                    "locations": [],
                    "zones": [],
                }],
            }],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        zones = next(
            c for c in result["checks"]
            if c["key"] == "shipping_zones"
        )
        assert zones["ok"] is False
        assert zones["applied"] == 0

    def test_zones_sum_across_profiles(self):
        """Multiple profiles each contributing zones get
        summed; the threshold is cumulative."""
        responses = dict(_ALL_GOOD)
        responses["shopify_list_delivery_profiles"] = _ok({
            "profiles": [
                {"id": "p1", "name": "Domestic",
                 "location_groups": [{
                     "location_group_id": "g1",
                     "locations": [],
                     "zones": [{"id": "z1", "name": "US"}],
                 }]},
                {"id": "p2", "name": "Intl",
                 "location_groups": [{
                     "location_group_id": "g2",
                     "locations": [],
                     "zones": [
                         {"id": "z2", "name": "EU"},
                         {"id": "z3", "name": "APAC"},
                     ],
                 }]},
            ],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store(expected_shipping_zones=3)
        zones = next(
            c for c in result["checks"]
            if c["key"] == "shipping_zones"
        )
        assert zones["ok"] is True
        assert zones["applied"] == 3
        assert zones["expected"] == 3

    def test_custom_threshold_unmet(self):
        # _ALL_GOOD has 1 zone; caller expects 4
        router = type("R", (), {})()
        router.execute = _router_with(_ALL_GOOD)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store(expected_shipping_zones=4)
        zones = next(
            c for c in result["checks"]
            if c["key"] == "shipping_zones"
        )
        assert zones["ok"] is False
        assert zones["applied"] == 1
        assert zones["expected"] == 4
        assert zones["missing"] == ["need 3 more"]


class TestFulfillableLocationsCheck:

    def test_one_fulfillable_passes(self):
        router = type("R", (), {})()
        router.execute = _router_with(_ALL_GOOD)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        locations = next(
            c for c in result["checks"]
            if c["key"] == "fulfillable_locations"
        )
        assert locations["ok"] is True
        assert locations["applied"] == 1
        assert locations["expected"] == 1
        assert locations["missing"] == []

    def test_zero_locations_flagged(self):
        responses = dict(_ALL_GOOD)
        responses["shopify_list_locations"] = _ok({
            "locations": [],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        locations = next(
            c for c in result["checks"]
            if c["key"] == "fulfillable_locations"
        )
        assert locations["ok"] is False
        assert locations["applied"] == 0
        assert locations["missing"] == ["need 1 more"]

    def test_inactive_location_doesnt_count(self):
        responses = dict(_ALL_GOOD)
        responses["shopify_list_locations"] = _ok({
            "locations": [{
                "id": "loc1",
                "name": "Old Warehouse",
                "is_active": False,
                "fulfills_online_orders": True,
            }],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        locations = next(
            c for c in result["checks"]
            if c["key"] == "fulfillable_locations"
        )
        assert locations["ok"] is False
        assert locations["applied"] == 0

    def test_pickup_only_location_doesnt_count(self):
        """A location that's active but opted out of
        online-order fulfillment (pickup-only outpost) can't
        satisfy a website order."""
        responses = dict(_ALL_GOOD)
        responses["shopify_list_locations"] = _ok({
            "locations": [{
                "id": "loc1",
                "name": "Pickup Counter",
                "is_active": True,
                "fulfills_online_orders": False,
            }],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        locations = next(
            c for c in result["checks"]
            if c["key"] == "fulfillable_locations"
        )
        assert locations["ok"] is False
        assert locations["applied"] == 0

    def test_mixed_locations_only_fulfillable_counted(self):
        """Three locations: one fulfillable, one inactive, one
        pickup-only. Only the fulfillable one counts."""
        responses = dict(_ALL_GOOD)
        responses["shopify_list_locations"] = _ok({
            "locations": [
                {"id": "loc1", "name": "Main",
                 "is_active": True,
                 "fulfills_online_orders": True},
                {"id": "loc2", "name": "Closed",
                 "is_active": False,
                 "fulfills_online_orders": True},
                {"id": "loc3", "name": "Pickup",
                 "is_active": True,
                 "fulfills_online_orders": False},
            ],
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        locations = next(
            c for c in result["checks"]
            if c["key"] == "fulfillable_locations"
        )
        assert locations["applied"] == 1
        assert locations["ok"] is True

    def test_custom_threshold_unmet(self):
        # _ALL_GOOD has 1 fulfillable; caller expects 3
        router = type("R", (), {})()
        router.execute = _router_with(_ALL_GOOD)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store(
                expected_fulfillable_locations=3,
            )
        locations = next(
            c for c in result["checks"]
            if c["key"] == "fulfillable_locations"
        )
        assert locations["ok"] is False
        assert locations["expected"] == 3
        assert locations["missing"] == ["need 2 more"]


class TestProbeFailureResilience:

    def test_adapter_raise_marks_check_as_missing(self):
        """A raising router doesn't abort the audit -- the
        affected probe degrades to empty, the rest still run."""
        def _exec(cap, params):
            if (
                getattr(cap, "value", "")
                == "shopify_get_shop_policies"
            ):
                raise RuntimeError("network")
            return _router_with(_ALL_GOOD)(cap, params)

        router = type("R", (), {})()
        router.execute = _exec
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        # Policies check fails since the read raised
        legal = next(
            c for c in result["checks"]
            if c["key"] == "legal_policies"
        )
        assert legal["ok"] is False
        # Other checks still pass
        pages = next(
            c for c in result["checks"]
            if c["key"] == "standard_pages"
        )
        assert pages["ok"] is True


class TestPatternZRecording:

    def test_audit_recorded_each_run(self):
        router = type("R", (), {})()
        router.execute = _router_with(_ALL_GOOD)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ) as record_mock:
            audit_store()
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "store_setup"
        assert kwargs["action_type"] == "audit_launch_readiness"
        assert kwargs["capability"] == "SHOPAI_AUDIT_LAUNCH"
        assert kwargs["success"] is True
        assert kwargs["metrics"]["completion_pct"] == 100
        assert kwargs["metrics"]["ready_to_launch"] is True

    def test_partial_audit_recorded_as_failure(self):
        # Remove all pages so standard_pages fails
        responses = dict(_ALL_GOOD)
        responses["shopify_list_pages"] = _ok({"pages": []})
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ) as record_mock:
            audit_store()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is False
        assert "standard_pages" in (kwargs["error"] or "")


class TestStoreIdPropagation:

    def test_store_id_in_recorded_params(self):
        router = type("R", (), {})()
        router.execute = _router_with(_ALL_GOOD)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ) as record_mock:
            audit_store(store_id="store-a")
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"


class TestShopSetupCompleteCheck:
    """`Shop.setupRequired` is Shopify's own "is this store ready
    to launch" flag. The check passes when False (admin setup
    finished) and fails when True (or when the shop probe is
    unreachable). Catches the case where every other check
    passes but the operator never finished Shopify's own
    plan-selection / billing / domain wizard at admin.shopify.com."""

    def _run(self, shop_data):
        responses = dict(_ALL_GOOD)
        responses["shopify_get_shop"] = _ok({"shop": shop_data})
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        return next(
            c for c in result["checks"]
            if c["key"] == "shop_setup_complete"
        )

    def test_setup_required_false_passes(self):
        check = self._run({"setup_required": False})
        assert check["ok"] is True
        assert check["applied"] == 1
        assert check["expected"] == 1
        assert check["missing"] == []

    def test_setup_required_true_fails(self):
        check = self._run({"setup_required": True})
        assert check["ok"] is False
        assert check["applied"] == 0
        assert "admin.shopify.com" in check["missing"][0]

    def test_missing_setup_field_treated_as_required(self):
        """When the shop response lacks ``setup_required``
        entirely, default conservatively to True (not yet
        complete) so the check fails closed rather than
        masking a real launch blocker."""
        check = self._run({"name": "Some Store"})
        assert check["ok"] is False

    def test_empty_shop_data_marks_unavailable(self):
        """A missing/empty shop dict (adapter unconfigured or
        the call returned no shop) yields a distinct missing
        reason so operators can tell "unreachable" apart from
        "actually still in setup"."""
        responses = dict(_ALL_GOOD)
        responses["shopify_get_shop"] = _ok({"shop": {}})
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        check = next(
            c for c in result["checks"]
            if c["key"] == "shop_setup_complete"
        )
        assert check["ok"] is False
        assert check["missing"] == ["shop_data_unavailable"]

    def test_router_raise_marks_unavailable(self):
        """If SHOPIFY_GET_SHOP raises the audit still completes
        and the shop_setup_complete check reports unavailable."""
        def _exec(cap, params):
            if getattr(cap, "value", "") == "shopify_get_shop":
                raise RuntimeError("network")
            return _router_with(_ALL_GOOD)(cap, params)
        router = type("R", (), {})()
        router.execute = _exec
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        check = next(
            c for c in result["checks"]
            if c["key"] == "shop_setup_complete"
        )
        assert check["ok"] is False
        assert check["missing"] == ["shop_data_unavailable"]

    def test_check_blocks_overall_ready_to_launch(self):
        """When every OTHER check passes but setup_required=True,
        ready_to_launch is False. This is the bug-class the
        check exists to catch: a store with full inventory +
        policies + pages that still can't take real payments
        because the operator never finished admin setup."""
        responses = dict(_ALL_GOOD)
        responses["shopify_get_shop"] = _ok({
            "shop": {"setup_required": True},
        })
        router = type("R", (), {})()
        router.execute = _router_with(responses)
        with patch(
            "core.adapters.get_router",
            return_value=router,
        ), patch(
            "engines.store_setup.launch_audit.record_writeback",
        ):
            result = audit_store()
        assert result["ready_to_launch"] is False
        # All other checks must still be passing -- this proves
        # the new check is the lone blocker
        for check in result["checks"]:
            if check["key"] != "shop_setup_complete":
                assert check["ok"] is True, (
                    f"unexpected failure: {check['key']}"
                )
