"""Tests for execution.fulfillment.landed_cost (Wave F-1)."""
from __future__ import annotations

import os
import unittest

from execution.fulfillment.landed_cost import (
    LandedCostBreakdown,
    LandedCostInput,
    _categorize_hts,
    calculate_landed_cost,
    effective_de_minimis,
    minimum_retail_for_margin,
)


class TestInputValidation(unittest.TestCase):
    def test_negative_fob_raises(self):
        with self.assertRaises(ValueError):
            LandedCostInput(
                fob_usd=-1, destination="US",
            )

    def test_blank_destination_raises(self):
        with self.assertRaises(ValueError):
            LandedCostInput(
                fob_usd=10, destination="",
            )

    def test_negative_weight_raises(self):
        with self.assertRaises(ValueError):
            LandedCostInput(
                fob_usd=10, destination="US",
                weight_g=-1,
            )


class TestHtsCategorize(unittest.TestCase):
    def test_apparel_prefix(self):
        self.assertEqual(
            _categorize_hts("6109.10"), "apparel",
        )

    def test_electronics_prefix(self):
        self.assertEqual(
            _categorize_hts("8517.12"), "electronics",
        )

    def test_home_prefix(self):
        self.assertEqual(
            _categorize_hts("9403.20"), "home",
        )

    def test_unknown_default(self):
        self.assertEqual(
            _categorize_hts("3926.10"), "default",
        )

    def test_empty_default(self):
        self.assertEqual(_categorize_hts(""), "default")


