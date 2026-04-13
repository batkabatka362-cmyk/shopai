"""AI Copywriter — generates selling copy, not just descriptions."""
from __future__ import annotations

import threading as _threading


class AICopywriter:
    """Generates marketing copy that sells."""

    def product_copy(self, product, style="persuasive"):
        name = product.get("title", product.get("name", ""))
        price = product.get("price", "")
        category = product.get("product_type", "")

        if style == "persuasive":
            return {
                "headline": "Transform Your Space with {}".format(name),
                "subheadline": "Join thousands who upgraded their {} game".format(category.lower() or "lifestyle"),
                "body": "The {} is not just a product — it is an experience. At ${}, you are investing in quality that lasts.".format(name, price),
                "cta": "Get Yours Now — 15% Off with WELCOME15",
                "urgency": "Limited stock available",
            }
        elif style == "minimal":
            return {
                "headline": name,
                "subheadline": "${} | Free shipping over $50".format(price),
                "body": "Quality {}. Simple design. Great value.".format(category.lower() or "product"),
                "cta": "Shop Now",
            }
        return {"headline": name, "body": "Great product at ${}".format(price), "cta": "Buy Now"}

    def ad_copy(self, product, platform="google"):
        name = product.get("title", product.get("name", ""))
        price = product.get("price", "")

        if platform == "google":
            return {
                "headline1": "{} | Only ${}".format(name[:30], price),
                "headline2": "Free Shipping Over $50 | 15% Off First Order",
                "description": "Shop premium {} at great prices. Use code WELCOME15.".format(name[:20]),
            }
        elif platform == "facebook":
            return {
                "primary_text": "Meet the {} — the upgrade you have been looking for. Now ${}.".format(name, price),
                "headline": "{} | Shop Now".format(name[:25]),
                "cta": "SHOP_NOW",
            }
        return {"text": "{} — ${}. Shop now!".format(name, price)}

    def blog_outline(self, topic, products):
        top = products[:3] if products else []
        return {
            "title": "Best {} for 2026 — Expert Guide".format(topic),
            "sections": [
                {"heading": "Why You Need a Good {}".format(topic), "type": "intro"},
                {"heading": "Top {} Picks".format(len(top)), "type": "product_list",
                 "products": [p.get("title","") for p in top]},
                {"heading": "How to Choose", "type": "buying_guide"},
                {"heading": "FAQ", "type": "faq"},
                {"heading": "Ready to Buy?", "type": "cta"},
            ],
        }


_instance = None
_instance_lock = _threading.Lock()


def get_copywriter():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AICopywriter()
    return _instance
