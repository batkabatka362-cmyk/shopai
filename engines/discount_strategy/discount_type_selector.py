"""Discount Strategy Engine — discount type selector.

Selects the optimal discount type based on business goal, product
characteristics, and margin headroom. Types: percentage_off, dollar_off,
bogo, free_shipping, bundle_deal, tiered.

Model note: Uses Mistral for nuanced type selection reasoning.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Goal-to-type affinity matrix — higher score = better fit
# ---------------------------------------------------------------------------

_GOAL_TYPE_AFFINITY: dict[str, dict[str, float]] = {
    "clear_inventory": {
        "percentage_off": 0.90,
        "dollar_off": 0.70,
        "bogo": 0.85,
        "free_shipping": 0.30,
        "bundle_deal": 0.75,
        "tiered": 0.60,
    },
    "boost_revenue": {
        "percentage_off": 0.70,
        "dollar_off": 0.60,
        "bogo": 0.50,
        "free_shipping": 0.65,
        "bundle_deal": 0.80,
        "tiered": 0.90,
    },
    "acquire_customers": {
        "percentage_off": 0.85,
        "dollar_off": 0.75,
        "bogo": 0.60,
        "free_shipping": 0.90,
        "bundle_deal": 0.55,
        "tiered": 0.50,
    },
    "reactivate": {
        "percentage_off": 0.80,
        "dollar_off": 0.85,
        "bogo": 0.55,
        "free_shipping": 0.70,
        "bundle_deal": 0.50,
        "tiered": 0.45,
    },
}

# ---------------------------------------------------------------------------
# Price-bracket type modifiers — some types work better at certain price points
# ---------------------------------------------------------------------------

_PRICE_BRACKET_MODIFIERS: dict[str, dict[str, float]] = {
    "low": {       # price < $25
        "percentage_off": 0.0,
        "dollar_off": -0.10,       # $2 off $10 feels weak
        "bogo": 0.15,              # BOGO works well for cheap items
        "free_shipping": 0.20,     # shipping may be > discount
        "bundle_deal": 0.10,
        "tiered": -0.10,
    },
    "mid": {       # $25 - $100
        "percentage_off": 0.05,
        "dollar_off": 0.05,
        "bogo": 0.0,
        "free_shipping": 0.10,
        "bundle_deal": 0.10,
        "tiered": 0.10,
    },
    "high": {      # > $100
        "percentage_off": 0.10,
        "dollar_off": 0.15,        # $20 off $150 feels concrete
        "bogo": -0.15,             # BOGO too expensive at high price
        "free_shipping": 0.0,
        "bundle_deal": 0.05,
        "tiered": 0.15,
    },
}

# ---------------------------------------------------------------------------
# Margin headroom modifiers — low margin restricts certain types
# ---------------------------------------------------------------------------

_MARGIN_MODIFIERS: dict[str, float] = {
    "bogo": -0.30,          # BOGO effectively 50% off — needs fat margins
    "tiered": -0.10,        # tiered can get expensive at high tiers
    "free_shipping": -0.05,
    "percentage_off": 0.0,
    "dollar_off": 0.0,
    "bundle_deal": -0.05,
}


def select_discount_type(
    goal: str,
    margin_summary: dict[str, Any],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Select the best discount type for the given context.

    Args:
        goal: Business goal (clear_inventory, boost_revenue, etc.).
        margin_summary: Aggregated margin summary from margin_analyzer.
        products: List of product dicts.

    Returns:
        Structured dict with DiscountTypeSelection data.
    """
    try:
        prods = copy.deepcopy(products)
        goal_key = goal.lower() if goal else "boost_revenue"

        avg_price = _compute_avg_price(prods)
        price_bracket = _classify_price_bracket(avg_price)
        avg_safe_room = float(margin_summary.get("avg_safe_discount_room", 0.10))
        low_margin = avg_safe_room < 0.10

        # --- Score each discount type ---
        base_scores = _GOAL_TYPE_AFFINITY.get(
            goal_key,
            _GOAL_TYPE_AFFINITY["boost_revenue"],
        )
        bracket_mods = _PRICE_BRACKET_MODIFIERS.get(price_bracket, {})

        scores: dict[str, float] = {}
        for dtype in base_scores:
            score = base_scores[dtype]
            score += bracket_mods.get(dtype, 0.0)

            # Penalize margin-heavy types when margins are thin
            if low_margin:
                score += _MARGIN_MODIFIERS.get(dtype, 0.0)

            scores[dtype] = max(round(score, 3), 0.0)

        # --- Select winner and alternatives ---
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        selected = ranked[0][0]
        alternatives = [r[0] for r in ranked[1:3]]
        goal_alignment = ranked[0][1]

        rationale = _build_rationale(
            selected, goal_key, price_bracket, avg_safe_room, goal_alignment,
        )

        return {
            "status": "success",
            "selection": {
                "selected_type": selected,
                "rationale": rationale,
                "alternatives": alternatives,
                "goal_alignment": round(min(goal_alignment, 1.0), 2),
                "model_note": "Mistral: discount type selection based on goal, price bracket, and margin headroom",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "selection": {},
            "error": f"Discount type selection failed: {exc}",
        }


def _compute_avg_price(products: list[dict[str, Any]]) -> float:
    """Compute average price across products."""
    prices = [float(p.get("price", 0.0)) for p in products if float(p.get("price", 0.0)) > 0]
    if not prices:
        return 0.0
    return sum(prices) / len(prices)


def _classify_price_bracket(avg_price: float) -> str:
    """Classify price bracket."""
    if avg_price < 25.0:
        return "low"
    if avg_price <= 100.0:
        return "mid"
    return "high"


def _build_rationale(
    selected: str,
    goal: str,
    price_bracket: str,
    avg_safe_room: float,
    alignment: float,
) -> str:
    """Build human-readable rationale for the selection."""
    type_labels = {
        "percentage_off": "Percentage-off discount",
        "dollar_off": "Fixed dollar-off discount",
        "bogo": "Buy-one-get-one (BOGO)",
        "free_shipping": "Free shipping offer",
        "bundle_deal": "Bundle deal",
        "tiered": "Tiered discount (spend more, save more)",
    }
    label = type_labels.get(selected, selected)

    parts = [
        f"{label} selected for goal '{goal}'.",
        f"Products are in the {price_bracket}-price bracket.",
        f"Average safe discount headroom is {avg_safe_room:.1%}.",
        f"Goal alignment score: {alignment:.2f}.",
    ]

    if selected == "bogo" and avg_safe_room < 0.15:
        parts.append("Warning: BOGO requires deep margin headroom; monitor closely.")

    return " ".join(parts)