class TestDeMinimis(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.pop(
            "SHOPAI_US_DE_MINIMIS_STATUS", None,
        )

    def tearDown(self):
        if self._orig is not None:
            os.environ[
                "SHOPAI_US_DE_MINIMIS_STATUS"
            ] = self._orig

    def test_us_active_default(self):
        self.assertEqual(
            effective_de_minimis(
                origin="CN", destination="US",
                status_override="active",
            ),
            800.0,
        )

    def test_us_suspended_cn(self):
        self.assertEqual(
            effective_de_minimis(
                origin="CN", destination="US",
                status_override="suspended_cn",
            ),
            0.0,
        )
        # Non-CN origin still gets threshold
        self.assertEqual(
            effective_de_minimis(
                origin="VN", destination="US",
                status_override="suspended_cn",
            ),
            800.0,
        )

    def test_us_suspended_all(self):
        self.assertEqual(
            effective_de_minimis(
                origin="CN", destination="US",
                status_override="suspended_all",
            ),
            0.0,
        )

    def test_us_custom_override(self):
        self.assertEqual(
            effective_de_minimis(
                origin="CN", destination="US",
                status_override="custom:200",
            ),
            200.0,
        )

    def test_eu_threshold(self):
        self.assertEqual(
            effective_de_minimis(
                origin="CN", destination="EU",
            ),
            150.0,
        )

    def test_uk_threshold(self):
        self.assertEqual(
            effective_de_minimis(
                origin="CN", destination="UK",
            ),
            135.0,
        )

    def test_env_var_honored(self):
        os.environ[
            "SHOPAI_US_DE_MINIMIS_STATUS"
        ] = "suspended_cn"
        self.assertEqual(
            effective_de_minimis(
                origin="CN", destination="US",
            ),
            0.0,
        )

    def test_invalid_custom_falls_back(self):
        self.assertEqual(
            effective_de_minimis(
                origin="CN", destination="US",
                status_override="custom:not_a_num",
            ),
            800.0,
        )


class TestCalculate(unittest.TestCase):
    def test_cn_us_under_deminimis_no_duty(self):
        inp = LandedCostInput(
            fob_usd=10.0, destination="US",
            origin="CN", shipping_usd=3.0,
        )
        r = calculate_landed_cost(
            inp, de_minimis_override="active",
        )
        self.assertEqual(r.duty_usd, 0.0)
        self.assertTrue(r.de_minimis_applied)
        self.assertEqual(r.vat_usd, 0.0)
        # total = 10 + 3 + 0 + 0 + 10*0.029 + 0 = 13.29
        self.assertAlmostEqual(
            r.total_usd, 13.29, places=2,
        )

    def test_cn_us_over_deminimis_duty_applied(self):
        # Large shipment
        inp = LandedCostInput(
            fob_usd=900.0, destination="US",
            origin="CN", shipping_usd=50.0,
        )
        r = calculate_landed_cost(
            inp, de_minimis_override="active",
        )
        # 900 + 50 = 950 > 800 → duty 7.5% default category
        self.assertFalse(r.de_minimis_applied)
        self.assertAlmostEqual(r.duty_rate, 0.075)
        self.assertAlmostEqual(r.duty_usd, 67.5)

    def test_cn_us_suspended_cn_no_threshold(self):
        inp = LandedCostInput(
            fob_usd=10.0, destination="US",
            origin="CN", shipping_usd=3.0,
        )
        r = calculate_landed_cost(
            inp, de_minimis_override="suspended_cn",
        )
        self.assertFalse(r.de_minimis_applied)
        # 10 * 0.075 = 0.75
        self.assertAlmostEqual(r.duty_usd, 0.75, places=2)

    def test_apparel_hts_higher_duty(self):
        inp = LandedCostInput(
            fob_usd=1000.0, destination="US",
            origin="CN", hts_code="6109.10",
        )
        r = calculate_landed_cost(
            inp, de_minimis_override="active",
        )
        self.assertAlmostEqual(r.duty_rate, 0.16)

    def test_cn_eu_applies_vat(self):
        inp = LandedCostInput(
            fob_usd=50.0, destination="EU",
            origin="CN", shipping_usd=5.0,
        )
        r = calculate_landed_cost(inp)
        self.assertAlmostEqual(r.vat_rate, 0.20)
        # VAT base = 50 + 5 + duty
        self.assertGreater(r.vat_usd, 0)

    def test_cn_uk_applies_20_vat(self):
        inp = LandedCostInput(
            fob_usd=50.0, destination="UK",
            origin="CN",
        )
        r = calculate_landed_cost(inp)
        self.assertAlmostEqual(r.vat_rate, 0.20)

    def test_us_us_no_duty_no_vat(self):
        inp = LandedCostInput(
            fob_usd=25.0, destination="US",
            origin="US",
        )
        r = calculate_landed_cost(inp)
        self.assertEqual(r.duty_usd, 0.0)
        self.assertEqual(r.vat_usd, 0.0)

    def test_fulfillment_fee_added(self):
        inp = LandedCostInput(
            fob_usd=10.0, destination="US",
            fulfillment_fee_usd=3.0,
        )
        r = calculate_landed_cost(inp)
        self.assertGreaterEqual(r.total_usd, 13.0)

    def test_vat_override_honored(self):
        inp = LandedCostInput(
            fob_usd=50.0, destination="EU",
            vat_pct=0.25,
        )
        r = calculate_landed_cost(inp)
        self.assertEqual(r.vat_rate, 0.25)

    def test_non_input_type_raises(self):
        with self.assertRaises(TypeError):
            calculate_landed_cost({"fob_usd": 10})


class TestMarginHelper(unittest.TestCase):
    def test_margin_closure(self):
        inp = LandedCostInput(
            fob_usd=10.0, destination="US",
            origin="CN",
        )
        r = calculate_landed_cost(
            inp, de_minimis_override="active",
        )
        # total ≈ 10.29; at retail 30, margin = (30-10.29)/30
        m = r.margin_ratio_at(30.0)
        self.assertGreater(m, 0.6)
        self.assertLess(m, 0.7)

    def test_margin_zero_retail(self):
        inp = LandedCostInput(
            fob_usd=10.0, destination="US",
        )
        r = calculate_landed_cost(inp)
        self.assertEqual(r.margin_ratio_at(0), 0.0)


class TestMinimumRetail(unittest.TestCase):
    def test_30pct_margin(self):
        inp = LandedCostInput(
            fob_usd=10.0, destination="US",
            origin="CN",
        )
        min_retail = minimum_retail_for_margin(
            inp, target_margin=0.30,
            de_minimis_override="active",
        )
        # total ≈ 10.29; retail = 10.29 / 0.7 ≈ 14.70
        self.assertAlmostEqual(
            min_retail, 14.70, delta=0.5,
        )

    def test_zero_margin_equals_total(self):
        inp = LandedCostInput(
            fob_usd=10.0, destination="US",
        )
        r = calculate_landed_cost(inp)
        min_retail = minimum_retail_for_margin(
            inp, target_margin=0.0,
        )
        self.assertAlmostEqual(
            min_retail, r.total_usd,
        )

    def test_invalid_margin_raises(self):
        inp = LandedCostInput(
            fob_usd=10.0, destination="US",
        )
        with self.assertRaises(ValueError):
            minimum_retail_for_margin(
                inp, target_margin=1.5,
            )


class TestDicts(unittest.TestCase):
    def test_input_dict(self):
        inp = LandedCostInput(
            fob_usd=10.0, destination="US",
        )
        d = inp.as_dict()
        self.assertEqual(d["fob_usd"], 10.0)

    def test_breakdown_dict(self):
        inp = LandedCostInput(
            fob_usd=10.0, destination="US",
        )
        r = calculate_landed_cost(inp)
        d = r.as_dict()
        self.assertIn("total_usd", d)
        self.assertIn("duty_rate", d)


if __name__ == "__main__":
    unittest.main()
