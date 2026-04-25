"""Inventory planner tests."""
from __future__ import annotations

import unittest

from core.brain import inventory_planner as ip


class TestZScore(unittest.TestCase):
    def test_known_service_levels(self) -> None:
        self.assertAlmostEqual(ip._z_for(0.95), 1.65, places=2)
        self.assertAlmostEqual(ip._z_for(0.99), 2.33, places=2)

    def test_interpolation(self) -> None:
        # Between 0.95 (1.65) and 0.97 (1.88)
        z = ip._z_for(0.96)
        self.assertGreater(z, 1.65)
        self.assertLess(z, 1.88)

    def test_clamped(self) -> None:
        self.assertAlmostEqual(ip._z_for(0.1), 0.0, places=2)
        self.assertAlmostEqual(ip._z_for(1.5), 3.09, places=2)


class TestSafetyStock(unittest.TestCase):
    def test_zero_std_zero_stock(self) -> None:
        self.assertEqual(ip.safety_stock(0, 7), 0.0)

    def test_formula(self) -> None:
        # 1.65 * 2 * sqrt(9) = 9.9
        self.assertAlmostEqual(
            ip.safety_stock(daily_std=2, lead_time_days=9,
                             service_level=0.95),
            9.9, delta=0.1,
        )


class TestReorderPoint(unittest.TestCase):
    def test_rop_is_lead_x_mean_plus_safety(self) -> None:
        # 5/day × 7d = 35; safety at σ=0 = 0 → ROP = 35
        self.assertAlmostEqual(
            ip.reorder_point(5, 0, 7), 35.0,
        )

    def test_rop_includes_safety(self) -> None:
        rop = ip.reorder_point(
            daily_mean=10, daily_std=3,
            lead_time_days=5, service_level=0.95,
        )
        # 50 + safety > 50
        self.assertGreater(rop, 50)


class TestEOQ(unittest.TestCase):
    def test_eoq_formula(self) -> None:
        # D=1000, S=10, H=0.5 → sqrt(2*1000*10/0.5) = sqrt(40000) = 200
        self.assertAlmostEqual(
            ip.eoq(annual_demand=1000, ordering_cost=10,
                    holding_cost_per_unit=0.5),
            200, delta=0.1,
        )

    def test_invalid_inputs_zero(self) -> None:
        self.assertEqual(ip.eoq(0, 10, 1), 0.0)
        self.assertEqual(ip.eoq(100, -1, 1), 0.0)


class TestStockoutRisk(unittest.TestCase):
    def test_high_stock_low_risk(self) -> None:
        risk = ip.stockout_risk(
            on_hand=1000, daily_mean=5, daily_std=1,
            days_until_next=7,
        )
        self.assertLess(risk, 0.05)

    def test_low_stock_high_risk(self) -> None:
        risk = ip.stockout_risk(
            on_hand=5, daily_mean=5, daily_std=1,
            days_until_next=7,
        )
        self.assertGreater(risk, 0.9)

    def test_zero_days_zero_risk(self) -> None:
        self.assertEqual(
            ip.stockout_risk(10, 5, 1, 0), 0.0,
        )

    def test_zero_std_boundary(self) -> None:
        # 5 units, 5/day, 2 days → deterministic 10 demand → stockout
        self.assertEqual(
            ip.stockout_risk(on_hand=5, daily_mean=5,
                              daily_std=0, days_until_next=2),
            1.0,
        )


class TestShouldReorder(unittest.TestCase):
    def test_below_rop_triggers(self) -> None:
        d = ip.should_reorder(
            sku="sku_a", on_hand=10,
            daily_mean=5, daily_std=1, lead_time_days=7,
        )
        self.assertTrue(d.should_reorder)

    def test_well_stocked_no_trigger(self) -> None:
        d = ip.should_reorder(
            sku="sku_b", on_hand=500,
            daily_mean=5, daily_std=1, lead_time_days=7,
        )
        self.assertFalse(d.should_reorder)

    def test_suggested_quantity_nonneg(self) -> None:
        d = ip.should_reorder(
            sku="x", on_hand=9999, daily_mean=5,
            daily_std=1, lead_time_days=7,
        )
        self.assertGreaterEqual(d.suggested_quantity, 0.0)


class TestBatch(unittest.TestCase):
    def test_batch_orders_most_urgent_first(self) -> None:
        skus = [
            ip.SKUStats("safe", on_hand=500, daily_mean=5,
                         daily_std=1, lead_time_days=7),
            ip.SKUStats("low", on_hand=5, daily_mean=5,
                         daily_std=1, lead_time_days=7),
            ip.SKUStats("mid", on_hand=40, daily_mean=5,
                         daily_std=1, lead_time_days=7),
        ]
        decisions = ip.batch_decisions(skus)
        # 'low' should come first
        self.assertEqual(decisions[0].sku, "low")


if __name__ == "__main__":
    unittest.main()
