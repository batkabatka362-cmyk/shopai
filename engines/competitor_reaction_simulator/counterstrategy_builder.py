"""Competitor Reaction Simulator Engine — counterstrategy builder.

Builds counter-strategies based on predicted competitor reactions.
"""
from __future__ import annotations

import copy
from typing import Any


def build_counterstrategy(
    predictions: list[dict[str, Any]],
    nash_equilibrium: dict[str, Any],
    our_action: dict[str, Any],
) -> dict[str, Any]:
    """Build recommended counter-strategies."""
    try:
        predictions = copy.deepcopy(predictions)
        high_threat = [p for p in predictions if float(p.get("probability", 0)) > 0.6]
        stable = nash_equilibrium.get("stable", False)

        if not high_threat:
            strategy = {
                "strategy": "proceed_as_planned",
                "description": "Low competitor reaction probability — proceed with original action",
                "trigger_condition": "Any competitor matches within 7 days",
                "expected_outcome": "Maintain market position with improved margins",
            }
        elif stable:
            strategy = {
                "strategy": "gradual_adjustment",
                "description": "Market is near equilibrium — make gradual moves to avoid price war",
                "trigger_condition": "Competitor undercuts by more than 5%",
                "expected_outcome": "Stable market share with gradual improvement",
            }
        else:
            aggressive_count = sum(
                1 for p in high_threat
                if p.get("likely_reaction", "") in ("undercut_further", "hold_lower_price")
            )
            if aggressive_count > len(high_threat) / 2:
                strategy = {
                    "strategy": "differentiation_focus",
                    "description": "Competitors likely to engage in price war — differentiate on value instead",
                    "trigger_condition": "Two or more competitors undercut within 5 days",
                    "expected_outcome": "Preserve margins through value-based positioning",
                }
            else:
                strategy = {
                    "strategy": "selective_response",
                    "description": "Mixed competitor reactions — respond selectively to key threats",
                    "trigger_condition": "Market leader matches or undercuts",
                    "expected_outcome": "Maintain competitive position while protecting margins",
                }

        return {"status": "success", "counterstrategy": strategy}
    except Exception as exc:
        return {"status": "error", "counterstrategy": {}, "error": f"Counterstrategy building failed: {exc}"}
