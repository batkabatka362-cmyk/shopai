"""Shipping optimizer tests."""
from __future__ import annotations

import unittest

from core.brain import shipping_optimizer as so


def _usps_ground():
    return so.Carrier(
        name="usps_ground",
        tiers=[
            so.RateTier(0.5, 4.00),
            so.RateTier(2.0, 7.50),
            so.RateTier(10.0, 15.00),
        ],
        zones=frozenset({"US"}),
        sla="ground",
    )


def _fedex_2day():
    return so.Carrier(
        name="fedex_2day",
        tiers=[
            so.RateTier(0.5, 9.00),
            so.RateTier(2.0, 14.00),
            so.RateTier(10.0, 25.00),
        ],
        zones=frozenset({"US", "CA"}),
        sla="two_day",
        fuel_surcharge_pct=0.08,
    )


def _dhl_overnight():
    return so.Carrier(
        name="dhl_overnight",
        tiers=[
            so.RateTier(0.5, 20.00),
            so.RateTier(2.0, 32.00),
            so.RateTier(10.0, 60.00),
        ],
        zones=frozenset({"US", "EU"}),
        sla="overnight",
        residential_fee_usd=3.00,
    )


class TestCarrier(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            so.ShippingOptimizer().add_carrier(
                so.Carrier(name="", tiers=[so.RateTier(1, 1)],
                            zones=frozenset({"US"}), sla="ground"),
            )

    def test_no_tiers_raises(self) -> None:
        with self.assertRaises(ValueError):
            so.ShippingOptimizer().add_carrier(
                so.Carrier(name="x", tiers=[],
                            zones=frozenset({"US"}), sla="ground"),
            )


class TestQuote(unittest.TestCase):
    def setUp(self) -> None:
        self.opt = so.ShippingOptimizer()
        self.opt.add_many([_usps_ground(), _fedex_2day()])

    def test_zone_rejection(self) -> None:
        pkg = so.Package(weight_kg=0.3, destination_zone="JP")
        result = self.opt.all_options(pkg)
        self.assertIsNone(result.best)
        self.assertTrue(result.rejected)

    def test_sla_rejection(self) -> None:
        pkg = so.Package(
            weight_kg=0.3, destination_zone="US",
            required_sla="overnight",
        )
        result = self.opt.all_options(pkg)
        self.assertIsNone(result.best)

    def test_finds_cheapest(self) -> None:
        pkg = so.Package(weight_kg=0.3, destination_zone="US")
        result = self.opt.all_options(pkg)
        self.assertEqual(result.best.carrier, "usps_ground")
        self.assertEqual(len(result.options), 2)

    def test_over_weight_rejected(self) -> None:
        pkg = so.Package(weight_kg=50, destination_zone="US")
        result = self.opt.all_options(pkg)
        self.assertIsNone(result.best)

    def test_fuel_surcharge_applied(self) -> None:
        pkg = so.Package(
            weight_kg=1.5, destination_zone="CA",
            required_sla="two_day",
        )
        result = self.opt.all_options(pkg)
        # FedEx tier at 14.00 × 1.08 = 15.12
        self.assertAlmostEqual(result.best.total_usd, 15.12, places=2)


class TestDIMWeight(unittest.TestCase):
    def test_dim_pushes_billable_up(self) -> None:
        opt = so.ShippingOptimizer()
        opt.add_carrier(so.Carrier(
            name="big_box",
            tiers=[so.RateTier(0.5, 5.00), so.RateTier(5.0, 20.00)],
            zones=frozenset({"US"}),
            sla="ground",
            dim_weight_divisor=5.0,   # 5 kg per 1L
        ))
        # Actual weight 0.3kg but 10L volume → 2kg DIM → tier 5kg
        pkg = so.Package(
            weight_kg=0.3, destination_zone="US",
            length_cm=30, width_cm=30, height_cm=11.2,   # ~10L
        )
        q = opt.best_option(pkg)
        self.assertEqual(q.base_price_usd, 20.00)
        self.assertGreater(q.billable_weight_kg, 0.3)


class TestResidentialFee(unittest.TestCase):
    def test_residential_fee_applied(self) -> None:
        opt = so.ShippingOptimizer()
        opt.add_carrier(_dhl_overnight())
        pkg = so.Package(
            weight_kg=0.3, destination_zone="US",
            required_sla="overnight", residential=True,
        )
        q = opt.best_option(pkg)
        # Base 20 + residential 3 = 23
        self.assertAlmostEqual(q.total_usd, 23.00, places=2)

    def test_business_no_fee(self) -> None:
        opt = so.ShippingOptimizer()
        opt.add_carrier(_dhl_overnight())
        pkg = so.Package(
            weight_kg=0.3, destination_zone="US",
            required_sla="overnight", residential=False,
        )
        self.assertAlmostEqual(
            opt.best_option(pkg).total_usd, 20.00, places=2,
        )


class TestCheapestPerCarrier(unittest.TestCase):
    def test_one_quote_per_carrier(self) -> None:
        opt = so.ShippingOptimizer()
        opt.add_many([_usps_ground(), _fedex_2day()])
        pkg = so.Package(weight_kg=0.3, destination_zone="US")
        per = opt.cheapest_per_carrier(pkg)
        self.assertIn("usps_ground", per)
        self.assertIn("fedex_2day", per)


class TestSLAOrdering(unittest.TestCase):
    def test_faster_sla_also_accepts_slower_requirement(self) -> None:
        opt = so.ShippingOptimizer()
        opt.add_many([_usps_ground(), _fedex_2day(), _dhl_overnight()])
        pkg = so.Package(
            weight_kg=0.3, destination_zone="US",
            required_sla="ground",
        )
        result = opt.all_options(pkg)
        # All three should quote — all meet 'ground' bar
        self.assertEqual(len(result.options), 3)


if __name__ == "__main__":
    unittest.main()
