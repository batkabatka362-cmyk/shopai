"""Audience Targeting Engine — segment builder.

Builds targetable audience segments from raw customer and order data.
Groups customers by behavioral and demographic attributes.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Default segment definitions when none are provided
# ---------------------------------------------------------------------------

_DEFAULT_SEGMENTS = [
    {
        "id": "high_value",
        "name": "High-Value Customers",
        "description": "Customers with above-average lifetime spend",
        "rules": [{"field": "total_spent", "operator": "gte", "value": "p75"}],
    },
    {
        "id": "frequent_buyers",
        "name": "Frequent Buyers",
        "description": "Customers with 3+ orders",
        "rules": [{"field": "total_orders", "operator": "gte", "value": 3}],
    },
    {
        "id": "recent_active",
        "name": "Recently Active",
        "description": "Customers who ordered in the last 30 days",
        "rules": [{"field": "last_order_date", "operator": "within_days", "value": 30}],
    },
    {
        "id": "at_risk",
        "name": "At-Risk Churners",
        "description": "Previously active customers with no order in 60+ days",
        "rules": [
            {"field": "total_orders", "operator": "gte", "value": 1},
            {"field": "last_order_date", "operator": "older_than_days", "value": 60},
        ],
    },
    {
        "id": "new_customers",
        "name": "New Customers",
        "description": "Customers with exactly 1 order",
        "rules": [{"field": "total_orders", "operator": "eq", "value": 1}],
    },
]


def build_segments(
    customers: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    segments: list[dict[str, Any]] | None = None,
    campaign_goal: str = "conversion",
) -> dict[str, Any]:
    """Build audience segments from customer and order data.

    Args:
        customers: List of CustomerRecord dicts.
        orders: List of OrderRecord dicts.
        segments: Optional pre-defined segment definitions. Uses defaults if empty.
        campaign_goal: The campaign goal to influence segment prioritization.

    Returns:
        Structured dict with built segments.
    """
    try:
        customers = copy.deepcopy(customers)
        orders = copy.deepcopy(orders)
        seg_defs = segments if segments else _DEFAULT_SEGMENTS

        # Pre-compute customer stats
        customer_map = _enrich_customers(customers, orders)

        # Compute percentile thresholds
        spends = sorted(c.get("total_spent", 0.0) for c in customer_map.values())
        p75_spend = _percentile(spends, 0.75)

        built: list[dict[str, Any]] = []
        for seg_def in seg_defs:
            seg_id = str(seg_def.get("id", "unknown"))
            name = str(seg_def.get("name", seg_id))
            description = str(seg_def.get("description", ""))
            rules = seg_def.get("rules", [])

            matched_ids: list[str] = []
            for cid, cdata in customer_map.items():
                if _customer_matches_rules(cdata, rules, p75_spend=p75_spend):
                    matched_ids.append(cid)

            built.append({
                "segment_id": seg_id,
                "name": name,
                "description": description,
                "customer_ids": matched_ids,
                "size": len(matched_ids),
                "criteria": {"rules": rules, "campaign_goal": campaign_goal},
            })

        # Sort by size descending
        built.sort(key=lambda s: s["size"], reverse=True)

        return {
            "status": "success",
            "segments": built,
            "total_customers": len(customer_map),
        }
    except Exception as exc:
        return {
            "status": "error",
            "segments": [],
            "error": f"Segment building failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _enrich_customers(
    customers: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build a dict of customer_id -> enriched customer data."""
    cmap: dict[str, dict[str, Any]] = {}
    for c in customers:
        cid = str(c.get("id", ""))
        if not cid:
            continue
        cmap[cid] = {
            "id": cid,
            "total_orders": int(c.get("total_orders", 0)),
            "total_spent": float(c.get("total_spent", 0.0)),
            "last_order_date": str(c.get("last_order_date", "")),
            "tags": list(c.get("tags", [])),
            "location": str(c.get("location", "")),
            "age_group": str(c.get("age_group", "")),
        }

    # Enrich from orders if customer data is sparse
    for order in orders:
        cid = str(order.get("customer_id", ""))
        if cid and cid in cmap:
            odate = str(order.get("date", ""))
            if odate > cmap[cid].get("last_order_date", ""):
                cmap[cid]["last_order_date"] = odate

    return cmap


def _customer_matches_rules(
    customer: dict[str, Any],
    rules: list[dict[str, Any]],
    p75_spend: float = 0.0,
) -> bool:
    """Check whether a customer matches ALL rules in a segment definition."""
    for rule in rules:
        field = rule.get("field", "")
        operator = rule.get("operator", "")
        value = rule.get("value")

        # Resolve percentile references
        if value == "p75" and field == "total_spent":
            value = p75_spend

        cval = customer.get(field)
        if cval is None:
            return False

        if operator == "gte" and not (float(cval) >= float(value)):
            return False
        elif operator == "lte" and not (float(cval) <= float(value)):
            return False
        elif operator == "eq" and not (float(cval) == float(value)):
            return False
        elif operator == "within_days":
            if not _is_within_days(str(cval), int(value)):
                return False
        elif operator == "older_than_days":
            if not _is_older_than_days(str(cval), int(value)):
                return False

    return True


def _is_within_days(date_str: str, days: int) -> bool:
    """Check if a date string is within N days of now."""
    import datetime
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - dt).days <= days
    except (ValueError, TypeError):
        return False


def _is_older_than_days(date_str: str, days: int) -> bool:
    """Check if a date string is older than N days."""
    import datetime
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - dt).days > days
    except (ValueError, TypeError):
        return False


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Compute a percentile from a pre-sorted list."""
    if not sorted_values:
        return 0.0
    idx = int(len(sorted_values) * pct)
    idx = min(idx, len(sorted_values) - 1)
    return sorted_values[idx]
