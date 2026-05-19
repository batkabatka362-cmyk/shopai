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
        # 5 of 6 pass -> round(100 * 5/6) = 83
        assert result["completion_pct"] == 83
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
