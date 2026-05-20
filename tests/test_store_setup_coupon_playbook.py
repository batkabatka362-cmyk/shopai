"""Tests for ``engines.store_setup.coupon_playbook``.

Generates the 6 evergreen discount specs per niche. Each
spec's ``params`` dict is ready to feed into
``SHOPIFY_CREATE_DISCOUNT``.

Coverage:
  1. Generator: empty store_name -> empty dict.
  2. Generator: 6 discount specs per niche.
  3. Generator: every spec has name + params + rationale +
     when_to_enable.
  4. Generator: every shipped niche resolves (no KeyError).
  5. Generator: unknown niche falls back to general.
  6. Free-shipping spec: threshold + code + free_shipping flag.
  7. Bundle spec: percentage + minimum_item_count >= 2.
  8. Loyalty spec: applies_once_per_customer + sensible pct.
  9. Email subscriber spec: shape.
 10. Cart recovery spec: shape.
 11. Seasonal spec: 90-day window (different from others).
 12. days_valid kwarg respected on evergreens.
 13. Code names are deterministic per niche tuning.
 14. Numeric typing: percentage int, threshold int /
     min_subtotal float, ISO timestamps.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engines.store_setup.coupon_playbook import (
    _NICHE_TUNING,
    generate_playbook,
)


# ── Generator empty + shape ─────────────────────────────────


class TestGeneratorEmpty:

    def test_empty_store_name(self):
        assert generate_playbook(store_name="") == {}
        assert generate_playbook(store_name="   ") == {}
        assert generate_playbook(store_name=None) == {}


class TestGeneratorShape:

    def test_six_discounts_per_niche(self):
        for niche in _NICHE_TUNING:
            spec = generate_playbook(
                store_name="Acme", niche=niche,
            )
            assert len(spec["discounts"]) == 6, niche

    def test_every_discount_has_full_shape(self):
        for niche in _NICHE_TUNING:
            spec = generate_playbook(
                store_name="Acme", niche=niche,
            )
            for d in spec["discounts"]:
                assert d["name"], niche
                assert d["params"], niche
                assert d["rationale"], niche
                assert d["when_to_enable"], niche
                # Every params dict carries the basics
                p = d["params"]
                assert p["code"], niche
                assert p["title"], niche
                assert p["starts_at"].endswith("Z")
                assert p["ends_at"].endswith("Z")

    def test_every_niche_resolves(self):
        for niche in (
            "beauty", "fashion", "tech", "home", "food",
            "pets", "fitness", "jewelry", "outdoor",
            "baby", "general",
        ):
            spec = generate_playbook(
                store_name="Acme", niche=niche,
            )
            assert spec["discounts"]

    def test_unknown_niche_falls_back_to_general(self):
        spec = generate_playbook(
            store_name="Acme", niche="ufo_parts",
        )
        # General's free-shipping threshold is 50
        free_ship = next(
            d for d in spec["discounts"]
            if d["name"] == "free_shipping_threshold"
        )
        assert free_ship["params"]["code"] == "FREESHIP50"


# ── Per-spec checks ────────────────────────────────────────


class TestFreeShipping:

    def test_threshold_per_niche(self):
        """Beauty threshold is 50; tech is 75."""
        for niche, expected in (
            ("beauty", 50),
            ("fashion", 75),
            ("tech", 75),
            ("home", 100),
            ("food", 40),
            ("jewelry", 100),
        ):
            spec = generate_playbook(
                store_name="Acme", niche=niche,
            )
            free = next(
                d for d in spec["discounts"]
                if d["name"] == "free_shipping_threshold"
            )
            assert free["params"]["code"] == (
                f"FREESHIP{expected}"
            )
            assert (
                free["params"]["minimum_subtotal"]
                == float(expected)
            )
            assert free["params"]["free_shipping"] is True

    def test_no_percentage_on_free_shipping(self):
        spec = generate_playbook(
            store_name="Acme", niche="beauty",
        )
        free = next(
            d for d in spec["discounts"]
            if d["name"] == "free_shipping_threshold"
        )
        # Free shipping is a SEPARATE discount type, not a
        # percentage. Adapter switches on free_shipping=True.
        assert "percentage" not in free["params"]


class TestBundle:

    def test_minimum_item_count(self):
        spec = generate_playbook(
            store_name="Acme", niche="beauty",
        )
        bundle = next(
            d for d in spec["discounts"]
            if d["name"] == "bundle_10pct"
        )
        assert bundle["params"]["minimum_item_count"] == 2

    def test_tier_pct_per_niche(self):
        """Beauty bundle is 10% / 15%; tech is 5% / 10%."""
        beauty = generate_playbook(
            store_name="Acme", niche="beauty",
        )
        b = next(
            d for d in beauty["discounts"]
            if d["name"] == "bundle_10pct"
        )
        assert b["params"]["percentage"] == 10
        assert b["params"]["code"] == "BUNDLE10"

        tech = generate_playbook(
            store_name="Acme", niche="tech",
        )
        t = next(
            d for d in tech["discounts"]
            if d["name"] == "bundle_10pct"
        )
        assert t["params"]["percentage"] == 5
        assert t["params"]["code"] == "BUNDLE5"


class TestLoyalty:

    def test_applies_once_per_customer(self):
        spec = generate_playbook(store_name="Acme")
        loy = next(
            d for d in spec["discounts"]
            if d["name"] == "loyalty_second_order"
        )
        assert (
            loy["params"]["applies_once_per_customer"]
            is True
        )

    def test_code_starts_with_again(self):
        spec = generate_playbook(
            store_name="Acme", niche="beauty",
        )
        loy = next(
            d for d in spec["discounts"]
            if d["name"] == "loyalty_second_order"
        )
        # Beauty loyalty pct is 10
        assert loy["params"]["code"] == "AGAIN10"


class TestEmailSubscriber:

    def test_shape_and_pct(self):
        spec = generate_playbook(
            store_name="Acme", niche="beauty",
        )
        email = next(
            d for d in spec["discounts"]
            if d["name"] == "email_subscriber"
        )
        # Beauty email_pct = 15
        assert email["params"]["percentage"] == 15
        assert email["params"]["code"] == "NEWSLETTER15"
        assert (
            email["params"]["applies_once_per_customer"]
            is True
        )


class TestCartRecovery:

    def test_shape(self):
        spec = generate_playbook(
            store_name="Acme", niche="fashion",
        )
        cart = next(
            d for d in spec["discounts"]
            if d["name"] == "cart_recovery"
        )
        # Fashion cart_recovery_pct = 15
        assert cart["params"]["percentage"] == 15
        assert cart["params"]["code"] == "COMEBACK15"
        assert (
            cart["params"]["applies_once_per_customer"]
            is True
        )


class TestSeasonal:

    def test_seasonal_has_shorter_window(self):
        """Seasonal is 90 days; others default to 365.
        Confirm the seasonal end_at is < other end_ats."""
        spec = generate_playbook(
            store_name="Acme",
            niche="beauty",
            days_valid=365,
        )
        seasonal = next(
            d for d in spec["discounts"]
            if d["name"] == "seasonal_clearance"
        )
        free_ship = next(
            d for d in spec["discounts"]
            if d["name"] == "free_shipping_threshold"
        )
        # Parse the timestamps and compare
        s_end = datetime.strptime(
            seasonal["params"]["ends_at"],
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)
        f_end = datetime.strptime(
            free_ship["params"]["ends_at"],
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)
        assert s_end < f_end
        # ~90 days roughly
        now = datetime.now(timezone.utc)
        assert 85 <= (s_end - now).days <= 95


# ── days_valid + numeric typing ─────────────────────────────


class TestDaysValid:

    def test_days_valid_propagates_to_evergreens(self):
        spec = generate_playbook(
            store_name="Acme", days_valid=30,
        )
        free_ship = next(
            d for d in spec["discounts"]
            if d["name"] == "free_shipping_threshold"
        )
        end = datetime.strptime(
            free_ship["params"]["ends_at"],
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (end - now).days
        # 30 day window +/- 1
        assert 28 <= delta <= 31

    def test_days_valid_clamped(self):
        # Negative -> floor 1
        spec = generate_playbook(
            store_name="Acme", days_valid=-5,
        )
        assert spec["discounts"]
        # Huge -> capped at 10y
        spec2 = generate_playbook(
            store_name="Acme", days_valid=100_000,
        )
        assert spec2["discounts"]


class TestNumericTyping:

    def test_percentages_are_int(self):
        spec = generate_playbook(
            store_name="Acme", niche="beauty",
        )
        for d in spec["discounts"]:
            if "percentage" in d["params"]:
                assert isinstance(
                    d["params"]["percentage"], int,
                )

    def test_minimum_subtotal_is_float(self):
        spec = generate_playbook(
            store_name="Acme", niche="beauty",
        )
        free = next(
            d for d in spec["discounts"]
            if d["name"] == "free_shipping_threshold"
        )
        assert isinstance(
            free["params"]["minimum_subtotal"], float,
        )

    def test_iso_timestamps(self):
        spec = generate_playbook(
            store_name="Acme", niche="beauty",
        )
        for d in spec["discounts"]:
            for key in ("starts_at", "ends_at"):
                v = d["params"][key]
                # Round-trip parse to ensure it's valid ISO
                datetime.strptime(
                    v, "%Y-%m-%dT%H:%M:%SZ",
                )


# ── Code naming determinism ──────────────────────────────────


class TestCodeNamingDeterministic:

    def test_same_niche_same_codes(self):
        """Two calls with the same niche -> same codes
        (deterministic naming from the tuning table)."""
        a = generate_playbook(
            store_name="Acme", niche="beauty",
        )
        b = generate_playbook(
            store_name="Acme", niche="beauty",
        )
        codes_a = [d["params"]["code"] for d in a["discounts"]]
        codes_b = [d["params"]["code"] for d in b["discounts"]]
        assert codes_a == codes_b

    def test_codes_uppercase(self):
        spec = generate_playbook(
            store_name="Acme", niche="beauty",
        )
        for d in spec["discounts"]:
            code = d["params"]["code"]
            assert code == code.upper()
