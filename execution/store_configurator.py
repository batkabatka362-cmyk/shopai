"""Store Configurator — auto-configure all Shopify store settings.

Configures: shipping, discounts, collections, pages, SEO, and more.
Teaches AI about the store and optimizes for the niche.
"""
from __future__ import annotations
import json
import time
import urllib.request
from typing import Any
from utils.logger import get_logger
logger = get_logger("store.configurator")

# Niche-specific configurations
NICHE_CONFIGS = {
    "home": {
        "collections": ["Home Decor", "Lighting", "Kitchen", "Bedroom", "Living Room"],
        "discount_strategy": "moderate",
        "shipping_message": "Free shipping on orders over $50",
        "target_audience": "homeowners, renters, gift buyers",
    },
    "fashion": {
        "collections": ["New Arrivals", "Tops", "Bottoms", "Accessories", "Sale"],
        "discount_strategy": "aggressive",
        "shipping_message": "Free shipping on all orders",
        "target_audience": "young adults, fashion-conscious",
    },
    "tech": {
        "collections": ["Gadgets", "Accessories", "Smart Home", "Audio", "Charging"],
        "discount_strategy": "moderate",
        "shipping_message": "Fast tech delivery — 2-5 days",
        "target_audience": "tech enthusiasts, gadget lovers",
    },
    "beauty": {
        "collections": ["Skincare", "Makeup", "Hair Care", "Tools", "Gift Sets"],
        "discount_strategy": "generous",
        "shipping_message": "Free shipping + free samples",
        "target_audience": "beauty enthusiasts",
    },
    "general": {
        "collections": ["Best Sellers", "New In", "Under $25", "Premium", "Gift Ideas"],
        "discount_strategy": "moderate",
        "shipping_message": "Free shipping on orders over $50",
        "target_audience": "general consumers",
    },
}


