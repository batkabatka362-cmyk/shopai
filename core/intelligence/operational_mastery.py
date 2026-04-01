"""OperationalMastery — deep supply chain and operations intelligence.

Veterans know: Shipping = MARKETING TOOL, not just cost.
Free shipping threshold → AOV increase.
Supplier leverage → better terms.
Cash conversion cycle → capital efficiency.

Extends SupplyChain with deeper operational knowledge.
"""
from __future__ import annotations

import math
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("intelligence.operational_mastery")

# Supplier leverage tactics by volume
SUPPLIER_LEVERAGE = {
    "volume_discount": {
        "threshold_units": 100,
        "typical_discount": "5-15%",
        "approach": "Commit to X units/month for Y% discount",
        "script": "Based on our {volume} unit monthly volume, we'd like to discuss volume pricing.",
    },
    "payment_terms": {
        "standard": "Net 30",
        "target": "Net 45-60",
        "approach": "Extend payment window in exchange for volume commitment",
        "cash_flow_impact": "15-30 extra days of working capital",
    },
    "exclusive_deal": {
        "what": "You become sole supplier for this category",
        "in_exchange": "15%+ cost reduction or priority fulfillment",
        "risk": "Single point of failure — need backup supplier identified",
    },
    "consignment": {
        "what": "Supplier ships inventory, you pay after sale",
        "benefit": "Zero upfront inventory cost",
        "when": "Proven sales velocity + strong relationship",
    },
}

# Margin stack — the REAL cost structure
MARGIN_STACK_COMPONENTS = [
    {"name": "COGS", "typical_pct": 40, "category": "product", "description": "Cost of goods sold"},
    {"name": "Shipping_inbound", "typical_pct": 3, "category": "logistics", "description": "Getting product to you"},
    {"name": "Shipping_outbound", "typical_pct": 8, "category": "logistics", "description": "Shipping to customer"},
    {"name": "Packaging", "typical_pct": 2, "category": "logistics", "description": "Boxes, labels, inserts"},
    {"name": "Payment_processing", "typical_pct": 3, "category": "fees", "description": "Stripe/PayPal 2.9%+$0.30"},
    {"name": "Platform_fees", "typical_pct": 2, "category": "fees", "description": "Shopify plan + app fees"},
    {"name": "Returns", "typical_pct": 4, "category": "risk", "description": "Return shipping + restock + value loss"},
    {"name": "Chargebacks", "typical_pct": 0.5, "category": "risk", "description": "Disputed transactions"},
    {"name": "Customer_acquisition", "typical_pct": 15, "category": "marketing", "description": "Ad spend / orders"},
    {"name": "Operations", "typical_pct": 5, "category": "overhead", "description": "Labor, tools, software"},
]

# Inventory velocity classifications
VELOCITY_TIERS = {
    "fast_mover": {"threshold_daily": 3.0, "strategy": "Reorder frequently, negotiate volume. Cash cow."},
    "steady": {"threshold_daily": 1.0, "strategy": "Standard reorder cycle. Core of business."},
    "slow_mover": {"threshold_daily": 0.3, "strategy": "Bundle with fast movers or run targeted promotion."},
    "dead_stock": {"threshold_daily": 0.05, "strategy": "Clearance at cost, donate for tax write-off, or discontinue."},
}


