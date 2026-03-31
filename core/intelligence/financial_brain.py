"""Financial Brain — comprehensive financial intelligence for store operations.

Answers: "Are we making money? Where? How much? What's the forecast?"

Features:
  - Real-time P&L calculation
  - Cash flow forecast (7/30 day)
  - Budget allocation optimizer (spend where ROI is highest)
  - Margin alerts (auto-detect margin erosion)
  - Per-product profitability ranking
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("intelligence.financial_brain")


class FinancialBrain:
    """Comprehensive financial intelligence for the store."""

    def full_analysis(self, products: list[dict[str, Any]],
                      orders: list[dict[str, Any]],
                      ad_spend: float = 0,
                      operating_costs: float = 0,
                      period_days: int = 30) -> dict[str, Any]:
        """Run full financial analysis on store data."""
        start = time.monotonic()

        pnl = self.calculate_pnl(products, orders, ad_spend, operating_costs)
        cash_flow = self.forecast_cash_flow(orders, ad_spend, operating_costs, period_days)
        product_profit = self.product_profitability(products, orders)
        margin_alerts = self.check_margins(products)
        budget = self.optimize_budget(ad_spend, pnl, product_profit)

        elapsed = time.monotonic() - start

        return {
            "elapsed_seconds": round(elapsed, 3),
            "pnl": pnl,
            "cash_flow": cash_flow,
            "product_profitability": product_profit,
            "margin_alerts": margin_alerts,
            "budget_recommendations": budget,
            "health_score": self._financial_health_score(pnl, margin_alerts),
        }

    # Configurable cost parameters (can be overridden per store)
    DEFAULT_COSTS = {
        "refund_rate": 0.08,            # 8% of orders get refunded
        "chargeback_rate": 0.005,       # 0.5% chargeback rate
        "chargeback_fee": 15.0,         # $15 per chargeback
        "payment_fee_pct": 0.029,       # 2.9% Stripe/Shopify Payments
        "payment_fee_fixed": 0.30,      # $0.30 per transaction
        "shopify_plan_fee": 0.0,        # Additional Shopify plan fee %
        "sales_tax_rate": 0.07,         # 7% average sales tax
        "return_shipping_cost": 6.0,    # $6 avg return shipping
        "packaging_cost": 1.50,         # $1.50 avg packaging
        "shipping_rates": {             # Weight-based shipping
            "light": {"max_kg": 0.5, "cost": 4.0},
            "medium": {"max_kg": 2.0, "cost": 7.0},
            "heavy": {"max_kg": 10.0, "cost": 12.0},
            "oversized": {"max_kg": 999, "cost": 20.0},
        },
    }

    def calculate_pnl(self, products: list[dict], orders: list[dict],
                      ad_spend: float = 0, operating_costs: float = 0,
                      cost_config: dict | None = None) -> dict[str, Any]:
        """Calculate Profit & Loss with real-world costs: refunds, taxes, fees, shipping."""
        cfg = {**self.DEFAULT_COSTS, **(cost_config or {})}

        # Revenue
        gross_revenue = sum(safe_float(o.get("total", o.get("amount", 0))) for o in orders if isinstance(o, dict))
        order_count = len([o for o in orders if isinstance(o, dict)])

        # COGS (Cost of Goods Sold)
        total_cogs = 0
        for order in orders:
            if not isinstance(order, dict):
                continue
            items = order.get("line_items", [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        qty = safe_int(item.get("quantity", 1))
                        pid = item.get("product_id", "")
                        cost = safe_float(item.get("cost", 0))
                        if cost == 0:
                            for p in products:
                                if isinstance(p, dict) and str(p.get("id")) == str(pid):
                                    cost = safe_float(p.get("cost"))
                                    break
                        total_cogs += cost * qty

        # Estimate COGS if no line items
        if total_cogs == 0 and products:
            avg_cost = sum(safe_float(p.get("cost")) for p in products if isinstance(p, dict)) / max(len(products), 1)
            avg_price = sum(safe_float(p.get("price")) for p in products if isinstance(p, dict)) / max(len(products), 1)
            if avg_price > 0:
                total_cogs = gross_revenue * (avg_cost / avg_price)

        gross_profit = gross_revenue - total_cogs
        gross_margin = round(gross_profit / max(gross_revenue, 0.01) * 100, 1)

        # Real-world expenses
        # Payment processing fees (Stripe: 2.9% + $0.30 per txn)
        payment_fees = round(gross_revenue * cfg["payment_fee_pct"] + order_count * cfg["payment_fee_fixed"], 2)

        # Shopify additional fees
        shopify_fees = round(gross_revenue * cfg["shopify_plan_fee"], 2)

        # Shipping — weight-based estimate
        avg_weight = 0
        if products:
            weights = [safe_float(p.get("weight")) for p in products if isinstance(p, dict)]
            avg_weight = sum(weights) / max(len(weights), 1) if weights else 1.0
        shipping_rate = 7.0  # default
        for tier in cfg["shipping_rates"].values():
            if avg_weight <= tier["max_kg"]:
                shipping_rate = tier["cost"]
                break
        shipping_cost = round(order_count * shipping_rate, 2)

        # Packaging
        packaging_cost = round(order_count * cfg["packaging_cost"], 2)

        # Refunds & returns
        refund_orders = round(order_count * cfg["refund_rate"])
        refund_cost = round(gross_revenue * cfg["refund_rate"], 2)
        return_shipping = round(refund_orders * cfg["return_shipping_cost"], 2)

        # Chargebacks
        chargeback_count = max(round(order_count * cfg["chargeback_rate"]), 0)
        chargeback_cost = round(chargeback_count * cfg["chargeback_fee"], 2)

        # Sales tax (collected but passed through — shown for awareness)
        sales_tax = round(gross_revenue * cfg["sales_tax_rate"], 2)

        total_expenses = (ad_spend + operating_costs + payment_fees + shopify_fees
                          + shipping_cost + packaging_cost + refund_cost
                          + return_shipping + chargeback_cost)

        net_profit = gross_profit - total_expenses
        net_margin = round(net_profit / max(gross_revenue, 0.01) * 100, 1)

        return {
            "gross_revenue": round(gross_revenue, 2),
            "total_cogs": round(total_cogs, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_margin_pct": gross_margin,
            "expenses": {
                "ad_spend": round(ad_spend, 2),
                "operating_costs": round(operating_costs, 2),
                "payment_fees": payment_fees,
                "shopify_fees": shopify_fees,
                "shipping_cost": shipping_cost,
                "packaging_cost": packaging_cost,
                "refund_cost": refund_cost,
                "return_shipping": return_shipping,
                "chargeback_cost": chargeback_cost,
                "total": round(total_expenses, 2),
            },
            "refunds": {
                "refund_rate": cfg["refund_rate"],
                "refund_orders": refund_orders,
                "refund_amount": refund_cost,
            },
            "tax_info": {
                "sales_tax_rate": cfg["sales_tax_rate"],
                "estimated_tax": sales_tax,
                "note": "Sales tax collected from customers, passed through to state",
            },
            "net_profit": round(net_profit, 2),
            "net_margin_pct": net_margin,
            "orders": order_count,
            "aov": round(gross_revenue / max(order_count, 1), 2),
            "status": "profitable" if net_profit > 0 else "break_even" if abs(net_profit) < 10 else "losing",
        }

    def forecast_cash_flow(self, orders: list[dict], ad_spend: float = 0,
                           operating_costs: float = 0, days_ahead: int = 30) -> dict[str, Any]:
        """Forecast cash flow based on order trends."""
        order_totals = [safe_float(o.get("total", o.get("amount", 0))) for o in orders if isinstance(o, dict)]

        if len(order_totals) < 3:
            return {"status": "insufficient_data", "note": "Need at least 3 orders for forecast"}

        # Calculate daily averages
        daily_revenue = sum(order_totals) / max(len(order_totals), 1)
        daily_costs = (ad_spend + operating_costs) / 30  # Assume monthly costs

        # Simple growth trend
        if len(order_totals) >= 4:
            first_half = sum(order_totals[:len(order_totals)//2]) / max(len(order_totals)//2, 1)
            second_half = sum(order_totals[len(order_totals)//2:]) / max(len(order_totals) - len(order_totals)//2, 1)
            growth_rate = (second_half - first_half) / max(first_half, 0.01)
        else:
            growth_rate = 0

        # Project forward
        projections = []
        cumulative_cash = 0
        for day in range(1, days_ahead + 1):
            day_revenue = daily_revenue * (1 + growth_rate * day / len(order_totals))
            day_cost = daily_costs
            day_net = day_revenue - day_cost
            cumulative_cash += day_net
            if day in (7, 14, 30) or day == days_ahead:
                projections.append({
                    "day": day,
                    "projected_revenue": round(day_revenue, 2),
                    "projected_cost": round(day_cost, 2),
                    "cumulative_cash": round(cumulative_cash, 2),
                })

        return {
            "daily_revenue_avg": round(daily_revenue, 2),
            "daily_costs_avg": round(daily_costs, 2),
            "growth_rate": round(growth_rate * 100, 1),
            "projections": projections,
            "forecast_total_revenue": round(daily_revenue * days_ahead * (1 + growth_rate * 0.5), 2),
            "forecast_net_cash": round(cumulative_cash, 2),
            "runway_days": round(abs(cumulative_cash) / max(daily_costs, 0.01), 0) if cumulative_cash < 0 else None,
        }

    def product_profitability(self, products: list[dict], orders: list[dict]) -> list[dict[str, Any]]:
        """Rank products by profitability."""
        results = []
        for p in products:
            if not isinstance(p, dict):
                continue
            price = safe_float(p.get("price"))
            cost = safe_float(p.get("cost"))
            inventory = safe_int(p.get("inventory_quantity", p.get("quantity", 0)))

            if price <= 0:
                continue

            margin = price - cost if cost > 0 else price * 0.5
            margin_pct = round(margin / price * 100, 1) if price > 0 else 0
            inventory_value = round(cost * inventory, 2) if cost > 0 else 0

            # Estimate revenue potential
            revenue_potential = round(price * min(inventory, 100), 2)
            profit_potential = round(margin * min(inventory, 100), 2)

            results.append({
                "name": p.get("name", p.get("title", "Unknown")),
                "price": price,
                "cost": cost,
                "margin": round(margin, 2),
                "margin_pct": margin_pct,
                "inventory": inventory,
                "inventory_value": inventory_value,
                "revenue_potential": revenue_potential,
                "profit_potential": profit_potential,
                "rating": safe_float(p.get("rating")),
            })

        results.sort(key=lambda x: x["profit_potential"], reverse=True)
        return results

    def check_margins(self, products: list[dict]) -> list[dict[str, Any]]:
        """Check for margin problems and generate alerts."""
        alerts = []
        for p in products:
            if not isinstance(p, dict):
                continue
            price = safe_float(p.get("price"))
            cost = safe_float(p.get("cost"))
            name = p.get("name", p.get("title", "Unknown"))

            if price <= 0:
                continue

            if cost > 0:
                margin_pct = (price - cost) / price * 100
                if margin_pct < 0:
                    alerts.append({
                        "product": name,
                        "severity": "critical",
                        "issue": f"Negative margin: selling at ${price} but costs ${cost}",
                        "margin_pct": round(margin_pct, 1),
                        "action": "Increase price immediately or discontinue",
                    })
                elif margin_pct < 15:
                    alerts.append({
                        "product": name,
                        "severity": "high",
                        "issue": f"Thin margin: {margin_pct:.1f}% (${price} - ${cost})",
                        "margin_pct": round(margin_pct, 1),
                        "action": "Review pricing or find cheaper supplier",
                    })
                elif margin_pct < 25:
                    alerts.append({
                        "product": name,
                        "severity": "medium",
                        "issue": f"Below-average margin: {margin_pct:.1f}%",
                        "margin_pct": round(margin_pct, 1),
                        "action": "Consider price adjustment or volume strategy",
                    })

        return alerts

    def optimize_budget(self, current_ad_spend: float, pnl: dict[str, Any],
                        product_profit: list[dict]) -> dict[str, Any]:
        """Recommend budget allocation based on profitability."""
        net_profit = safe_float(pnl.get("net_profit"))
        gross_margin = safe_float(pnl.get("gross_margin_pct"))
        roas = safe_float(pnl.get("gross_revenue")) / max(current_ad_spend, 0.01) if current_ad_spend > 0 else 0

        recommendations = []

        # Ad spend recommendation
        if roas > 4 and net_profit > 0:
            increase = round(current_ad_spend * 0.20, 2)
            recommendations.append({
                "type": "increase_ad_spend",
                "amount": increase,
                "reason": f"ROAS {roas:.1f}x — scale up profitable ads",
                "expected_revenue_gain": round(increase * roas, 2),
            })
        elif roas < 2 and current_ad_spend > 0:
            decrease = round(current_ad_spend * 0.30, 2)
            recommendations.append({
                "type": "decrease_ad_spend",
                "amount": decrease,
                "reason": f"ROAS {roas:.1f}x — reduce unprofitable spend",
                "expected_savings": decrease,
            })

        # Product-level allocation
        if product_profit:
            top_products = product_profit[:3]
            for tp in top_products:
                if tp.get("profit_potential", 0) > 500:
                    recommendations.append({
                        "type": "invest_in_product",
                        "product": tp["name"],
                        "reason": f"High profit potential: ${tp['profit_potential']} ({tp['margin_pct']}% margin)",
                        "suggested_action": "Increase inventory + promote",
                    })

        # Overall budget health
        if net_profit < 0:
            recommendations.append({
                "type": "cost_reduction",
                "reason": f"Net loss ${abs(net_profit):.2f} — cut non-essential expenses",
                "priority": "critical",
            })

        return {
            "current_ad_spend": round(current_ad_spend, 2),
            "current_roas": round(roas, 1),
            "recommendations": recommendations,
            "budget_health": "healthy" if net_profit > 0 and roas > 2 else "warning" if net_profit > 0 else "critical",
        }

    @staticmethod
    def _financial_health_score(pnl: dict, margin_alerts: list) -> dict[str, Any]:
        """Calculate overall financial health score 0-100."""
        score = 50  # Baseline

        # Profitability (+/- 20)
        net_margin = safe_float(pnl.get("net_margin_pct"))
        if net_margin > 20:
            score += 20
        elif net_margin > 10:
            score += 15
        elif net_margin > 0:
            score += 5
        else:
            score -= 20

        # Gross margin (+/- 15)
        gross_margin = safe_float(pnl.get("gross_margin_pct"))
        if gross_margin > 50:
            score += 15
        elif gross_margin > 30:
            score += 10
        elif gross_margin < 15:
            score -= 10

        # Margin alerts (-5 each)
        critical_alerts = sum(1 for a in margin_alerts if a.get("severity") == "critical")
        high_alerts = sum(1 for a in margin_alerts if a.get("severity") == "high")
        score -= critical_alerts * 10 + high_alerts * 5

        # Revenue volume (+/- 10)
        orders = pnl.get("orders", 0)
        if orders > 50:
            score += 10
        elif orders > 10:
            score += 5

        grade = "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "F"

        return {
            "score": max(0, min(100, score)),
            "grade": grade,
            "profitable": pnl.get("status") == "profitable",
        }
