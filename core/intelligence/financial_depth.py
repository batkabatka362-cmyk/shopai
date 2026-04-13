"""Financial Depth — expert-level financial intelligence beyond basic P&L.

What a 10-year e-commerce veteran knows:
  - Tax nexus: 12,000+ US jurisdictions, economic nexus thresholds vary by state
  - BNPL: Increases AOV 30-50%, but merchant fees 4-6%
  - Dimensional weight: Carriers charge max(actual_weight, L*W*H/divisor)
  - Working capital: Cash conversion cycle, AP/AR aging
  - Payment processor optimization: Route to lowest-cost processor
  - Chargeback management: >1% rate = account termination risk
  - Currency conversion: 2-4% FX fees on international sales
  - Contribution margin per SKU: The REAL profitability metric
"""
from __future__ import annotations

import math
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("intelligence.financial_depth")


# US Economic Nexus Thresholds (simplified — top states)
TAX_NEXUS_THRESHOLDS = {
    "CA": {"revenue": 500000, "transactions": 0, "rate": 0.0725},
    "TX": {"revenue": 500000, "transactions": 0, "rate": 0.0625},
    "NY": {"revenue": 500000, "transactions": 100, "rate": 0.08},
    "FL": {"revenue": 100000, "transactions": 0, "rate": 0.06},
    "IL": {"revenue": 100000, "transactions": 200, "rate": 0.0625},
    "PA": {"revenue": 100000, "transactions": 0, "rate": 0.06},
    "OH": {"revenue": 100000, "transactions": 200, "rate": 0.0575},
    "GA": {"revenue": 100000, "transactions": 200, "rate": 0.04},
    "NC": {"revenue": 100000, "transactions": 200, "rate": 0.0475},
    "MI": {"revenue": 100000, "transactions": 200, "rate": 0.06},
    "NJ": {"revenue": 100000, "transactions": 200, "rate": 0.06625},
    "VA": {"revenue": 100000, "transactions": 200, "rate": 0.053},
    "WA": {"revenue": 100000, "transactions": 0, "rate": 0.065},
    "MA": {"revenue": 100000, "transactions": 0, "rate": 0.0625},
    "AZ": {"revenue": 100000, "transactions": 0, "rate": 0.056},
    "CO": {"revenue": 100000, "transactions": 0, "rate": 0.029},
    "TN": {"revenue": 100000, "transactions": 0, "rate": 0.07},
    "IN": {"revenue": 100000, "transactions": 0, "rate": 0.07},
    "MO": {"revenue": 100000, "transactions": 0, "rate": 0.04225},
    "WI": {"revenue": 100000, "transactions": 0, "rate": 0.05},
}

# DIM weight divisors by carrier
DIM_WEIGHT_DIVISORS = {
    "ups": 139,       # UPS domestic (inches)
    "fedex": 139,     # FedEx domestic (inches)
    "usps": 166,      # USPS (inches)
    "dhl": 5000,      # DHL (cm, international)
}

# BNPL provider fees
BNPL_PROVIDERS = {
    "afterpay": {"merchant_fee_pct": 0.06, "merchant_fee_fixed": 0.30, "avg_aov_lift": 0.40, "avg_cvr_lift": 0.20},
    "klarna": {"merchant_fee_pct": 0.0399, "merchant_fee_fixed": 0.30, "avg_aov_lift": 0.45, "avg_cvr_lift": 0.25},
    "affirm": {"merchant_fee_pct": 0.055, "merchant_fee_fixed": 0.30, "avg_aov_lift": 0.50, "avg_cvr_lift": 0.20},
    "shop_pay_installments": {"merchant_fee_pct": 0.052, "merchant_fee_fixed": 0.0, "avg_aov_lift": 0.35, "avg_cvr_lift": 0.15},
}

# Payment processors
PAYMENT_PROCESSORS = {
    "shopify_payments": {"pct": 0.029, "fixed": 0.30, "chargeback_fee": 15, "hold_days": 2},
    "stripe": {"pct": 0.029, "fixed": 0.30, "chargeback_fee": 15, "hold_days": 2},
    "paypal": {"pct": 0.0349, "fixed": 0.49, "chargeback_fee": 20, "hold_days": 1},
    "square": {"pct": 0.029, "fixed": 0.30, "chargeback_fee": 0, "hold_days": 1},
}


