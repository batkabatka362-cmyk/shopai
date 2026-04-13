"""Competitor Reaction Simulator Engine — behavior modeler.

Models competitor behavior from historical data. Identifies strategy patterns,
aggressiveness levels, and typical response times.
"""
from __future__ import annotations

import copy
from typing import Any


def model_behavior(
    competitors: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Model competitor behavior patterns from history."""
    try:
        competitors = copy.deepcopy(competitors)
        history = copy.deepcopy(history)

        models: list[dict[str, Any]] = []
        for comp in competitors:
            name = str(comp.get("name", "unknown"))
            aggressiveness = float(comp.get("aggressiveness", 0.5))
            pricing_strategy = str(comp.get("pricing_strategy", "follow"))

            # Analyze history for this competitor
            comp_history = [h for h in history if h.get("competitor") == name]
            response_times = [float(h.get("response_days", 7)) for h in comp_history]
            avg_response = round(sum(response_times) / len(response_times), 1) if response_times else 7.0

            price_follows = [h for h in comp_history if h.get("action_type") == "price_match"]
            follow_rate = round(len(price_follows) / max(len(comp_history), 1), 2)

            # Classify strategy
            if aggressiveness > 0.7:
                strategy_type = "aggressive_undercutter"
            elif follow_rate > 0.6:
                strategy_type = "price_follower"
            elif aggressiveness < 0.3:
                strategy_type = "passive_differentiator"
            else:
                strategy_type = "selective_responder"

            confidence = 0.6
            if len(comp_history) > 5:
                confidence = min(confidence + 0.2, 0.95)
            if len(comp_history) > 10:
                confidence = min(confidence + 0.1, 0.95)

            models.append({
                "competitor": name,
                "strategy_type": strategy_type,
                "aggressiveness": aggressiveness,
                "response_speed_days": avg_response,
                "price_follow_rate": follow_rate,
                "confidence": round(confidence, 2),
            })

        return {"status": "success", "models": models}
    except Exception as exc:
        return {"status": "error", "models": [], "error": f"Behavior modeling failed: {exc}"}
