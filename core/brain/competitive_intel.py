"""Competitive Intelligence — deep market position analysis.

Goes beyond price comparison: analyzes positioning, market gaps,
competitive advantages, and strategic recommendations.
"""
from __future__ import annotations
import threading as _threading
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("brain.competitive_intel")


class CompetitiveIntelligence:
    """Deep competitive analysis and market positioning."""

    def analyze(self, products: list[dict],
                competitor_data: list[dict] | None = None) -> dict[str, Any]:
        """Full competitive analysis."""
        prices = [float(p.get("price", 0)) for p in products if p.get("price")]
        costs = [float(p.get("cost", 0)) for p in products if p.get("cost")]
        margins = []
        for p in products:
            pr, co = float(p.get("price", 0)), float(p.get("cost", 0))
            if pr > 0 and co > 0:
                margins.append((pr - co) / pr)

        avg_price = sum(prices) / max(len(prices), 1) if prices else 0
        avg_margin = sum(margins) / max(len(margins), 1) if margins else 0

        # Market position analysis
        position = self._analyze_position(products, competitor_data or [])

        # Find competitive advantages
        advantages = self._find_advantages(products, avg_margin)

        # Find vulnerabilities
        vulnerabilities = self._find_vulnerabilities(products)

        # Strategic recommendations
        recommendations = self._generate_recommendations(
            position, advantages, vulnerabilities)

        return {
            "market_position": position,
            "advantages": advantages,
            "vulnerabilities": vulnerabilities,
            "recommendations": recommendations,
            "metrics": {
                "avg_price": round(avg_price, 2),
                "avg_margin": round(avg_margin, 3),
                "product_count": len(products),
                "price_range": [min(prices, default=0), max(prices, default=0)],
            },
        }

    @staticmethod
    def _analyze_position(products, competitors):
        if not competitors:
            return {"status": "no_competitor_data", "position": "unknown"}
        competitive = sum(1 for c in competitors
                          if isinstance(c, dict) and c.get("position") == "competitive")
        return {
            "competitive_products": competitive,
            "total_compared": len(competitors),
            "position": "strong" if competitive > len(competitors) * 0.6
                        else "moderate" if competitive > len(competitors) * 0.3
                        else "weak",
        }

    @staticmethod
    def _find_advantages(products, avg_margin):
        advs = []
        high_margin = [p for p in products
                       if float(p.get("cost", 0)) > 0
                       and (float(p.get("price", 0)) - float(p.get("cost", 0))) / float(p.get("price", 1)) > 0.5]
        if high_margin:
            advs.append({"type": "high_margins",
                         "detail": "{} products with >50% margin".format(len(high_margin)),
                         "strength": "strong"})
        if avg_margin > 0.4:
            advs.append({"type": "overall_profitability",
                         "detail": "Average margin {:.0%}".format(avg_margin),
                         "strength": "strong"})
        if len(products) >= 10:
            advs.append({"type": "catalog_breadth",
                         "detail": "{} products in catalog".format(len(products)),
                         "strength": "moderate"})
        return advs

    @staticmethod
    def _find_vulnerabilities(products):
        vulns = []
        no_images = sum(1 for p in products
                        if not (p.get("images") or p.get("image") or p.get("image_url")))
        if no_images > 0:
            vulns.append({"type": "missing_images",
                          "detail": "{}/{} products lack images".format(no_images, len(products)),
                          "severity": "high" if no_images == len(products) else "medium"})
        low_inv = sum(1 for p in products if int(p.get("inventory_quantity", 0)) < 5)
        if low_inv > 0:
            vulns.append({"type": "low_inventory",
                          "detail": "{} products with <5 inventory".format(low_inv),
                          "severity": "medium"})
        return vulns

    @staticmethod
    def _generate_recommendations(position, advantages, vulnerabilities):
        recs = []
        for v in vulnerabilities:
            if v["severity"] == "high":
                recs.append("FIX: {} — {}".format(v["type"], v["detail"]))
        for a in advantages:
            if a["strength"] == "strong":
                recs.append("LEVERAGE: {} — {}".format(a["type"], a["detail"]))
        if not recs:
            recs.append("MONITOR: maintain current position")
        return recs


_instance = None
_instance_lock = _threading.Lock()

def get_competitive_intelligence():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = CompetitiveIntelligence()
    return _instance
