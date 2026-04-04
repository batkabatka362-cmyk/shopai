"""Customer Behavior Simulator Engine — action simulator.

Simulates the effect of marketing/pricing actions on customer behavior.
"""
from __future__ import annotations

import copy
from typing import Any


_ACTION_EFFECTS = {
    "discount": {"retention": 0.05, "ltv": -0.03, "revenue": 0.08},
    "loyalty_program": {"retention": 0.12, "ltv": 0.15, "revenue": 0.10},
    "email_campaign": {"retention": 0.03, "ltv": 0.02, "revenue": 0.04},
    "price_increase": {"retention": -0.08, "ltv": 0.05, "revenue": -0.03},
    "product_bundle": {"retention": 0.04, "ltv": 0.10, "revenue": 0.12},
    "personalization": {"retention": 0.07, "ltv": 0.08, "revenue": 0.06},
}


def simulate_actions(
    proposed_actions: list[dict[str, Any]],
    behavior_patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Simulate the effect of proposed actions on customer behavior."""
    try:
        proposed_actions = copy.deepcopy(proposed_actions)
        pattern_map = {p.get("segment", ""): p for p in behavior_patterns}

        simulations: list[dict[str, Any]] = []
        for action in proposed_actions:
            action_type = str(action.get("type", "email_campaign"))
            target_segment = str(action.get("target_segment", "general"))
            effects = _ACTION_EFFECTS.get(action_type, {"retention": 0.02, "ltv": 0.01, "revenue": 0.02})

            pattern = pattern_map.get(target_segment, {})
            engagement = float(pattern.get("engagement_score", 0.5))

            # Scale effects by engagement (more engaged = stronger response)
            scale = 0.5 + engagement

            retention_change = round(effects["retention"] * scale * 100, 2)
            ltv_change = round(effects["ltv"] * scale * 100, 2)
            revenue_impact = round(effects["revenue"] * scale * 100, 2)

            confidence = 0.65
            if pattern.get("customer_count", 0) > 50:
                confidence = min(confidence + 0.15, 0.95)

            simulations.append({
                "action": action_type,
                "target_segment": target_segment,
                "predicted_retention_change": retention_change,
                "predicted_ltv_change": ltv_change,
                "predicted_revenue_impact": revenue_impact,
                "confidence": round(confidence, 2),
            })

        return {"status": "success", "simulations": simulations}
    except Exception as exc:
        return {"status": "error", "simulations": [], "error": f"Action simulation failed: {exc}"}
