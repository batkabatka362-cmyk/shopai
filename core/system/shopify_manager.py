"""ShopifyManager — manages ALL Shopify store settings, pages, themes, navigation.

Complete store control:
  - Store settings (name, email, currency, timezone)
  - Theme management
  - Pages (about, contact, FAQ, policies)
  - Navigation menus
  - Payment settings info
  - Shipping zones info
  - Product collections
  - Metafields
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from utils.logger import get_logger

logger = get_logger("shopify_manager")

_API_VERSION = "2024-01"


class ShopifyManager:
    """Full Shopify store management via Admin API."""

    def __init__(self, shop_url: str = "", token: str = "") -> None:
        self._shop = shop_url.rstrip("/")
        self._token = token

    def configure(self, shop_url: str, token: str) -> None:
        self._shop = shop_url.rstrip("/")
        self._token = token

    # ── Store Info ───────────────────────────────────────────

    def get_store_info(self) -> dict[str, Any]:
        """Get full store details."""
        return self._get("shop.json").get("shop", {})

    def update_store(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Update store settings (name, email, etc.)."""
        return self._put("shop.json", {"shop": updates})

    # ── Products ─────────────────────────────────────────────

    def get_products(self, limit: int = 250) -> list[dict]:
        return self._get(f"products.json?limit={limit}").get("products", [])

    def get_product(self, product_id: str) -> dict:
        return self._get(f"products/{product_id}.json").get("product", {})

    def create_product(self, product: dict) -> dict:
        return self._post("products.json", {"product": product}).get("product", {})

    def update_product(self, product_id: str, updates: dict) -> dict:
        return self._put(f"products/{product_id}.json", {"product": {"id": product_id, **updates}}).get("product", {})

    def delete_product(self, product_id: str) -> bool:
        try:
            self._delete(f"products/{product_id}.json")
            return True
        except Exception:
            return False

    # ── Collections ──────────────────────────────────────────

    def get_collections(self) -> list[dict]:
        custom = self._get("custom_collections.json").get("custom_collections", [])
        smart = self._get("smart_collections.json").get("smart_collections", [])
        return custom + smart

    def create_collection(self, title: str, rules: list | None = None) -> dict:
        if rules:
            return self._post("smart_collections.json", {
                "smart_collection": {"title": title, "rules": rules}
            }).get("smart_collection", {})
        return self._post("custom_collections.json", {
            "custom_collection": {"title": title}
        }).get("custom_collection", {})

    def add_to_collection(self, collection_id: str, product_id: str) -> dict:
        return self._post("collects.json", {
            "collect": {"collection_id": collection_id, "product_id": product_id}
        })

    # ── Pages ────────────────────────────────────────────────

    def get_pages(self) -> list[dict]:
        return self._get("pages.json").get("pages", [])

    def create_page(self, title: str, body_html: str, published: bool = True) -> dict:
        return self._post("pages.json", {
            "page": {"title": title, "body_html": body_html, "published": published}
        }).get("page", {})

    def update_page(self, page_id: str, updates: dict) -> dict:
        return self._put(f"pages/{page_id}.json", {"page": {"id": page_id, **updates}}).get("page", {})

    # ── Themes ───────────────────────────────────────────────

    def get_themes(self) -> list[dict]:
        return self._get("themes.json").get("themes", [])

    def get_active_theme(self) -> dict:
        themes = self.get_themes()
        for t in themes:
            if t.get("role") == "main":
                return t
        return themes[0] if themes else {}

    # ── Navigation ───────────────────────────────────────────

    def get_menus(self) -> list[dict]:
        """Get navigation menus (requires Online Store channel)."""
        try:
            return self._get("menus.json").get("menus", [])
        except Exception:
            return []

    # ── Shipping ─────────────────────────────────────────────

    def get_shipping_zones(self) -> list[dict]:
        return self._get("shipping_zones.json").get("shipping_zones", [])

    # ── Policies ─────────────────────────────────────────────

    def get_policies(self) -> list[dict]:
        return self._get("policies.json").get("policies", [])

    # ── Metafields ───────────────────────────────────────────

    def get_metafields(self, resource: str = "shop") -> list[dict]:
        if resource == "shop":
            return self._get("metafields.json").get("metafields", [])
        return self._get(f"{resource}/metafields.json").get("metafields", [])

    def set_metafield(self, namespace: str, key: str, value: str,
                      value_type: str = "single_line_text_field") -> dict:
        return self._post("metafields.json", {
            "metafield": {
                "namespace": namespace, "key": key,
                "value": value, "type": value_type,
            }
        })

    # ── Orders ───────────────────────────────────────────────

    def get_orders(self, status: str = "any", limit: int = 50) -> list[dict]:
        return self._get(f"orders.json?status={status}&limit={limit}").get("orders", [])

    def get_order(self, order_id: str) -> dict:
        return self._get(f"orders/{order_id}.json").get("order", {})

    # ── Customers ────────────────────────────────────────────

    def get_customers(self, limit: int = 50) -> list[dict]:
        return self._get(f"customers.json?limit={limit}").get("customers", [])

    # ── Inventory ────────────────────────────────────────────

    def get_inventory_levels(self, location_id: str = "") -> list[dict]:
        if location_id:
            return self._get(f"inventory_levels.json?location_ids={location_id}").get("inventory_levels", [])
        locs = self.get_locations()
        if locs:
            return self._get(f"inventory_levels.json?location_ids={locs[0]['id']}").get("inventory_levels", [])
        return []

    def get_locations(self) -> list[dict]:
        return self._get("locations.json").get("locations", [])

    # ── Full Store Audit ─────────────────────────────────────

    def full_audit(self) -> dict[str, Any]:
        """Complete store audit — fetches everything."""
        audit: dict[str, Any] = {"timestamp": time.time()}

        try:
            audit["store"] = self.get_store_info()
        except Exception as e:
            audit["store"] = {"error": str(e)}

        try:
            products = self.get_products()
            audit["products"] = {"count": len(products), "items": products[:10]}
        except Exception as e:
            audit["products"] = {"error": str(e)}

        try:
            audit["collections"] = self.get_collections()
        except Exception as e:
            audit["collections"] = {"error": str(e)}

        try:
            audit["pages"] = self.get_pages()
        except Exception as e:
            audit["pages"] = {"error": str(e)}

        try:
            audit["themes"] = self.get_themes()
        except Exception as e:
            audit["themes"] = {"error": str(e)}

        try:
            audit["shipping"] = self.get_shipping_zones()
        except Exception as e:
            audit["shipping"] = {"error": str(e)}

        try:
            audit["policies"] = self.get_policies()
        except Exception as e:
            audit["policies"] = {"error": str(e)}

        try:
            audit["locations"] = self.get_locations()
        except Exception as e:
            audit["locations"] = {"error": str(e)}

        return audit

    # ── HTTP Helpers ─────────────────────────────────────────

    def _get(self, endpoint: str) -> dict:
        return self._request("GET", endpoint)

    def _post(self, endpoint: str, data: dict) -> dict:
        return self._request("POST", endpoint, data)

    def _put(self, endpoint: str, data: dict) -> dict:
        return self._request("PUT", endpoint, data)

    def _delete(self, endpoint: str) -> dict:
        return self._request("DELETE", endpoint)

    def _request(self, method: str, endpoint: str, data: dict | None = None) -> dict:
        url = f"https://{self._shop}/admin/api/{_API_VERSION}/{endpoint}"
        headers = {
            "X-Shopify-Access-Token": self._token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.warning("Shopify API %s %s → %d: %s", method, endpoint, exc.code, error_body[:200])
            raise
