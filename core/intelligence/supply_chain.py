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

import math
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("intelligence.supply_chain")


# Dead stock aging tiers
DEAD_STOCK_TIERS = [
    {"days": 90, "label": "slow_moving", "action": "Bundle with fast movers or run 20% discount"},
    {"days": 120, "label": "at_risk", "action": "Run 40% clearance sale, consider liquidation"},
    {"days": 180, "label": "dead_stock", "action": "Liquidate at cost or donate for tax write-off"},
    {"days": 365, "label": "write_off", "action": "Write off inventory, stop reordering"},
]

# Return reason categories and typical rates
RETURN_REASONS = {
    "not_as_described": {"typical_rate": 0.25, "preventable": True, "fix": "Improve product photos and descriptions"},
    "wrong_size": {"typical_rate": 0.20, "preventable": True, "fix": "Add detailed size chart with measurements"},
    "damaged_in_transit": {"typical_rate": 0.15, "preventable": True, "fix": "Improve packaging, add fragile labels"},
    "changed_mind": {"typical_rate": 0.20, "preventable": False, "fix": "Extend return window to reduce urgency"},
    "defective": {"typical_rate": 0.10, "preventable": True, "fix": "Quality inspection before shipping"},
    "late_delivery": {"typical_rate": 0.10, "preventable": True, "fix": "Use faster carrier, set realistic expectations"},
}


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
            "reorder_analysis": self.analyze_reorder_points(products, orders),
            "dead_stock": self.detect_dead_stock(products, orders),
            "shipping_optimization": self.optimize_shipping_threshold(products, orders),
            "returns_intelligence": self.analyze_returns(orders),
            "fulfillment_model": self.recommend_fulfillment_model(orders),
            "demand_planning": self.plan_demand(products, orders),
        }

    def analyze_reorder_points(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
        lead_time_days: int = 14,
        lead_time_variance: int = 7,
    ) -> dict[str, Any]:
        """Calculate reorder points with lead time variance buffer.

        Reorder Point = (avg_daily_sales * max_lead_time) + safety_stock
        Safety Stock = Z * σ * √(lead_time)
        where Z=1.65 for 95% service level, σ = demand std dev
        """
        if not products:
            return {"status": "no_data"}

        # Calculate daily sales per product from orders
        daily_sales: dict[str, float] = {}
        if orders:
            product_units: dict[str, int] = {}
            for order in orders:
                if not isinstance(order, dict):
                    continue
                for item in order.get("line_items", []):
                    if isinstance(item, dict):
                        pid = str(item.get("product_id", ""))
                        qty = safe_int(item.get("quantity", 1))
                        product_units[pid] = product_units.get(pid, 0) + qty
            for pid, units in product_units.items():
                daily_sales[pid] = units / 30  # Assume 30-day order window

        max_lead_time = lead_time_days + lead_time_variance
        z_score = 1.65  # 95% service level

        results = []
        urgent_reorders = 0

        for product in products:
            if not isinstance(product, dict):
                continue

            pid = str(product.get("id", ""))
            name = product.get("title", product.get("name", f"Product {pid}"))
            current_stock = safe_int(product.get("inventory_quantity", 0))
            avg_daily = daily_sales.get(pid, 0.5)  # Default 0.5/day if no data

            # Safety stock calculation
            demand_std = avg_daily * 0.3  # Assume 30% demand variability
            safety_stock = round(z_score * demand_std * math.sqrt(lead_time_days))

            # Reorder point
            reorder_point = round(avg_daily * max_lead_time + safety_stock)

            # Days until stockout
            days_remaining = round(current_stock / max(avg_daily, 0.01))

            needs_reorder = current_stock <= reorder_point
            is_urgent = days_remaining <= lead_time_days

            if is_urgent:
                urgent_reorders += 1

            # Economic order quantity (simplified)
            annual_demand = avg_daily * 365
            ordering_cost = 25  # $25 per order (admin, shipping setup)
            holding_cost_pct = 0.25  # 25% of item cost per year
            item_cost = safe_float(product.get("cost", 10))
            holding_cost = item_cost * holding_cost_pct
            eoq = round(math.sqrt(2 * annual_demand * ordering_cost / max(holding_cost, 0.01))) if annual_demand > 0 else 0

            results.append({
                "product": name,
                "product_id": pid,
                "current_stock": current_stock,
                "avg_daily_sales": round(avg_daily, 2),
                "reorder_point": reorder_point,
                "safety_stock": safety_stock,
                "days_remaining": days_remaining,
                "needs_reorder": needs_reorder,
                "is_urgent": is_urgent,
                "recommended_order_qty": max(eoq, reorder_point * 2),
                "lead_time": f"{lead_time_days}±{lead_time_variance} days",
            })

        results.sort(key=lambda r: r["days_remaining"])

        return {
            "products_analyzed": len(results),
            "urgent_reorders": urgent_reorders,
            "needs_reorder": sum(1 for r in results if r["needs_reorder"]),
            "details": results,
            "lead_time_config": {
                "expected_days": lead_time_days,
                "variance_days": lead_time_variance,
                "max_lead_time": max_lead_time,
                "service_level": "95%",
            },
        }

    def detect_dead_stock(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Detect dead stock — inventory aging that ties up capital."""
        if not products:
            return {"status": "no_data"}

        # Track which products have sold recently
        sold_products = set()
        if orders:
            for order in orders:
                if not isinstance(order, dict):
                    continue
                for item in order.get("line_items", []):
                    if isinstance(item, dict):
                        sold_products.add(str(item.get("product_id", "")))

        results = []
        total_dead_value = 0

        for product in products:
            if not isinstance(product, dict):
                continue

            pid = str(product.get("id", ""))
            name = product.get("title", product.get("name", f"Product {pid}"))
            stock = safe_int(product.get("inventory_quantity", 0))
            cost = safe_float(product.get("cost", 0))
            price = safe_float(product.get("price", 0))
            days_since_last_sale = safe_int(product.get("days_since_last_sale", 0))

            if pid not in sold_products and stock > 0:
                days_since_last_sale = max(days_since_last_sale, 30)

            if stock <= 0 or days_since_last_sale < 30:
                continue

            # Determine aging tier
            tier_label = "active"
            tier_action = "Monitor"
            for tier in DEAD_STOCK_TIERS:
                if days_since_last_sale >= tier["days"]:
                    tier_label = tier["label"]
                    tier_action = tier["action"]

            if tier_label == "active":
                continue

            inventory_value = round(stock * cost, 2)
            total_dead_value += inventory_value

            results.append({
                "product": name,
                "product_id": pid,
                "stock": stock,
                "days_since_sale": days_since_last_sale,
                "tier": tier_label,
                "inventory_value": inventory_value,
                "retail_value": round(stock * price, 2),
                "action": tier_action,
            })

        results.sort(key=lambda r: r["inventory_value"], reverse=True)

        return {
            "dead_stock_items": len(results),
            "total_capital_tied_up": round(total_dead_value, 2),
            "details": results[:20],
            "recommendation": (
                f"${total_dead_value:,.0f} tied up in dead stock. "
                "Bundle slow movers with fast sellers, or run clearance."
                if total_dead_value > 0 else "No significant dead stock detected."
            ),
        }

    def optimize_shipping_threshold(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Calculate optimal free shipping threshold.

        Formula: AOV * 1.3 = optimal threshold
        This turns shipping from a cost into a marketing tool that increases AOV.
        """
        order_values = []
        if orders:
            order_values = [safe_float(o.get("total", 0)) for o in orders if isinstance(o, dict) and safe_float(o.get("total", 0)) > 0]

        if not order_values:
            prices = [safe_float(p.get("price", 0)) for p in products if isinstance(p, dict)]
            avg_price = sum(prices) / max(len(prices), 1)
            order_values = [avg_price]

        current_aov = round(sum(order_values) / len(order_values), 2)
        optimal_threshold = round(current_aov * 1.3, 2)

        # Round to nearest $5 for clean pricing
        optimal_threshold = round(optimal_threshold / 5) * 5

        # Estimate impact
        orders_below = sum(1 for v in order_values if v < optimal_threshold)
        pct_below = round(orders_below / max(len(order_values), 1) * 100, 1)

        return {
            "current_aov": current_aov,
            "recommended_threshold": optimal_threshold,
            "formula": "AOV × 1.3, rounded to nearest $5",
            "orders_below_threshold": orders_below,
            "pct_orders_below": pct_below,
            "expected_aov_increase": f"+{round((optimal_threshold - current_aov) / current_aov * 100)}% if {pct_below}% of customers add items to qualify",
            "key_insight": "Free shipping threshold should be JUST above AOV — customers will add items to qualify. "
                          f"At ${optimal_threshold}, ~{pct_below}% of current orders would need to add more items.",
        }

    def analyze_returns(self, orders: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Analyze return patterns and true cost of returns.

        True return cost = return shipping + restock labor + value loss + potential churn.
        """
        if not orders:
            return {"status": "no_data"}

        total_orders = len(orders)
        returns = [o for o in orders if isinstance(o, dict) and o.get("financial_status") in ("refunded", "partially_refunded")]
        return_count = len(returns)
        return_rate = round(return_count / max(total_orders, 1) * 100, 1)

        avg_order_value = sum(safe_float(o.get("total", 0)) for o in orders if isinstance(o, dict)) / max(total_orders, 1)

        # True cost per return
        return_shipping = 8.0  # Average return shipping cost
        restock_labor = 3.0   # Labor to inspect, repackage
        value_loss = avg_order_value * 0.15  # 15% value depreciation
        customer_churn_cost = avg_order_value * 2 * 0.30  # 30% chance of losing a customer worth 2x AOV

        true_cost_per_return = round(return_shipping + restock_labor + value_loss + customer_churn_cost, 2)
        total_return_cost = round(true_cost_per_return * return_count, 2)

        return {
            "total_orders": total_orders,
            "return_count": return_count,
            "return_rate": return_rate,
            "avg_order_value": round(avg_order_value, 2),
            "true_cost_per_return": true_cost_per_return,
            "cost_breakdown": {
                "return_shipping": return_shipping,
                "restock_labor": restock_labor,
                "value_loss": round(value_loss, 2),
                "customer_churn_risk": round(customer_churn_cost, 2),
            },
            "total_return_cost": total_return_cost,
            "return_reasons": RETURN_REASONS,
            "preventable_pct": sum(v["typical_rate"] for v in RETURN_REASONS.values() if v["preventable"]) * 100,
            "recommendation": (
                f"Returns costing ${total_return_cost:,.0f}/month. "
                f"{sum(1 for v in RETURN_REASONS.values() if v['preventable'])} of {len(RETURN_REASONS)} "
                "return reasons are preventable with better photos, size charts, and packaging."
                if return_count > 0 else "No returns data available."
            ),
        }

    def recommend_fulfillment_model(self, orders: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Recommend self-fulfillment vs 3PL based on volume.

        Breakeven typically at 100+ orders/day.
        """
        daily_orders = len(orders) / 30 if orders else 0

        self_ship_cost = {
            "per_order": 4.50,  # Labor + materials
            "fixed_monthly": 500,  # Rent, utilities for shipping area
        }
        tpl_cost = {
            "per_order": 3.00,  # Pick + pack fee
            "storage_per_unit": 0.50,  # Monthly storage per unit
            "fixed_monthly": 200,  # Account fee
        }

        monthly_orders = daily_orders * 30
        self_total = self_ship_cost["per_order"] * monthly_orders + self_ship_cost["fixed_monthly"]
        tpl_total = tpl_cost["per_order"] * monthly_orders + tpl_cost["fixed_monthly"] + tpl_cost["storage_per_unit"] * monthly_orders * 0.5

        recommendation = "self_fulfillment" if self_total < tpl_total or daily_orders < 5 else "3pl"

        return {
            "daily_order_volume": round(daily_orders, 1),
            "monthly_orders": round(monthly_orders),
            "cost_comparison": {
                "self_fulfillment": round(self_total, 2),
                "3pl": round(tpl_total, 2),
                "savings": round(abs(self_total - tpl_total), 2),
            },
            "recommendation": recommendation,
            "breakeven_point": "~100 orders/day is typical 3PL breakeven",
            "key_insight": (
                "At your volume, self-fulfillment is more cost-effective. "
                "Consider 3PL when you consistently exceed 100 orders/day."
                if recommendation == "self_fulfillment" else
                "At your volume, 3PL would save money and free up your time for growth."
            ),
        }

    def plan_demand(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Demand planning with promotional lift and cannibalization awareness."""
        if not products:
            return {"status": "no_data"}

        # Calculate velocity per product
        product_velocity: dict[str, float] = {}
        if orders:
            for order in orders:
                if not isinstance(order, dict):
                    continue
                for item in order.get("line_items", []):
                    if isinstance(item, dict):
                        pid = str(item.get("product_id", ""))
                        qty = safe_int(item.get("quantity", 1))
                        product_velocity[pid] = product_velocity.get(pid, 0) + qty

        fast_movers = []
        slow_movers = []
        for product in products:
            if not isinstance(product, dict):
                continue
            pid = str(product.get("id", ""))
            name = product.get("title", product.get("name", f"Product {pid}"))
            units = product_velocity.get(pid, 0)
            daily_velocity = units / 30

            entry = {"product": name, "units_30d": units, "daily_velocity": round(daily_velocity, 2)}
            if daily_velocity >= 1:
                fast_movers.append(entry)
            else:
                slow_movers.append(entry)

        fast_movers.sort(key=lambda x: x["daily_velocity"], reverse=True)
        slow_movers.sort(key=lambda x: x["daily_velocity"])

        return {
            "fast_movers": fast_movers[:10],
            "slow_movers": slow_movers[:10],
            "promotional_lift_guide": {
                "10%_discount": "Expected 1.5x volume lift",
                "20%_discount": "Expected 2.5x volume lift",
                "30%_discount": "Expected 3.5x volume lift",
                "bogo": "Expected 4x volume lift but 50% margin hit",
                "free_shipping": "Expected 1.3x volume lift",
            },
            "cannibalization_warning": (
                "Launching similar products may cannibalize existing sales. "
                "Track net revenue change, not just new product revenue."
            ),
        }