class FinancialDepth:
    """Expert-level financial intelligence for e-commerce stores."""

    def full_analysis(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]],
        revenue_by_state: dict[str, float] | None = None,
        current_processor: str = "shopify_payments",
    ) -> dict[str, Any]:
        """Run comprehensive financial depth analysis."""
        return {
            "tax_nexus": self.analyze_tax_nexus(revenue_by_state or {}),
            "bnpl_opportunity": self.analyze_bnpl(products, orders),
            "shipping_optimization": self.analyze_dimensional_shipping(products),
            "working_capital": self.analyze_working_capital(orders),
            "payment_optimization": self.optimize_payment_processor(orders, current_processor),
            "chargeback_risk": self.assess_chargeback_risk(orders),
            "contribution_margins": self.contribution_margin_by_sku(products, orders),
        }

    def analyze_tax_nexus(self, revenue_by_state: dict[str, float]) -> dict[str, Any]:
        """Analyze tax nexus obligations across US states.

        Returns which states you have economic nexus in and estimated tax liability.
        """
        if not revenue_by_state:
            return {"status": "no_data", "note": "Provide revenue_by_state for nexus analysis"}

        nexus_states = []
        non_nexus_states = []
        total_liability = 0

        for state, threshold in TAX_NEXUS_THRESHOLDS.items():
            state_revenue = revenue_by_state.get(state, 0)
            has_nexus = state_revenue >= threshold["revenue"]

            if has_nexus:
                tax = round(state_revenue * threshold["rate"], 2)
                total_liability += tax
                nexus_states.append({
                    "state": state,
                    "revenue": state_revenue,
                    "threshold": threshold["revenue"],
                    "rate": threshold["rate"],
                    "estimated_tax": tax,
                    "over_by": round(state_revenue - threshold["revenue"], 2),
                })
            elif state_revenue > threshold["revenue"] * 0.7:
                non_nexus_states.append({
                    "state": state,
                    "revenue": state_revenue,
                    "threshold": threshold["revenue"],
                    "pct_to_nexus": round(state_revenue / threshold["revenue"] * 100, 1),
                    "warning": "Approaching nexus threshold",
                })

        return {
            "nexus_states": nexus_states,
            "approaching_nexus": non_nexus_states,
            "total_estimated_tax": round(total_liability, 2),
            "states_with_nexus": len(nexus_states),
            "states_approaching": len(non_nexus_states),
            "action_needed": len(nexus_states) > 0,
        }

    def analyze_bnpl(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Analyze Buy Now Pay Later opportunity.

        BNPL typically increases AOV 30-50% and conversion 15-25%,
        but costs 4-6% in merchant fees.
        """
        prices = [safe_float(p.get("price", 0)) for p in products if isinstance(p, dict)]
        if not prices:
            return {"status": "no_data"}

        avg_price = sum(prices) / len(prices)
        order_values = [safe_float(o.get("total", 0)) for o in orders if isinstance(o, dict)]
        current_aov = sum(order_values) / max(len(order_values), 1) if order_values else avg_price
        monthly_revenue = sum(order_values)
        monthly_orders = len(order_values)

        # BNPL makes most sense for $50-3000 range
        bnpl_suitable = 50 <= avg_price <= 3000

        results = []
        for provider, config in BNPL_PROVIDERS.items():
            projected_aov = current_aov * (1 + config["avg_aov_lift"])
            projected_orders = monthly_orders * (1 + config["avg_cvr_lift"])
            projected_revenue = projected_aov * projected_orders

            # Estimate BNPL adoption rate (typically 15-30% of orders)
            bnpl_adoption = 0.20
            bnpl_revenue = projected_revenue * bnpl_adoption
            bnpl_fees = bnpl_revenue * config["merchant_fee_pct"] + projected_orders * bnpl_adoption * config["merchant_fee_fixed"]

            # Net impact
            incremental_revenue = projected_revenue - monthly_revenue
            net_benefit = incremental_revenue - bnpl_fees

            results.append({
                "provider": provider,
                "merchant_fee": f"{config['merchant_fee_pct']*100:.1f}%",
                "projected_aov_lift": f"+{config['avg_aov_lift']*100:.0f}%",
                "projected_cvr_lift": f"+{config['avg_cvr_lift']*100:.0f}%",
                "projected_monthly_revenue": round(projected_revenue, 2),
                "estimated_monthly_fees": round(bnpl_fees, 2),
                "net_monthly_benefit": round(net_benefit, 2),
                "roi": round(net_benefit / max(bnpl_fees, 1) * 100, 1),
            })

        results.sort(key=lambda r: r["net_monthly_benefit"], reverse=True)

        return {
            "suitable_for_bnpl": bnpl_suitable,
            "current_aov": round(current_aov, 2),
            "avg_product_price": round(avg_price, 2),
            "providers": results,
            "recommendation": results[0]["provider"] if results and results[0]["net_monthly_benefit"] > 0 else "none",
        }

    def analyze_dimensional_shipping(self, products: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate dimensional weight shipping costs.

        Carriers charge whichever is greater: actual weight or dimensional weight.
        dim_weight = (L x W x H) / divisor

        Most stores only track actual weight — this finds hidden shipping cost increases.
        """
        results = []
        underpaying = 0
        total_actual_cost = 0
        total_dim_cost = 0

        for product in products:
            if not isinstance(product, dict):
                continue

            actual_weight = safe_float(product.get("weight", 0))
            # Convert grams to lbs if needed
            if actual_weight > 100:
                actual_weight = actual_weight / 453.592  # grams to lbs

            length = safe_float(product.get("length", 0))
            width = safe_float(product.get("width", 0))
            height = safe_float(product.get("height", 0))

            if length == 0 or width == 0 or height == 0:
                continue

            dim_weights = {}
            for carrier, divisor in DIM_WEIGHT_DIVISORS.items():
                if carrier == "dhl":
                    # DHL uses cm
                    dim_w = (length * 2.54 * width * 2.54 * height * 2.54) / divisor
                    dim_w = dim_w * 2.20462  # kg to lbs
                else:
                    dim_w = (length * width * height) / divisor
                dim_weights[carrier] = round(dim_w, 2)

            # Find which carriers would charge dim weight
            billable_weights = {}
            for carrier, dim_w in dim_weights.items():
                billable = max(actual_weight, dim_w)
                billable_weights[carrier] = billable
                if dim_w > actual_weight:
                    underpaying += 1

            product_name = product.get("title", product.get("name", "Unknown"))
            results.append({
                "product": product_name,
                "actual_weight_lbs": round(actual_weight, 2),
                "dim_weights": dim_weights,
                "billable_weights": billable_weights,
                "using_dim": any(dw > actual_weight for dw in dim_weights.values()),
            })

        return {
            "products_analyzed": len(results),
            "products_with_dim_surcharge": underpaying,
            "details": results[:20],  # Top 20
            "recommendation": (
                f"{underpaying} products may incur dimensional weight surcharges. "
                "Consider optimizing packaging to reduce L×W×H."
                if underpaying > 0 else "No dimensional weight issues detected."
            ),
        }

    def analyze_working_capital(self, orders: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze working capital and cash conversion cycle.

        Cash Conversion Cycle = DIO + DSO - DPO
          DIO = Days Inventory Outstanding (how long inventory sits)
          DSO = Days Sales Outstanding (how long to collect payment)
          DPO = Days Payable Outstanding (how long before paying suppliers)
        """
        if not orders:
            return {"status": "no_data"}

        order_values = [safe_float(o.get("total", 0)) for o in orders if isinstance(o, dict)]
        total_revenue = sum(order_values)
        daily_revenue = total_revenue / 30  # Assume 30-day period

        # Shopify pays out in 2-3 business days
        dso = 3  # Days to receive payment from Shopify

        # Typical supplier payment terms
        dpo = 30  # Net 30 terms assumed

        # Inventory turnover estimate
        avg_inventory_value = total_revenue * 0.4  # Rough estimate: 40% of revenue in inventory
        dio = round(avg_inventory_value / max(daily_revenue * 0.4, 0.01), 1) if daily_revenue > 0 else 0

        ccc = round(dio + dso - dpo, 1)

        # Runway calculation
        cash_needed_per_day = daily_revenue * 0.6  # 60% of revenue goes to costs
        monthly_cash_need = round(cash_needed_per_day * 30, 2)

        return {
            "daily_revenue": round(daily_revenue, 2),
            "cash_conversion_cycle_days": ccc,
            "days_inventory_outstanding": dio,
            "days_sales_outstanding": dso,
            "days_payable_outstanding": dpo,
            "monthly_cash_requirement": monthly_cash_need,
            "interpretation": (
                "Negative CCC = good (you collect before paying suppliers)"
                if ccc < 0 else
                f"Positive CCC ({ccc} days) = you need working capital to bridge the gap"
            ),
            "recommendations": self._working_capital_recommendations(ccc, dio, daily_revenue),
        }

    def optimize_payment_processor(
        self,
        orders: list[dict[str, Any]],
        current_processor: str = "shopify_payments",
    ) -> dict[str, Any]:
        """Compare payment processors and find the cheapest option."""
        order_values = [safe_float(o.get("total", 0)) for o in orders if isinstance(o, dict)]
        if not order_values:
            return {"status": "no_data"}

        total_revenue = sum(order_values)
        order_count = len(order_values)
        avg_order = total_revenue / max(order_count, 1)

        comparisons = []
        for processor, config in PAYMENT_PROCESSORS.items():
            fees = total_revenue * config["pct"] + order_count * config["fixed"]
            fee_pct = fees / max(total_revenue, 1) * 100
            comparisons.append({
                "processor": processor,
                "monthly_fees": round(fees, 2),
                "effective_rate": round(fee_pct, 2),
                "per_transaction": round(avg_order * config["pct"] + config["fixed"], 2),
                "chargeback_fee": config["chargeback_fee"],
                "hold_days": config["hold_days"],
                "is_current": processor == current_processor,
            })

        comparisons.sort(key=lambda c: c["monthly_fees"])
        cheapest = comparisons[0]
        current = next((c for c in comparisons if c["is_current"]), comparisons[0])
        savings = round(current["monthly_fees"] - cheapest["monthly_fees"], 2)

        return {
            "comparisons": comparisons,
            "cheapest": cheapest["processor"],
            "current": current_processor,
            "potential_monthly_savings": savings,
            "recommendation": (
                f"Switch to {cheapest['processor']} to save ${savings}/month"
                if savings > 10 else "Current processor is optimal or near-optimal"
            ),
        }

    def assess_chargeback_risk(self, orders: list[dict[str, Any]]) -> dict[str, Any]:
        """Assess chargeback risk. >1% rate = Shopify Payments termination risk."""
        if not orders:
            return {"status": "no_data"}

        total_orders = len(orders)
        # Count orders with chargeback indicators
        chargebacks = sum(
            1 for o in orders
            if isinstance(o, dict) and o.get("financial_status") == "refunded"
            and o.get("cancel_reason") == "fraud"
        )
        # Estimate from refund rate if no direct chargeback data
        refunds = sum(
            1 for o in orders
            if isinstance(o, dict) and o.get("financial_status") in ("refunded", "partially_refunded")
        )

        chargeback_rate = chargebacks / max(total_orders, 1)
        refund_rate = refunds / max(total_orders, 1)
        estimated_chargeback_rate = max(chargeback_rate, refund_rate * 0.1)  # ~10% of refunds become chargebacks

        risk_level = "low"
        if estimated_chargeback_rate > 0.01:
            risk_level = "critical"
        elif estimated_chargeback_rate > 0.005:
            risk_level = "high"
        elif estimated_chargeback_rate > 0.002:
            risk_level = "medium"

        return {
            "total_orders": total_orders,
            "known_chargebacks": chargebacks,
            "refunds": refunds,
            "refund_rate": round(refund_rate * 100, 2),
            "estimated_chargeback_rate": round(estimated_chargeback_rate * 100, 3),
            "risk_level": risk_level,
            "threshold": "1% = Shopify Payments account termination",
            "recommendations": self._chargeback_recommendations(risk_level, estimated_chargeback_rate),
        }

    def contribution_margin_by_sku(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Calculate true contribution margin per SKU.

        Contribution Margin = Revenue - COGS - Variable Costs (shipping, payment fees, packaging)
        This is the REAL profitability metric, not just price - cost.
        """
        sku_data: dict[str, dict[str, Any]] = {}

        # Build product lookup
        product_lookup: dict[str, dict[str, Any]] = {}
        for p in products:
            if isinstance(p, dict):
                pid = str(p.get("id", ""))
                if pid:
                    product_lookup[pid] = p

        # Aggregate order data by product
        for order in orders:
            if not isinstance(order, dict):
                continue
            for item in order.get("line_items", []):
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("product_id", ""))
                qty = safe_int(item.get("quantity", 1))
                revenue = safe_float(item.get("price", 0)) * qty

                product = product_lookup.get(pid, {})
                cost = safe_float(item.get("cost", 0)) or safe_float(product.get("cost", 0))
                cogs = cost * qty

                if pid not in sku_data:
                    sku_data[pid] = {
                        "product_id": pid,
                        "name": product.get("title", product.get("name", f"Product {pid}")),
                        "units_sold": 0,
                        "revenue": 0,
                        "cogs": 0,
                    }

                sku_data[pid]["units_sold"] += qty
                sku_data[pid]["revenue"] += revenue
                sku_data[pid]["cogs"] += cogs

        # Calculate contribution margin per SKU
        results = []
        for pid, data in sku_data.items():
            revenue = data["revenue"]
            cogs = data["cogs"]
            units = data["units_sold"]

            # Variable costs per unit
            payment_fee = revenue * 0.029 + units * 0.30
            shipping_est = units * 7.0  # Average shipping
            packaging = units * 1.50
            return_cost = units * 0.08 * 6.0  # 8% return rate * $6 return shipping

            total_variable = cogs + payment_fee + shipping_est + packaging + return_cost
            contribution = revenue - total_variable
            margin_pct = round(contribution / max(revenue, 0.01) * 100, 1)

            results.append({
                "product_id": pid,
                "name": data["name"],
                "units_sold": units,
                "revenue": round(revenue, 2),
                "cogs": round(cogs, 2),
                "variable_costs": {
                    "payment_fees": round(payment_fee, 2),
                    "shipping": round(shipping_est, 2),
                    "packaging": round(packaging, 2),
                    "returns": round(return_cost, 2),
                },
                "contribution_margin": round(contribution, 2),
                "contribution_margin_pct": margin_pct,
                "status": "profitable" if margin_pct > 0 else "unprofitable",
            })

        results.sort(key=lambda r: r["contribution_margin"], reverse=True)

        profitable = [r for r in results if r["contribution_margin_pct"] > 0]
        unprofitable = [r for r in results if r["contribution_margin_pct"] <= 0]

        return {
            "skus_analyzed": len(results),
            "profitable_skus": len(profitable),
            "unprofitable_skus": len(unprofitable),
            "details": results,
            "recommendation": (
                f"{len(unprofitable)} SKUs are unprofitable after variable costs. "
                "Consider price increases or discontinuation."
                if unprofitable else "All SKUs are profitable."
            ),
        }

    def _working_capital_recommendations(self, ccc: float, dio: float, daily_revenue: float) -> list[str]:
        recs = []
        if ccc > 15:
            recs.append("Negotiate longer payment terms with suppliers (Net 45/60)")
        if dio > 45:
            recs.append("Inventory sitting too long — run clearance on slow movers")
        if daily_revenue > 500 and ccc > 0:
            recs.append(f"Consider a line of credit for ${round(ccc * daily_revenue * 0.6, 0)} working capital gap")
        if not recs:
            recs.append("Working capital position is healthy")
        return recs

    def _chargeback_recommendations(self, risk_level: str, rate: float) -> list[str]:
        recs = []
        if risk_level == "critical":
            recs.append("URGENT: Chargeback rate exceeds 1% — Shopify Payments at risk of termination")
            recs.append("Enable fraud analysis on all orders")
            recs.append("Require signature confirmation on orders > $250")
        if risk_level in ("critical", "high"):
            recs.append("Add clear product descriptions and photos to reduce 'not as described' disputes")
            recs.append("Send shipping confirmation with tracking immediately")
            recs.append("Make return policy prominent and easy to find")
        if risk_level == "medium":
            recs.append("Monitor chargeback rate weekly")
            recs.append("Consider adding chargeback prevention tools (Verifi, Ethoca)")
        if not recs:
            recs.append("Chargeback risk is low — maintain current practices")
        return recs
