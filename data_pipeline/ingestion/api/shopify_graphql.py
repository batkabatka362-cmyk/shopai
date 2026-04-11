"""ShopifyGraphQL — modern Shopify API client using GraphQL.

REST API is legacy. GraphQL is the future:
  - Single endpoint, precise data
  - Lower latency, no over-fetching
  - Access to ALL new Shopify features
  - Cost-based rate limiting (more predictable)

Usage:
    gql = ShopifyGraphQL("mystore.myshopify.com", token)
    products = gql.get_products(first=50)
    orders = gql.get_orders(first=50)
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from utils.helpers import safe_float, safe_int
from utils.logger import get_logger

logger = get_logger("shopify.graphql")

_API_VERSION = "2024-01"


def _normalize_shop_url(raw: str) -> str:
    """Strip scheme / trailing slashes from a Shopify shop URL.

    See ``data_pipeline.ingestion.api.shopify_api`` for the
    rationale — the same double-scheme bug exists in both
    clients. Audit pass 43.
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip().rstrip("/")
    if s.startswith("https://"):
        s = s[len("https://"):]
    elif s.startswith("http://"):
        s = s[len("http://"):]
    return s


class ShopifyGraphQLError(Exception):
    """Raised when the Shopify GraphQL API request fails terminally."""


