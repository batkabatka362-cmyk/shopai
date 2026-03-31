"""Financial Intelligence — real unit economics and profitability algorithms.

  - LTV/CAC ratio optimizer
  - Unit economics calculator (all costs included)
  - Break-even analysis
  - Profit waterfall (revenue → all deductions → net profit)
  - Cohort revenue tracking
  - Payback period calculation
"""
from __future__ import annotations

import math
from typing import Any


class FinancialIntelligence:
    """Real financial calculations for e-commerce."""

    def unit_economics(self, product: dict[str, Any], ad_spend: float = 0,
                        orders: int = 0, customers: int = 0) -> dict[str, Any]:
        """Complete unit economics for a product."""
        price = float(product.get("price", 0))
        cost = float(product.get("cost", product.get("cogs", 0)))
        shipping_cost = float(product.get("shipping_cost", 3))
        packaging = float(product.get("packaging_cost", 1))
        return_rate = float(product.get("return_rate", 0.05))

        # Revenue per unit
        gross_revenue = price
        returns_cost = price * return_rate
        net_revenue = gross_revenue - returns_cost

        # COGS
        total_cogs = cost + shipping_cost + packaging

        # Platform fees
        shopify_fee = price * 0.029 + 0.30  # 2.9% + $0.30
        payment_fee = 0  # included in Shopify
        total_fees = shopify_fee

        # Gross profit
        gross_profit = net_revenue - total_cogs - total_fees
        gross_margin = (gross_profit / price * 100) if price > 0 else 0

        # Marketing cost per unit
        cpa = (ad_spend / max(customers, 1)) if customers > 0 else 0
        marketing_per_unit = (ad_spend / max(orders, 1)) if orders > 0 else 0

        # Net profit
        net_profit = gross_profit - marketing_per_unit
        net_margin = (net_profit / price * 100) if price > 0 else 0

        return {
            "revenue": {
                "price": round(price, 2),
                "returns_cost": round(returns_cost, 2),
                "net_revenue": round(net_revenue, 2),
            },
            "costs": {
                "product_cost": round(cost, 2),
                "shipping": round(shipping_cost, 2),
                "packaging": round(packaging, 2),
                "total_cogs": round(total_cogs, 2),
                "shopify_fees": round(shopify_fee, 2),
                "marketing_per_unit": round(marketing_per_unit, 2),
            },
            "profit": {
                "gross_profit": round(gross_profit, 2),
                "gross_margin_pct": round(gross_margin, 1),
                "net_profit": round(net_profit, 2),
                "net_margin_pct": round(net_margin, 1),
            },
            "metrics": {
                "cpa": round(cpa, 2),
                "return_rate": f"{return_rate*100:.0f}%",
                "break_even_units": math.ceil(ad_spend / max(gross_profit, 0.01)) if ad_spend > 0 and gross_profit > 0 else 0,
            },
            "waterfall": self._profit_waterfall(price, cost, shipping_cost, packaging, return_rate, shopify_fee, marketing_per_unit),
        }

    def ltv_cac_analysis(self, customers: list[dict[str, Any]], ad_spend: float, months: int = 12) -> dict[str, Any]:
        """LTV/CAC ratio analysis from customer data."""
        if not customers:
            return {"error": "No customer data"}

        total_customers = len(customers)
        new_customers = sum(1 for c in customers if int(c.get("orders", 0)) <= 1)
        cac = ad_spend / max(new_customers, 1) if ad_spend > 0 else 0

        # LTV calculation
        revenues = [float(c.get("total_spent", c.get("ltv", 0))) for c in customers]
        avg_revenue = sum(revenues) / max(len(revenues), 1)
        order_counts = [int(c.get("orders", c.get("order_count", 0))) for c in customers]
        avg_orders = sum(order_counts) / max(len(order_counts), 1)
        avg_order_value = avg_revenue / max(avg_orders, 1)
        repeat_rate = sum(1 for o in order_counts if o > 1) / max(total_customers, 1)

        # Projected LTV (simple model)
        purchase_frequency_year = avg_orders * (12 / max(months, 1))
        customer_lifespan_years = 1 / max(1 - repeat_rate, 0.1)
        projected_ltv = avg_order_value * purchase_frequency_year * customer_lifespan_years

        ratio = projected_ltv / max(cac, 1) if cac > 0 else 0
        payback_months = cac / max(avg_order_value * (purchase_frequency_year / 12), 0.01) if cac > 0 else 0

        return {
            "ltv": round(projected_ltv, 2),
            "cac": round(cac, 2),
            "ltv_cac_ratio": round(ratio, 2),
            "ratio_grade": "Excellent" if ratio >= 5 else "Good" if ratio >= 3 else "OK" if ratio >= 1.5 else "Poor",
            "payback_months": round(payback_months, 1),
            "inputs": {
                "avg_order_value": round(avg_order_value, 2),
                "purchase_frequency": round(purchase_frequency_year, 1),
                "repeat_rate": round(repeat_rate * 100, 1),
                "customer_lifespan_years": round(customer_lifespan_years, 1),
            },
            "recommendation": self._ltv_recommendation(ratio, payback_months, cac),
        }

    def break_even_analysis(self, fixed_costs: float, price: float, variable_cost: float,
                             ad_spend_monthly: float = 0) -> dict[str, Any]:
        """Break-even analysis with ad spend."""
        total_variable = variable_cost + (price * 0.029 + 0.30)  # Include Shopify fees
        contribution = price - total_variable
        monthly_fixed = fixed_costs + ad_spend_monthly

        if contribution <= 0:
            return {"error": "Negative contribution margin — price doesn't cover variable costs",
                    "contribution_margin": round(contribution, 2)}

        break_even_units = math.ceil(monthly_fixed / contribution)
        break_even_revenue = break_even_units * price

        # Scenarios
        scenarios = []
        for margin_target in [0, 10, 20, 30]:
            target_profit = monthly_fixed * (margin_target / 100)
            units_needed = math.ceil((monthly_fixed + target_profit) / contribution)
            scenarios.append({
                "margin_target": f"{margin_target}%",
                "units_needed": units_needed,
                "revenue_needed": round(units_needed * price, 2),
                "daily_units": math.ceil(units_needed / 30),
            })

        return {
            "break_even_units": break_even_units,
            "break_even_revenue": round(break_even_revenue, 2),
            "break_even_daily": math.ceil(break_even_units / 30),
            "contribution_per_unit": round(contribution, 2),
            "contribution_margin_pct": round(contribution / price * 100, 1),
            "fixed_costs": round(monthly_fixed, 2),
            "scenarios": scenarios,
        }

    def profit_waterfall(self, monthly_data: dict[str, Any]) -> dict[str, Any]:
        """Detailed profit waterfall from gross revenue to net."""
        revenue = float(monthly_data.get("gross_revenue", monthly_data.get("revenue", 0)))
        cogs = float(monthly_data.get("cogs", monthly_data.get("cost_of_goods", 0)))
        shipping = float(monthly_data.get("shipping_costs", 0))
        returns = float(monthly_data.get("returns", 0))
        platform_fees = float(monthly_data.get("platform_fees", revenue * 0.029))
        marketing = float(monthly_data.get("marketing_spend", monthly_data.get("ad_spend", 0)))
        tools = float(monthly_data.get("tools_subscriptions", 50))
        labor = float(monthly_data.get("labor", 0))

        gross_profit = revenue - cogs - shipping - returns
        operating_profit = gross_profit - platform_fees - marketing - tools - labor
        tax_estimate = max(0, operating_profit * 0.25)
        net_profit = operating_profit - tax_estimate

        steps = [
            {"label": "Gross Revenue", "amount": round(revenue, 2), "running": round(revenue, 2)},
            {"label": "- COGS", "amount": round(-cogs, 2), "running": round(revenue - cogs, 2)},
            {"label": "- Shipping", "amount": round(-shipping, 2), "running": round(revenue - cogs - shipping, 2)},
            {"label": "- Returns", "amount": round(-returns, 2), "running": round(gross_profit, 2)},
            {"label": "= Gross Profit", "amount": round(gross_profit, 2), "running": round(gross_profit, 2), "highlight": True},
            {"label": "- Platform Fees", "amount": round(-platform_fees, 2), "running": round(gross_profit - platform_fees, 2)},
            {"label": "- Marketing", "amount": round(-marketing, 2), "running": round(gross_profit - platform_fees - marketing, 2)},
            {"label": "- Tools/Subs", "amount": round(-tools, 2), "running": round(gross_profit - platform_fees - marketing - tools, 2)},
            {"label": "- Labor", "amount": round(-labor, 2), "running": round(operating_profit, 2)},
            {"label": "= Operating Profit", "amount": round(operating_profit, 2), "running": round(operating_profit, 2), "highlight": True},
            {"label": "- Tax (est 25%)", "amount": round(-tax_estimate, 2), "running": round(net_profit, 2)},
            {"label": "= Net Profit", "amount": round(net_profit, 2), "running": round(net_profit, 2), "highlight": True},
        ]

        return {
            "waterfall": steps,
            "summary": {
                "gross_revenue": round(revenue, 2),
                "gross_profit": round(gross_profit, 2),
                "gross_margin_pct": round(gross_profit / max(revenue, 1) * 100, 1),
                "operating_profit": round(operating_profit, 2),
                "operating_margin_pct": round(operating_profit / max(revenue, 1) * 100, 1),
                "net_profit": round(net_profit, 2),
                "net_margin_pct": round(net_profit / max(revenue, 1) * 100, 1),
            },
        }

    @staticmethod
    def _profit_waterfall(price, cost, shipping, packaging, return_rate, fees, marketing):
        return [
            {"step": "Sale Price", "amount": round(price, 2)},
            {"step": "- Product Cost", "amount": round(-cost, 2)},
            {"step": "- Shipping", "amount": round(-shipping, 2)},
            {"step": "- Packaging", "amount": round(-packaging, 2)},
            {"step": "- Returns Reserve", "amount": round(-price * return_rate, 2)},
            {"step": "- Platform Fees", "amount": round(-fees, 2)},
            {"step": "- Marketing/Unit", "amount": round(-marketing, 2)},
            {"step": "= Net Profit", "amount": round(price - cost - shipping - packaging - price*return_rate - fees - marketing, 2)},
        ]

    @staticmethod
    def _ltv_recommendation(ratio: float, payback: float, cac: float) -> str:
        if ratio >= 5:
            return f"Excellent LTV/CAC ({ratio:.1f}x). Scale acquisition aggressively — room to spend more."
        if ratio >= 3:
            return f"Healthy LTV/CAC ({ratio:.1f}x). Continue current strategy, optimize for efficiency."
        if ratio >= 1.5:
            return f"Marginal LTV/CAC ({ratio:.1f}x). Focus on retention to increase LTV or reduce CAC."
        return f"Poor LTV/CAC ({ratio:.1f}x). CAC=${cac:.2f} too high — reduce ad spend or improve targeting."