class OperationalMastery:
    """Deep operational intelligence for e-commerce.

    Usage:
        ops = OperationalMastery()
        margin = ops.compute_true_margin(product, orders)
        supplier = ops.analyze_supplier_leverage(supplier_data)
        velocity = ops.classify_inventory_velocity(products, orders)
    """

    def full_analysis(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
        suppliers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run full operational analysis."""
        return {
            "true_margins": self.compute_true_margins(products, orders),
            "inventory_velocity": self.classify_inventory_velocity(products, orders),
            "supplier_leverage": self.analyze_supplier_leverage(products, suppliers),
            "operational_efficiency": self.audit_operations(products, orders),
        }

    def compute_true_margins(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Compute TRUE margin after ALL costs (not just COGS).

        Most store owners think margin = price - cost.
        Real margin = price - COGS - shipping - packaging - payment_fee
                      - platform_fee - return_cost - chargeback - CAC - labor
        """
        results = []
        order_count = len(orders) if orders else 1

        for product in products:
            if not isinstance(product, dict):
                continue

            price = safe_float(product.get("price", 0))
            cost = safe_float(product.get("cost", 0))
            weight = safe_float(product.get("weight", 0.5))
            name = product.get("title", product.get("name", "?"))

            if price <= 0:
                continue

            # Build full margin stack
            stack = {
                "revenue": price,
                "cogs": cost,
                "shipping_out": self._estimate_shipping(weight),
                "packaging": 1.50,
                "payment_fee": round(price * 0.029 + 0.30, 2),
                "platform_fee": round(price * 0.02, 2),
                "return_cost": round(price * 0.08 * 0.15 + 0.08 * 6, 2),  # 8% return rate
                "chargeback_cost": round(price * 0.005 * 15 / max(price, 1), 2),  # 0.5% rate * $15 fee
                "cac_per_unit": round(price * 0.15, 2),  # 15% of price typical CAC
                "operations": round(price * 0.05, 2),  # 5% labor/tools
            }

            total_costs = sum(v for k, v in stack.items() if k != "revenue")
            true_profit = price - total_costs
            true_margin = round(true_profit / max(price, 0.01) * 100, 1)
            naive_margin = round((price - cost) / max(price, 0.01) * 100, 1)

            results.append({
                "product": name,
                "price": price,
                "naive_margin": f"{naive_margin}%",
                "true_margin": f"{true_margin}%",
                "margin_gap": f"{naive_margin - true_margin:.1f}%",
                "true_profit_per_unit": round(true_profit, 2),
                "cost_stack": stack,
                "status": "profitable" if true_margin > 0 else "unprofitable",
                "action": (
                    "Raise price or reduce costs" if true_margin < 5
                    else "Monitor" if true_margin < 15
                    else "Healthy"
                ),
            })

        results.sort(key=lambda r: safe_float(r.get("true_profit_per_unit", 0)))

        profitable = [r for r in results if r["status"] == "profitable"]
        unprofitable = [r for r in results if r["status"] == "unprofitable"]

        return {
            "products_analyzed": len(results),
            "profitable": len(profitable),
            "unprofitable": len(unprofitable),
            "avg_naive_margin": f"{sum(safe_float(r['naive_margin'].rstrip('%')) for r in results) / max(len(results), 1):.1f}%",
            "avg_true_margin": f"{sum(safe_float(r['true_margin'].rstrip('%')) for r in results) / max(len(results), 1):.1f}%",
            "margin_stack_template": MARGIN_STACK_COMPONENTS,
            "details": results,
            "insight": (
                f"Average true margin is {sum(safe_float(r['true_margin'].rstrip('%')) for r in results) / max(len(results), 1):.0f}% "
                f"vs naive margin of {sum(safe_float(r['naive_margin'].rstrip('%')) for r in results) / max(len(results), 1):.0f}%. "
                f"Hidden costs eat {sum(safe_float(r['margin_gap'].rstrip('%')) for r in results) / max(len(results), 1):.0f}% of perceived margin."
            ),
        }

    def classify_inventory_velocity(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Classify products by sales velocity → different strategies."""
        velocity: dict[str, float] = {}
        if orders:
            for order in orders:
                if not isinstance(order, dict):
                    continue
                for item in order.get("line_items", []):
                    if isinstance(item, dict):
                        pid = str(item.get("product_id", ""))
                        qty = safe_int(item.get("quantity", 1))
                        velocity[pid] = velocity.get(pid, 0) + qty
            for pid in velocity:
                velocity[pid] /= 30

        classified = {"fast_mover": [], "steady": [], "slow_mover": [], "dead_stock": []}

        for product in products:
            if not isinstance(product, dict):
                continue
            pid = str(product.get("id", ""))
            name = product.get("title", product.get("name", "?"))
            daily = velocity.get(pid, 0.1)

            tier = "dead_stock"
            for tier_name, config in VELOCITY_TIERS.items():
                if daily >= config["threshold_daily"]:
                    tier = tier_name
                    break

            classified[tier].append({
                "product": name,
                "daily_velocity": round(daily, 2),
                "strategy": VELOCITY_TIERS[tier]["strategy"],
            })

        return {
            "fast_movers": len(classified["fast_mover"]),
            "steady": len(classified["steady"]),
            "slow_movers": len(classified["slow_mover"]),
            "dead_stock": len(classified["dead_stock"]),
            "classification": classified,
        }

    def analyze_supplier_leverage(
        self,
        products: list[dict[str, Any]],
        suppliers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Analyze supplier leverage and negotiation opportunities."""
        total_spend = sum(safe_float(p.get("cost", 0)) * safe_int(p.get("units_sold", 1)) for p in products if isinstance(p, dict))
        leverage_tactics = []

        for tactic_name, config in SUPPLIER_LEVERAGE.items():
            applicable = True
            if tactic_name == "volume_discount" and total_spend < 1000:
                applicable = False
            if tactic_name == "consignment" and total_spend < 5000:
                applicable = False

            leverage_tactics.append({
                "tactic": tactic_name,
                "applicable": applicable,
                **{k: v for k, v in config.items() if k not in ("threshold_units",)},
            })

        return {
            "estimated_monthly_spend": round(total_spend, 2),
            "leverage_tactics": leverage_tactics,
            "top_recommendation": next(
                (t["tactic"] for t in leverage_tactics if t["applicable"]),
                "Build volume first",
            ),
        }

    def audit_operations(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Audit operational efficiency and find savings."""
        savings = []
        order_count = len(orders) if orders else 0

        # Packaging optimization
        avg_price = sum(safe_float(p.get("price", 0)) for p in products if isinstance(p, dict)) / max(len(products), 1)
        if avg_price > 50:
            savings.append({
                "area": "packaging",
                "action": "Upgrade to branded packaging — increases perceived value at $0.50 more/unit",
                "monthly_cost": round(order_count * 0.50, 2),
                "expected_impact": "+5-10% repeat purchase rate",
            })

        # Shipping optimization
        if order_count > 100:
            savings.append({
                "area": "shipping",
                "action": "Negotiate carrier rates — at 100+ orders/month, you qualify for volume discounts",
                "potential_savings": f"${round(order_count * 1.5, 0)}/month (est. $1.50/order)",
            })

        # Returns reduction
        if order_count > 50:
            savings.append({
                "area": "returns",
                "action": "Add size charts + 5 product photos — reduces returns 20-30%",
                "potential_savings": f"${round(order_count * 0.08 * 15 * 0.25, 0)}/month",
            })

        return {
            "order_volume": order_count,
            "savings_opportunities": savings,
            "total_potential_savings": sum(safe_float(s.get("potential_savings", "0").replace("$", "").replace("/month", "").replace(",", "")) for s in savings if "potential_savings" in s),
        }

    def _estimate_shipping(self, weight_kg: float) -> float:
        """Estimate shipping cost by weight."""
        if weight_kg <= 0.5:
            return 4.0
        elif weight_kg <= 2:
            return 7.0
        elif weight_kg <= 5:
            return 10.0
        return 15.0