class ShopifyGraphQL:
    """Shopify GraphQL Admin API client."""

    def __init__(self, shop_url: str, access_token: str) -> None:
        self._shop = _normalize_shop_url(shop_url)
        self._token = access_token if isinstance(access_token, str) else ""
        self._url = f"https://{self._shop}/admin/api/{_API_VERSION}/graphql.json"
        self._cost_used = 0

    # ── Core Query ───────────────────────────────────────────

    def query(
        self,
        graphql: str,
        variables: dict | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> dict[str, Any]:
        """Execute a GraphQL query with exponential-backoff retry.

        Pre-audit this method had NO retry logic at all — a
        single HTTP 5xx / network blip / rate-limit propagated
        to the caller immediately while the REST client
        retried three times. Audit pass 43 brings the two
        clients to parity.
        """
        if not isinstance(graphql, str) or not graphql:
            raise ShopifyGraphQLError("query: graphql string is empty or not a string")
        if variables is not None and not isinstance(variables, dict):
            variables = None

        payload = json.dumps({
            "query": graphql,
            "variables": variables or {},
        }).encode()

        last_exc: Exception | None = None
        for attempt in range(1, max(1, max_retries) + 1):
            req = urllib.request.Request(
                self._url, data=payload,
                headers={
                    "X-Shopify-Access-Token": self._token,
                    "Content-Type": "application/json",
                },
            )
            start = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read()
            except urllib.error.HTTPError as exc:
                last_exc = exc
                # Rate limit / server error → retry with backoff.
                if exc.code == 429 or exc.code >= 500:
                    if attempt < max_retries:
                        time.sleep(retry_delay * attempt)
                        continue
                # 4xx (other than 429) → no point retrying.
                raise ShopifyGraphQLError(
                    f"HTTP {exc.code} from Shopify GraphQL: {exc}"
                ) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(retry_delay * attempt)
                    continue
                raise ShopifyGraphQLError(
                    f"Network error after {max_retries} attempts: {exc}"
                ) from exc

            elapsed = time.monotonic() - start

            try:
                data = json.loads(raw)
            except ValueError as exc:
                raise ShopifyGraphQLError(
                    f"Invalid JSON from Shopify GraphQL: {exc}"
                ) from exc
            if not isinstance(data, dict):
                raise ShopifyGraphQLError(
                    f"Expected JSON object, got {type(data).__name__}"
                )

            # Track cost. ``.get("extensions", {}).get(...)``
            # crashed on present-but-None extensions; use the
            # ``or {}`` pattern from passes 32/36/40/41/42.
            extensions = data.get("extensions") or {}
            cost = extensions.get("cost") if isinstance(extensions, dict) else None
            if not isinstance(cost, dict):
                cost = {}
            self._cost_used += safe_int(cost.get("actualQueryCost"))

            if data.get("errors"):
                logger.warning("GraphQL errors: %s", data["errors"])

            logger.debug(
                "GraphQL query %.2fs (cost: %s)", elapsed,
                cost.get("actualQueryCost", "?"),
            )
            return data

        # Exhausted retries with a retryable error.
        raise ShopifyGraphQLError(
            f"Query failed after {max_retries} attempts: {last_exc}"
        )

    # ── Products ─────────────────────────────────────────────

    def get_products(self, first: int = 50, after: str = "") -> dict[str, Any]:
        """Fetch products with variants, images, and inventory."""
        cursor = f', after: "{after}"' if after else ""
        result = self.query(f"""
        {{
          products(first: {first}{cursor}) {{
            edges {{
              cursor
              node {{
                id
                title
                descriptionHtml
                vendor
                productType
                tags
                status
                createdAt
                updatedAt
                images(first: 5) {{
                  edges {{ node {{ url altText }} }}
                }}
                variants(first: 10) {{
                  edges {{
                    node {{
                      id
                      title
                      price
                      compareAtPrice
                      inventoryQuantity
                      sku
                      inventoryItem {{
                        unitCost {{ amount currencyCode }}
                      }}
                    }}
                  }}
                }}
              }}
            }}
            pageInfo {{ hasNextPage endCursor }}
          }}
        }}""")

        data = (result.get("data") or {}).get("products") or {}
        products = []
        for edge in data.get("edges", []) or []:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node") or {}
            if isinstance(node, dict):
                products.append(self._normalize_product(node))

        return {
            "products": products,
            "total": len(products),
            "has_next": data.get("pageInfo", {}).get("hasNextPage", False),
            "end_cursor": data.get("pageInfo", {}).get("endCursor", ""),
        }

    def get_all_products(self) -> list[dict[str, Any]]:
        """Fetch ALL products with pagination."""
        all_products = []
        cursor = ""
        while True:
            result = self.get_products(first=50, after=cursor)
            all_products.extend(result["products"])
            if not result["has_next"]:
                break
            cursor = result["end_cursor"]
        return all_products

    # ── Orders ───────────────────────────────────────────────

    def get_orders(self, first: int = 50, after: str = "") -> dict[str, Any]:
        cursor = f', after: "{after}"' if after else ""
        result = self.query(f"""
        {{
          orders(first: {first}{cursor}, sortKey: CREATED_AT, reverse: true) {{
            edges {{
              cursor
              node {{
                id
                name
                createdAt
                totalPriceSet {{ shopMoney {{ amount currencyCode }} }}
                subtotalPriceSet {{ shopMoney {{ amount }} }}
                displayFinancialStatus
                displayFulfillmentStatus
                lineItems(first: 20) {{
                  edges {{
                    node {{
                      title
                      quantity
                      originalUnitPriceSet {{ shopMoney {{ amount }} }}
                      variant {{ id }}
                    }}
                  }}
                }}
                customer {{ id firstName lastName email }}
              }}
            }}
            pageInfo {{ hasNextPage endCursor }}
          }}
        }}""")

        data = (result.get("data") or {}).get("orders") or {}
        orders = []
        for edge in data.get("edges", []) or []:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node") or {}
            if isinstance(node, dict):
                orders.append(self._normalize_order(node))

        return {
            "orders": orders,
            "total": len(orders),
            "has_next": data.get("pageInfo", {}).get("hasNextPage", False),
            "end_cursor": data.get("pageInfo", {}).get("endCursor", ""),
        }

    # ── Customers ────────────────────────────────────────────

    def get_customers(self, first: int = 50, after: str = "") -> dict[str, Any]:
        cursor = f', after: "{after}"' if after else ""
        result = self.query(f"""
        {{
          customers(first: {first}{cursor}) {{
            edges {{
              cursor
              node {{
                id
                firstName
                lastName
                email
                numberOfOrders
                amountSpent {{ amount currencyCode }}
                tags
                createdAt
              }}
            }}
            pageInfo {{ hasNextPage endCursor }}
          }}
        }}""")

        data = (result.get("data") or {}).get("customers") or {}
        customers = []
        for edge in data.get("edges", []) or []:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node") or {}
            if isinstance(node, dict):
                customers.append(self._normalize_customer(node))

        return {
            "customers": customers,
            "total": len(customers),
            "has_next": data.get("pageInfo", {}).get("hasNextPage", False),
        }

    # ── Store Info ───────────────────────────────────────────

    def get_store_info(self) -> dict[str, Any]:
        result = self.query("""
        {
          shop {
            name
            email
            url
            myshopifyDomain
            plan { displayName }
            currencyCode
            timezoneAbbreviation
            billingAddress { country city }
          }
        }""")
        return (result.get("data") or {}).get("shop") or {}

    # ── Product Mutations ────────────────────────────────────

    def create_product(self, title: str, description: str = "",
                       vendor: str = "", product_type: str = "",
                       tags: list[str] | None = None) -> dict[str, Any]:
        result = self.query("""
        mutation productCreate($input: ProductInput!) {
          productCreate(input: $input) {
            product { id title }
            userErrors { field message }
          }
        }""", {
            "input": {
                "title": title,
                "descriptionHtml": description,
                "vendor": vendor,
                "productType": product_type,
                "tags": tags or [],
            }
        })
        return (result.get("data") or {}).get("productCreate") or {}

    def update_product(self, product_id: str, updates: dict) -> dict[str, Any]:
        if not isinstance(updates, dict):
            updates = {}
        result = self.query("""
        mutation productUpdate($input: ProductInput!) {
          productUpdate(input: $input) {
            product { id title }
            userErrors { field message }
          }
        }""", {"input": {"id": product_id, **updates}})
        return (result.get("data") or {}).get("productUpdate") or {}

    # ── Inventory ────────────────────────────────────────────

    def get_inventory_levels(self, first: int = 50) -> list[dict]:
        result = self.query(f"""
        {{
          locations(first: 5) {{
            edges {{
              node {{
                id
                name
                inventoryLevels(first: {first}) {{
                  edges {{
                    node {{
                      id
                      quantities(names: ["available"]) {{ name quantity }}
                      item {{ id sku unitCost {{ amount }} }}
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}""")
        levels = []
        locations = ((result.get("data") or {}).get("locations") or {}).get("edges") or []
        for loc_edge in locations:
            if not isinstance(loc_edge, dict):
                continue
            loc = loc_edge.get("node") or {}
            if not isinstance(loc, dict):
                continue
            inv_edges = (loc.get("inventoryLevels") or {}).get("edges") or []
            for inv_edge in inv_edges:
                if not isinstance(inv_edge, dict):
                    continue
                inv = inv_edge.get("node") or {}
                if not isinstance(inv, dict):
                    continue
                # Pre-audit: ``inv.get("quantities", [{}])[0].get(...)``
                # — if quantities was a non-list (dict from weird
                # API shape) the ``[0]`` access crashed. Audit
                # pass 43.
                quantities = inv.get("quantities") or []
                qty = 0
                if isinstance(quantities, list) and quantities:
                    first_q = quantities[0]
                    if isinstance(first_q, dict):
                        qty = safe_int(first_q.get("quantity"))
                item = inv.get("item") or {}
                if not isinstance(item, dict):
                    item = {}
                unit_cost = item.get("unitCost") or {}
                if not isinstance(unit_cost, dict):
                    unit_cost = {}
                levels.append({
                    "location_id": loc.get("id", "") or "",
                    "location_name": loc.get("name", "") or "",
                    "inventory_item_id": item.get("id", "") or "",
                    "sku": item.get("sku", "") or "",
                    "available": qty,
                    "cost": safe_float(unit_cost.get("amount")),
                })
        return levels

    # ── Analytics ────────────────────────────────────────────

    def get_api_cost_status(self) -> dict[str, Any]:
        """Check API cost usage."""
        return {"total_cost_used": self._cost_used}

    # ── Normalizers ──────────────────────────────────────────

    @staticmethod
    def _id_tail(gid: Any) -> str:
        """Extract the trailing numeric id from a GraphQL gid.

        Shopify returns ids like ``gid://shopify/Product/12345``;
        we usually want just ``"12345"``. Pre-audit this was
        ``node.get("id", "").split("/")[-1]`` which crashed
        with AttributeError when the id was present-but-None.
        """
        if not isinstance(gid, str) or not gid:
            return ""
        return gid.split("/")[-1]

    @staticmethod
    def _normalize_product(node: dict) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        variants = []
        variant_edges = (node.get("variants") or {}).get("edges") or []
        for ve in variant_edges:
            if not isinstance(ve, dict):
                continue
            v = ve.get("node") or {}
            if not isinstance(v, dict):
                continue
            inventory_item = v.get("inventoryItem") or {}
            if not isinstance(inventory_item, dict):
                inventory_item = {}
            cost_data = inventory_item.get("unitCost") or {}
            if not isinstance(cost_data, dict):
                cost_data = {}
            variants.append({
                "id": v.get("id", "") or "",
                "price": safe_float(v.get("price")),
                "compare_at_price": safe_float(v.get("compareAtPrice")),
                "cost": safe_float(cost_data.get("amount")),
                "inventory_quantity": safe_int(v.get("inventoryQuantity")),
                "sku": v.get("sku", "") or "",
            })

        image_edges = (node.get("images") or {}).get("edges") or []
        images = []
        for ie in image_edges:
            if not isinstance(ie, dict):
                continue
            inode = ie.get("node") or {}
            if isinstance(inode, dict):
                url = inode.get("url", "") or ""
                if url:
                    images.append(url)
        first_variant = variants[0] if variants else {}

        status = node.get("status") or ""
        return {
            "id": ShopifyGraphQL._id_tail(node.get("id")),
            "graphql_id": node.get("id", "") or "",
            "name": node.get("title", "") or "",
            "description": node.get("descriptionHtml", "") or "",
            "vendor": node.get("vendor", "") or "",
            "category": node.get("productType", "") or "",
            "tags": node.get("tags") or [],
            "status": status.lower() if isinstance(status, str) else "",
            "price": first_variant.get("price", 0),
            "cost": first_variant.get("cost", 0),
            "compare_at_price": first_variant.get("compare_at_price", 0),
            "inventory_quantity": first_variant.get("inventory_quantity", 0),
            "image_url": images[0] if images else "",
            "images": images,
            "variants": variants,
            "created_at": node.get("createdAt", "") or "",
        }

    @staticmethod
    def _normalize_order(node: dict) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        # ``.get("totalPriceSet", {}).get("shopMoney", {})``
        # crashed on present-but-None values. Use ``or {}``.
        total_set = node.get("totalPriceSet") or {}
        total_data = (total_set if isinstance(total_set, dict) else {}).get("shopMoney") or {}
        if not isinstance(total_data, dict):
            total_data = {}
        subtotal_set = node.get("subtotalPriceSet") or {}
        subtotal_data = (subtotal_set if isinstance(subtotal_set, dict) else {}).get("shopMoney") or {}
        if not isinstance(subtotal_data, dict):
            subtotal_data = {}

        customer = node.get("customer") or {}
        if not isinstance(customer, dict):
            customer = {}

        line_edges = (node.get("lineItems") or {}).get("edges") or []
        items = []
        for ie in line_edges:
            if isinstance(ie, dict):
                inode = ie.get("node") or {}
                if isinstance(inode, dict):
                    items.append(inode)

        return {
            "id": ShopifyGraphQL._id_tail(node.get("id")),
            "name": node.get("name", "") or "",
            "total": safe_float(total_data.get("amount")),
            "subtotal": safe_float(subtotal_data.get("amount")),
            "status": node.get("displayFinancialStatus", "") or "",
            "fulfillment_status": node.get("displayFulfillmentStatus", "") or "",
            "items": len(items),
            "customer_id": ShopifyGraphQL._id_tail(customer.get("id")),
            "customer_email": customer.get("email", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "line_items": [
                {
                    "title": i.get("title", "") or "",
                    "quantity": safe_int(i.get("quantity")),
                    "price": safe_float(
                        ((i.get("originalUnitPriceSet") or {}).get("shopMoney") or {}).get("amount")
                    ),
                }
                for i in items
            ],
        }

    @staticmethod
    def _normalize_customer(node: dict) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        spent = node.get("amountSpent") or {}
        if not isinstance(spent, dict):
            spent = {}
        first = node.get("firstName") or ""
        last = node.get("lastName") or ""
        return {
            "id": ShopifyGraphQL._id_tail(node.get("id")),
            "name": f"{first} {last}".strip(),
            "email": node.get("email", "") or "",
            "orders": safe_int(node.get("numberOfOrders")),
            "total_spent": safe_float(spent.get("amount")),
            "tags": node.get("tags") or [],
            "created_at": node.get("createdAt", "") or "",
        }
