"""Customer Segmentation Engine — behavioral clusterer.

Clusters customers by behavior patterns: browse intensity, cart activity,
purchase timing, and channel preference. Uses rule-based clustering
derived from behavioral signals.

No external model calls — pure algorithmic clustering.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Cluster definitions
# ---------------------------------------------------------------------------

_CLUSTERS = {
    "power_buyer":      "High frequency, high spend, low cart abandonment",
    "bargain_hunter":   "Moderate frequency, high cart abandonment, price sensitive",
    "window_shopper":   "Low purchase, high browse, high cart abandonment",
    "loyal_regular":    "Consistent purchases, moderate frequency, low abandonment",
    "impulse_buyer":    "Variable frequency, quick purchase cycles, diverse categories",
    "dormant_browser":  "Low recent activity, historical engagement exists",
    "new_explorer":     "Recent first purchase, exploring categories",
    "email_engaged":    "Strong email engagement, moderate purchase activity",
}


def cluster_behaviors(
    customers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Cluster customers by behavioral patterns.

    Analyzes browse intensity (via email opens as proxy), cart behavior,
    purchase timing, and category diversity to assign behavioral clusters.

    Args:
        customers: List of normalized customer dicts.

    Returns:
        Structured dict with list of BehavioralCluster dicts.
    """
    try:
        if not customers:
            return {"status": "success", "clusters": [], "count": 0}

        custs = copy.deepcopy(customers)

        # Compute population medians for relative scoring
        medians = _compute_medians(custs)

        clusters: list[dict[str, Any]] = []
        for c in custs:
            cluster = _classify_one(c, medians)
            clusters.append(cluster)

        return {
            "status": "success",
            "clusters": clusters,
            "count": len(clusters),
        }
    except Exception as exc:
        return {
            "status": "error",
            "clusters": [],
            "count": 0,
            "error": f"Behavioral clustering failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_medians(customers: list[dict[str, Any]]) -> dict[str, float]:
    """Compute median values across the population for relative comparison."""
    def _median(vals: list[float]) -> float:
        if not vals:
            return 0.0
        s = sorted(vals)
        n = len(s)
        if n % 2 == 1:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2.0

    return {
        "orders": _median([c.get("total_orders", 0) for c in customers]),
        "spent": _median([c.get("total_spent", 0.0) for c in customers]),
        "email_opens": _median([c.get("email_opens", 0) for c in customers]),
        "cart_abandons": _median([c.get("cart_abandons", 0) for c in customers]),
        "days_since_last": _median([c.get("days_since_last", 0) for c in customers]),
        "categories": _median([len(c.get("categories_bought", [])) for c in customers]),
        "tenure_days": _median([c.get("tenure_days", 0) for c in customers]),
    }


def _classify_one(
    c: dict[str, Any],
    medians: dict[str, float],
) -> dict[str, Any]:
    """Classify a single customer into a behavioral cluster."""
    cid = c.get("id", "unknown")
    orders = c.get("total_orders", 0)
    spent = c.get("total_spent", 0.0)
    email_opens = c.get("email_opens", 0)
    cart_abandons = c.get("cart_abandons", 0)
    days_since = c.get("days_since_last", 0)
    categories = c.get("categories_bought", [])
    tenure = c.get("tenure_days", 0)

    # Relative signals
    high_orders = orders > medians["orders"] * 1.3
    high_spend = spent > medians["spent"] * 1.3
    high_email = email_opens > medians["email_opens"] * 1.3
    high_abandons = cart_abandons > medians["cart_abandons"] * 1.3
    low_orders = orders <= max(medians["orders"] * 0.5, 1)
    diverse_categories = len(categories) > max(medians["categories"] * 1.2, 2)
    recent = days_since <= 30
    dormant = days_since > 90
    new_customer = tenure <= 60

    # Browse intensity
    if high_email and high_abandons:
        browse_intensity = "high"
    elif high_email or high_abandons:
        browse_intensity = "medium"
    else:
        browse_intensity = "low"

    # Cart behavior
    if cart_abandons == 0:
        cart_behavior = "decisive"
    elif high_abandons and not high_orders:
        cart_behavior = "abandoner"
    elif high_abandons and high_orders:
        cart_behavior = "comparison_shopper"
    else:
        cart_behavior = "normal"

    # Purchase timing
    if orders == 0:
        purchase_timing = "none"
    elif tenure > 0 and orders > 0:
        avg_gap = tenure / orders
        if avg_gap <= 14:
            purchase_timing = "frequent"
        elif avg_gap <= 45:
            purchase_timing = "regular"
        elif avg_gap <= 90:
            purchase_timing = "occasional"
        else:
            purchase_timing = "rare"
    else:
        purchase_timing = "single"

    # Channel preference (inferred from email engagement)
    if high_email:
        channel_preference = "email"
    elif email_opens == 0 and orders > 0:
        channel_preference = "direct"
    else:
        channel_preference = "mixed"

    # Cluster assignment — ordered from most specific to fallback
    if high_orders and high_spend and not high_abandons:
        cluster = "power_buyer"
    elif new_customer and recent:
        cluster = "new_explorer"
    elif high_abandons and low_orders:
        cluster = "window_shopper"
    elif high_abandons and not low_orders:
        cluster = "bargain_hunter"
    elif high_email and not high_orders:
        cluster = "email_engaged"
    elif diverse_categories and recent:
        cluster = "impulse_buyer"
    elif dormant:
        cluster = "dormant_browser"
    elif orders > 0:
        cluster = "loyal_regular"
    else:
        cluster = "window_shopper"

    return {
        "customer_id": cid,
        "cluster": cluster,
        "browse_intensity": browse_intensity,
        "cart_behavior": cart_behavior,
        "purchase_timing": purchase_timing,
        "channel_preference": channel_preference,
    }
