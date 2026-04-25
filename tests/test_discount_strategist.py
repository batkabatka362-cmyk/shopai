"""Discount strategist tests."""
from __future__ import annotations

import unittest

from core.brain import discount_strategist as ds


def _inp(**kw):
    defaults = dict(
        sku="sku", base_price=50.0, unit_cost=20.0,
        margin_pct=0.6, churn_risk=0.0,
        elasticity_beta=-1.0, inventory_units=100,
        days_of_stock=30.0, customer_ltv=100.0,
    )
    defaults.update(kw)
    return ds.StrategyInputs(**defaults)


class TestGuards(unittest.TestCase):
    def test_blacklist_refuses(self) -> None:
        s = ds.DiscountStrategist(
            ds.StrategyConfig(
                blacklist_skus=frozenset({"no_touch"}),
            ),
        )
        r = s.recommend(_inp(sku="no_touch"))
        self.assertFalse(r.allowed)
        self.assertEqual(r.guardrail, "blacklist")

    def test_invalid_price_refuses(self) -> None:
        s = ds.DiscountStrategist()
        r = s.recommend(_inp(base_price=0))
        self.assertFalse(r.allowed)
        self.assertEqual(r.guardrail, "invalid_inputs")


class TestBasic(unittest.TestCase):
    def test_low_risk_gets_minimum_discount(self) -> None:
        s = ds.DiscountStrategist()
        r = s.recommend(_inp(churn_risk=0.0))
        self.assertTrue(r.allowed)
        self.assertAlmostEqual(
            r.percent_off, s.config().min_pct,
        )

    def test_high_churn_risk_bigger_discount(self) -> None:
        s = ds.DiscountStrategist()
        low = s.recommend(_inp(churn_risk=0.1))
        high = s.recommend(_inp(churn_risk=0.9))
        self.assertGreater(high.percent_off, low.percent_off)
        self.assertIn("churn", high.reason.lower())

    def test_high_inventory_pressure_deep_cut(self) -> None:
        s = ds.DiscountStrategist()
        r = s.recommend(_inp(
            days_of_stock=200, churn_risk=0.0,
            elasticity_beta=-1.0,
        ))
        self.assertGreater(r.percent_off, 10)
        self.assertIn("stock", r.reason.lower())

    def test_highly_elastic_product(self) -> None:
        s = ds.DiscountStrategist()
        r = s.recommend(_inp(
            elasticity_beta=-3.0, churn_risk=0.0,
            days_of_stock=30,
        ))
        self.assertIn("elastic", r.reason.lower())


class TestMarginFloor(unittest.TestCase):
    def test_clamped_to_preserve_margin(self) -> None:
        s = ds.DiscountStrategist(ds.StrategyConfig(
            floor_margin_pct=0.4, min_pct=5, max_pct=30,
        ))
        # Base 10, cost 6 → 40% margin. 30% off → price 7 → margin
        # (7-6)/7 = 14% which is below 40%.
        r = s.recommend(_inp(
            base_price=10, unit_cost=6, margin_pct=0.4,
            churn_risk=0.8,       # wants large discount
        ))
        # Either clamped below max, or refused entirely.
        if r.allowed:
            self.assertGreaterEqual(r.final_margin_pct, 0.4 - 0.01)

    def test_impossible_margin_refuses(self) -> None:
        s = ds.DiscountStrategist(ds.StrategyConfig(
            floor_margin_pct=0.9, min_pct=15,
        ))
        r = s.recommend(_inp(
            base_price=10, unit_cost=9, churn_risk=0.8,
        ))
        # 90% floor margin is impossible given cost=9/price=10
        self.assertFalse(r.allowed)


class TestExpectedLift(unittest.TestCase):
    def test_lift_scales_with_elasticity(self) -> None:
        s = ds.DiscountStrategist()
        soft = s.recommend(_inp(
            elasticity_beta=-0.5, churn_risk=0.5,
        ))
        hard = s.recommend(_inp(
            elasticity_beta=-3.0, churn_risk=0.5,
        ))
        self.assertGreaterEqual(
            hard.expected_unit_lift_pct,
            soft.expected_unit_lift_pct,
        )


class TestBatch(unittest.TestCase):
    def test_batch_sorted_by_lift(self) -> None:
        s = ds.DiscountStrategist()
        inputs = [
            _inp(sku="a", elasticity_beta=-0.5, churn_risk=0.5),
            _inp(sku="b", elasticity_beta=-3.0, churn_risk=0.5),
        ]
        out = s.batch(inputs)
        self.assertEqual(out[0].sku, "b")


class TestRanges(unittest.TestCase):
    def test_percent_within_bounds(self) -> None:
        s = ds.DiscountStrategist(
            ds.StrategyConfig(min_pct=5, max_pct=30),
        )
        for churn in (0.0, 0.3, 0.5, 0.7, 0.9):
            r = s.recommend(_inp(churn_risk=churn))
            if r.allowed:
                self.assertGreaterEqual(r.percent_off, 5)
                self.assertLessEqual(r.percent_off, 30)


if __name__ == "__main__":
    unittest.main()
