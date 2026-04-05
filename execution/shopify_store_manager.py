"""Shopify Store Manager — full store management via API.

Uses available scopes to maximize store automation:
  write_products: CRUD products, descriptions, tags, images
  write_inventory: update stock levels
  read_orders: analyze orders for learning
  read_customers: segment and target customers

Features:
  - Collection management (smart + manual)
  - Webhook registration (real-time events)
  - Metafield storage (AI data on products)
  - Bulk product operations
  - Inventory sync
"""
from __future__ import annotations
import json
import time
import urllib.request
from typing import Any
from utils.logger import get_logger
logger = get_logger("shopify.manager")


class ShopifyStoreManager:
    """Full Shopify store management."""

    def __init__(self, shop_url: str = "", token: str = "") -> None:
        self._shop_url = shop_url
        self._token = token

    def set_credentials(self, shop_url: str, token: str) -> None:
        self._shop_url = shop_url
        self._token = token

    # == COLLECTIONS ===============================================

    def create_collection(self, title: str, rules: list[dict] | None = None,
                          body_html: str = "") -> dict[str, Any]:
        """Create a smart or manual collection."""
        if rules:
            # Smart collection with automatic rules
            payload = {"smart_collection": {
                "title": title,
                "body_html": body_html,
                "rules": rules,
                "disjunctive": False,
            }}
            endpoint = "smart_collections"
        else:
            payload = {"custom_collection": {
                "title": title,
                "body_html": body_html,
            }}
            endpoint = "custom_collections"
        return self._post(endpoint, payload)

    def create_smart_collections(self, products: list[dict]) -> dict[str, Any]:
        """Auto-create smart collections based on product categories."""
        categories = set()
        for p in products:
            cat = p.get("product_type", "")
            if cat:
                categories.add(cat)

        created = []
        for cat in categories:
            result = self.create_collection(
                title=cat,
                rules=[{"column": "type", "relation": "equals", "condition": cat}],
                body_html="<p>Browse our {} collection.</p>".format(cat),
            )
            if result.get("smart_collection", {}).get("id"):
                created.append({"category": cat, "id": result["smart_collection"]["id"]})

        # Price-based collections
        result = self.create_collection(
            title="Under $20",
            rules=[{"column": "variant_price", "relation": "less_than", "condition": "20"}],
        )
        if result.get("smart_collection", {}).get("id"):
            created.append({"category": "under_20", "id": result["smart_collection"]["id"]})

        result = self.create_collection(
            title="Premium ($30+)",
            rules=[{"column": "variant_price", "relation": "greater_than", "condition": "30"}],
        )
        if result.get("smart_collection", {}).get("id"):
            created.append({"category": "premium", "id": result["smart_collection"]["id"]})

        return {"created": len(created), "collections": created}

    def list_collections(self) -> list[dict]:
        """List all collections."""
        smart = self._get("smart_collections").get("smart_collections", [])
        custom = self._get("custom_collections").get("custom_collections", [])
        all_cols = []
        for c in smart:
            all_cols.append({"id": c["id"], "title": c["title"], "type": "smart",
                             "products_count": c.get("products_count", 0)})
        for c in custom:
            all_cols.append({"id": c["id"], "title": c["title"], "type": "custom"})
        return all_cols

    # == WEBHOOKS ==================================================

    def register_webhooks(self, callback_url: str) -> dict[str, Any]:
        """Register webhooks for real-time events."""
        topics = [
            "orders/create",
            "orders/updated",
            "products/update",
            "products/create",
            "customers/create",
            "inventory_levels/update",
        ]
        registered = []
        for topic in topics:
            result = self._post("webhooks", {
                "webhook": {
                    "topic": topic,
                    "address": callback_url,
                    "format": "json",
                }
            })
            if result.get("webhook", {}).get("id"):
                registered.append(topic)

        return {"registered": len(registered), "topics": registered}

    def list_webhooks(self) -> list[dict]:
        data = self._get("webhooks")
        return [{"id": w["id"], "topic": w["topic"], "address": w.get("address", "")}
                for w in data.get("webhooks", [])]

    # == METAFIELDS ================================================

    def set_product_metafield(self, product_id: str, namespace: str,
                              key: str, value: str,
                              value_type: str = "single_line_text_field") -> dict:
        """Store AI data on a product via metafields."""
        return self._post("products/{}/metafields".format(product_id), {
            "metafield": {
                "namespace": namespace,
                "key": key,
                "value": value,
                "type": value_type,
            }
        })

    def set_ai_score(self, product_id: str, score: float, grade: str) -> dict:
        """Store AI product score as metafield."""
        return self.set_product_metafield(
            product_id, "shopai", "score",
            json.dumps({"score": score, "grade": grade, "updated": time.time()}),
            "json",
        )

    # == INVENTORY =================================================

    def update_inventory(self, inventory_item_id: str, location_id: str,
                         available: int) -> dict:
        """Update inventory level."""
        return self._post("inventory_levels/set", {
            "location_id": int(location_id),
            "inventory_item_id": int(inventory_item_id),
            "available": available,
        })

    def get_locations(self) -> list[dict]:
        data = self._get("locations")
        return [{"id": l["id"], "name": l["name"]} for l in data.get("locations", [])]

    # == BULK OPERATIONS ===========================================

    def bulk_update_descriptions(self, updates: list[dict]) -> dict[str, Any]:
        """Bulk update product descriptions."""
        success = 0
        for u in updates:
            pid = u.get("product_id", "")
            desc = u.get("description", "")
            if pid and desc:
                result = self._put("products/{}".format(pid), {
                    "product": {"id": int(pid), "body_html": desc}
                })
                if "product" in result:
                    success += 1
        return {"total": len(updates), "success": success}

    # == API HELPERS ===============================================

    def _get(self, endpoint: str) -> dict:
        url = "https://{}/admin/api/2024-01/{}.json".format(self._shop_url, endpoint)
        req = urllib.request.Request(url,
            headers={"X-Shopify-Access-Token": self._token})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            return {"error": str(exc)[:100]}

    def _post(self, endpoint: str, payload: dict) -> dict:
        url = "https://{}/admin/api/2024-01/{}.json".format(self._shop_url, endpoint)
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST",
            headers={"X-Shopify-Access-Token": self._token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            return {"error": "HTTP {} {}".format(exc.code, body)}
        except Exception as exc:
            return {"error": str(exc)[:100]}

    def _put(self, endpoint: str, payload: dict) -> dict:
        url = "https://{}/admin/api/2024-01/{}.json".format(self._shop_url, endpoint)
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method="PUT",
            headers={"X-Shopify-Access-Token": self._token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            return {"error": "HTTP {} {}".format(exc.code, body)}
        except Exception as exc:
            return {"error": str(exc)[:100]}


_instance = None
def get_shopify_manager():
    global _instance
    if _instance is None:
        _instance = ShopifyStoreManager()
    return _instance