class StoreConfigurator:
    """Auto-configure Shopify store based on niche and products."""

    def __init__(self) -> None:
        self._log: list[dict] = []

    def configure(self, shop_url: str, token: str, niche: str = "general",
                  store_name: str = "") -> dict[str, Any]:
        """Full store configuration — shipping, discounts, collections, content."""
        h = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
        config = NICHE_CONFIGS.get(niche, NICHE_CONFIGS["general"])
        results = {}

        # Get current products
        products = self._api_get(shop_url, "products.json?limit=50", h).get("products", [])

        # 1. Smart collections by niche
        results["collections"] = self._setup_collections(
            shop_url, h, config, products)

        # 2. Discount strategy
        results["discounts"] = self._setup_discounts(
            shop_url, h, config, store_name)

        # 3. Shipping optimization
        results["shipping"] = self._check_shipping(shop_url, h)

        # 4. SEO pages (buying guides)
        results["content"] = self._create_niche_content(
            shop_url, h, niche, config, products)

        # 5. Product organization by niche
        results["product_tags"] = self._organize_products(
            shop_url, h, niche, products)

        # 6. Store metafields (AI config)
        results["ai_config"] = self._save_ai_config(
            shop_url, h, niche, config)

        # Record
        self._record(results)

        return {
            "status": "configured",
            "niche": niche,
            "results": results,
        }

    def _setup_collections(self, shop_url, h, config, products):
        """Create niche-specific collections."""
        created = 0
        existing = self._api_get(shop_url, "smart_collections.json", h).get("smart_collections", [])
        existing_titles = set(c["title"].lower() for c in existing)

        for title in config["collections"]:
            if title.lower() in existing_titles:
                continue
            # Create based on tag matching
            result = self._api_post(shop_url, "smart_collections.json", h, {
                "smart_collection": {
                    "title": title,
                    "body_html": "<p>Explore our {} selection.</p>".format(title),
                    "rules": [{"column": "tag", "relation": "equals", "condition": title.lower()}],
                    "published": True,
                }
            })
            if result.get("smart_collection"):
                created += 1

        # Price-based collections
        for title, rule in [("Under $20", "20"), ("Under $50", "50")]:
            if title.lower() not in existing_titles:
                self._api_post(shop_url, "smart_collections.json", h, {
                    "smart_collection": {
                        "title": title,
                        "rules": [{"column": "variant_price", "relation": "less_than", "condition": rule}],
                        "published": True,
                    }
                })
                created += 1

        return {"created": created, "total": len(existing) + created}

    def _setup_discounts(self, shop_url, h, config, store_name):
        """Create discount strategy based on niche."""
        existing = self._api_get(shop_url, "price_rules.json", h).get("price_rules", [])
        existing_titles = set(r["title"] for r in existing)
        created = []

        strategy = config["discount_strategy"]

        # Always: welcome discount
        if "WELCOME15" not in existing_titles:
            self._create_discount(shop_url, h, "WELCOME15", -15.0, once_per_customer=True)
            created.append("WELCOME15")

        if strategy == "aggressive":
            if "FLASH25" not in existing_titles:
                self._create_discount(shop_url, h, "FLASH25", -25.0)
                created.append("FLASH25")
            if "BOGO50" not in existing_titles:
                self._create_discount(shop_url, h, "BOGO50", -50.0, min_qty=2)
                created.append("BOGO50")
        elif strategy == "generous":
            if "BEAUTY20" not in existing_titles:
                self._create_discount(shop_url, h, "BEAUTY20", -20.0)
                created.append("BEAUTY20")
        else:  # moderate
            if "SAVE10" not in existing_titles:
                self._create_discount(shop_url, h, "SAVE10", -10.0)
                created.append("SAVE10")

        return {"created": len(created), "codes": created}

    def _create_discount(self, shop_url, h, code, value, once_per_customer=False, min_qty=0):
        rule = {
            "price_rule": {
                "title": code,
                "target_type": "line_item",
                "target_selection": "all",
                "allocation_method": "across",
                "value_type": "percentage",
                "value": str(value),
                "customer_selection": "all",
                "starts_at": time.strftime("%Y-%m-%dT00:00:00Z"),
                "once_per_customer": once_per_customer,
            }
        }
        if min_qty:
            rule["price_rule"]["prerequisite_quantity_range"] = {
                "greater_than_or_equal_to": min_qty}

        result = self._api_post(shop_url, "price_rules.json", h, rule)
        if result.get("price_rule"):
            rule_id = result["price_rule"]["id"]
            self._api_post(shop_url, "price_rules/{}/discount_codes.json".format(rule_id), h,
                           {"discount_code": {"code": code}})

    def _check_shipping(self, shop_url, h):
        zones = self._api_get(shop_url, "shipping_zones.json", h).get("shipping_zones", [])
        return {
            "zones": len(zones),
            "details": [{"name": z.get("name",""), "countries": len(z.get("countries",[]))}
                        for z in zones],
        }

    def _create_niche_content(self, shop_url, h, niche, config, products):
        """Create niche-specific content pages."""
        created = 0
        existing_pages = self._api_get(shop_url, "pages.json", h).get("pages", [])
        existing_titles = set(p["title"].lower() for p in existing_pages)

        # Buying guide
        guide_title = "Buying Guide: Best {} Products".format(niche.title())
        if guide_title.lower() not in existing_titles:
            body = "<h2>How to Choose the Best {} Products</h2>".format(niche.title())
            body += "<p>Our AI-curated selection helps you find the perfect products.</p>"
            body += "<h3>What to Look For</h3><ul>"
            body += "<li>Quality materials and construction</li>"
            body += "<li>Good reviews and ratings</li>"
            body += "<li>Fair pricing with good margin</li>"
            body += "<li>Fast shipping availability</li></ul>"
            if products:
                body += "<h3>Our Top Picks</h3><ul>"
                for p in products[:5]:
                    body += '<li><a href="/products/{}">{}</a></li>'.format(
                        p.get("handle",""), p.get("title",""))
                body += "</ul>"
            body += "<p>Use code <strong>WELCOME15</strong> for 15% off!</p>"

            result = self._api_post(shop_url, "pages.json", h, {
                "page": {"title": guide_title, "body_html": body, "published": True}
            })
            if result.get("page"):
                created += 1

        return {"pages_created": created}

    def _organize_products(self, shop_url, h, niche, products):
        """Add niche-specific tags to products."""
        tagged = 0
        for p in products[:20]:
            pid = p["id"]
            current_tags = p.get("tags", "") or ""
            new_tags = set(t.strip() for t in current_tags.split(",") if t.strip())

            # Add niche tag
            new_tags.add(niche)

            # Price-based tags
            price = float(p.get("variants", [{}])[0].get("price", "0") if p.get("variants") else "0")
            if price < 20:
                new_tags.add("budget-friendly")
            elif price > 40:
                new_tags.add("premium")

            # Gift tag for appropriate products
            if price > 15 and price < 60:
                new_tags.add("gift-idea")

            updated_tags = ", ".join(sorted(new_tags))
            if updated_tags != current_tags:
                self._api_put(shop_url, "products/{}.json".format(pid), h,
                              {"product": {"id": pid, "tags": updated_tags}})
                tagged += 1

        return {"tagged": tagged}

    def _save_ai_config(self, shop_url, h, niche, config):
        """Save AI configuration as shop metafield."""
        ai_config = {
            "niche": niche,
            "target_audience": config["target_audience"],
            "discount_strategy": config["discount_strategy"],
            "configured_at": time.time(),
            "version": "2.0",
        }
        result = self._api_post(shop_url, "metafields.json", h, {
            "metafield": {
                "namespace": "shopai",
                "key": "config",
                "value": json.dumps(ai_config),
                "type": "json",
            }
        })
        return {"saved": bool(result.get("metafield"))}

    def _record(self, results):
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            da.capture("action", {
                "action_type": "store_configuration",
                "success": True,
            }, source="configurator", score=4.5)
        except Exception:
            pass

    @staticmethod
    def _api_get(shop_url, path, h):
        try:
            req = urllib.request.Request("https://{}/admin/api/2024-01/{}".format(shop_url, path), headers=h)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception:
            return {}

    @staticmethod
    def _api_post(shop_url, path, h, payload):
        try:
            url = "https://{}/admin/api/2024-01/{}".format(shop_url, path)
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, method="POST", headers=h)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception:
            return {}

    @staticmethod
    def _api_put(shop_url, path, h, payload):
        try:
            url = "https://{}/admin/api/2024-01/{}".format(shop_url, path)
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, method="PUT", headers=h)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception:
            return {}


_instance = None
def get_store_configurator():
    global _instance
    if _instance is None:
        _instance = StoreConfigurator()
    return _instance
