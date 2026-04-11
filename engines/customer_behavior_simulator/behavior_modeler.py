"""Customer Behavior Simulator Engine — behavior modeler.

Models customer behavior patterns from customer and historical data.
"""
from __future__ import annotations

import copy
from typing import Any


def model_customer_behavior(
    customers: list[dict[str, Any]],
    historical_data: dict[str, Any],
) -> dict[str, Any]:
    """Model customer behavior patterns by segment."""
    try:
        customers = copy.deepcopy(customers)

        # Group customers by segment
        segments: dict[str, list[dict[str, Any]]] = {}
        for cust in customers:
            seg = str(cust.get("segment", "general"))
            segments.setdefault(seg, []).append(cust)

        patterns: list[dict[str, Any]] = []
        for seg_name, seg_customers in segments.items():
            n = len(seg_customers)
            avg_frequency = round(sum(float(c.get("order_frequency", 1)) for c in seg_customers) / n, 2)
            avg_aov = round(sum(float(c.get("avg_order_value", 50)) for c in seg_customers) / n, 2)
            churn_rate = round(sum(1 for c in seg_customers if c.get("churned", False)) / max(n, 1), 3)
            avg_ltv = round(avg_aov * avg_frequency * 12 * (1 - churn_rate), 2)

            engagement_scores = [float(c.get("engagement_score", 0.5)) for c in seg_customers]
            avg_engagement = round(sum(engagement_scores) / n, 2)

            patterns.append({
                "segment": seg_name,
                "customer_count": n,
                "avg_order_frequency": avg_frequency,
                "avg_order_value": avg_aov,
                "churn_rate": churn_rate,
                "ltv": avg_ltv,
                "engagement_score": avg_engagement,
            })

        return {"status": "success", "patterns": patterns}
    except Exception as exc:
        return {"status": "error", "patterns": [], "error": f"Behavior modeling failed: {exc}"}
