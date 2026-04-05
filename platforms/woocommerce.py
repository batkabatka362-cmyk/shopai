"""WooCommerce Adapter — manage WooCommerce stores with same AI."""
from __future__ import annotations
import json
import urllib.request
import hashlib
import hmac
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("platform.woocommerce")


class WooCommerceAdapter:
    """WooCommerce REST API adapter."""

    def __init__(self, store_url: str = "", consumer_key: str = "",
                 consumer_secret: str = "") -> None:
        self._url = store_url.rstrip("/")
        self._key = consumer_key
        self._secret = consumer_secret

    def configure(self, store_url: str, consumer_key: str, consumer_secret: str) -> None:
        self._url = store_url.rstrip("/")
        self._key = consumer_key
        self._secret = consumer_secret

    def get_products(self, limit: int = 50) -> list[dict]:
        data = self._get("products?per_page={}".format(limit))
        if isinstance(data, list):
            return [self._normalize_product(p) for p in data]
        return []

    def get_orders(self, limit: int = 50) -> list[dict]:
        data = self._get("orders?per_page={}".format(limit))
        if isinstance(data, list):
            return [self._normalize_order(o) for o in data]
        return []

    def get_customers(self, limit: int = 50) -> list[dict]:
        data = self._get("customers?per_page={}".format(limit))
        if isinstance(data, list):
            return data
        return []

    def update_product(self, product_id: str, fields: dict) -> dict:
        return self._put("products/{}".format(product_id), fields)

    @staticmethod
    def _normalize_product(p: dict) -> dict:
        return {
            "id": str(p.get("id", "")),
            "name": p.get("name", ""),
            "price": float(p.get("price", 0) or 0),
            "cost": float(p.get("meta_data", [{}])[0].get("value", 0) if p.get("meta_data") else 0),
            "description": p.get("description", ""),
            "tags": ", ".join(t.get("name", "") for t in p.get("tags", [])),
            "category": p.get("categories", [{}])[0].get("name", "") if p.get("categories") else "",
            "images": [img.get("src", "") for img in p.get("images", [])],
            "inventory_quantity": p.get("stock_quantity", 0),
            "platform": "woocommerce",
        }

    @staticmethod
    def _normalize_order(o: dict) -> dict:
        return {
            "id": str(o.get("id", "")),
            "total": float(o.get("total", 0)),
            "status": o.get("status", ""),
            "customer_id": str(o.get("customer_id", "")),
            "items": len(o.get("line_items", [])),
            "platform": "woocommerce",
        }

    def _get(self, endpoint: str) -> Any:
        url = "{}/wp-json/wc/v3/{}".format(self._url, endpoint)
        sep = "&" if "?" in url else "?"
        url += "{}consumer_key={}&consumer_secret={}".format(sep, self._key, self._secret)
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            return {"error": str(exc)[:100]}

    def _put(self, endpoint: str, data: dict) -> dict:
        url = "{}/wp-json/wc/v3/{}?consumer_key={}&consumer_secret={}".format(
            self._url, endpoint, self._key, self._secret)
        payload = json.dumps(data).encode()
        req = urllib.request.Request(url, data=payload, method="PUT",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            return {"error": str(exc)[:100]}

    def get_stats(self) -> dict:
        return {"platform": "woocommerce", "configured": bool(self._url and self._key)}


_instance = None
def get_woocommerce():
    global _instance
    if _instance is None:
        _instance = WooCommerceAdapter()
    return _instance
