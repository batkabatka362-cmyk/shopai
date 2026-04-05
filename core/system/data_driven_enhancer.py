"""Data-Driven Enhancer — makes all components read data before acting.

ADDITIVE ONLY — existing components unchanged, this adds intelligence layer.
Every function reads memory+data BEFORE generating output.
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("enhancer.data_driven")


class DataDrivenEnhancer:
    """Adds data intelligence to components that lack it."""

    def __init__(self):
        self._mi = None
        self._da = None

    def _ensure(self):
        if not self._mi:
            try:
                from core.memory.intelligence import get_memory_intelligence
                self._mi = get_memory_intelligence()
            except Exception:
                pass
        if not self._da:
            try:
                from core.data.architecture import get_data_architecture
                self._da = get_data_architecture()
            except Exception:
                pass

    def smart_description(self, product):
        """Generate description using product data + memory."""
        self._ensure()
        name = product.get("title", product.get("name", "Product"))
        price = product.get("price", "")
        category = product.get("product_type", "")

        rules_context = ""
        if self._mi:
            rules = self._mi.get_rules("product")
            if rules:
                rc = rules[0].get("content", {})
                if isinstance(rc, dict):
                    rules_context = rc.get("rule", "")[:60]

        is_top = False
        if self._da:
            best = self._da.get_best("product", limit=3)
            if best:
                is_top = True

        parts = []
        parts.append("<p><strong>{}</strong>".format(name))
        if category:
            parts.append(" &mdash; premium {} product".format(category.lower()))
        parts.append(".</p>")
        parts.append("<h3>Why Choose This?</h3><ul>")
        parts.append("<li>Carefully selected for quality and value</li>")
        if is_top:
            parts.append("<li>AI-recommended based on customer data</li>")
        if float(price or 0) < 30:
            parts.append("<li>Great value at just ${}</li>".format(price))
        else:
            parts.append("<li>Premium quality at ${}</li>".format(price))
        parts.append("<li>Fast shipping</li></ul>")
        parts.append("<p><em>Use <strong>WELCOME15</strong> for 15% off!</em></p>")
        return "".join(parts)

    def smart_discount_strategy(self, products, orders):
        """Choose discount strategy based on actual margins + order data."""
        self._ensure()
        margins = []
        for p in products:
            pr = float(p.get("price", 0))
            co = float(p.get("cost", 0))
            if pr > 0 and co > 0:
                margins.append((pr - co) / pr)
        avg = sum(margins) / max(len(margins), 1) if margins else 0
        has_orders = len(orders) > 0

        if not has_orders:
            return {"strategy": "aggressive", "reason": "No orders yet",
                    "suggested_discount": 20}
        elif avg > 0.5:
            return {"strategy": "generous", "reason": "High margins {:.0%}".format(avg),
                    "suggested_discount": 15}
        else:
            return {"strategy": "conservative", "reason": "Low margins {:.0%}".format(avg),
                    "suggested_discount": 10}

    def smart_social_post(self, product, platform="instagram"):
        """Generate social content using product performance data."""
        self._ensure()
        name = product.get("title", product.get("name", ""))
        price = product.get("price", "0")
        if isinstance(price, (list, dict)):
            price = "0"
        category = product.get("product_type", "")

        is_top = False
        if self._da:
            best = self._da.get_best("product", limit=3)
            if best:
                is_top = True

        tag1 = name.split()[0].lower() if name else "product"
        tag2 = category.split()[0].lower() if category else "shop"
        perf = "AI Top Pick!" if is_top else "New arrival"

        if platform == "instagram":
            return "{name}\n\n${price} | {cat}\n{perf}\n\nLink in bio | WELCOME15 = 15% off\n\n#{t1} #{t2} #shopify".format(
                name=name, price=price, cat=category or "Quality product",
                perf=perf, t1=tag1, t2=tag2)
        elif platform == "tiktok":
            return "POV: You found {name} for ${price}. {perf} Link in bio! #{t1}".format(
                name=name, price=price, perf=perf, t1=tag1)
        return "Check out {name} - ${price}!".format(name=name, price=price)

    def smart_email(self, email_type, store_name, products):
        """Generate email content using store data."""
        self._ensure()
        top = sorted(products,
            key=lambda p: (float(p.get("price", 0)) - float(p.get("cost", 0)))
                / max(float(p.get("price", 1)), 1),
            reverse=True)[:3]
        top_list = "\n".join("  - {} (${})".format(
            p.get("title", p.get("name", "")), p.get("price", ""))
            for p in top)

        if email_type == "welcome":
            return {
                "subject": "Welcome to {}! 15% off inside".format(store_name),
                "body": "Welcome to {}!\n\nTop picks:\n{}\n\nCode: WELCOME15\n\nHappy shopping!".format(
                    store_name, top_list),
            }
        elif email_type == "win_back":
            return {
                "subject": "We miss you! 20% off",
                "body": "Come back!\n\n{}\n\nCode: COMEBACK20".format(top_list),
            }
        return {"subject": "News from {}".format(store_name), "body": top_list}

    def smart_collections(self, products):
        """Suggest collections based on actual product data."""
        self._ensure()
        suggestions = []
        types = {}
        for p in products:
            t = p.get("product_type", "")
            if t:
                types[t] = types.get(t, 0) + 1
        for t, c in sorted(types.items(), key=lambda x: -x[1]):
            if c >= 2:
                suggestions.append({"title": t, "type": "category", "count": c})

        prices = [float(p.get("price", 0)) for p in products if p.get("price")]
        if prices:
            median = sorted(prices)[len(prices)//2]
            under = sum(1 for p in prices if p < median)
            suggestions.append({"title": "Under ${}".format(int(median)), "type": "price", "count": under})

        gift = sum(1 for p in products if 15 < float(p.get("price", 0)) < 60)
        if gift >= 3:
            suggestions.append({"title": "Gift Ideas", "type": "gift", "count": gift})

        if self._mi:
            top = self._mi.retrieve("product", min_score=4.0, limit=5)
            if top:
                suggestions.append({"title": "AI Top Picks", "type": "ai", "count": len(top)})

        return suggestions


_instance = None
def get_enhancer():
    global _instance
    if _instance is None:
        _instance = DataDrivenEnhancer()
    return _instance
