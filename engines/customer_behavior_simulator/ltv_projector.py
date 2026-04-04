"""Customer Behavior Simulator Engine — LTV projector.

Projects lifetime value changes from proposed actions.
"""
from __future__ import annotations

import copy
from typing import Any


def project_ltv(
    simulations: list[dict[str, Any]],
    behavior_patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project LTV changes per segment from actions."""
    try:
        pattern_map = {p.get("segment", ""): p for p in behavior_patterns}

        projections: list[dict[str, Any]] = []
        for sim in simulations:
            segment = sim.get("target_segment", "")
            pattern = pattern_map.get(segment, {})
            current_ltv = float(pattern.get("ltv", 500))
            ltv_change_pct = float(sim.get("predicted_ltv_change", 0))
            projected_ltv = round(current_ltv * (1 + ltv_change_pct / 100), 2)

            # Payback: months to recoup action cost (estimate)
            action_cost_estimate = current_ltv * 0.05  # 5% of LTV as action cost
            monthly_ltv_gain = (projected_ltv - current_ltv) / 12 if projected_ltv > current_ltv else 0
            payback_months = round(action_cost_estimate / max(monthly_ltv_gain, 0.01), 1)

            projections.append({
                "segment": segment,
                "action": sim.get("action", ""),
                "current_ltv": current_ltv,
                "projected_ltv": projected_ltv,
                "change_pct": ltv_change_pct,
                "payback_months": min(payback_months, 36),
            })

        return {"status": "success", "projections": projections}
    except Exception as exc:
        return {"status": "error", "projections": [], "error": f"LTV projection failed: {exc}"}
