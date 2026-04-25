"""Ethics gate tests."""
from __future__ import annotations

import unittest

from core.brain import ethics_gate as eg


class TestDeceptivePriceAnchor(unittest.TestCase):
    def test_inflated_compare_at_hard_blocks(self) -> None:
        verdict = eg.check({
            "kind": "set_price",
            "price": 29.0,
            "compare_at_price": 299.0,
            "verified_historical_max_price": 50.0,
        })
        self.assertEqual(verdict.status, "hard_block")
        self.assertEqual(
            verdict.violations[0].rule, "no_deceptive_price_anchor",
        )

    def test_legitimate_anchor_allowed(self) -> None:
        verdict = eg.check({
            "kind": "set_price",
            "price": 29.0,
            "compare_at_price": 49.0,
            "verified_historical_max_price": 50.0,
        })
        self.assertTrue(verdict.allowed)


class TestScarcityLie(unittest.TestCase):
    def test_claimed_below_actual_hard_blocks(self) -> None:
        v = eg.check({
            "kind": "publish_scarcity",
            "claimed_stock": 3, "actual_stock": 100,
        })
        self.assertEqual(v.status, "hard_block")

    def test_claimed_equal_ok(self) -> None:
        v = eg.check({
            "kind": "publish_scarcity",
            "claimed_stock": 5, "actual_stock": 5,
        })
        self.assertTrue(v.allowed)


class TestSpamFrequency(unittest.TestCase):
    def test_soft_block_on_third_email(self) -> None:
        v = eg.check({
            "kind": "send_email",
            "recipient": "alice@x.com",
            "emails_in_last_24h": 2,
        })
        self.assertEqual(v.status, "soft_block")

    def test_single_email_ok(self) -> None:
        v = eg.check({
            "kind": "send_email",
            "recipient": "alice@x.com",
            "emails_in_last_24h": 0,
        })
        self.assertTrue(v.allowed)


class TestFakeReviews(unittest.TestCase):
    def test_fake_flag_hard_blocks(self) -> None:
        v = eg.check({
            "kind": "publish_review", "product_id": 1, "fake": True,
        })
        self.assertEqual(v.status, "hard_block")

    def test_generated_source_hard_blocks(self) -> None:
        v = eg.check({
            "kind": "publish_review", "product_id": 1,
            "source": "generated",
        })
        self.assertEqual(v.status, "hard_block")


class TestForbiddenCategories(unittest.TestCase):
    def test_weapons_blocked(self) -> None:
        v = eg.check({"category": "weapons"})
        self.assertEqual(v.status, "hard_block")

    def test_apparel_allowed(self) -> None:
        v = eg.check({"category": "apparel"})
        self.assertTrue(v.allowed)


class TestPiiLeak(unittest.TestCase):
    def test_email_in_public_hard_blocks(self) -> None:
        v = eg.check({
            "audience": "public",
            "body": "Contact alice@store.com for details",
        })
        self.assertEqual(v.status, "hard_block")

    def test_phone_in_public_hard_blocks(self) -> None:
        v = eg.check({
            "audience": "public",
            "body": "Call us at 415-555-1234 today!",
        })
        self.assertEqual(v.status, "hard_block")

    def test_private_audience_ok(self) -> None:
        v = eg.check({
            "audience": "customer",
            "body": "Hi alice@x.com, your order ships today.",
        })
        self.assertTrue(v.allowed)


class TestDeceptiveUrgency(unittest.TestCase):
    def test_24h_claim_but_14d_sale(self) -> None:
        v = eg.check({
            "kind": "publish_sale_copy",
            "claim_hours": 24, "actual_duration_hours": 24 * 14,
        })
        self.assertEqual(v.status, "soft_block")

    def test_matching_duration_ok(self) -> None:
        v = eg.check({
            "kind": "publish_sale_copy",
            "claim_hours": 48, "actual_duration_hours": 48,
        })
        self.assertTrue(v.allowed)


class TestSpendingCap(unittest.TestCase):
    def test_exceeds_daily_cap_hard_blocks(self) -> None:
        v = eg.check({
            "kind": "spend",
            "amount_usd": 60, "already_spent_today_usd": 50,
            "daily_cap_usd": 100,
        })
        self.assertEqual(v.status, "hard_block")

    def test_within_cap_ok(self) -> None:
        v = eg.check({
            "kind": "spend",
            "amount_usd": 20, "already_spent_today_usd": 50,
            "daily_cap_usd": 100,
        })
        self.assertTrue(v.allowed)

    def test_no_cap_set_allowed(self) -> None:
        v = eg.check({
            "kind": "spend",
            "amount_usd": 9999,
            "daily_cap_usd": 0,
        })
        self.assertTrue(v.allowed)


class TestCombined(unittest.TestCase):
    def test_multiple_violations_all_surfaced(self) -> None:
        v = eg.check({
            "kind": "publish_scarcity",
            "claimed_stock": 1, "actual_stock": 100,
            "category": "weapons",
        })
        self.assertEqual(v.status, "hard_block")
        rules = {viol.rule for viol in v.violations}
        self.assertIn("no_scarcity_lie", rules)
        self.assertIn("no_forbidden_categories", rules)

    def test_soft_then_hard_yields_hard(self) -> None:
        # Spam + forbidden category — hard wins
        v = eg.check({
            "kind": "send_email", "recipient": "a",
            "emails_in_last_24h": 5,
            "category": "prescription_drugs",
        })
        self.assertEqual(v.status, "hard_block")


class TestRegistry(unittest.TestCase):
    def test_registered_rules_names(self) -> None:
        names = eg.registered_rules()
        self.assertIn("no_forbidden_categories", names)
        self.assertIn("no_pii_leak", names)
        self.assertIn("owner_spending_cap", names)


if __name__ == "__main__":
    unittest.main()
