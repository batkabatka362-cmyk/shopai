"""Fraud detector tests."""
from __future__ import annotations

import unittest

from core.brain import fraud_detector as fd


class TestScoring(unittest.TestCase):
    def setUp(self) -> None:
        self.d = fd.FraudDetector()

    def test_clean_order_allowed(self) -> None:
        r = self.d.score({
            "order_id": "o1",
            "order_value": 50,
            "customer_order_count": 5,
            "billing_country": "us",
            "shipping_country": "us",
            "account_age_days": 200,
        })
        self.assertEqual(r.verdict, "allow")
        self.assertLess(r.score, 30)

    def test_high_value_first_order_flagged(self) -> None:
        r = self.d.score({
            "order_id": "o1",
            "order_value": 2000,
            "customer_order_count": 1,
        })
        hits = [h.name for h in r.signals_hit]
        self.assertIn("high_value_first_order", hits)

    def test_billing_shipping_mismatch(self) -> None:
        r = self.d.score({
            "order_id": "o1",
            "billing_country": "US",
            "shipping_country": "RU",
        })
        hits = [h.name for h in r.signals_hit]
        self.assertIn("mismatch_billing_shipping", hits)

    def test_rush_on_low_margin(self) -> None:
        r = self.d.score({
            "order_id": "o", "rush_shipping": True,
            "margin_pct": 0.1,
        })
        hits = [h.name for h in r.signals_hit]
        self.assertIn("rush_shipping", hits)

    def test_rush_on_healthy_margin_ok(self) -> None:
        r = self.d.score({
            "order_id": "o", "rush_shipping": True,
            "margin_pct": 0.5,
        })
        hits = [h.name for h in r.signals_hit]
        self.assertNotIn("rush_shipping", hits)

    def test_disposable_email_flagged(self) -> None:
        r = self.d.score({
            "order_id": "o",
            "email": "bob@mailinator.com",
        })
        hits = [h.name for h in r.signals_hit]
        self.assertIn("email_disposable", hits)

    def test_velocity_spike_flagged(self) -> None:
        r = self.d.score({
            "order_id": "o",
            "orders_same_ip_1h": 5,
        })
        hits = [h.name for h in r.signals_hit]
        self.assertIn("velocity_spike", hits)


class TestVerdict(unittest.TestCase):
    def test_allow_below_30(self) -> None:
        self.assertEqual(fd.FraudDetector.verdict(10), "allow")

    def test_review_between_30_60(self) -> None:
        self.assertEqual(fd.FraudDetector.verdict(45), "review")

    def test_block_60_plus(self) -> None:
        self.assertEqual(fd.FraudDetector.verdict(75), "block")


class TestMultipleSignals(unittest.TestCase):
    def test_stacked_signals_block(self) -> None:
        d = fd.FraudDetector()
        r = d.score({
            "order_id": "x",
            "order_value": 2000, "customer_order_count": 1,
            "billing_country": "US", "shipping_country": "RU",
            "account_age_days": 1,
            "email": "scam@mailinator.com",
        })
        self.assertEqual(r.verdict, "block")

    def test_score_capped_at_100(self) -> None:
        d = fd.FraudDetector()
        r = d.score({
            "order_id": "x",
            "order_value": 2000, "customer_order_count": 1,
            "billing_country": "US", "shipping_country": "RU",
            "rush_shipping": True, "margin_pct": 0.1,
            "account_age_days": 1,
            "declines_24h": 5,
            "email": "x@mailinator.com",
            "ip_vpn": True,
            "orders_same_ip_1h": 5,
            "address_lookup_failed": True,
        })
        self.assertEqual(r.score, 100.0)


class TestRegistry(unittest.TestCase):
    def test_register_custom_signal(self) -> None:
        d = fd.FraudDetector()
        def always_fires(o):
            return True, "always"
        d.register_signal("always", 5.0, always_fires)
        self.assertIn("always", d.signals())
        r = d.score({"order_id": "o"})
        hits = [h.name for h in r.signals_hit]
        self.assertIn("always", hits)

    def test_register_blank_name_raises(self) -> None:
        d = fd.FraudDetector()
        with self.assertRaises(ValueError):
            d.register_signal("", 1.0, lambda o: (True, ""))

    def test_deregister(self) -> None:
        d = fd.FraudDetector()
        self.assertTrue(d.deregister("rush_shipping"))
        self.assertNotIn("rush_shipping", d.signals())

    def test_signal_that_raises_skipped(self) -> None:
        d = fd.FraudDetector()
        def broken(o):
            raise RuntimeError("x")
        d.register_signal("broken", 100.0, broken)
        # Should not crash
        r = d.score({"order_id": "o"})
        names = [h.name for h in r.signals_hit]
        self.assertNotIn("broken", names)


class TestBatch(unittest.TestCase):
    def test_batch_sorted_by_score_desc(self) -> None:
        d = fd.FraudDetector()
        clean = {"order_id": "clean", "customer_order_count": 5}
        bad = {"order_id": "bad",
                "order_value": 2000, "customer_order_count": 1,
                "account_age_days": 1}
        out = d.batch([clean, bad])
        self.assertEqual(out[0].order_id, "bad")


if __name__ == "__main__":
    unittest.main()
