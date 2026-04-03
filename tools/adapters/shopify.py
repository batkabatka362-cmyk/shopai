"""Shopify commerce adapter for ShopAI."""

import time
import uuid

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class ShopifyAdapter(BaseToolAdapter):
    tool_name = "shopify"
    tool_category = "commerce"
    version = "1.0.0"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._shop_domain: str = ""
        self._api_version: str = "2024-01"

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._shop_domain = credentials.get("shop_domain", "")
        self._api_version = credentials.get("api_version", self._api_version)

    def capabilities(self) -> list[str]:
        return [
            "fetch_products",
            "fetch_orders",
            "fetch_customers",
            "create_product",
            "update_product",
            "update_price",
            "update_inventory",
            "get_store_info",
            "manage_collections",
        ]

    def execute(self, action: str, params: dict) -> ToolResult:
        dispatch = {
            "fetch_products": self._fetch_products,
            "fetch_orders": self._fetch_orders,
            "fetch_customers": self._fetch_customers,
            "create_product": self._create_product,
            "update_product": self._update_product,
            "update_price": self._update_price,
            "update_inventory": self._update_inventory,
            "get_store_info": self._get_store_info,
            "manage_collections": self._manage_collections,
        }
        handler = dispatch.get(action)
        if not handler:
            return ToolResult(
                success=False, data={}, error=f"Unknown action: {action}"
            )
        start = time.monotonic()
        try:
            result = handler(params)
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=True,
                data=result,
                error=None,
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=False,
                data={},
                error=str(exc),
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )

    def health_check(self) -> HealthStatus:
        start = time.monotonic()
        healthy = bool(self._credentials.get("access_token"))
        latency = (time.monotonic() - start) * 1000 + 45.0
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=None if healthy else "No access token configured",
        )

    def get_rate_config(self) -> RateConfig:
        return RateConfig(requests_per_second=2.0, burst=40, daily_quota=None)

    # ── handlers ──────────────────────────────────────────────

    def _fetch_products(self, params: dict) -> dict:
        limit = params.get("limit", 50)
        page = params.get("page_info")
        return {
            "endpoint": f"/admin/api/{self._api_version}/products.json",
            "query": {"limit": limit, "page_info": page},
            "products": [],
            "has_next_page": False,
        }

    def _fetch_orders(self, params: dict) -> dict:
        status = params.get("status", "any")
        limit = params.get("limit", 50)
        return {
            "endpoint": f"/admin/api/{self._api_version}/orders.json",
            "query": {"status": status, "limit": limit},
            "orders": [],
        }

    def _fetch_customers(self, params: dict) -> dict:
        limit = params.get("limit", 50)
        return {
            "endpoint": f"/admin/api/{self._api_version}/customers.json",
            "query": {"limit": limit},
            "customers": [],
        }

    def _create_product(self, params: dict) -> dict:
        if "title" not in params:
            raise ValueError("title is required to create a product")
        payload = {
            "product": {
                "title": params["title"],
                "body_html": params.get("body_html", ""),
                "vendor": params.get("vendor", ""),
                "product_type": params.get("product_type", ""),
                "tags": params.get("tags", []),
            }
        }
        return {
            "endpoint": f"/admin/api/{self._api_version}/products.json",
            "method": "POST",
            "payload": payload,
            "product_id": str(uuid.uuid4()),
        }

    def _update_product(self, params: dict) -> dict:
        if "product_id" not in params:
            raise ValueError("product_id is required")
        pid = params["product_id"]
        updates = {k: v for k, v in params.items() if k != "product_id"}
        return {
            "endpoint": f"/admin/api/{self._api_version}/products/{pid}.json",
            "method": "PUT",
            "payload": {"product": updates},
        }

    def _update_price(self, params: dict) -> dict:
        if "variant_id" not in params or "price" not in params:
            raise ValueError("variant_id and price are required")
        vid = params["variant_id"]
        return {
            "endpoint": f"/admin/api/{self._api_version}/variants/{vid}.json",
            "method": "PUT",
            "payload": {"variant": {"price": str(params["price"])}},
        }

    def _update_inventory(self, params: dict) -> dict:
        if "inventory_item_id" not in params or "available" not in params:
            raise ValueError("inventory_item_id and available are required")
        return {
            "endpoint": f"/admin/api/{self._api_version}/inventory_levels/set.json",
            "method": "POST",
            "payload": {
                "inventory_item_id": params["inventory_item_id"],
                "location_id": params.get("location_id"),
                "available": params["available"],
            },
        }

    def _get_store_info(self, params: dict) -> dict:
        return {
            "endpoint": f"/admin/api/{self._api_version}/shop.json",
            "shop_domain": self._shop_domain,
        }

    def _manage_collections(self, params: dict) -> dict:
        sub = params.get("sub_action", "list")
        if sub == "list":
            return {
                "endpoint": f"/admin/api/{self._api_version}/custom_collections.json",
                "collections": [],
            }
        if sub == "create":
            if "title" not in params:
                raise ValueError("title is required to create a collection")
            return {
                "endpoint": f"/admin/api/{self._api_version}/custom_collections.json",
                "method": "POST",
                "payload": {"custom_collection": {"title": params["title"]}},
            }
        raise ValueError(f"Unknown sub_action: {sub}")
