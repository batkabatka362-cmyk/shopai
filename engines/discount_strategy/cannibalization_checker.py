"""Discount Strategy Engine — cannibalization checker.

Checks whether a proposed discount will cannibalize regular-price sales,
impact brand perception, or cause forward-buying behavior.

Risk factors:
  1. Regular sales cannibalization: customers who would have bought at full
     price now buy discounted. Deeper discounts on staple products = higher risk.
  2. Brand perception: frequent or deep discounts erode perceived brand value.
  3. Forward buying: customers stock up during discount and reduce post-promo
     purchases. Duration and discount type influence this.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Cannibalization risk by discount type — some types cannibalize more
# ---------------------------------------------------------------------------

_TYPE_CANNIBALIZATION_BASE: dict[str, float] = {
    "percentage_off": 0.35,     # moderate — clear price cut
    "dollar_off": 0.30,         # slightly less visible
    "bogo": 0.45,               # high — encourages stockpiling
    "free_shipping": 0.10,      # low — additive value
    "bundle_deal": 0.20,        # low — different purchase behavior
    "tiered": 0.25,             # moderate — encourages larger baskets
}

# ---------------------------------------------------------------------------
# Brand perception impact by type
# ---------------------------------------------------------------------------

_TYPE_BRAND_IMPACT: dict[str, str] = {
    "percentage_off": "slight",
    "dollar_off": "slight",
    "bogo": "moderate",
    "free_shipping": "none",
    "bundle_deal": "none",
    "tiered": "slight",
}


def check_cannibalization(
    discount_type: str,
    sweet_spot_pct: float,
    duration_hours: int,
    target_audience: str,
    goal: str,
    margin_summary: dict[str, Any],
) -> dict[str, Any]:
    """Check cannibalization risk for the proposed discount strategy.

    Args:
        discount_type: Selected discount type.
        sweet_spot_pct: Discount depth.
        duration_hours: Duration in hours.
        target_audience: Target audience.
        goal: Business goal.
        margin_summary: Margin summary from analyzer.

    Returns:
        Structured dict with CannibalizationCheck data.
    """
    try:
        # --- Regular sales cannibalization risk ---
        base_risk = _TYPE_CANNIBALIZATION_BASE.get(discount_type, 0.30)

        # Depth modifier: deeper discounts cannibalize more
        # Linear: 10% depth -> +0.05, 30% depth -> +0.15
        depth_modifier = sweet_spot_pct * 0.50

        # Duration modifier: longer durations increase cannibalization
        duration_modifier = _duration_risk_modifier(duration_hours)

        # Targeting modifier: narrow targeting reduces cannibalization
        # because fewer full-price buyers see the discount
        if target_audience == "all":
            target_modifier = 0.10
        elif target_audience in ("new_customers",):
            target_modifier = -0.15  # new customers wouldn't have bought anyway
        elif target_audience in ("at_risk",):
            target_modifier = -0.10  # at-risk may have churned
        else:
            target_modifier = -0.05  # segment-specific

        raw_risk = base_risk + depth_modifier + duration_modifier + target_modifier
        raw_risk = max(0.0, min(1.0, raw_risk))

        # Convert to percentage impact on regular sales
        regular_sales_impact_pct = round(raw_risk * 0.50, 4)  # up to 50% of risk as actual sales impact

        # Classify risk level
        if raw_risk < 0.25:
            risk_level = "low"
        elif raw_risk < 0.50:
            risk_level = "medium"
        else:
            risk_level = "high"

        # --- Brand perception impact ---
        brand_impact = _TYPE_BRAND_IMPACT.get(discount_type, "slight")
        if sweet_spot_pct >= 0.40:
            # Very deep discounts always hurt brand
            brand_impact = "significant" if brand_impact != "none" else "moderate"
        elif sweet_spot_pct >= 0.25 and brand_impact == "none":
            brand_impact = "slight"

        # --- Forward buying risk ---
        forward_buying = _assess_forward_buying(
            discount_type, sweet_spot_pct, duration_hours,
        )

        # --- Rationale ---
        rationale = (
            f"Cannibalization risk: {risk_level} (score {raw_risk:.2f}). "
            f"Base risk for {discount_type}: {base_risk:.2f}, "
            f"depth modifier: +{depth_modifier:.2f}, "
            f"duration modifier: +{duration_modifier:.2f}, "
            f"targeting modifier: {target_modifier:+.2f}. "
            f"Estimated {regular_sales_impact_pct:.1%} regular sales impact. "
            f"Brand perception: {brand_impact}. Forward buying: {forward_buying}."
        )

        return {
            "status": "success",
            "check": {
                "cannibalization_risk": risk_level,
                "regular_sales_impact_pct": regular_sales_impact_pct,
                "brand_perception_impact": brand_impact,
                "forward_buying_risk": forward_buying,
                "risk_rationale": rationale,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "check": {},
            "error": f"Cannibalization check failed: {exc}",
        }


def _duration_risk_modifier(hours: int) -> float:
    """Compute risk modifier from duration.

    Flash (4h): minimal cannibalization (+0.00)
    Daily (24h): low (+0.05)
    Weekend (48h): moderate (+0.08)
    Weekly (168h): high (+0.12)
    Seasonal (336h+): very high (+0.18)
    """
    if hours <= 4:
        return 0.00
    if hours <= 24:
        return 0.05
    if hours <= 48:
        return 0.08
    if hours <= 168:
        return 0.12
    return 0.18


def _assess_forward_buying(
    discount_type: str,
    depth_pct: float,
    duration_hours: int,
) -> str:
    """Assess forward-buying risk.

    Forward buying = customers stock up during discount, reducing future sales.
    Higher with: BOGO, deep discounts, longer windows.
    """
    score = 0.0

    # Type
    if discount_type == "bogo":
        score += 0.40
    elif discount_type == "percentage_off":
        score += 0.20
    elif discount_type == "dollar_off":
        score += 0.15
    elif discount_type == "tiered":
        score += 0.25  # tiered encourages buying more
    else:
        score += 0.05

    # Depth
    score += depth_pct * 0.40

    # Duration
    if duration_hours >= 168:
        score += 0.15
    elif duration_hours >= 48:
        score += 0.08

    if score < 0.25:
        return "low"
    if score < 0.50:
        return "medium"
    return "high"
