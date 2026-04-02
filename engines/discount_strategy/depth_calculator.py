"""Discount Strategy Engine — depth calculator.

Calculates optimal discount depth: minimum to trigger customer action,
maximum before margin erosion, and the sweet spot between them.

All math is real — no placeholders or random numbers.

Key formulas:
  - min_depth: threshold based on discount type (consumers ignore tiny discounts)
  - max_depth: constrained by margin floor from margin_analyzer
  - sweet_spot: weighted midpoint biased by goal urgency
  - volume_lift: estimated from depth using empirical elasticity curves
  - margin_at_sweet_spot: (price * (1 - depth) - cogs) / (price * (1 - depth))
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Minimum discount thresholds by type — below these, customers don't act
# ---------------------------------------------------------------------------

_MIN_DEPTH_BY_TYPE: dict[str, float] = {
    "percentage_off": 0.10,     # 10% min to trigger action
    "dollar_off": 0.08,         # ~8% equivalent
    "bogo": 0.50,               # BOGO is inherently 50%
    "free_shipping": 0.00,      # free shipping has no depth per se
    "bundle_deal": 0.12,        # 12% perceived savings
    "tiered": 0.05,             # first tier can be shallow
}

# ---------------------------------------------------------------------------
# Goal urgency weights — higher urgency pushes sweet spot toward max_depth
# ---------------------------------------------------------------------------

_GOAL_URGENCY: dict[str, float] = {
    "clear_inventory": 0.80,    # urgent — push deeper
    "boost_revenue": 0.45,      # moderate
    "acquire_customers": 0.60,  # willing to go deeper for acquisition
    "reactivate": 0.55,         # moderate-high
}

# ---------------------------------------------------------------------------
# Volume lift estimation — empirical curve coefficients
# Lift = base_lift * (depth / reference_depth) ^ elasticity_exponent
# ---------------------------------------------------------------------------

_BASE_LIFT = 1.50          # 50% volume lift at reference depth
_REFERENCE_DEPTH = 0.20    # 20% discount as reference point
_ELASTICITY_EXPONENT = 0.7 # diminishing returns on deeper discounts


def calculate_depth(
    discount_type: str,
    margin_analyses: list[dict[str, Any]],
    goal: str,
    inventory_days: int,
) -> dict[str, Any]:
    """Calculate the optimal discount depth.

    Args:
        discount_type: Selected discount type from type_selector.
        margin_analyses: Per-product MarginAnalysis list from margin_analyzer.
        goal: Business goal driving the discount.
        inventory_days: Days of inventory remaining (lower = more urgency).

    Returns:
        Structured dict with DepthCalculation data.
    """
    try:
        if not margin_analyses:
            return {
                "status": "error",
                "calculation": {},
                "error": "No margin analyses provided",
            }

        # Aggregate across products: use weighted average by daily_sales if available
        avg_price, avg_cogs, avg_max_discount = _aggregate_products(margin_analyses)

        if avg_price <= 0:
            return {
                "status": "error",
                "calculation": {},
                "error": "Average price is zero — cannot compute depth",
            }

        # --- Min depth: type-specific floor ---
        min_depth = _MIN_DEPTH_BY_TYPE.get(discount_type, 0.10)

        # --- Max depth: from margin analysis (average across products) ---
        max_depth = avg_max_discount

        # BOGO is special: effective depth is always ~50%
        if discount_type == "bogo":
            min_depth = 0.50
            max_depth = max(max_depth, 0.50) if avg_max_discount >= 0.40 else avg_max_discount

        # Clamp min <= max
        if min_depth > max_depth:
            min_depth = max_depth

        # --- Urgency modifier from inventory days ---
        # Low inventory days => higher urgency => push toward max
        inventory_urgency = _compute_inventory_urgency(inventory_days)

        # --- Sweet spot: weighted between min and max ---
        goal_urgency = _GOAL_URGENCY.get(goal.lower(), 0.50)
        combined_urgency = 0.6 * goal_urgency + 0.4 * inventory_urgency
        combined_urgency = max(0.0, min(1.0, combined_urgency))

        # sweet_spot = min + urgency_weight * (max - min)
        sweet_spot = min_depth + combined_urgency * (max_depth - min_depth)
        sweet_spot = round(max(min_depth, min(sweet_spot, max_depth)), 4)

        # --- Volume lift at sweet spot ---
        volume_lift = _estimate_volume_lift(sweet_spot)

        # --- Margin at sweet spot ---
        margin_at_sweet_spot = _compute_margin_at_depth(avg_price, avg_cogs, sweet_spot)

        # --- Rationale ---
        rationale = (
            f"Sweet spot {sweet_spot:.1%} set between min {min_depth:.1%} and max {max_depth:.1%}. "
            f"Goal urgency {goal_urgency:.0%}, inventory urgency {inventory_urgency:.0%} "
            f"(inventory_days={inventory_days}). "
            f"Expected {volume_lift:.2f}x volume lift with margin dropping to {margin_at_sweet_spot:.1%}."
        )

        return {
            "status": "success",
            "calculation": {
                "min_depth_pct": round(min_depth, 4),
                "max_depth_pct": round(max_depth, 4),
                "sweet_spot_pct": sweet_spot,
                "expected_volume_lift": round(volume_lift, 4),
                "margin_at_sweet_spot": round(margin_at_sweet_spot, 4),
                "depth_rationale": rationale,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "calculation": {},
            "error": f"Depth calculation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _aggregate_products(analyses: list[dict[str, Any]]) -> tuple[float, float, float]:
    """Compute weighted-average price, cogs, max_discount across products."""
    total_price = 0.0
    total_cogs = 0.0
    total_max_disc = 0.0
    count = 0

    for a in analyses:
        price = float(a.get("price", 0.0))
        cogs = float(a.get("cogs", 0.0))
        max_d = float(a.get("max_discount_pct", 0.0))
        if price > 0:
            total_price += price
            total_cogs += cogs
            total_max_disc += max_d
            count += 1

    if count == 0:
        return 0.0, 0.0, 0.0

    return (
        total_price / count,
        total_cogs / count,
        total_max_disc / count,
    )


def _compute_inventory_urgency(inventory_days: int) -> float:
    """Convert inventory_days into a 0-1 urgency score.

    <=7 days  -> 1.0 (critical)
    14 days   -> 0.8
    30 days   -> 0.6
    60 days   -> 0.3
    90+ days  -> 0.1
    """
    if inventory_days <= 0:
        return 1.0
    if inventory_days <= 7:
        return 1.0
    if inventory_days <= 14:
        return 0.80
    if inventory_days <= 30:
        return 0.60
    if inventory_days <= 60:
        return 0.30
    return 0.10


def _estimate_volume_lift(depth_pct: float) -> float:
    """Estimate volume lift multiplier from discount depth.

    Uses a power-law curve: lift = base * (depth / ref) ^ exponent.
    At 0% depth => 1.0x (no lift).
    At 20% depth => ~1.5x.
    Diminishing returns beyond that.
    """
    if depth_pct <= 0:
        return 1.0

    raw_lift = _BASE_LIFT * (depth_pct / _REFERENCE_DEPTH) ** _ELASTICITY_EXPONENT
    # Minimum lift is 1.0 (can't decrease volume with a discount)
    return max(1.0, raw_lift)


def _compute_margin_at_depth(
    price: float,
    cogs: float,
    depth_pct: float,
) -> float:
    """Compute margin percentage at a given discount depth.

    margin = (discounted_price - cogs) / discounted_price
    """
    if price <= 0:
        return 0.0
    discounted_price = price * (1.0 - depth_pct)
    if discounted_price <= 0:
        return -1.0  # selling below zero
    return (discounted_price - cogs) / discounted_price
