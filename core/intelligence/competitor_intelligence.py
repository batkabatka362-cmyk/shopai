"""Competitor Intelligence — track, analyze, and counter competitors.

  - Price tracking and comparison
  - Product catalog overlap analysis
  - Market positioning map
  - Counter-strategy generation
  - Opportunity detection (gaps in competitor offerings)
"""
from __future__ import annotations

from typing import Any


class CompetitorIntelligence:
    """Real competitor analysis algorithms."""

    def analyze_competitors(self, our_store: dict[str, Any],
                             competitors: list[dict[str, Any]]) -> dict[str, Any]:
        """Full competitive analysis."""
        if not competitors:
            return {"error": "No competitor data provided"}

        our_products = our_store.get("products", [])
        our_avg_price = self._avg_price(our_products) if our_products else 0

        analyses = []
        for comp in competitors:
            comp_products = comp.get("products", [])
            comp_avg_price = self._avg_price(comp_products)

            # Price comparison
            price_index = round(our_avg_price / max(comp_avg_price, 1) * 100, 1) if comp_avg_price > 0 else 0

            # Catalog overlap
            our_cats = set(p.get("category", "").lower() for p in our_products if p.get("category"))
            comp_cats = set(p.get("category", "").lower() for p in comp_products if p.get("category"))
            overlap = our_cats & comp_cats
            their_unique = comp_cats - our_cats

            analyses.append({
                "competitor": comp.get("name", comp.get("store", "Unknown")),
                "products": len(comp_products),
                "avg_price": round(comp_avg_price, 2),
                "price_index": price_index,
                "position": "cheaper" if price_index < 90 else "pricier" if price_index > 110 else "similar",
                "category_overlap": list(overlap),
                "unique_categories": list(their_unique),
                "threat_level": self._assess_threat(price_index, len(comp_products), len(overlap)),
            })

        # Overall market position
        all_avg_prices = [a["avg_price"] for a in analyses if a["avg_price"] > 0]
        market_avg = sum(all_avg_prices) / max(len(all_avg_prices), 1)

        return {
            "our_position": {
                "avg_price": round(our_avg_price, 2),
                "products": len(our_products),
                "vs_market_avg": round(our_avg_price / max(market_avg, 1) * 100, 1),
                "positioning": "value" if our_avg_price < market_avg * 0.9 else "premium" if our_avg_price > market_avg * 1.1 else "mid-market",
            },
            "competitors": analyses,
            "market_avg_price": round(market_avg, 2),
            "top_threat": max(analyses, key=lambda a: a["threat_level"])["competitor"] if analyses else None,
            "opportunities": self._find_opportunities(our_products, competitors),
            "counter_strategies": self._generate_strategies(analyses),
        }

    def price_comparison(self, our_products: list[dict], competitor_products: list[dict]) -> dict[str, Any]:
        """Product-level price comparison."""
        comparisons = []

        for our in our_products:
            our_name = our.get("name", "").lower()
            our_price = float(our.get("price", 0))
            our_cat = our.get("category", "").lower()

            matches = []
            for comp in competitor_products:
                comp_cat = comp.get("category", "").lower()
                comp_price = float(comp.get("price", 0))

                if our_cat and our_cat == comp_cat:
                    matches.append({
                        "product": comp.get("name", ""),
                        "price": comp_price,
                        "diff_pct": round((our_price - comp_price) / max(comp_price, 1) * 100, 1),
                    })

            if matches:
                avg_comp_price = sum(m["price"] for m in matches) / len(matches)
                comparisons.append({
                    "our_product": our.get("name"),
                    "our_price": our_price,
                    "competitor_avg": round(avg_comp_price, 2),
                    "our_vs_avg": round((our_price - avg_comp_price) / max(avg_comp_price, 1) * 100, 1),
                    "matches": len(matches),
                    "cheapest_competitor": min(matches, key=lambda m: m["price"]),
                })

        overpriced = sum(1 for c in comparisons if c["our_vs_avg"] > 15)
        underpriced = sum(1 for c in comparisons if c["our_vs_avg"] < -15)

        return {
            "comparisons": comparisons,
            "summary": {
                "products_compared": len(comparisons),
                "overpriced": overpriced,
                "underpriced": underpriced,
                "at_parity": len(comparisons) - overpriced - underpriced,
            },
        }

    def _find_opportunities(self, our_products: list, competitors: list) -> list[dict]:
        """Find gaps in competitor offerings we could exploit."""
        opportunities = []

        our_cats = set(p.get("category", "").lower() for p in our_products if p.get("category"))
        all_comp_cats = set()
        for comp in competitors:
            for p in comp.get("products", []):
                cat = p.get("category", "").lower()
                if cat:
                    all_comp_cats.add(cat)

        # Categories competitors have but we don't
        gaps = all_comp_cats - our_cats
        for cat in gaps:
            opportunities.append({"type": "category_gap", "category": cat,
                                  "action": f"Expand into {cat} — competitors are there but we're not"})

        # Price gaps — are there price tiers nobody serves?
        all_comp_prices = []
        for comp in competitors:
            for p in comp.get("products", []):
                price = float(p.get("price", 0))
                if price > 0:
                    all_comp_prices.append(price)

        if all_comp_prices:
            avg = sum(all_comp_prices) / len(all_comp_prices)
            low_count = sum(1 for p in all_comp_prices if p < avg * 0.5)
            high_count = sum(1 for p in all_comp_prices if p > avg * 1.5)

            if low_count < len(all_comp_prices) * 0.1:
                opportunities.append({"type": "price_gap", "segment": "budget",
                                      "action": "Few budget options in market — consider value product line"})
            if high_count < len(all_comp_prices) * 0.1:
                opportunities.append({"type": "price_gap", "segment": "premium",
                                      "action": "Few premium options — opportunity for high-margin products"})

        return opportunities[:5]

    def _generate_strategies(self, analyses: list[dict]) -> list[dict]:
        """Generate counter-strategies based on competitive analysis."""
        strategies = []

        threats = [a for a in analyses if a["threat_level"] == "high"]
        if threats:
            strategies.append({
                "strategy": "competitive_pricing",
                "target": threats[0]["competitor"],
                "action": "Price-match or undercut on overlapping products. Highlight free shipping as differentiator.",
            })

        unique_cats = set()
        for a in analyses:
            unique_cats.update(a.get("unique_categories", []))
        if unique_cats:
            strategies.append({
                "strategy": "catalog_expansion",
                "categories": list(unique_cats)[:3],
                "action": f"Expand into {', '.join(list(unique_cats)[:3])} to compete on breadth.",
            })

        strategies.append({
            "strategy": "differentiation",
            "action": "Focus on brand story, customer service, and unboxing experience to stand out beyond price.",
        })

        return strategies

    @staticmethod
    def _avg_price(products: list[dict]) -> float:
        prices = [float(p.get("price", 0)) for p in products if float(p.get("price", 0)) > 0]
        return sum(prices) / max(len(prices), 1) if prices else 0

    @staticmethod
    def _assess_threat(price_index: float, product_count: int, overlap_count: int) -> str:
        score = 0
        if price_index > 90 and price_index < 110: score += 2  # Similar pricing = direct competition
        if price_index < 90: score += 3  # Cheaper = bigger threat
        if product_count > 50: score += 1
        if overlap_count > 3: score += 2
        return "high" if score >= 5 else "medium" if score >= 3 else "low"
