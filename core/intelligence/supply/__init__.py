"""Supply Chain Intelligence — operational mastery from 10 years experience.

What veterans know:
  - MOQ negotiation affects cash requirements and storage costs
  - Lead time variance: supplier says 14 days, actual is 10-21 — plan for worst case
  - Dead stock ties up capital: 90/120/180 day aging rules for clearance
  - Returns cost 3x what you think: shipping + restock + value loss + customer churn
  - Free shipping threshold = AOV * 1.3 (turns shipping into marketing tool)
  - 3PL vs self-ship breakeven at ~100 orders/day
  - Reorder point = (avg_daily_sales * lead_time) + safety_stock
"""
from __future__ import annotations

from typing import Any

from .reorder_calculator import analyze_reorder_points
from .dead_stock import detect_dead_stock
from .shipping_threshold import optimize_shipping_threshold
from .returns_analyzer import analyze_returns
from .fulfillment_model import recommend_fulfillment_model
from .demand_planner import plan_demand


class SupplyChainIntelligence:
    """Supply chain and inventory intelligence engine."""

    def full_analysis(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
        supplier_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run full supply chain analysis."""
        return {
            "reorder_analysis": analyze_reorder_points(products, orders),
            "dead_stock": detect_dead_stock(products, orders),
            "shipping_optimization": optimize_shipping_threshold(products, orders),
            "returns_intelligence": analyze_returns(orders),
            "fulfillment_model": recommend_fulfillment_model(orders),
            "demand_planning": plan_demand(products, orders),
        }

    def analyze_reorder_points(self, products, orders=None, lead_time_days=14, lead_time_variance=7):
        return analyze_reorder_points(products, orders, lead_time_days, lead_time_variance)

    def detect_dead_stock(self, products, orders=None):
        return detect_dead_stock(products, orders)

    def optimize_shipping_threshold(self, products, orders=None):
        return optimize_shipping_threshold(products, orders)

    def analyze_returns(self, orders=None):
        return analyze_returns(orders)

    def recommend_fulfillment_model(self, orders=None):
        return recommend_fulfillment_model(orders)

    def plan_demand(self, products, orders=None):
        return plan_demand(products, orders)
