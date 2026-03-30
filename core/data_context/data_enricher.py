"""DataEnricher — enriches engine data with computed intelligence.

Adds computed fields that help engines make better decisions.
Never modifies original data — only adds new fields.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("data_context.enricher")


class DataEnricher:
    """Enriches data context with computed intelligence."""

    def enrich(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Enrich data based on engine type. Returns new dict, never mutates."""
        enriched = dict(data)

        # Universal enrichments
        enriched["_enrichment"] = {
            "timestamp": time.time(),
            "engine": engine_name,
            "data_hash": self._hash_data(data),
        }

        # Product enrichments
        products = data.get("products", data.get("product_data", []))
        if isinstance(products, list) and products:
            enriched["_product_stats"] = self._compute_product_stats(products)
        elif isinstance(products, dict):
            enriched["_product_stats"] = self._compute_product_stats([products])

        # Customer enrichments
        customers = data.get("customer_data", data.get("customers", []))
        if isinstance(customers, list) and customers:
            enriched["_customer_stats"] = self._compute_customer_stats(customers)

        # Order enrichments
        orders = data.get("order_data", data.get("orders", []))
        if isinstance(orders, list) and orders:
            enriched["_order_stats"] = self._compute_order_stats(orders)

        return enriched

    @staticmethod
    def _compute_product_stats(products: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute aggregate product statistics."""
        prices = [float(p.get("price", 0)) for p in products if p.get("price")]
        costs = [float(p.get("cost", 0)) for p in products if p.get("cost")]

        stats: dict[str, Any] = {
            "total_products": len(products),
        }

        if prices:
            stats["price_min"] = round(min(prices), 2)
            stats["price_max"] = round(max(prices), 2)
            stats["price_avg"] = round(sum(prices) / len(prices), 2)
            stats["price_median"] = round(sorted(prices)[len(prices) // 2], 2)

        if costs:
            stats["cost_avg"] = round(sum(costs) / len(costs), 2)

        if prices and costs and len(prices) == len(costs):
            margins = [(p - c) / p * 100 for p, c in zip(prices, costs) if p > 0]
            if margins:
                stats["margin_avg"] = round(sum(margins) / len(margins), 2)
                stats["margin_min"] = round(min(margins), 2)
                stats["margin_max"] = round(max(margins), 2)

        # Category distribution
        categories: dict[str, int] = {}
        for p in products:
            cat = p.get("category", p.get("type", "unknown"))
            if isinstance(cat, str):
                categories[cat] = categories.get(cat, 0) + 1
        stats["category_distribution"] = categories

        return stats

    @staticmethod
    def _compute_customer_stats(customers: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute aggregate customer statistics."""
        stats: dict[str, Any] = {"total_customers": len(customers)}

        order_counts = [int(c.get("order_count", c.get("orders", 0))) for c in customers]
        if order_counts:
            stats["avg_orders"] = round(sum(order_counts) / len(order_counts), 2)
            stats["max_orders"] = max(order_counts)
            stats["single_purchase_pct"] = round(sum(1 for o in order_counts if o <= 1) / len(order_counts) * 100, 1)

        ltv_values = [float(c.get("ltv", c.get("lifetime_value", 0))) for c in customers if c.get("ltv") or c.get("lifetime_value")]
        if ltv_values:
            stats["avg_ltv"] = round(sum(ltv_values) / len(ltv_values), 2)
            stats["median_ltv"] = round(sorted(ltv_values)[len(ltv_values) // 2], 2)

        return stats

    @staticmethod
    def _compute_order_stats(orders: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute aggregate order statistics."""
        stats: dict[str, Any] = {"total_orders": len(orders)}

        totals = [float(o.get("total", o.get("amount", 0))) for o in orders if o.get("total") or o.get("amount")]
        if totals:
            stats["aov"] = round(sum(totals) / len(totals), 2)
            stats["revenue_total"] = round(sum(totals), 2)
            stats["order_min"] = round(min(totals), 2)
            stats["order_max"] = round(max(totals), 2)

        statuses: dict[str, int] = {}
        for o in orders:
            s = o.get("status", "unknown")
            if isinstance(s, str):
                statuses[s] = statuses.get(s, 0) + 1
        stats["status_distribution"] = statuses

        return stats

    @staticmethod
    def _hash_data(data: dict[str, Any]) -> str:
        """Hash data for deduplication and tracking."""
        content = str(sorted(data.keys()))
        return hashlib.md5(content.encode()).hexdigest()[:12]
