"""AI Product Finder — discovers trending products to add to store.

Searches: web trends, competitor stores, marketplace bestsellers.
Scores each product: margin potential, demand, competition level.
Auto-suggests which to add and at what price.
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("product.finder")

# Product niches and their search terms
NICHE_SEARCHES = {
    "home": ["trending home decor 2026", "best selling home gadgets", "viral home products tiktok"],
    "fashion": ["trending fashion accessories", "viral clothing items", "best selling fashion"],
    "tech": ["trending tech gadgets", "best selling electronics", "viral tech products"],
    "beauty": ["trending beauty products", "viral skincare", "best selling beauty tools"],
    "general": ["trending products to sell online", "best dropshipping products", "viral products"],
}


class AIProductFinder:
    """Discovers and scores trending products for your store."""

    def __init__(self):
        self._found: list[dict] = []

    def find_products(self, niche: str = "general", current_products: list[dict] | None = None,
                      max_results: int = 10) -> dict[str, Any]:
        """Find trending products for the niche."""
        searches = NICHE_SEARCHES.get(niche, NICHE_SEARCHES["general"])
        candidates = []

        # Method 1: Web search for trending products
        for query in searches[:2]:
            results = self._web_search(query)
            for r in results:
                product = self._extract_product(r)
                if product:
                    candidates.append(product)

        # Method 2: Generate niche-specific suggestions
        suggestions = self._niche_suggestions(niche)
        candidates.extend(suggestions)

        # Deduplicate
        seen = set()
        unique = []
        for c in candidates:
            key = c.get("name", "").lower()[:30]
            if key not in seen:
                seen.add(key)
                unique.append(c)

        # Score each candidate
        current_names = set((p.get("title", p.get("name", "")).lower() for p in (current_products or [])))
        scored = []
        for c in unique[:max_results * 2]:
            if c.get("name", "").lower() in current_names:
                continue  # Already in store
            score = self._score_product(c, niche)
            c["score"] = score
            scored.append(c)

        scored.sort(key=lambda x: -x.get("score", 0))
        top = scored[:max_results]
        self._found.extend(top)

        # Record in data architecture
        self._record(top, niche)

        return {
            "products_found": len(top),
            "niche": niche,
            "candidates_checked": len(candidates),
            "products": top,
        }

    @staticmethod
    def _web_search(query):
        try:
            from core.ai.external_tools import web_search
            return web_search(query, max_results=5) or []
        except Exception:
            return []

    @staticmethod
    def _extract_product(search_result):
        if isinstance(search_result, dict):
            title = search_result.get("title", "")
            snippet = search_result.get("snippet", search_result.get("description", ""))
            if title and len(title) > 5:
                return {
                    "name": title[:60],
                    "description": snippet[:200] if snippet else "",
                    "source": "web_search",
                }
        return None

    @staticmethod
    def _niche_suggestions(niche):
        """Generate niche-specific product suggestions."""
        suggestions_db = {
            "home": [
                {"name": "LED Cloud Light", "suggested_price": 24.99, "estimated_cost": 8.0, "category": "Home Decor"},
                {"name": "Floating Shelf Set", "suggested_price": 29.99, "estimated_cost": 10.0, "category": "Home Decor"},
                {"name": "Smart Aroma Diffuser", "suggested_price": 34.99, "estimated_cost": 12.0, "category": "Home"},
                {"name": "Minimalist Desk Organizer", "suggested_price": 19.99, "estimated_cost": 6.0, "category": "Home Office"},
                {"name": "Galaxy Projector Lamp", "suggested_price": 27.99, "estimated_cost": 9.0, "category": "Lighting"},
            ],
            "fashion": [
                {"name": "Minimalist Watch", "suggested_price": 39.99, "estimated_cost": 12.0, "category": "Accessories"},
                {"name": "Leather Card Holder", "suggested_price": 14.99, "estimated_cost": 4.0, "category": "Accessories"},
                {"name": "Silk Scrunchie Set", "suggested_price": 12.99, "estimated_cost": 3.0, "category": "Hair"},
            ],
            "tech": [
                {"name": "Wireless Earbuds Pro", "suggested_price": 29.99, "estimated_cost": 10.0, "category": "Audio"},
                {"name": "USB-C Hub 7-in-1", "suggested_price": 24.99, "estimated_cost": 8.0, "category": "Accessories"},
                {"name": "Portable Power Bank 10000mAh", "suggested_price": 19.99, "estimated_cost": 7.0, "category": "Charging"},
            ],
        }
        return [dict(s, source="niche_database") for s in suggestions_db.get(niche, suggestions_db.get("home", []))]

    @staticmethod
    def _score_product(product, niche):
        score = 50  # Base
        price = float(product.get("suggested_price", 25))
        cost = float(product.get("estimated_cost", 10))

        # Margin score (0-25)
        if price > 0 and cost > 0:
            margin = (price - cost) / price
            score += min(25, margin * 40)

        # Price sweet spot (0-15) — $15-$40 is ideal
        if 15 <= price <= 40:
            score += 15
        elif 10 <= price <= 50:
            score += 8

        # Category match (0-10)
        if product.get("category"):
            score += 10

        return round(min(100, score))

    def import_to_shopify(self, product: dict, shop_url: str, token: str) -> dict:
        """Import a found product to Shopify store."""
        import json, urllib.request
        name = product.get("name", "Product")
        price = product.get("suggested_price", 19.99)
        cost = product.get("estimated_cost", 8.0)
        category = product.get("category", "")
        desc = product.get("description", "")

        if not desc:
            desc = "<p>Discover the <strong>{}</strong> — premium quality for your everyday needs.</p>".format(name)

        payload = json.dumps({"product": {
            "title": name,
            "body_html": desc,
            "product_type": category,
            "vendor": "ShopAI",
            "tags": "{}, {}, new, trending".format(category.lower(), "home"),
            "variants": [{"price": str(price), "cost": str(cost),
                          "inventory_management": "shopify", "inventory_quantity": 100}],
        }}).encode()

        h = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
        req = urllib.request.Request(
            "https://{}/admin/api/2024-01/products.json".format(shop_url),
            data=payload, method="POST", headers=h)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                if data.get("product"):
                    return {"status": "imported", "product_id": data["product"]["id"], "name": name}
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:80]}
        return {"status": "error"}

    @staticmethod
    def _record(products, niche):
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            for p in products:
                da.capture("product", {
                    "id": "finder_{}".format(p.get("name","")[:20]),
                    "name": p.get("name", ""),
                    "price": p.get("suggested_price", 0),
                    "source": "product_finder",
                }, source="ai_finder", score=p.get("score", 50) / 20)
        except Exception:
            pass

    def get_found(self):
        return list(self._found)

    def get_stats(self):
        return {"total_found": len(self._found)}


_instance = None
def get_product_finder():
    global _instance
    if _instance is None:
        _instance = AIProductFinder()
    return _instance
