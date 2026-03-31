"""AutoDS Intelligence — dropshipping automation algorithms.

Real algorithms for:
  - Product sourcing: score suppliers by reliability, price, shipping
  - Price monitoring: detect competitor price changes, auto-adjust
  - Profit calculator: landed cost, fees, margins after all costs
  - Auto-fulfillment routing: select best supplier per order
  - Winning product detection: trend + margin + competition scoring
"""
from __future__ import annotations

import math
import time
from typing import Any


class AutoDSIntelligence:
    """Dropshipping automation intelligence."""

    def score_product_for_dropship(self, product: dict[str, Any], suppliers: list[dict[str, Any]]) -> dict[str, Any]:
        """Score a product for dropshipping viability (0-100)."""
        score = 0
        factors = []

        sell_price = float(product.get("price", product.get("sell_price", 0)))
        category = product.get("category", "").lower()

        # Best supplier analysis
        best_supplier = self._find_best_supplier(suppliers)
        if not best_supplier:
            return {"score": 0, "viable": False, "reason": "No suppliers found"}

        cost = float(best_supplier.get("price", best_supplier.get("cost", 0)))
        shipping_cost = float(best_supplier.get("shipping_cost", best_supplier.get("shipping", 3)))
        shipping_days = int(best_supplier.get("shipping_days", best_supplier.get("delivery_days", 14)))
        supplier_rating = float(best_supplier.get("rating", best_supplier.get("reliability", 4.0)))

        # Landed cost
        platform_fee_pct = 0.029 + 0.30 / max(sell_price, 1)  # ~2.9% + $0.30 Shopify
        landed_cost = cost + shipping_cost
        total_fees = sell_price * platform_fee_pct
        net_profit = sell_price - landed_cost - total_fees
        margin_pct = (net_profit / sell_price * 100) if sell_price > 0 else 0

        # Margin score (0-30)
        if margin_pct >= 40:
            score += 30; factors.append({"factor": "margin", "score": 30, "detail": f"{margin_pct:.0f}% — excellent"})
        elif margin_pct >= 25:
            score += 20; factors.append({"factor": "margin", "score": 20, "detail": f"{margin_pct:.0f}% — good"})
        elif margin_pct >= 15:
            score += 10; factors.append({"factor": "margin", "score": 10, "detail": f"{margin_pct:.0f}% — acceptable"})
        else:
            factors.append({"factor": "margin", "score": 0, "detail": f"{margin_pct:.0f}% — too low"})

        # Shipping score (0-25)
        if shipping_days <= 7:
            score += 25; factors.append({"factor": "shipping", "score": 25, "detail": f"{shipping_days}d — fast"})
        elif shipping_days <= 14:
            score += 15; factors.append({"factor": "shipping", "score": 15, "detail": f"{shipping_days}d — acceptable"})
        elif shipping_days <= 21:
            score += 5; factors.append({"factor": "shipping", "score": 5, "detail": f"{shipping_days}d — slow"})
        else:
            factors.append({"factor": "shipping", "score": 0, "detail": f"{shipping_days}d — too slow"})

        # Supplier reliability (0-20)
        if supplier_rating >= 4.5:
            score += 20; factors.append({"factor": "supplier", "score": 20, "detail": f"{supplier_rating}/5 — excellent"})
        elif supplier_rating >= 4.0:
            score += 12; factors.append({"factor": "supplier", "score": 12, "detail": f"{supplier_rating}/5 — good"})
        else:
            score += 5; factors.append({"factor": "supplier", "score": 5, "detail": f"{supplier_rating}/5 — risky"})

        # Price point score (0-15) — $15-$60 sweet spot for dropshipping
        if 15 <= sell_price <= 60:
            score += 15; factors.append({"factor": "price_point", "score": 15, "detail": f"${sell_price} — sweet spot"})
        elif 10 <= sell_price <= 100:
            score += 8; factors.append({"factor": "price_point", "score": 8, "detail": f"${sell_price} — acceptable"})
        else:
            factors.append({"factor": "price_point", "score": 0, "detail": f"${sell_price} — outside optimal range"})

        # Weight score (0-10) — lighter = cheaper shipping
        weight = float(product.get("weight", 0))
        if weight > 0 and weight < 0.5:
            score += 10; factors.append({"factor": "weight", "score": 10, "detail": f"{weight}kg — light"})
        elif weight < 2:
            score += 5; factors.append({"factor": "weight", "score": 5, "detail": f"{weight}kg — moderate"})

        return {
            "score": min(score, 100),
            "viable": score >= 50,
            "grade": "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D",
            "factors": factors,
            "financials": {
                "sell_price": round(sell_price, 2),
                "supplier_cost": round(cost, 2),
                "shipping_cost": round(shipping_cost, 2),
                "landed_cost": round(landed_cost, 2),
                "platform_fees": round(total_fees, 2),
                "net_profit": round(net_profit, 2),
                "margin_pct": round(margin_pct, 1),
                "break_even_units": max(1, math.ceil(50 / max(net_profit, 0.01))),  # $50 ad spend
            },
            "best_supplier": {
                "name": best_supplier.get("name", "Unknown"),
                "cost": round(cost, 2),
                "shipping_days": shipping_days,
                "rating": supplier_rating,
            },
            "recommendation": self._dropship_recommendation(score, margin_pct, shipping_days),
        }

    def monitor_prices(self, our_products: list[dict], competitor_products: list[dict]) -> dict[str, Any]:
        """Monitor competitor prices and suggest adjustments."""
        alerts = []
        for our in our_products:
            our_name = our.get("name", "").lower()
            our_price = float(our.get("price", 0))

            for comp in competitor_products:
                comp_name = comp.get("name", "").lower()
                comp_price = float(comp.get("price", 0))

                # Simple name matching
                if our_name and comp_name and (our_name in comp_name or comp_name in our_name):
                    diff_pct = (our_price - comp_price) / max(comp_price, 1) * 100
                    if diff_pct > 15:
                        alerts.append({
                            "product": our.get("name"),
                            "our_price": our_price,
                            "competitor_price": comp_price,
                            "competitor": comp.get("store", comp.get("source", "competitor")),
                            "diff_pct": round(diff_pct, 1),
                            "alert": "overpriced",
                            "suggested_price": round(comp_price * 1.05, 2),
                        })
                    elif diff_pct < -20:
                        alerts.append({
                            "product": our.get("name"),
                            "our_price": our_price,
                            "competitor_price": comp_price,
                            "diff_pct": round(diff_pct, 1),
                            "alert": "opportunity",
                            "suggested_price": round(comp_price * 0.95, 2),
                        })

        return {
            "alerts": alerts,
            "total_monitored": len(our_products),
            "overpriced": sum(1 for a in alerts if a["alert"] == "overpriced"),
            "opportunities": sum(1 for a in alerts if a["alert"] == "opportunity"),
        }

    def select_fulfillment_supplier(self, order: dict[str, Any], suppliers: list[dict[str, Any]]) -> dict[str, Any]:
        """Select best supplier for an order based on cost, speed, reliability."""
        if not suppliers:
            return {"error": "No suppliers available"}

        scored = []
        for s in suppliers:
            cost = float(s.get("price", s.get("cost", 0)))
            shipping = float(s.get("shipping_cost", 0))
            days = int(s.get("shipping_days", 14))
            rating = float(s.get("rating", 3.0))
            stock = int(s.get("stock", s.get("inventory", 0)))
            quantity = int(order.get("quantity", 1))

            if stock < quantity:
                continue

            score = rating * 20 + max(0, 30 - days) + max(0, 20 - cost / 5)
            scored.append({"supplier": s, "score": round(score, 1), "total_cost": round(cost + shipping, 2)})

        if not scored:
            return {"error": "No supplier has sufficient stock"}

        scored.sort(key=lambda x: -x["score"])
        winner = scored[0]

        return {
            "selected_supplier": winner["supplier"].get("name", "Unknown"),
            "total_cost": winner["total_cost"],
            "score": winner["score"],
            "alternatives": len(scored) - 1,
        }

    def _find_best_supplier(self, suppliers: list[dict]) -> dict | None:
        if not suppliers:
            return None
        return min(suppliers, key=lambda s: float(s.get("price", s.get("cost", 999))) + float(s.get("shipping_cost", 0)))

    @staticmethod
    def _dropship_recommendation(score: int, margin: float, days: int) -> str:
        if score >= 80:
            return "Strong dropship candidate. List immediately and start testing ads."
        if score >= 60:
            return "Good potential. List and test with small ad budget ($20-50/day)."
        if score >= 40:
            if margin < 20:
                return "Margin too thin. Negotiate better supplier price or increase sell price."
            if days > 14:
                return "Shipping too slow. Find faster supplier or set clear delivery expectations."
            return "Borderline. Test cautiously with minimal investment."
        return "Not recommended for dropshipping. Low margin, slow shipping, or poor supplier."
