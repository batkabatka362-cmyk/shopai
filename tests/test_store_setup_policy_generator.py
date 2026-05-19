"""Tests for ``engines.store_setup.policy_generator``.

Generates niche-aware HTML bodies for the essential Shopify
shop policies (refund / privacy / terms / shipping / contact),
plus optional legal_notice + subscription_policy.

Coverage:
  1. Default invocation returns the 5 essential policies.
  2. Each body is non-empty HTML mentioning the store name.
  3. Niche-specific tone in refund window (food = final-sale,
     fashion = 14d, beauty/home/tech/general = 30d).
  4. Region propagates into privacy + contact bodies.
  5. Empty store_name returns empty dict.
  6. Optional include_legal_notice + include_subscription_policy.
"""
from __future__ import annotations

from engines.store_setup.policy_generator import (
    generate_policies,
)


class TestDefaultGeneration:

    def test_returns_five_essential_policies(self):
        out = generate_policies(store_name="Acme")
        assert set(out.keys()) == {
            "REFUND_POLICY", "PRIVACY_POLICY",
            "TERMS_OF_SERVICE", "SHIPPING_POLICY",
            "CONTACT_INFORMATION",
        }

    def test_bodies_are_non_empty_html(self):
        out = generate_policies(store_name="Acme")
        for policy_type, body in out.items():
            assert isinstance(body, str)
            assert body.startswith("<h2>")
            assert len(body) > 100

    def test_store_name_interpolated(self):
        out = generate_policies(store_name="Acme")
        for body in out.values():
            assert "Acme" in body


class TestNicheTone:

    def test_fashion_uses_14_day_refund(self):
        out = generate_policies(
            store_name="Acme", niche="fashion",
        )
        assert "14-day refund" in out["REFUND_POLICY"]

    def test_beauty_uses_30_day_refund(self):
        out = generate_policies(
            store_name="Acme", niche="beauty",
        )
        assert "30-day refund" in out["REFUND_POLICY"]

    def test_food_is_final_sale(self):
        out = generate_policies(
            store_name="Acme", niche="food",
        )
        assert "all sales" in out["REFUND_POLICY"].lower()
        assert "final" in out["REFUND_POLICY"].lower()

    def test_unknown_niche_falls_back_to_general(self):
        out = generate_policies(
            store_name="Acme", niche="ufo_parts",
        )
        # 30-day default
        assert "30-day refund" in out["REFUND_POLICY"]


class TestRegionInterpolation:

    def test_us_region_in_privacy_body(self):
        out = generate_policies(store_name="Acme", region="us")
        # California / CCPA mention since we hardcode it
        assert "California" in out["PRIVACY_POLICY"]
        # contact body mentions region uppercase
        assert "US" in out["CONTACT_INFORMATION"]

    def test_eu_region_includes_gdpr(self):
        out = generate_policies(store_name="Acme", region="eu")
        # GDPR mention
        assert "GDPR" in out["PRIVACY_POLICY"]
        assert "EU" in out["CONTACT_INFORMATION"]


class TestEmptyStoreName:

    def test_empty_string_returns_empty(self):
        assert generate_policies(store_name="") == {}
        assert generate_policies(store_name="   ") == {}

    def test_none_treated_as_empty(self):
        assert generate_policies(store_name=None) == {}


class TestOptionalPolicies:

    def test_legal_notice_opt_in(self):
        out = generate_policies(
            store_name="Acme", include_legal_notice=True,
        )
        assert "LEGAL_NOTICE" in out
        assert "Impressum" in out["LEGAL_NOTICE"]

    def test_legal_notice_not_in_default(self):
        out = generate_policies(store_name="Acme")
        assert "LEGAL_NOTICE" not in out

    def test_subscription_policy_opt_in(self):
        out = generate_policies(
            store_name="Acme",
            include_subscription_policy=True,
        )
        assert "SUBSCRIPTION_POLICY" in out
        assert "renew automatically" in out["SUBSCRIPTION_POLICY"]

    def test_subscription_policy_not_in_default(self):
        out = generate_policies(store_name="Acme")
        assert "SUBSCRIPTION_POLICY" not in out

    def test_both_optional_flags(self):
        out = generate_policies(
            store_name="Acme",
            include_legal_notice=True,
            include_subscription_policy=True,
        )
        assert "LEGAL_NOTICE" in out
        assert "SUBSCRIPTION_POLICY" in out
        # Essentials still there
        assert "REFUND_POLICY" in out
