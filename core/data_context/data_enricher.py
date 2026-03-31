"""DataEnricher — enriches engine data with computed intelligence.

Adds computed fields that help engines make better decisions:
  - Product stats: prices, margins, percentiles, outliers, inventory health
  - Customer stats: RFM segments, churn risk, LTV distribution
  - Order stats: AOV, revenue, trend detection
  - Data quality: freshness, completeness, anomalies

Never modifies original data — only adds new underscore-prefixed fields.
"""
from __future__ import annotations

import hashlib
import math
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("data_context.enricher")


class DataEnricher:
    """Enriches data context with computed intelligence."""

    def enrich(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Enrich data based on engine type. Returns new dict, never mutates."""
        enriched = dict(data)

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

        # Data quality assessment
        enriched["_data_quality"] = self._assess_data_quality(data)

        return enriched

    @staticmethod
    def _compute_product_stats(products: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute aggregate product statistics with percentiles and outliers."""
        prices = [safe_float(p.get("price")) for p in products if isinstance(p, dict) and safe_float(p.get("price")) > 0]
        costs = [safe_float(p.get("cost")) for p in products if isinstance(p, dict) and safe_float(p.get("cost")) > 0]
        inventories = [safe_int(p.get("inventory_quantity", p.get("quantity"))) for p in products if isinstance(p, dict)]
        ratings = [safe_float(p.get("rating")) for p in products if isinstance(p, dict) and safe_float(p.get("rating")) > 0]

        stats: dict[str, Any] = {"total_products": len(products)}

        if prices:
            sorted_prices = sorted(prices)
            n = len(sorted_prices)
            stats["price_min"] = round(sorted_prices[0], 2)
            stats["price_max"] = round(sorted_prices[-1], 2)
            stats["price_avg"] = round(sum(prices) / n, 2)
            stats["price_median"] = round(sorted_prices[n // 2], 2)
            stats["price_p25"] = round(sorted_prices[max(0, n // 4)], 2)
            stats["price_p75"] = round(sorted_prices[min(n - 1, 3 * n // 4)], 2)

            # Outlier detection (IQR method)
            iqr = stats["price_p75"] - stats["price_p25"]
            lower_fence = stats["price_p25"] - 1.5 * iqr
            upper_fence = stats["price_p75"] + 1.5 * iqr
            outliers = [p for p in prices if p < lower_fence or p > upper_fence]
            stats["price_outliers"] = len(outliers)

            # Price standard deviation
            mean = stats["price_avg"]
            variance = sum((p - mean) ** 2 for p in prices) / n
            stats["price_std"] = round(math.sqrt(variance), 2)

        if costs:
            stats["cost_avg"] = round(sum(costs) / len(costs), 2)
            stats["cost_min"] = round(min(costs), 2)
            stats["cost_max"] = round(max(costs), 2)

        # Margin analysis
        margins = []
        for p in products:
            if not isinstance(p, dict):
                continue
            price = safe_float(p.get("price"))
            cost = safe_float(p.get("cost"))
            if price > 0 and cost > 0:
                margins.append((price - cost) / price * 100)

        if margins:
            sorted_margins = sorted(margins)
            n = len(sorted_margins)
            stats["margin_avg"] = round(sum(margins) / n, 2)
            stats["margin_min"] = round(sorted_margins[0], 2)
            stats["margin_max"] = round(sorted_margins[-1], 2)
            stats["margin_median"] = round(sorted_margins[n // 2], 2)
            stats["negative_margin_count"] = sum(1 for m in margins if m < 0)
            stats["high_margin_count"] = sum(1 for m in margins if m > 50)

        # Inventory health
        if inventories:
            stats["inventory_total"] = sum(inventories)
            stats["out_of_stock"] = sum(1 for i in inventories if i == 0)
            stats["low_stock"] = sum(1 for i in inventories if 0 < i <= 5)
            stats["inventory_avg"] = round(sum(inventories) / len(inventories), 1)
            if stats["out_of_stock"] > 0:
                stats["stockout_rate"] = round(stats["out_of_stock"] / len(inventories) * 100, 1)

        # Rating distribution
        if ratings:
            stats["rating_avg"] = round(sum(ratings) / len(ratings), 2)
            stats["rating_min"] = round(min(ratings), 1)
            stats["high_rated"] = sum(1 for r in ratings if r >= 4.0)
            stats["low_rated"] = sum(1 for r in ratings if r < 3.0)

        # Category distribution
        categories: dict[str, int] = {}
        for p in products:
            if not isinstance(p, dict):
                continue
            cat = p.get("category", p.get("type", "unknown"))
            if isinstance(cat, str):
                categories[cat] = categories.get(cat, 0) + 1
        stats["category_distribution"] = categories
        stats["category_count"] = len(categories)

        return stats

    @staticmethod
    def _compute_customer_stats(customers: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute customer stats with RFM segmentation and churn risk."""
        stats: dict[str, Any] = {"total_customers": len(customers)}

        order_counts = [safe_int(c.get("order_count", c.get("orders"))) for c in customers if isinstance(c, dict)]
        if order_counts:
            stats["avg_orders"] = round(sum(order_counts) / len(order_counts), 2)
            stats["max_orders"] = max(order_counts)
            stats["single_purchase_pct"] = round(sum(1 for o in order_counts if o <= 1) / len(order_counts) * 100, 1)
            stats["repeat_pct"] = round(sum(1 for o in order_counts if o > 1) / len(order_counts) * 100, 1)
            stats["vip_count"] = sum(1 for o in order_counts if o >= 5)

        # Churn risk analysis
        days_since = [safe_int(c.get("days_since_last_order", c.get("days_inactive"))) for c in customers if isinstance(c, dict)]
        days_since = [d for d in days_since if d > 0]
        if days_since:
            stats["avg_days_since_order"] = round(sum(days_since) / len(days_since), 1)
            stats["at_risk_count"] = sum(1 for d in days_since if d > 60)
            stats["churned_count"] = sum(1 for d in days_since if d > 120)
            stats["active_count"] = sum(1 for d in days_since if d <= 30)

        # Spending analysis
        spent = [safe_float(c.get("total_spent", c.get("lifetime_value", c.get("ltv")))) for c in customers if isinstance(c, dict)]
        spent = [s for s in spent if s > 0]
        if spent:
            sorted_spent = sorted(spent)
            n = len(sorted_spent)
            stats["avg_ltv"] = round(sum(spent) / n, 2)
            stats["median_ltv"] = round(sorted_spent[n // 2], 2)
            stats["ltv_p25"] = round(sorted_spent[max(0, n // 4)], 2)
            stats["ltv_p75"] = round(sorted_spent[min(n - 1, 3 * n // 4)], 2)
            stats["high_value_count"] = sum(1 for s in spent if s > sorted_spent[min(n - 1, 3 * n // 4)])

        return stats

    @staticmethod
    def _compute_order_stats(orders: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute order stats with trend detection."""
        stats: dict[str, Any] = {"total_orders": len(orders)}

        totals = [safe_float(o.get("total", o.get("amount", o.get("total_price")))) for o in orders if isinstance(o, dict)]
        totals = [t for t in totals if t > 0]

        if totals:
            sorted_totals = sorted(totals)
            n = len(sorted_totals)
            stats["aov"] = round(sum(totals) / n, 2)
            stats["revenue_total"] = round(sum(totals), 2)
            stats["order_min"] = round(sorted_totals[0], 2)
            stats["order_max"] = round(sorted_totals[-1], 2)
            stats["order_median"] = round(sorted_totals[n // 2], 2)

            # Trend detection: compare first half vs second half
            if n >= 4:
                first_half = totals[:n // 2]
                second_half = totals[n // 2:]
                avg_first = sum(first_half) / len(first_half)
                avg_second = sum(second_half) / len(second_half)
                change_pct = ((avg_second - avg_first) / max(avg_first, 0.01)) * 100

                stats["trend"] = "growing" if change_pct > 5 else "declining" if change_pct < -5 else "stable"
                stats["trend_change_pct"] = round(change_pct, 1)

            # Large order detection
            if n >= 3:
                p75 = sorted_totals[min(n - 1, 3 * n // 4)]
                stats["large_orders"] = sum(1 for t in totals if t > p75 * 1.5)

        # Status distribution
        statuses: dict[str, int] = {}
        for o in orders:
            if not isinstance(o, dict):
                continue
            s = o.get("status", "unknown")
            if isinstance(s, str):
                statuses[s] = statuses.get(s, 0) + 1
        stats["status_distribution"] = statuses

        return stats

    @staticmethod
    def _assess_data_quality(data: dict[str, Any]) -> dict[str, Any]:
        """Assess overall data quality for decision confidence."""
        total_fields = len([k for k in data if not k.startswith("_")])
        non_empty = sum(1 for k, v in data.items() if not k.startswith("_") and v is not None and v != "" and v != [])

        products = data.get("products", data.get("product_data", []))
        customers = data.get("customer_data", data.get("customers", []))
        orders = data.get("order_data", data.get("orders", []))

        # Completeness score
        completeness = round(non_empty / max(total_fields, 1) * 100, 1)

        # Volume assessment
        has_products = isinstance(products, list) and len(products) > 0
        has_customers = isinstance(customers, list) and len(customers) > 0
        has_orders = isinstance(orders, list) and len(orders) > 0

        data_sources = sum([has_products, has_customers, has_orders])

        # Quality tier
        if completeness > 80 and data_sources >= 2:
            tier = "high"
        elif completeness > 50 or data_sources >= 1:
            tier = "medium"
        else:
            tier = "low"

        return {
            "completeness_pct": completeness,
            "total_fields": total_fields,
            "data_sources": data_sources,
            "has_products": has_products,
            "has_customers": has_customers,
            "has_orders": has_orders,
            "quality_tier": tier,
            "product_count": len(products) if isinstance(products, list) else 0,
            "customer_count": len(customers) if isinstance(customers, list) else 0,
            "order_count": len(orders) if isinstance(orders, list) else 0,
        }

    @staticmethod
    def _hash_data(data: dict[str, Any]) -> str:
        content = str(sorted(data.keys()))
        return hashlib.md5(content.encode()).hexdigest()[:12]
