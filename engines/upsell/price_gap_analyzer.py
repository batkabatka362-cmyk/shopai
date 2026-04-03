"""Upsell Engine — price gap analyzer.

Analyzes the price gap between the current product and each upgrade candidate.
Applies real pricing psychology: Weber-Fechner thresholds, charm pricing
anchoring, round-number aversion, and left-digit effects.

Key psychological thresholds used in production upsell systems:
  - Under $10 absolute: trivial cost framing works
  - Under 30% relative: within "acceptable upgrade" range
  - Under $5/day reframed: daily cost framing is effective
  - Left-digit boundary: $99 -> $119 feels larger than $101 -> $119
"""
from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Psychological threshold constants
# ---------------------------------------------------------------------------

# Absolute thresholds (in dollars)
TRIVIAL_THRESHOLD = 10.0          # under this, "just $X more" works well
IMPULSE_THRESHOLD = 20.0          # under this, minimal deliberation
CONSIDERATION_THRESHOLD = 50.0    # above this, customer needs justification

# Relative thresholds (as decimal)
EASY_RELATIVE = 0.10              # 10% — barely noticeable
SWEET_SPOT_LOW = 0.15             # 15% — sweet spot start
SWEET_SPOT_HIGH = 0.30            # 30% — sweet spot end
STRETCH_THRESHOLD = 0.50          # 50% — needs strong value prop
REJECTION_THRESHOLD = 1.00        # 100% — double the price, very hard sell

# Daily reframing works when per-day cost is under this
DAILY_REFRAME_THRESHOLD = 1.50    # $1.50/day feels trivial

# Product life assumption for daily cost calculation
ASSUMED_PRODUCT_LIFE_DAYS = 365


def analyze_price_gaps(
    candidates: list[dict[str, Any]],
    current_price: float,
    customer_aov: float = 0.0,
) -> dict[str, Any]:
    """Analyze price gaps for all upgrade candidates.

    Args:
        candidates: List of UpgradeCandidate dicts from upgrade_finder.
        current_price: Current product price.
        customer_aov: Customer average order value (for anchoring).

    Returns:
        Structured dict with PriceGapAnalysis per candidate.
    """
    try:
        if current_price <= 0:
            return {
                "status": "error",
                "analyses": [],
                "error": "Current price must be positive",
            }

        analyses: list[dict[str, Any]] = []

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            candidate_price = float(candidate.get("price", 0.0))
            product_id = str(candidate.get("product_id", ""))

            gap = _analyze_single_gap(
                product_id=product_id,
                current_price=current_price,
                candidate_price=candidate_price,
                customer_aov=customer_aov,
            )
            analyses.append(gap)

        return {
            "status": "success",
            "analyses": analyses,
            "count": len(analyses),
        }
    except Exception as exc:
        return {
            "status": "error",
            "analyses": [],
            "error": f"Price gap analysis failed: {exc}",
        }


def _analyze_single_gap(
    product_id: str,
    current_price: float,
    candidate_price: float,
    customer_aov: float,
) -> dict[str, Any]:
    """Full psychological analysis for one price gap."""
    absolute_diff = candidate_price - current_price
    pct_increase = absolute_diff / current_price if current_price > 0 else 0.0

    # --- Threshold booleans ---
    under_10 = absolute_diff < TRIVIAL_THRESHOLD
    under_30_pct = pct_increase < SWEET_SPOT_HIGH

    # --- Per-day cost ---
    per_day = absolute_diff / ASSUMED_PRODUCT_LIFE_DAYS

    # --- Sweet spot detection ---
    in_sweet_spot = (
        SWEET_SPOT_LOW <= pct_increase <= SWEET_SPOT_HIGH
        and absolute_diff < CONSIDERATION_THRESHOLD
    )

    # --- Psychological acceptability score (0-1) ---
    psych_score = _psychological_score(
        absolute_diff=absolute_diff,
        pct_increase=pct_increase,
        per_day=per_day,
        current_price=current_price,
        candidate_price=candidate_price,
        customer_aov=customer_aov,
    )

    # --- Anchoring effect ---
    anchoring = _anchoring_effect(current_price, candidate_price, customer_aov)

    return {
        "product_id": product_id,
        "absolute_difference": round(absolute_diff, 2),
        "percentage_increase": round(pct_increase, 4),
        "under_10_dollars": under_10,
        "under_30_percent": under_30_pct,
        "in_sweet_spot": in_sweet_spot,
        "psychological_score": round(psych_score, 4),
        "per_day_cost_increase": round(per_day, 4),
        "anchoring_effect": round(anchoring, 4),
    }


