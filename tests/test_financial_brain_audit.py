"""Tests for audit-pass-25 fixes in core/intelligence/financial_brain.

  1. forecast_cash_flow computed `daily_revenue = sum / len(orders)`
     which is actually AVERAGE ORDER VALUE, not daily revenue.
     The forecast then projected AOV forward as if it were daily
     revenue, systematically under-forecasting by a factor of
     (orders_per_day). For a store with 100 orders averaging $50,
     the old code projected $50/day instead of the real ~$5000/day.
  2. _order_amount fallback chain: `o.get("total", o.get("amount",
     0))` didn't fall back to `amount` when `total=None` (key
     present, value None). Orders that only had amount got
     silently coerced to 0.
  3. shipping_rates tier loop used direct `tier["max_kg"]` /
     `tier["cost"]` access — a malformed tier (e.g. from a partial
     cost_config override) crashed the whole P&L with KeyError.
  4. cost_config shipping_rates override completely replaced the
     default tiers instead of merging — a partial override
     dropped the tiers it didn't mention.
"""
import time

import pytest


def _brain():
    from core.intelligence.financial_brain import FinancialBrain
    return FinancialBrain()


# ── forecast_cash_flow daily_revenue fix ────────────────────


class TestForecastDailyRevenue:
    def test_daily_revenue_uses_actual_span_when_timestamps_present(self):
        """100 orders × $50 spanning 10 days should produce
        daily_revenue ≈ 500/day, NOT 50/day (which was the AOV
        the old code returned)."""
        b = _brain()
        now = time.time()
        orders = [
            {"total": 50, "created_at": now - (10 - i * 0.1) * 86400}
            for i in range(100)
        ]
        result = b.forecast_cash_flow(orders, ad_spend=0, operating_costs=0)
        # 100 orders × $50 = $5000 total. Span ≈ 10 days → ~500/day.
        # Old buggy code returned ~50/day.
        assert result["daily_revenue_avg"] >= 400
        assert result["daily_revenue_avg"] <= 600
        # span_days observed should be about 10
        assert 9 <= result["span_days_observed"] <= 11

    def test_daily_revenue_falls_back_to_period_days(self):
        """Without timestamps, falls back to period_days=30."""
        b = _brain()
        orders = [{"total": 50} for _ in range(60)]  # no timestamps
        result = b.forecast_cash_flow(
            orders, ad_spend=0, operating_costs=0, period_days=30,
        )
        # 60 × $50 = $3000 over 30 days → $100/day
        assert result["daily_revenue_avg"] == pytest.approx(100, abs=1)

    def test_insufficient_orders_returns_status(self):
        b = _brain()
        result = b.forecast_cash_flow([{"total": 100}, {"total": 200}])
        assert result["status"] == "insufficient_data"


# ── _order_amount None fallback ─────────────────────────────


class TestOrderAmountFallback:
    def test_total_none_falls_back_to_amount(self):
        from core.intelligence.financial_brain import FinancialBrain
        order = {"total": None, "amount": 25.50}
        assert FinancialBrain._order_amount(order) == pytest.approx(25.50)

    def test_total_present_wins(self):
        from core.intelligence.financial_brain import FinancialBrain
        order = {"total": 50, "amount": 25}
        assert FinancialBrain._order_amount(order) == 50

    def test_total_zero_falls_through_to_amount(self):
        """A `total=0` is treated as not-set so the fallback to
        amount fires. Most stores never store $0 orders."""
        from core.intelligence.financial_brain import FinancialBrain
        order = {"total": 0, "amount": 25}
        assert FinancialBrain._order_amount(order) == 25

    def test_total_price_field_works(self):
        from core.intelligence.financial_brain import FinancialBrain
        order = {"total_price": "99.99"}
        assert FinancialBrain._order_amount(order) == pytest.approx(99.99)

    def test_no_amount_returns_none(self):
        from core.intelligence.financial_brain import FinancialBrain
        order = {"id": "x", "name": "no money"}
        assert FinancialBrain._order_amount(order) is None

    def test_non_dict_returns_none(self):
        from core.intelligence.financial_brain import FinancialBrain
        assert FinancialBrain._order_amount("not a dict") is None
        assert FinancialBrain._order_amount(None) is None


# ── calculate_pnl uses _order_amount ────────────────────────


class TestCalculatePnlAmountFallback:
    def test_pnl_picks_up_amount_when_total_is_none(self):
        b = _brain()
        # Mix of orders: some with total, some with None+amount
        orders = [
            {"total": 100},
            {"total": None, "amount": 50},
            {"total_price": "200.00"},
        ]
        pnl = b.calculate_pnl([], orders)
        assert pnl["gross_revenue"] == 350
        assert pnl["orders"] == 3


# ── Shipping tier defensive access ──────────────────────────


class TestShippingTierDefensive:
    def test_partial_cost_config_override_does_not_drop_tiers(self):
        """A cost_config that overrides only one tier should
        DEEP-MERGE with defaults, not replace the whole
        shipping_rates dict."""
        b = _brain()
        # Override just the "light" tier
        cfg = {"shipping_rates": {"light": {"max_kg": 0.5, "cost": 5.0}}}
        # Should not crash and should still have all other tiers
        pnl = b.calculate_pnl(
            products=[{"weight": 5.0, "price": 100, "cost": 50}],
            orders=[{"total": 100}],
            cost_config=cfg,
        )
        # 5 kg should hit "heavy" tier ($12) — only works if
        # the heavy tier was preserved by the merge.
        assert pnl["expenses"]["shipping_cost"] == 12.0

    def test_malformed_tier_does_not_crash(self):
        """A tier missing max_kg or cost should be skipped, not
        crash the whole P&L."""
        b = _brain()
        cfg = {
            "shipping_rates": {
                "broken": {"cost": 100},  # no max_kg
                "valid": {"max_kg": 999, "cost": 7.0},
            }
        }
        pnl = b.calculate_pnl(
            products=[{"weight": 1, "price": 50, "cost": 25}],
            orders=[{"total": 50}],
            cost_config=cfg,
        )
        # The broken tier was skipped; the valid one fired.
        assert pnl["expenses"]["shipping_cost"] == 7.0


# ── End-to-end full_analysis still works ───────────────────


class TestFullAnalysisRegression:
    def test_full_analysis_runs_and_returns_expected_fields(self):
        b = _brain()
        result = b.full_analysis(
            products=[{"id": "p1", "price": 50, "cost": 20, "weight": 0.3}],
            orders=[
                {"total": 50, "line_items": [
                    {"product_id": "p1", "quantity": 1, "cost": 20},
                ]},
                {"total": 50, "line_items": [
                    {"product_id": "p1", "quantity": 1, "cost": 20},
                ]},
                {"total": 50, "line_items": [
                    {"product_id": "p1", "quantity": 1, "cost": 20},
                ]},
            ],
            ad_spend=10,
        )
        assert "pnl" in result
        assert "cash_flow" in result
        assert "health_score" in result
        assert result["pnl"]["gross_revenue"] == 150
