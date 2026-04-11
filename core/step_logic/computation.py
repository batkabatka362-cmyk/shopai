"""Computation — reusable business logic computations.

Pure functions that compute business metrics. Used by PreProcessor
and engines. No side effects, no I/O — just math and logic.
"""
from __future__ import annotations

import math
from typing import Any


class Computation:
    """Reusable business computation functions. All static, pure, no side effects."""

    # --- Pricing ---

    @staticmethod
    def margin(price: float, cost: float) -> float:
        """Compute margin percentage. Treats missing cost as zero (100% margin)."""
        from utils.finance import margin_pct
        return margin_pct(price, cost, require_cost=False)

    @staticmethod
    def markup(price: float, cost: float) -> float:
        """Compute markup percentage."""
        if cost <= 0:
            return 0.0
        return round((price - cost) / cost * 100, 2)

    @staticmethod
    def break_even_units(fixed_costs: float, price: float, variable_cost: float) -> int:
        """Compute break-even units."""
        contribution = price - variable_cost
        if contribution <= 0:
            return -1  # Never breaks even
        return math.ceil(fixed_costs / contribution)

    @staticmethod
    def optimal_price(cost: float, elasticity: float, target_margin: float = 0.3) -> float:
        """Compute optimal price given cost and price elasticity."""
        if elasticity >= -1:
            # Inelastic — can price higher
            return round(cost / (1 - target_margin * 1.2), 2)
        else:
            # Elastic — price sensitively
            return round(cost / (1 - target_margin * 0.8), 2)

    # --- Customer metrics ---

    @staticmethod
    def ltv(avg_order_value: float, purchase_frequency: float, customer_lifespan_years: float) -> float:
        """Compute customer lifetime value."""
        return round(avg_order_value * purchase_frequency * customer_lifespan_years, 2)

    @staticmethod
    def cac(total_marketing_cost: float, new_customers: int) -> float:
        """Compute customer acquisition cost."""
        if new_customers <= 0:
            return 0.0
        return round(total_marketing_cost / new_customers, 2)

    @staticmethod
    def ltv_cac_ratio(ltv: float, cac: float) -> float:
        """Compute LTV:CAC ratio. >3 is healthy."""
        if cac <= 0:
            return 0.0
        return round(ltv / cac, 2)

    @staticmethod
    def churn_rate(lost_customers: int, total_customers: int) -> float:
        """Compute churn rate."""
        if total_customers <= 0:
            return 0.0
        return round(lost_customers / total_customers * 100, 2)

    @staticmethod
    def retention_rate(churn_rate: float) -> float:
        """Compute retention rate from churn rate."""
        return round(100 - churn_rate, 2)

    @staticmethod
    def rfm_score(recency_days: int, frequency: int, monetary: float) -> dict[str, int]:
        """Compute RFM scores (1-5 each)."""
        r = 5 if recency_days < 30 else 4 if recency_days < 60 else 3 if recency_days < 90 else 2 if recency_days < 180 else 1
        f = min(5, max(1, frequency))
        m = 5 if monetary > 500 else 4 if monetary > 200 else 3 if monetary > 100 else 2 if monetary > 50 else 1
        return {"recency": r, "frequency": f, "monetary": m, "total": r + f + m}

    # --- Marketing metrics ---

    @staticmethod
    def roas(revenue: float, ad_spend: float) -> float:
        """Compute Return on Ad Spend."""
        if ad_spend <= 0:
            return 0.0
        return round(revenue / ad_spend, 2)

    @staticmethod
    def ctr(clicks: int, impressions: int) -> float:
        """Compute Click-Through Rate."""
        if impressions <= 0:
            return 0.0
        return round(clicks / impressions * 100, 4)

    @staticmethod
    def conversion_rate(conversions: int, visitors: int) -> float:
        """Compute conversion rate."""
        if visitors <= 0:
            return 0.0
        return round(conversions / visitors * 100, 4)

    @staticmethod
    def cpc(total_spend: float, clicks: int) -> float:
        """Compute Cost Per Click."""
        if clicks <= 0:
            return 0.0
        return round(total_spend / clicks, 2)

    @staticmethod
    def cpa(total_spend: float, acquisitions: int) -> float:
        """Compute Cost Per Acquisition."""
        if acquisitions <= 0:
            return 0.0
        return round(total_spend / acquisitions, 2)

    @staticmethod
    def aov(total_revenue: float, total_orders: int) -> float:
        """Compute Average Order Value."""
        if total_orders <= 0:
            return 0.0
        return round(total_revenue / total_orders, 2)

    # --- Inventory metrics ---

    @staticmethod
    def inventory_turnover(cogs: float, avg_inventory: float) -> float:
        """Compute inventory turnover ratio."""
        if avg_inventory <= 0:
            return 0.0
        return round(cogs / avg_inventory, 2)

    @staticmethod
    def days_of_supply(current_stock: int, daily_sales: float) -> int:
        """Compute days of supply remaining."""
        if daily_sales <= 0:
            return 999
        return math.ceil(current_stock / daily_sales)

    @staticmethod
    def reorder_point(daily_demand: float, lead_time_days: int, safety_stock: int = 0) -> int:
        """Compute reorder point."""
        return math.ceil(daily_demand * lead_time_days + safety_stock)

    @staticmethod
    def economic_order_quantity(annual_demand: int, order_cost: float, holding_cost: float) -> int:
        """Compute EOQ."""
        if holding_cost <= 0:
            return annual_demand
        return round(math.sqrt(2 * annual_demand * order_cost / holding_cost))

    # --- Statistical ---

    @staticmethod
    def mean(values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 4)

    @staticmethod
    def median(values: list[float]) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        n = len(s)
        if n % 2 == 0:
            return round((s[n // 2 - 1] + s[n // 2]) / 2, 4)
        return round(s[n // 2], 4)

    @staticmethod
    def std_dev(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        m = sum(values) / len(values)
        variance = sum((v - m) ** 2 for v in values) / len(values)
        return round(math.sqrt(variance), 4)

    @staticmethod
    def percentile(values: list[float], p: float) -> float:
        """Compute p-th percentile (0-100)."""
        if not values:
            return 0.0
        s = sorted(values)
        k = (len(s) - 1) * (p / 100)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return round(s[int(k)], 4)
        return round(s[f] * (c - k) + s[c] * (k - f), 4)

    @staticmethod
    def z_score(value: float, mean: float, std: float) -> float:
        """Compute z-score."""
        if std <= 0:
            return 0.0
        return round((value - mean) / std, 4)

    @staticmethod
    def growth_rate(current: float, previous: float) -> float:
        """Compute growth rate percentage."""
        if previous <= 0:
            return 0.0
        return round((current - previous) / previous * 100, 2)

    @staticmethod
    def compound_growth(start: float, end: float, periods: int) -> float:
        """Compute compound annual growth rate (CAGR)."""
        if start <= 0 or periods <= 0:
            return 0.0
        return round((math.pow(end / start, 1 / periods) - 1) * 100, 2)