def _psychological_score(
    absolute_diff: float,
    pct_increase: float,
    per_day: float,
    current_price: float,
    candidate_price: float,
    customer_aov: float,
) -> float:
    """Compute psychological acceptability score (0-1).

    Combines multiple pricing psychology signals:
      1. Weber-Fechner: relative change perception is logarithmic
      2. Absolute pain: raw dollar amount aversion
      3. Daily reframe: per-day cost triviality
      4. Left-digit effect: crossing $X0/$X00 boundaries hurts
      5. AOV anchoring: gap relative to typical spend
    """
    # 1. Weber-Fechner relative perception (log-scaled)
    #    JND (just-noticeable difference) in pricing ~10-15%
    if pct_increase <= 0:
        weber = 1.0
    elif pct_increase <= EASY_RELATIVE:
        weber = 0.95  # barely noticed
    elif pct_increase <= SWEET_SPOT_HIGH:
        # Smooth decay through sweet spot
        weber = 0.95 - 0.45 * ((pct_increase - EASY_RELATIVE) / (SWEET_SPOT_HIGH - EASY_RELATIVE))
    elif pct_increase <= STRETCH_THRESHOLD:
        weber = 0.50 - 0.25 * ((pct_increase - SWEET_SPOT_HIGH) / (STRETCH_THRESHOLD - SWEET_SPOT_HIGH))
    elif pct_increase <= REJECTION_THRESHOLD:
        weber = 0.25 - 0.15 * ((pct_increase - STRETCH_THRESHOLD) / (REJECTION_THRESHOLD - STRETCH_THRESHOLD))
    else:
        weber = max(0.05, 0.10 - 0.05 * (pct_increase - REJECTION_THRESHOLD))

    # 2. Absolute dollar pain
    if absolute_diff < TRIVIAL_THRESHOLD:
        abs_score = 1.0
    elif absolute_diff < IMPULSE_THRESHOLD:
        abs_score = 0.85
    elif absolute_diff < CONSIDERATION_THRESHOLD:
        abs_score = 0.60
    else:
        abs_score = max(0.10, 0.60 - (absolute_diff - CONSIDERATION_THRESHOLD) / 200.0)

    # 3. Daily reframe effectiveness
    if per_day < 0.25:
        daily_score = 1.0   # "pennies a day"
    elif per_day < DAILY_REFRAME_THRESHOLD:
        daily_score = 0.80
    elif per_day < 5.0:
        daily_score = 0.50
    else:
        daily_score = 0.20

    # 4. Left-digit effect penalty
    left_digit_penalty = _left_digit_penalty(current_price, candidate_price)

    # 5. AOV anchoring bonus
    aov_bonus = 0.0
    if customer_aov > 0 and absolute_diff < customer_aov * 0.15:
        # Gap is tiny relative to what they usually spend
        aov_bonus = 0.10

    # Weighted combination
    score = (
        weber * 0.30
        + abs_score * 0.25
        + daily_score * 0.20
        + (1.0 - left_digit_penalty) * 0.15
        + aov_bonus
    )
    # Normalize remaining 0.10 weight from aov_bonus max
    return max(0.0, min(1.0, score))


def _left_digit_penalty(current_price: float, candidate_price: float) -> float:
    """Compute left-digit crossing penalty.

    Crossing a $X0 or $X00 boundary creates disproportionate perceived
    price increase (Thomas & Morwitz 2005). E.g., $29.99 -> $32 feels
    bigger than $32 -> $35 despite same absolute gap.

    Returns:
        Penalty 0.0 (no boundary crossed) to 0.5 (major boundary crossed).
    """
    if current_price <= 0 or candidate_price <= current_price:
        return 0.0

    # Check hundreds boundary crossing
    current_hundreds = int(current_price) // 100
    candidate_hundreds = int(candidate_price) // 100
    if candidate_hundreds > current_hundreds:
        return 0.5  # crossed a $100 boundary — major

    # Check tens boundary crossing
    current_tens = int(current_price) // 10
    candidate_tens = int(candidate_price) // 10
    if candidate_tens > current_tens:
        return 0.25  # crossed a $10 boundary — moderate

    return 0.0


def _anchoring_effect(
    current_price: float,
    candidate_price: float,
    customer_aov: float,
) -> float:
    """How strongly the original price anchors perception of the upgrade.

    Higher anchoring means the current price makes the upgrade feel
    more reasonable. Best when the gap is small relative to base price.

    Returns:
        0.0 (weak anchor) to 1.0 (strong anchor).
    """
    if current_price <= 0:
        return 0.0

    ratio = candidate_price / current_price

    # Strong anchoring when ratio is close to 1.0
    if ratio <= 1.10:
        anchor = 0.95
    elif ratio <= 1.25:
        anchor = 0.80
    elif ratio <= 1.50:
        anchor = 0.60
    elif ratio <= 2.0:
        anchor = 0.35
    else:
        anchor = 0.15

    # AOV context bonus: if upgrade price is still under AOV, strong anchor
    if customer_aov > 0 and candidate_price <= customer_aov:
        anchor = min(1.0, anchor + 0.15)

    return anchor
