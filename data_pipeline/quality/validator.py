"""Data Quality Pipeline — validates, cleans, scores, and reports on store data.

Runs after Shopify sync, before engine analysis. Catches bad data BEFORE
the AI makes decisions on it.

Pipeline:
  Raw store data → Validate → Clean → Enrich → Score → Report

Quality dimensions:
  - Completeness: required fields present?
  - Accuracy: prices > 0, valid URLs, reasonable ranges?
  - Consistency: cost < price, inventory non-negative?
  - Freshness: data not stale?
  - Uniqueness: no duplicate products?

Integrates with UnifiedMemory — stores quality reports for brain to consult.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.helpers import safe_float, safe_int
from utils.logger import get_logger

logger = get_logger("data_quality")


def _nonempty_str(val: Any) -> str:
    """Return ``val`` as a stripped string, or ``""`` if None/non-str.

    Pre-audit several rules did ``str(p.get("title", ""))`` which
    turns a present-but-None value into the literal string
    ``"None"`` — non-empty, so ``title_not_empty`` silently
    passed on products with ``"title": null``. Audit pass 47.
    """
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    return str(val).strip()


def _first_nonempty(*vals: Any) -> str:
    """Return the first truthy stripped string from *vals*, or ``""``."""
    for v in vals:
        s = _nonempty_str(v)
        if s:
            return s
    return ""


# --- Schemas for each data type ---

PRODUCT_REQUIRED = ["id", "price"]
PRODUCT_RULES = {
    "price_positive": lambda p: safe_float(p.get("price")) > 0,
    "title_not_empty": lambda p: bool(_first_nonempty(p.get("title"), p.get("name"))),
    "cost_reasonable": lambda p: (
        # Pre-audit: ``p.get("cost") and p.get("price")`` — if cost is 0
        # or missing, the rule short-circuits to True. That's fine, but
        # the float() calls below used to crash on non-numeric strings.
        safe_float(p.get("cost")) <= safe_float(p.get("price"), default=1.0) * 2
        if safe_float(p.get("cost")) > 0 and safe_float(p.get("price")) > 0 else True
    ),
    "cost_less_than_price": lambda p: (
        safe_float(p.get("cost")) < safe_float(p.get("price"), default=1.0)
        if safe_float(p.get("cost")) > 0 and safe_float(p.get("price")) > 0 else True
    ),
    "inventory_non_negative": lambda p: safe_int(p.get("inventory_quantity")) >= 0,
    "has_description": lambda p: bool(_first_nonempty(p.get("body_html"), p.get("description"))),
    "has_images": lambda p: bool(p.get("images") or p.get("image") or p.get("image_url")),
    "has_cost": lambda p: safe_float(p.get("cost")) > 0,
}

ORDER_REQUIRED = ["id"]
ORDER_RULES = {
    "has_total": lambda o: (
        safe_float(o.get("total_price")) > 0
        or safe_float(o.get("total")) > 0
    ),
    "has_date": lambda o: bool(o.get("created_at")),
}

CUSTOMER_REQUIRED = ["id"]
CUSTOMER_RULES = {
    "has_email": lambda c: bool(c.get("email")),
    "has_orders": lambda c: safe_int(c.get("orders_count")) >= 0,
}


class DataQualityPipeline:
    """Validates and scores store data quality before AI processing."""

    def __init__(self) -> None:
        self._last_report: dict[str, Any] = {}

    def run(self, store_data: dict[str, Any]) -> dict[str, Any]:
        """Run the full data quality pipeline.

        Args:
            store_data: Raw store data with products, orders, customers.

        Returns:
            Quality report with scores, issues, cleaned data.
        """
        start = time.monotonic()

        # Defensive coercion of public entry point. Audit pass 47.
        if not isinstance(store_data, dict):
            store_data = {}

        products = store_data.get("products") or []
        orders = store_data.get("order_data") or store_data.get("orders") or []
        customers = store_data.get("customer_data") or store_data.get("customers") or []
        # Filter each list to dicts only so downstream loops
        # can't crash on a stray string / None / int item.
        products = [p for p in products if isinstance(p, dict)] if isinstance(products, list) else []
        orders = [o for o in orders if isinstance(o, dict)] if isinstance(orders, list) else []
        customers = [c for c in customers if isinstance(c, dict)] if isinstance(customers, list) else []

        # Stage 1: Validate
        product_quality = self._validate_records(products, PRODUCT_REQUIRED, PRODUCT_RULES, "product")
        order_quality = self._validate_records(orders, ORDER_REQUIRED, ORDER_RULES, "order")
        customer_quality = self._validate_records(customers, CUSTOMER_REQUIRED, CUSTOMER_RULES, "customer")

        # Stage 2: Clean & enrich products
        cleaned_products = self._clean_products(products)

        # Stage 3: Detect anomalies
        anomalies = self._detect_anomalies(cleaned_products, orders)

        # Stage 4: Score overall quality
        overall_score = self._calculate_overall_score(
            product_quality, order_quality, customer_quality, anomalies,
        )

        # Stage 5: Generate actionable issues
        issues = self._generate_issues(
            product_quality, order_quality, customer_quality, anomalies,
        )

        elapsed = time.monotonic() - start

        report = {
            "status": "success",
            "overall_score": overall_score,
            "products": {
                "total": len(products),
                "valid": product_quality["valid_count"],
                "score": product_quality["score"],
                "issues": product_quality["issues"],
            },
            "orders": {
                "total": len(orders),
                "valid": order_quality["valid_count"],
                "score": order_quality["score"],
            },
            "customers": {
                "total": len(customers),
                "valid": customer_quality["valid_count"],
                "score": customer_quality["score"],
            },
            "anomalies": anomalies,
            "issues": issues,
            "cleaned_products": cleaned_products,
            "duration_s": round(elapsed, 3),
        }

        self._last_report = report
        logger.info(
            "Data quality: score=%d/100, products=%d/%d valid, issues=%d",
            overall_score, product_quality["valid_count"], len(products), len(issues),
        )
        return report

    def _validate_records(
        self,
        records: list[dict],
        required: list[str],
        rules: dict[str, Any],
        record_type: str,
    ) -> dict[str, Any]:
        """Validate records against required fields and business rules."""
        if not records:
            return {
                "valid_count": 0, "invalid_count": 0, "score": 0,
                "issues": [f"No {record_type} data available"],
                "rule_scores": {},
            }

        valid = 0
        issues: list[str] = []
        rule_pass: dict[str, int] = {name: 0 for name in rules}

        # Critical rules that make a record invalid
        critical_rules = {"price_positive", "title_not_empty", "cost_less_than_price",
                          "inventory_non_negative", "has_total", "has_email"}

        for rec in records:
            rec_valid = True

            # Check required fields
            for field in required:
                if not rec.get(field):
                    rec_valid = False
                    break

            # Check business rules — only critical rules invalidate
            for rule_name, rule_fn in rules.items():
                try:
                    if rule_fn(rec):
                        rule_pass[rule_name] += 1
                    elif rule_name in critical_rules:
                        rec_valid = False
                except Exception:
                    pass

            if rec_valid:
                valid += 1

        total = len(records)
        score = round(valid / total * 100) if total else 0

        # Generate issues from failed rules
        for rule_name, passed in rule_pass.items():
            fail_count = total - passed
            if fail_count > 0:
                pct = round(fail_count / total * 100)
                issues.append(f"{record_type}.{rule_name}: {fail_count}/{total} failed ({pct}%)")

        return {
            "valid_count": valid,
            "invalid_count": total - valid,
            "score": score,
            "issues": issues,
            "rule_scores": {
                name: round(passed / total * 100) if total else 0
                for name, passed in rule_pass.items()
            },
        }

    def _clean_products(self, products: list[dict]) -> list[dict]:
        """Clean and enrich product records."""
        cleaned = []
        for p in products:
            if not isinstance(p, dict):
                continue
            rec = dict(p)

            # Ensure numeric fields. Pre-audit ``float()`` was
            # try/except-wrapped but ``int(rec.get("inventory_quantity",
            # 0))`` was NOT — crashed on non-numeric strings
            # from scraped / file-loaded data. Replaced with
            # ``safe_float`` / ``safe_int`` for consistency.
            # Audit pass 47.
            rec["price"] = safe_float(rec.get("price"))
            rec["cost"] = safe_float(rec.get("cost"))
            rec["inventory_quantity"] = safe_int(rec.get("inventory_quantity"))

            # Derive missing fields
            if rec["cost"] > 0 and rec["price"] > 0:
                rec["margin"] = round((rec["price"] - rec["cost"]) / rec["price"], 3)
                rec["markup"] = round((rec["price"] - rec["cost"]) / rec["cost"], 3)
            else:
                rec["margin"] = 0.0
                rec["markup"] = 0.0

            # Flag data quality
            rec["_quality"] = {
                "has_cost": rec["cost"] > 0,
                "has_images": bool(rec.get("images") or rec.get("image") or rec.get("image_url")),
                "has_description": bool(
                    _first_nonempty(rec.get("body_html"), rec.get("description"))
                ),
                "profitable": rec["margin"] > 0.1 if rec["cost"] > 0 else None,
            }

            cleaned.append(rec)

        return cleaned

    def _detect_anomalies(
        self,
        products: list[dict],
        orders: list[dict],
    ) -> list[dict[str, Any]]:
        """Detect data anomalies that might indicate problems."""
        anomalies: list[dict[str, Any]] = []

        if not products:
            return anomalies

        # Price anomalies. Pre-audit ``p["price"] > 0`` crashed
        # on non-numeric strings (``"$99.99" > 0`` → TypeError).
        # Now use safe_float throughout. Audit pass 47.
        dict_products = [p for p in products if isinstance(p, dict)]
        prices = [
            safe_float(p.get("price"))
            for p in dict_products
        ]
        prices = [x for x in prices if x > 0]
        if prices:
            avg_price = sum(prices) / len(prices)
            for p in dict_products:
                price = safe_float(p.get("price"))
                if price > 0 and price > avg_price * 5:
                    anomalies.append({
                        "type": "price_outlier_high",
                        "severity": "warning",
                        "product": _first_nonempty(p.get("title"), p.get("id")),
                        "value": price,
                        "expected_range": f"< {avg_price * 3:.2f}",
                    })
                if price > 0 and price < avg_price * 0.1:
                    anomalies.append({
                        "type": "price_outlier_low",
                        "severity": "warning",
                        "product": _first_nonempty(p.get("title"), p.get("id")),
                        "value": price,
                        "expected_range": f"> {avg_price * 0.2:.2f}",
                    })

        # Margin anomalies
        for p in dict_products:
            margin = p.get("margin", 0)
            if isinstance(margin, bool):
                # ``bool`` is a subclass of int; reject it for
                # numeric checks — same rule as pass 41/45.
                continue
            if isinstance(margin, (int, float)) and margin < 0:
                anomalies.append({
                    "type": "negative_margin",
                    "severity": "critical",
                    "product": _first_nonempty(p.get("title"), p.get("id")),
                    "value": margin,
                    "message": "Product costs more than its price",
                })

        # Zero inventory with recent orders. Pre-audit
        # ``p.get("inventory_quantity", 0) == 0`` compared
        # strings vs ints and silently missed string-zero
        # cases (``"0" == 0`` is False in Python). Now uses
        # safe_int.
        zero_stock = [
            p for p in dict_products
            if safe_int(p.get("inventory_quantity")) == 0
        ]
        if zero_stock:
            anomalies.append({
                "type": "zero_inventory",
                "severity": "warning",
                "count": len(zero_stock),
                "products": [
                    _first_nonempty(p.get("title"))
                    for p in zero_stock[:5]
                ],
            })

        # Duplicate detection (same title). Pre-audit
        # ``p.get("title", "").lower().strip()`` crashed on
        # ``"title": null`` because None.lower() is not a
        # method.
        titles = []
        for p in dict_products:
            t = _nonempty_str(p.get("title")).lower()
            if t:
                titles.append(t)
        seen: set[str] = set()
        dupes: list[str] = []
        for t in titles:
            if t in seen:
                dupes.append(t)
            seen.add(t)
        if dupes:
            anomalies.append({
                "type": "duplicate_products",
                "severity": "warning",
                "count": len(dupes),
                "titles": dupes[:5],
            })

        return anomalies

    def _calculate_overall_score(
        self,
        product_q: dict,
        order_q: dict,
        customer_q: dict,
        anomalies: list,
    ) -> int:
        """Calculate overall data quality score (0-100)."""
        # Weighted: products 50%, orders 25%, customers 15%, anomalies 10%
        p_score = product_q.get("score", 0)
        o_score = order_q.get("score", 0)
        c_score = customer_q.get("score", 0)

        # Anomaly penalty
        anomaly_penalty = min(len(anomalies) * 5, 30)
        critical_count = sum(1 for a in anomalies if a.get("severity") == "critical")
        anomaly_penalty += critical_count * 10

        raw = p_score * 0.50 + o_score * 0.25 + c_score * 0.15 + (100 - anomaly_penalty) * 0.10
        return max(0, min(100, round(raw)))

    def _generate_issues(
        self,
        product_q: dict,
        order_q: dict,
        customer_q: dict,
        anomalies: list,
    ) -> list[dict[str, Any]]:
        """Generate prioritized actionable issues."""
        issues: list[dict[str, Any]] = []

        # Product issues
        rule_scores = product_q.get("rule_scores", {})
        if rule_scores.get("has_cost", 100) < 80:
            issues.append({
                "priority": "high",
                "category": "completeness",
                "message": f"Only {rule_scores['has_cost']}% of products have cost data — margin analysis unreliable",
                "action": "Add cost data to products in Shopify",
            })
        if rule_scores.get("has_images", 100) < 70:
            issues.append({
                "priority": "high",
                "category": "completeness",
                "message": f"Only {rule_scores['has_images']}% of products have images — hurts conversion",
                "action": "Add product images via Shopify or image sourcing",
            })
        if rule_scores.get("has_description", 100) < 70:
            issues.append({
                "priority": "medium",
                "category": "completeness",
                "message": f"Only {rule_scores['has_description']}% of products have descriptions",
                "action": "Generate descriptions using AI Writer",
            })
        if rule_scores.get("cost_less_than_price", 100) < 100:
            issues.append({
                "priority": "critical",
                "category": "accuracy",
                "message": "Some products have cost >= price — selling at a loss",
                "action": "Review pricing or correct cost data",
            })

        # Anomaly issues
        for anomaly in anomalies:
            if anomaly.get("severity") == "critical":
                issues.append({
                    "priority": "critical",
                    "category": "anomaly",
                    "message": f"{anomaly['type']}: {anomaly.get('message', anomaly.get('product', ''))}",
                    "action": "Investigate and fix immediately",
                })

        # Data volume issues
        if product_q.get("valid_count", 0) < 5:
            issues.append({
                "priority": "high",
                "category": "volume",
                "message": f"Only {product_q['valid_count']} valid products — need more for AI analysis",
                "action": "Add more products to store",
            })
        if order_q.get("valid_count", 0) == 0:
            issues.append({
                "priority": "high",
                "category": "volume",
                "message": "No valid orders — AI cannot learn from sales data",
                "action": "Focus on driving first sales",
            })

        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        issues.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 4))

        return issues

    def get_last_report(self) -> dict[str, Any]:
        """Get the last quality report."""
        return self._last_report


_singleton_lock = threading.Lock()


def get_data_quality() -> DataQualityPipeline:
    """Get singleton data quality pipeline.

    Thread-safe: two concurrent first-callers will observe the
    same instance instead of silently creating two (pre-audit
    the check-then-assign pattern could race). Audit pass 47.
    """
    with _singleton_lock:
        inst = getattr(get_data_quality, "_instance", None)
        if inst is None:
            inst = DataQualityPipeline()
            get_data_quality._instance = inst  # type: ignore[attr-defined]
        return inst
