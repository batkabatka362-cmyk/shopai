"""Tests for the shared margin utility."""
import pytest

from utils.finance import margin, margin_pct


class TestMarginBasic:
    def test_simple_ratio(self):
        assert margin(25, 10) == 0.6

    def test_zero_margin(self):
        assert margin(10, 10) == 0.0

    def test_negative_margin(self):
        # cost > price → negative margin, returned as-is
        assert margin(10, 15) == pytest.approx(-0.5)

    def test_as_percent(self):
        assert margin(25, 10, as_percent=True) == 60.0

    def test_precision(self):
        # 1/3 = 0.3333...
        assert margin(30, 20, precision=2) == 0.33

    def test_precision_percent(self):
        assert margin(30, 20, as_percent=True, precision=1) == 33.3


class TestMarginInvalidInputs:
    def test_none_price_returns_default(self):
        assert margin(None, 10) == 0.0
        assert margin(None, 10, default=0.5) == 0.5

    def test_none_cost_returns_default(self):
        assert margin(25, None) == 0.0
        assert margin(25, None, default=0.3) == 0.3

    def test_zero_price_returns_default(self):
        assert margin(0, 10) == 0.0

    def test_negative_price_returns_default(self):
        assert margin(-5, 2) == 0.0

    def test_non_numeric_price_returns_default(self):
        assert margin("abc", 10) == 0.0

    def test_non_numeric_cost_returns_default(self):
        assert margin(25, "xyz") == 0.0


class TestMarginCostRequirement:
    def test_require_cost_true_rejects_zero_cost(self):
        assert margin(25, 0) == 0.0
        assert margin(25, 0, default=0.5) == 0.5

    def test_require_cost_false_allows_zero(self):
        # Treat cost=0 as zero-cost item → 100% margin
        assert margin(25, 0, require_cost=False) == 1.0
        assert margin(25, 0, require_cost=False, as_percent=True) == 100.0

    def test_require_cost_false_still_rejects_bad_price(self):
        assert margin(0, 0, require_cost=False) == 0.0


class TestMarginString:
    def test_numeric_strings_parse(self):
        assert margin("25", "10") == 0.6

    def test_float_strings(self):
        assert margin("25.5", "10.2") == pytest.approx(0.6)


class TestMarginPct:
    def test_basic(self):
        assert margin_pct(25, 10) == 60.0

    def test_default_precision_is_two(self):
        # 1/3 * 100 = 33.333... → should round to 33.33
        assert margin_pct(30, 20) == 33.33

    def test_override_precision(self):
        assert margin_pct(30, 20, precision=0) == 33.0

    def test_invalid_inputs_return_default(self):
        assert margin_pct(None, 10) == 0.0
        assert margin_pct(25, 0, default=50.0) == 50.0

    def test_require_cost_false(self):
        assert margin_pct(25, 0, require_cost=False) == 100.0
