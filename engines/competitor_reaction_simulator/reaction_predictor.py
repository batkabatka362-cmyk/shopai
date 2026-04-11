"""Competitor Reaction Simulator Engine — reaction predictor.

Predicts how each competitor will react to our planned action.
"""
from __future__ import annotations

import copy
from typing import Any


def predict_reactions(
    our_action: dict[str, Any],
    behavior_models: list[dict[str, Any]],
) -> dict[str, Any]:
    """Predict competitor reactions to our action."""
    try:
        our_action = copy.deepcopy(our_action)
        action_type = str(our_action.get("type", "price_change"))
        magnitude = float(our_action.get("magnitude", 0.0))

        predictions: list[dict[str, Any]] = []
        for model in behavior_models:
            name = model.get("competitor", "")
            strategy = model.get("strategy_type", "selective_responder")
            aggressiveness = float(model.get("aggressiveness", 0.5))
            response_days = float(model.get("response_speed_days", 7))
            follow_rate = float(model.get("price_follow_rate", 0.5))

            if action_type == "price_decrease":
                if strategy == "aggressive_undercutter":
                    reaction = "undercut_further"
                    probability = min(0.9, aggressiveness + 0.2)
                    timeline = f"{max(1, response_days - 2):.0f} days"
                elif strategy == "price_follower":
                    reaction = "match_price"
                    probability = follow_rate
                    timeline = f"{response_days:.0f} days"
                else:
                    reaction = "hold_price_add_value"
                    probability = 0.6
                    timeline = f"{response_days + 3:.0f} days"
            elif action_type == "price_increase":
                if strategy == "aggressive_undercutter":
                    reaction = "hold_lower_price"
                    probability = 0.85
                    timeline = f"{1:.0f} days"
                else:
                    reaction = "partial_follow"
                    probability = follow_rate * 0.7
                    timeline = f"{response_days + 5:.0f} days"
            elif action_type == "new_product":
                reaction = "accelerate_own_launch" if aggressiveness > 0.5 else "monitor_and_wait"
                probability = aggressiveness
                timeline = f"{response_days * 3:.0f} days"
            else:
                reaction = "no_immediate_reaction"
                probability = 0.5
                timeline = f"{response_days:.0f} days"

            impact = "high" if probability > 0.7 else ("medium" if probability > 0.4 else "low")

            predictions.append({
                "competitor": name,
                "likely_reaction": reaction,
                "probability": round(probability, 2),
                "timeline": timeline,
                "impact_on_us": impact,
            })

        return {"status": "success", "predictions": predictions}
    except Exception as exc:
        return {"status": "error", "predictions": [], "error": f"Reaction prediction failed: {exc}"}
