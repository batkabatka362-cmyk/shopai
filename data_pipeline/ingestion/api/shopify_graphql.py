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
import urllib.request
from typing import Any

from utils.logger import get_logger

logger = get_logger("shopify.graphql")

_API_VERSION = "2024-01"


class ShopifyGraphQL:
    """Shopify GraphQL Admin API client."""

    def __init__(self, shop_url: str, access_token: str) -> None:
        self._shop = shop_url.rstrip("/")
        self._token = access_token
        self._url = f"https://{self._shop}/admin/api/{_API_VERSION}/graphql.json"
        self._cost_used = 0

    # ── Core Query ───────────────────────────────────────────

    def query(self, graphql: str, variables: dict | None = None) -> dict[str, Any]:
        """Execute a GraphQL query."""
        payload = json.dumps({
            "query": graphql,
            "variables": variables or {},
        }).encode()

        req = urllib.request.Request(
            self._url, data=payload,
            headers={
                "X-Shopify-Access-Token": self._token,
                "Content-Type": "application/json",
            },
        )

        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        elapsed = time.monotonic() - start

        # Track cost
        cost = data.get("extensions", {}).get("cost", {})
        self._cost_used += cost.get("actualQueryCost", 0)

        if data.get("errors"):
            logger.warning("GraphQL errors: %s", data["errors"])

        logger.debug("GraphQL query %.2fs (cost: %s)", elapsed,
                     cost.get("actualQueryCost", "?"))
        return data

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

        data = result.get("data", {}).get("products", {})
        products = []
        for edge in data.get("edges", []):
            node = edge.get("node", {})
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

        data = result.get("data", {}).get("orders", {})
        orders = []
        for edge in data.get("edges", []):
            node = edge.get("node", {})
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

        data = result.get("data", {}).get("customers", {})
        customers = []
        for edge in data.get("edges", []):
            node = edge.get("node", {})
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
        return result.get("data", {}).get("shop", {})

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
        return result.get("data", {}).get("productCreate", {})

    def update_product(self, product_id: str, updates: dict) -> dict[str, Any]:
        result = self.query("""
        mutation productUpdate($input: ProductInput!) {
          productUpdate(input: $input) {
            product { id title }
            userErrors { field message }
          }
        }""", {"input": {"id": product_id, **updates}})
        return result.get("data", {}).get("productUpdate", {})

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
        for loc_edge in result.get("data", {}).get("locations", {}).get("edges", []):
            loc = loc_edge.get("node", {})
            for inv_edge in loc.get("inventoryLevels", {}).get("edges", []):
                inv = inv_edge.get("node", {})
                qty = inv.get("quantities", [{}])[0].get("quantity", 0) if inv.get("quantities") else 0
                item = inv.get("item", {})
                levels.append({
                    "location_id": loc.get("id", ""),
                    "location_name": loc.get("name", ""),
                    "inventory_item_id": item.get("id", ""),
                    "sku": item.get("sku", ""),
                    "available": qty,
                    "cost": float(item.get("unitCost", {}).get("amount", 0) or 0),
                })
        return levels

    # ── Analytics ────────────────────────────────────────────

    def get_api_cost_status(self) -> dict[str, Any]:
        """Check API cost usage."""
        return {"total_cost_used": self._cost_used}

    # ── Normalizers ──────────────────────────────────────────

    @staticmethod
    def _normalize_product(node: dict) -> dict[str, Any]:
        variants = []
        for ve in node.get("variants", {}).get("edges", []):
            v = ve.get("node", {})
            cost_data = v.get("inventoryItem", {}).get("unitCost", {})
            variants.append({
                "id": v.get("id", ""),
                "price": float(v.get("price", 0) or 0),
                "compare_at_price": float(v.get("compareAtPrice", 0) or 0),
                "cost": float(cost_data.get("amount", 0) or 0),
                "inventory_quantity": int(v.get("inventoryQuantity", 0) or 0),
                "sku": v.get("sku", ""),
            })

        images = [ie.get("node", {}).get("url", "") for ie in node.get("images", {}).get("edges", [])]
        first_variant = variants[0] if variants else {}

        return {
            "id": node.get("id", "").split("/")[-1],
            "graphql_id": node.get("id", ""),
            "name": node.get("title", ""),
            "description": node.get("descriptionHtml", ""),
            "vendor": node.get("vendor", ""),
            "category": node.get("productType", ""),
            "tags": node.get("tags", []),
            "status": node.get("status", "").lower(),
            "price": first_variant.get("price", 0),
            "cost": first_variant.get("cost", 0),
            "compare_at_price": first_variant.get("compare_at_price", 0),
            "inventory_quantity": first_variant.get("inventory_quantity", 0),
            "image_url": images[0] if images else "",
            "images": images,
            "variants": variants,
            "created_at": node.get("createdAt", ""),
        }

    @staticmethod
    def _normalize_order(node: dict) -> dict[str, Any]:
        total_data = node.get("totalPriceSet", {}).get("shopMoney", {})
        subtotal_data = node.get("subtotalPriceSet", {}).get("shopMoney", {})
        customer = node.get("customer", {})
        items = [ie.get("node", {}) for ie in node.get("lineItems", {}).get("edges", [])]

        return {
            "id": node.get("id", "").split("/")[-1],
            "name": node.get("name", ""),
            "total": float(total_data.get("amount", 0) or 0),
            "subtotal": float(subtotal_data.get("amount", 0) or 0),
            "status": node.get("displayFinancialStatus", ""),
            "fulfillment_status": node.get("displayFulfillmentStatus", ""),
            "items": len(items),
            "customer_id": (customer.get("id", "").split("/")[-1]) if customer else "",
            "customer_email": customer.get("email", "") if customer else "",
            "created_at": node.get("createdAt", ""),
            "line_items": [{
                "title": i.get("title", ""),
                "quantity": i.get("quantity", 0),
                "price": float(i.get("originalUnitPriceSet", {}).get("shopMoney", {}).get("amount", 0) or 0),
            } for i in items],
        }

    @staticmethod
    def _normalize_customer(node: dict) -> dict[str, Any]:
        spent = node.get("amountSpent", {})
        return {
            "id": node.get("id", "").split("/")[-1],
            "name": f"{node.get('firstName', '')} {node.get('lastName', '')}".strip(),
            "email": node.get("email", ""),
            "orders": int(node.get("numberOfOrders", 0) or 0),
            "total_spent": float(spent.get("amount", 0) or 0),
            "tags": node.get("tags", []),
            "created_at": node.get("createdAt", ""),
        }
