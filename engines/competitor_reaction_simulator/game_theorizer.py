"""Competitor Reaction Simulator Engine — game theorizer.

Applies game theory concepts: tit-for-tat, Nash equilibrium analysis.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_game_theory(
    our_action: dict[str, Any],
    predictions: list[dict[str, Any]],
    market_data: dict[str, Any],
) -> dict[str, Any]:
    """Apply game theory to find Nash equilibrium."""
    try:
        our_action = copy.deepcopy(our_action)
        our_price = float(our_action.get("our_price", 100.0))
        market_avg_price = float(market_data.get("avg_price", our_price))

        competitor_prices: dict[str, float] = {}
        for pred in predictions:
            name = pred.get("competitor", "")
            reaction = pred.get("likely_reaction", "")
            prob = float(pred.get("probability", 0.5))

            if reaction in ("undercut_further", "hold_lower_price"):
                opt_price = round(our_price * 0.95, 2)
            elif reaction == "match_price":
                opt_price = round(our_price, 2)
            elif reaction == "partial_follow":
                opt_price = round((our_price + market_avg_price) / 2, 2)
            else:
                opt_price = round(market_avg_price, 2)

            competitor_prices[name] = opt_price

        # Find Nash equilibrium price (simplified: where no one benefits from unilateral change)
        all_prices = list(competitor_prices.values()) + [our_price]
        equilibrium_price = round(sum(all_prices) / len(all_prices), 2) if all_prices else our_price

        # Check stability
        price_spread = max(all_prices) - min(all_prices) if all_prices else 0
        stable = price_spread < market_avg_price * 0.1

        nash_equilibrium = {
            "description": "Price equilibrium where no player benefits from unilateral deviation",
            "our_optimal_price": equilibrium_price,
            "competitor_optimal_prices": competitor_prices,
            "stable": stable,
        }

        return {"status": "success", "nash_equilibrium": nash_equilibrium}
    except Exception as exc:
        return {"status": "error", "nash_equilibrium": {}, "error": f"Game theory analysis failed: {exc}"}
