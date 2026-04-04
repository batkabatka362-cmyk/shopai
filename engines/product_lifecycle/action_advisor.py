"""Product Lifecycle Engine — action advisor.

Recommends actions for each product based on its lifecycle stage,
velocity, and projected trajectory.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_STAGE_ACTIONS: dict[str, list[str]] = {
    "introduction": [
        "increase_marketing_spend",
        "gather_customer_feedback",
        "monitor_adoption_rate",
    ],
    "growth": [
        "scale_inventory",
        "expand_distribution_channels",
        "optimize_pricing_strategy",
    ],
    "maturity": [
        "defend_market_share",
        "reduce_costs",
        "explore_product_variants",
    ],
    "decline": [
        "reduce_inventory",
        "evaluate_discontinuation",
        "harvest_remaining_value",
    ],
}


def advise_actions(
    classifications: list[dict[str, Any]],
    projections: list[dict[str, Any]],
    velocities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Advise actions for each product.

    Args:
        classifications: Per-product stage classification results.
        projections: Per-product trend projection results.
        velocities: Per-product velocity results.

    Returns:
        Structured dict with per-product action advice.
    """
    try:
        proj_map = {str(p.get("product_id", "")): p for p in projections}
        vel_map = {str(v.get("product_id", "")): v for v in velocities}

        advice_list: list[dict[str, Any]] = []

        for cls in classifications:
            product_id = str(cls.get("product_id", "unknown"))
            stage = str(cls.get("stage", "introduction"))
            proj = proj_map.get(product_id, {})
            vel = vel_map.get(product_id, {})

            actions = list(_STAGE_ACTIONS.get(stage, ["review_product"]))

            velocity_trend = str(vel.get("velocity_trend", "stable"))
            periods_to_transition = int(proj.get("periods_to_transition", 12))

            # Urgency-based priority
            if stage == "decline" or periods_to_transition <= 2:
                priority = "high"
            elif velocity_trend == "decelerating" or periods_to_transition <= 5:
                priority = "medium"
            else:
                priority = "low"

            # Add velocity-specific action
            if velocity_trend == "decelerating" and stage != "decline":
                actions.append("investigate_velocity_drop")
            elif velocity_trend == "accelerating" and stage == "introduction":
                actions.append("prepare_for_growth_phase")

            rationale = (
                f"Product in {stage} stage with {velocity_trend} velocity. "
                f"Estimated {periods_to_transition} periods until transition to "
                f"{proj.get('projected_transition', 'next stage')}."
            )

            advice_list.append({
                "product_id": product_id,
                "recommended_actions": actions,
                "priority": priority,
                "rationale": rationale,
            })

        return {"status": "success", "advice": advice_list}
    except Exception as exc:
        return {"status": "error", "advice": [], "error": f"Action advising failed: {exc}"}
