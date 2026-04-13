"""Customer Journey Engine — optimization advisor.

Advises journey optimizations based on stage metrics and drop-off analysis.
Generates actionable recommendations prioritized by potential impact.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Optimization templates per drop-off transition
# ---------------------------------------------------------------------------

_OPTIMIZATION_MAP: dict[str, dict[str, Any]] = {
    "awareness->consideration": {
        "strategy": "improve_engagement",
        "recommendations": [
            "Enhance landing page relevance and load speed",
            "Add social proof and trust signals above the fold",
            "Implement retargeting campaigns for bounced visitors",
            "Improve ad-to-page message match",
        ],
    },
    "consideration->purchase": {
        "strategy": "reduce_purchase_friction",
        "recommendations": [
            "Simplify checkout flow — reduce steps to 3 or fewer",
            "Add guest checkout option",
            "Display transparent pricing with no hidden fees",
            "Implement cart abandonment email sequences",
            "Add urgency elements (limited stock, time-bound offers)",
        ],
    },
    "purchase->retention": {
        "strategy": "increase_retention",
        "recommendations": [
            "Implement post-purchase email nurture sequence",
            "Launch a loyalty rewards program",
            "Send personalized product recommendations",
            "Request reviews and feedback at optimal timing",
            "Offer subscription or auto-replenishment options",
        ],
    },
}


def advise_optimizations(
    drop_off_points: list[dict[str, Any]],
    stage_metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate optimization recommendations for the customer journey.

    Matches drop-off points to optimization strategies and prioritizes
    by potential revenue impact.

    Args:
        drop_off_points: Detected drop-offs from drop_off_detector.
        stage_metrics: Per-stage metrics from stage_analyzer.

    Returns:
        Structured dict with optimizations list.
    """
    try:
        dropoffs = copy.deepcopy(drop_off_points)
        metrics = copy.deepcopy(stage_metrics)

        # Build metric map for impact estimation
        metric_map = {str(m.get("stage", "")): m for m in metrics}

        optimizations: list[dict[str, Any]] = []

        for dp in dropoffs:
            from_stage = str(dp.get("from_stage", ""))
            to_stage = str(dp.get("to_stage", ""))
            drop_rate = float(dp.get("drop_off_rate", 0.0))
            drop_count = int(dp.get("drop_off_count", 0))
            severity = str(dp.get("severity", "low"))

            transition = f"{from_stage}->{to_stage}"
            template = _OPTIMIZATION_MAP.get(transition, {
                "strategy": "general_improvement",
                "recommendations": [
                    f"Investigate why customers leave at {from_stage}",
                    "Conduct user research on this transition point",
                ],
            })

            # Estimate potential impact
            # If we recover 20% of drop-offs, how many customers gained?
            recoverable = int(drop_count * 0.2)

            # Revenue impact estimate from purchase stage data
            purchase_data = metric_map.get("purchase", {})
            total_purchasers = int(purchase_data.get("customers_reached", 0))
            revenue = float(purchase_data.get("revenue", 0.0) or 0.0)
            avg_order_value = (
                round(revenue / total_purchasers, 2)
                if total_purchasers > 0 else 0.0
            )

            # Impact depends on which stage the drop-off is at
            if to_stage == "purchase":
                potential_revenue = round(recoverable * avg_order_value, 2)
            elif to_stage == "retention":
                potential_revenue = round(recoverable * avg_order_value * 2.5, 2)
            else:
                potential_revenue = round(recoverable * avg_order_value * 0.3, 2)

            # Priority: severity weight * drop count
            severity_weight = {"critical": 4, "high": 3, "medium": 2, "low": 1}
            priority = severity_weight.get(severity, 1) * max(drop_count, 1)

            optimizations.append({
                "transition": transition,
                "from_stage": from_stage,
                "to_stage": to_stage,
                "severity": severity,
                "strategy": template["strategy"],
                "recommendations": template["recommendations"],
                "drop_off_rate": drop_rate,
                "recoverable_customers": recoverable,
                "potential_revenue": potential_revenue,
                "priority_score": priority,
            })

        # Sort by priority score descending
        optimizations.sort(key=lambda o: o["priority_score"], reverse=True)

        return {
            "status": "success",
            "optimizations": optimizations,
            "total_optimizations": len(optimizations),
        }
    except Exception as exc:
        return {
            "status": "error",
            "optimizations": [],
            "error": f"Optimization advising failed: {exc}",
        }
