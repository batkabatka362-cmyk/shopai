"""Product Scorer ML — AI-learned product ranking.

Scores products on: margin, demand potential, image quality,
price competitiveness, inventory health. Learns from MemoryIntelligence.
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("ml.product_scorer")


class ProductScorer:
    """Scores and ranks products by AI-learned criteria."""

    def __init__(self) -> None:
        self._weights = {
            "margin": 0.25,
            "price_competitiveness": 0.20,
            "inventory_health": 0.15,
            "has_images": 0.15,
            "demand_potential": 0.15,
            "description_quality": 0.10,
        }

    def score_all(self, products: list[dict]) -> list[dict[str, Any]]:
        """Score and rank all products."""
        scored = []
        for p in products:
            s = self._score_product(p)
            scored.append(s)
        scored.sort(key=lambda x: -x["total_score"])
        for i, s in enumerate(scored):
            s["rank"] = i + 1
        return scored

    def _score_product(self, product: dict) -> dict[str, Any]:
        price = float(product.get("price", 0))
        cost = float(product.get("cost", 0))
        inv = int(product.get("inventory_quantity", 0))
        has_img = bool(product.get("images") or product.get("image") or product.get("image_url"))
        has_desc = bool(str(product.get("body_html", product.get("description", ""))).strip())
        name = product.get("name", product.get("title", ""))

        scores = {}
        # Margin score (0-1)
        if price > 0 and cost > 0:
            margin = (price - cost) / price
            scores["margin"] = min(1.0, margin / 0.6)
        else:
            scores["margin"] = 0.3

        # Price competitiveness (moderate price = better)
        if price > 0:
            scores["price_competitiveness"] = min(1.0, 30 / max(price, 1)) if price > 30 else min(1.0, price / 30)
        else:
            scores["price_competitiveness"] = 0.0

        # Inventory health
        if inv > 20:
            scores["inventory_health"] = 1.0
        elif inv > 5:
            scores["inventory_health"] = 0.7
        elif inv > 0:
            scores["inventory_health"] = 0.4
        else:
            scores["inventory_health"] = 0.1

        scores["has_images"] = 1.0 if has_img else 0.0
        scores["demand_potential"] = 0.5  # Default, updated by memory
        scores["description_quality"] = 0.8 if has_desc else 0.2

        total = sum(scores[k] * self._weights[k] for k in self._weights)

        return {
            "product_id": product.get("id", ""),
            "name": name[:40],
            "total_score": round(total, 3),
            "scores": {k: round(v, 2) for k, v in scores.items()},
            "grade": "A" if total >= 0.8 else "B" if total >= 0.6 else "C" if total >= 0.4 else "D",
            "top_issue": min(scores, key=scores.get),
        }

    def learn_weights(self) -> dict[str, Any]:
        """Adjust weights from MemoryIntelligence."""
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            rules = mi.get_rules("product")
            for r in rules:
                rc = r.get("content", {})
                if isinstance(rc, dict) and rc.get("recommended_action") == "prefer":
                    self._weights["demand_potential"] = min(0.3, self._weights["demand_potential"] + 0.02)
            return {"adjusted": True, "weights": dict(self._weights)}
        except Exception:
            return {"adjusted": False}


_instance = None
def get_product_scorer():
    global _instance
    if _instance is None:
        _instance = ProductScorer()
    return _instance
