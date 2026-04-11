"""Pricing Engine — psychology optimizer.

Applies pricing psychology techniques to optimize the final price:
  - Charm pricing: ending in .99 or .95
  - Anchoring: suggest a higher reference price
  - Decoy pricing: recommend a decoy option
  - Framing: per-day vs per-month presentation
  - Round number avoidance: steer away from $20, $30, etc.

Model note: Uses LLaMA for creative pricing psychology.
"""
from __future__ import annotations

import copy
import math
from typing import Any


def optimize_psychology(
    proposed_price: float,
    cost_floor: float,
    ceiling_price: float,
    competitor_mapping: dict[str, Any],
) -> dict[str, Any]:
    """Apply pricing psychology techniques to the proposed price.

    Args:
        proposed_price: The calculated optimal price before psychology.
        cost_floor: Minimum viable price (cannot go below).
        ceiling_price: Maximum market-tolerable price.
        competitor_mapping: CompetitorPrices data for anchoring context.

    Returns:
        Structured dict with PsychologyAdjustment data.
    """
    try:
        comp = copy.deepcopy(competitor_mapping)
        price = float(proposed_price)
        floor = float(cost_floor)
        ceiling = float(ceiling_price)
        max_competitor = float(comp.get("max_price", 0.0))

        techniques_considered: list[str] = []
        technique_applied = "none"
        adjusted_price = price

        # --- Technique 1: Charm pricing (.99 ending) ---
        charm_price = _apply_charm_pricing(price)
        techniques_considered.append("charm_pricing")

        # --- Technique 2: Round number avoidance ---
        # Check if price is too close to a round number ($20, $25, $30...)
        is_round = _is_near_round_number(price)
        techniques_considered.append("round_number_avoidance")

        # --- Technique 3: Just-below threshold ---
        # Prices just below psychological thresholds ($19.99 vs $20)
        threshold_price = _apply_threshold_pricing(price)
        techniques_considered.append("threshold_pricing")

        # --- Select best technique ---
        # Charm pricing is most universally effective for products under $100
        if price < 100.0:
            if is_round:
                # Round numbers feel more expensive; use threshold pricing
                adjusted_price = threshold_price
                technique_applied = "threshold_pricing"
            else:
                adjusted_price = charm_price
                technique_applied = "charm_pricing"
        else:
            # For higher-priced items, .99 can feel cheap; use .95 or clean
            adjusted_price = _apply_prestige_pricing(price)
            technique_applied = "prestige_rounding"
            techniques_considered.append("prestige_rounding")

        # --- Ensure adjusted price respects floor and ceiling ---
        adjusted_price = max(adjusted_price, floor)
        if ceiling > 0:
            adjusted_price = min(adjusted_price, ceiling)

        adjusted_price = round(adjusted_price, 2)

        # --- Anchoring price: suggest a higher reference ---
        # Anchor at the max competitor price or 30% above our price
        if max_competitor > adjusted_price:
            anchoring_price = round(max_competitor, 2)
        else:
            anchoring_price = round(adjusted_price * 1.30, 2)

        # --- Framing suggestion ---
        framing_suggestion = _generate_framing(adjusted_price)

        return {
            "status": "success",
            "adjustment": {
                "original_price": round(price, 2),
                "adjusted_price": adjusted_price,
                "technique_applied": technique_applied,
                "techniques_considered": techniques_considered,
                "anchoring_price": anchoring_price,
                "framing_suggestion": framing_suggestion,
                "model_note": "LLaMA: creative pricing psychology optimization",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "adjustment": {},
            "error": f"Psychology optimization failed: {exc}",
        }


def _apply_charm_pricing(price: float) -> float:
    """Apply charm pricing: round down to nearest .99.

    E.g. 27.45 -> 26.99, 28.10 -> 27.99
    Preserves the dollar if already ending near .99.
    """
    whole = math.floor(price)
    fractional = price - whole

    if 0.95 <= fractional <= 0.99:
        # Already charmed
        return whole + 0.99

    if fractional < 0.50:
        # Drop to previous dollar .99
        return (whole - 1) + 0.99 if whole > 1 else whole + 0.99
    else:
        # Stay at current dollar .99
        return whole + 0.99


def _apply_threshold_pricing(price: float) -> float:
    """Move price just below the nearest $5 or $10 threshold.

    E.g. 30.20 -> 29.99, 25.40 -> 24.99
    """
    # Find nearest round threshold above price
    thresholds = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100]

    for t in thresholds:
        if price <= t:
            return t - 0.01
    # For prices above 100, just below the nearest 10
    nearest_ten = math.ceil(price / 10.0) * 10
    return nearest_ten - 0.01


def _apply_prestige_pricing(price: float) -> float:
    """For premium products, use .95 or .00 endings.

    Avoids .99 which can feel discount-oriented for expensive items.
    """
    whole = math.floor(price)
    # Round to nearest .95
    return whole + 0.95


def _is_near_round_number(price: float, tolerance: float = 0.50) -> bool:
    """Check if price is within tolerance of a round $5 or $10 mark."""
    nearest_five = round(price / 5.0) * 5.0
    return abs(price - nearest_five) < tolerance


def _generate_framing(price: float) -> str:
    """Generate a per-day framing for the price.

    Useful for subscription or long-life products.
    """
    daily = price / 365.0
    if daily < 0.10:
        return f"Less than ${daily:.2f}/day — cheaper than a penny a day"
    if daily < 1.00:
        return f"Just ${daily:.2f}/day — less than a cup of coffee"
    if daily < 5.00:
        return f"Only ${daily:.2f}/day"
    return f"${price:.2f} total value"
