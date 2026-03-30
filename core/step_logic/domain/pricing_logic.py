"""PricingLogic — deep business logic for pricing engines.

Covers: pricing, dynamic_pricing, price_elasticity, discount_strategy,
        price_optimization, price_testing, competitor_pricing, markdown_optimization
"""
from __future__ import annotations

import copy
import math
from typing import Any


class PricingLogic:
    """Real pricing computations for pricing-related engines."""

    PRICING_ENGINES = {
        "pricing", "dynamic_pricing", "price_elasticity", "discount_strategy",
        "price_optimization", "price_testing", "competitor_pricing",
        "markdown_optimization", "b2b_pricing", "wholesale", "tiered_pricing",
        "volume_pricing", "weather_pricing", "time_based_pricing",
    }

    def applies_to(self, engine_name: str) -> bool:
        return engine_name in self.PRICING_ENGINES

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        """Analyze pricing data and compute pricing intelligence."""
        result = {}
        products = self._get_products(data)

        if products:
            result["price_analysis"] = self._analyze_prices(products)
            result["margin_analysis"] = self._analyze_margins(products)
            result["price_segments"] = self._segment_by_price(products)
            result["pricing_opportunities"] = self._find_opportunities(products, data)
            result["score"] = self._pricing_health_score(result)
            result["decision"] = "approve" if result["score"] >= 5 else "reject"
            result["reason"] = self._pricing_reason(result)

        competitors = data.get("competitor_data", data.get("competitor_prices", []))
        if isinstance(competitors, list) and competitors:
            result["competitive_position"] = self._competitive_analysis(products, competitors)

        return result

    def execute(self, data: dict[str, Any]) -> dict[str, Any]:
        """Generate pricing recommendations."""
        result = {}
        products = self._get_products(data)
        analysis = data.get("_analyze_output", data.get("price_analysis", {}))

        if products:
            result["pricing_recommendations"] = []
            for p in products:
                rec = self._recommend_price(p, analysis)
                result["pricing_recommendations"].append(rec)

            result["discount_strategy"] = self._recommend_discounts(products, data)
            result["bundle_opportunities"] = self._find_bundles(products)
            result["generated"] = True

        return result

    def _analyze_prices(self, products: list[dict]) -> dict[str, Any]:
        prices = [float(p.get("price", 0)) for p in products if p.get("price")]
        if not prices:
            return {"has_data": False}

        return {
            "count": len(prices),
            "min": round(min(prices), 2),
            "max": round(max(prices), 2),
            "mean": round(sum(prices) / len(prices), 2),
            "median": round(sorted(prices)[len(prices) // 2], 2),
            "std_dev": round(self._std(prices), 2),
            "range_ratio": round(max(prices) / min(prices), 2) if min(prices) > 0 else 0,
            "coefficient_of_variation": round(self._std(prices) / (sum(prices)/len(prices)) * 100, 1) if sum(prices) > 0 else 0,
        }

    def _analyze_margins(self, products: list[dict]) -> dict[str, Any]:
        margins = []
        for p in products:
            price = float(p.get("price", 0))
            cost = float(p.get("cost", 0))
            if price > 0 and cost > 0:
                margins.append((price - cost) / price * 100)

        if not margins:
            return {"has_data": False}

        return {
            "avg_margin": round(sum(margins) / len(margins), 2),
            "min_margin": round(min(margins), 2),
            "max_margin": round(max(margins), 2),
            "below_30": sum(1 for m in margins if m < 30),
            "above_50": sum(1 for m in margins if m > 50),
            "healthy_count": sum(1 for m in margins if 30 <= m <= 70),
            "risk_level": "high" if min(margins) < 15 else "medium" if min(margins) < 25 else "low",
        }

    def _segment_by_price(self, products: list[dict]) -> dict[str, list[str]]:
        segments: dict[str, list[str]] = {"impulse": [], "budget": [], "mid": [], "premium": [], "luxury": []}
        for p in products:
            price = float(p.get("price", 0))
            name = p.get("name", "unknown")
            if price < 15: segments["impulse"].append(name)
            elif price < 30: segments["budget"].append(name)
            elif price < 60: segments["mid"].append(name)
            elif price < 150: segments["premium"].append(name)
            else: segments["luxury"].append(name)
        return {k: v for k, v in segments.items() if v}

    def _find_opportunities(self, products: list[dict], data: dict) -> list[dict]:
        opportunities = []
        for p in products:
            price = float(p.get("price", 0))
            cost = float(p.get("cost", 0))
            compare = float(p.get("compare_at_price", 0))
            margin = (price - cost) / price * 100 if price > 0 and cost > 0 else 0

            if margin > 60:
                opportunities.append({"product": p.get("name"), "type": "discount_room", "detail": f"{margin:.0f}% margin allows discounting"})
            if margin < 20 and margin > 0:
                opportunities.append({"product": p.get("name"), "type": "price_increase", "detail": f"Only {margin:.0f}% margin — consider raising price"})
            if compare > 0 and price < compare * 0.7:
                opportunities.append({"product": p.get("name"), "type": "deep_discount", "detail": f"{(1-price/compare)*100:.0f}% below compare price"})

        return opportunities

    def _recommend_price(self, product: dict, analysis: dict) -> dict:
        price = float(product.get("price", 0))
        cost = float(product.get("cost", 0))
        margin = (price - cost) / price * 100 if price > 0 else 0

        rec = {"name": product.get("name"), "current_price": price, "current_margin": round(margin, 1)}

        if cost > 0:
            target_40 = round(cost / 0.6, 2)
            target_50 = round(cost / 0.5, 2)
            rec["target_price_40pct"] = target_40
            rec["target_price_50pct"] = target_50
            rec["min_viable_price"] = round(cost * 1.3, 2)

        if margin > 60:
            rec["action"] = "can_discount"
            rec["max_discount_pct"] = round(margin - 30, 0)
        elif margin < 25:
            rec["action"] = "increase_price"
            rec["suggested_increase_pct"] = round((30 - margin) * 1.2, 0)
        else:
            rec["action"] = "maintain"

        # Psychological pricing
        charm_price = self._charm_price(price)
        if charm_price != price:
            rec["charm_price"] = charm_price
            rec["charm_savings_pct"] = round((price - charm_price) / price * 100, 1)

        # Price anchoring
        if cost > 0:
            rec["anchor_price"] = round(price * 1.4, 2)  # Show "was" price at 40% higher
            rec["perceived_discount"] = round((1 - price / (price * 1.4)) * 100, 0)

        # Elasticity estimate (simplified)
        rec["elasticity_estimate"] = self._estimate_elasticity(product)

        return rec

    @staticmethod
    def _charm_price(price: float) -> float:
        """Convert to psychological charm price: $30 → $29.99, $45 → $44.99."""
        if price <= 0:
            return price
        rounded = round(price)
        if rounded == price and price >= 10:
            return price - 0.01
        if price % 1 == 0 and price >= 5:
            return price - 0.01
        return price

    @staticmethod
    def _estimate_elasticity(product: dict) -> dict:
        """Estimate price elasticity based on product attributes."""
        price = float(product.get("price", 0))
        category = product.get("category", "").lower()
        competition = float(product.get("competition", 0))

        # Higher competition = more elastic (customers switch easily)
        # Luxury/premium = less elastic (brand loyalty)
        if category in ("luxury", "premium", "designer"):
            elasticity = -0.5  # Inelastic
        elif competition > 500:
            elasticity = -2.5  # Very elastic
        elif competition > 100:
            elasticity = -1.5  # Moderately elastic
        else:
            elasticity = -0.8  # Relatively inelastic

        return {
            "coefficient": elasticity,
            "interpretation": "inelastic" if abs(elasticity) < 1 else "elastic",
            "pricing_power": "high" if abs(elasticity) < 1 else "low",
            "10pct_increase_demand_change": round(elasticity * 10, 1),
        }

    def _recommend_discounts(self, products: list[dict], data: dict) -> dict:
        high_margin = [p for p in products if self._margin(p) > 50]
        return {
            "eligible_for_discount": len(high_margin),
            "suggested_tiers": [
                {"threshold": 50, "discount_pct": 5, "label": "Spend $50, save 5%"},
                {"threshold": 100, "discount_pct": 10, "label": "Spend $100, save 10%"},
                {"threshold": 200, "discount_pct": 15, "label": "Spend $200, save 15%"},
            ],
            "free_shipping_threshold": self._optimal_free_shipping(products),
        }

    def _find_bundles(self, products: list[dict]) -> list[dict]:
        if len(products) < 2:
            return []
        bundles = []
        sorted_p = sorted(products, key=lambda p: float(p.get("price", 0)))
        if len(sorted_p) >= 2:
            low = sorted_p[0]
            high = sorted_p[-1]
            bundle_price = round((float(low.get("price", 0)) + float(high.get("price", 0))) * 0.85, 2)
            bundles.append({
                "items": [low.get("name"), high.get("name")],
                "bundle_price": bundle_price,
                "savings_pct": 15,
            })
        return bundles

    def _competitive_analysis(self, products: list[dict], competitors: list[dict]) -> dict:
        comp_prices = [float(c.get("price", 0)) for c in competitors if c.get("price")]
        our_prices = [float(p.get("price", 0)) for p in products if p.get("price")]
        if not comp_prices or not our_prices:
            return {"has_data": False}

        our_avg = sum(our_prices) / len(our_prices)
        comp_avg = sum(comp_prices) / len(comp_prices)
        return {
            "our_avg": round(our_avg, 2),
            "competitor_avg": round(comp_avg, 2),
            "price_index": round(our_avg / comp_avg * 100, 1) if comp_avg > 0 else 0,
            "position": "below" if our_avg < comp_avg * 0.95 else "above" if our_avg > comp_avg * 1.05 else "at_parity",
        }

    def _pricing_health_score(self, analysis: dict) -> float:
        score = 5.0
        margins = analysis.get("margin_analysis", {})
        if margins.get("avg_margin", 0) > 40: score += 2
        if margins.get("risk_level") == "low": score += 1
        if margins.get("below_30", 0) == 0: score += 1
        opportunities = analysis.get("pricing_opportunities", [])
        if len(opportunities) > 0: score += 0.5
        return min(round(score, 1), 10)

    def _pricing_reason(self, analysis: dict) -> str:
        margins = analysis.get("margin_analysis", {})
        opps = len(analysis.get("pricing_opportunities", []))
        return f"Avg margin {margins.get('avg_margin', 0):.1f}%, risk={margins.get('risk_level', 'unknown')}, {opps} opportunities"

    @staticmethod
    def _margin(p: dict) -> float:
        price = float(p.get("price", 0))
        cost = float(p.get("cost", 0))
        return (price - cost) / price * 100 if price > 0 else 0

    @staticmethod
    def _std(values: list[float]) -> float:
        if len(values) < 2: return 0
        m = sum(values) / len(values)
        return (sum((v - m) ** 2 for v in values) / len(values)) ** 0.5

    @staticmethod
    def _optimal_free_shipping(products: list[dict]) -> float:
        prices = sorted([float(p.get("price", 0)) for p in products if p.get("price")])
        if not prices: return 50
        avg = sum(prices) / len(prices)
        return round(avg * 1.5, 0)

    @staticmethod
    def _get_products(data: dict) -> list[dict]:
        for key in ("products", "product_data", "product_catalog", "pricing_data"):
            val = data.get(key, [])
            if isinstance(val, list) and val:
                return val
            if isinstance(val, dict):
                return [val]
        return []
