"""Discount Strategy Engine — target selector.

Selects who gets the discount: all customers, specific segments,
new customers, at-risk customers, or high-value customers.

Model note: Uses Mistral for segment selection reasoning.

Selection logic:
  1. Goal determines primary affinity (e.g. acquire_customers -> new_customers)
  2. Available segments constrain options
  3. Depth and type influence reach vs. exclusivity tradeoff
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Goal-to-target affinity — higher = better fit for that goal
# ---------------------------------------------------------------------------

_GOAL_TARGET_AFFINITY: dict[str, dict[str, float]] = {
    "clear_inventory": {
        "all": 0.90,
        "vip": 0.40,
        "at_risk": 0.50,
        "new_customers": 0.60,
        "high_value": 0.45,
    },
    "boost_revenue": {
        "all": 0.60,
        "vip": 0.70,
        "at_risk": 0.40,
        "new_customers": 0.50,
        "high_value": 0.90,
    },
    "acquire_customers": {
        "all": 0.50,
        "vip": 0.20,
        "at_risk": 0.30,
        "new_customers": 0.95,
        "high_value": 0.35,
    },
    "reactivate": {
        "all": 0.30,
        "vip": 0.50,
        "at_risk": 0.95,
        "new_customers": 0.20,
        "high_value": 0.60,
    },
}

# ---------------------------------------------------------------------------
# Estimated reach and response rate by target
# ---------------------------------------------------------------------------

_TARGET_REACH: dict[str, float] = {
    "all": 1.00,
    "vip": 0.10,
    "at_risk": 0.15,
    "new_customers": 0.25,
    "high_value": 0.12,
}

_TARGET_RESPONSE_RATE: dict[str, float] = {
    "all": 0.03,            # 3% baseline conversion
    "vip": 0.12,            # VIPs respond well
    "at_risk": 0.08,        # at-risk need a nudge
    "new_customers": 0.06,  # new customer acquisition
    "high_value": 0.10,     # high-value are engaged
}

# ---------------------------------------------------------------------------
# Depth modifiers — deeper discounts favor broader audiences
# ---------------------------------------------------------------------------

_DEEP_DISCOUNT_THRESHOLD = 0.25  # 25%+ is considered deep


def select_target(
    goal: str,
    customer_segments: list[str],
    discount_type: str,
    sweet_spot_pct: float,
) -> dict[str, Any]:
    """Select the optimal target audience for the discount.

    Args:
        goal: Business goal (clear_inventory, boost_revenue, etc.).
        customer_segments: Available customer segments (e.g. ["vip", "at_risk"]).
        discount_type: Selected discount type.
        sweet_spot_pct: The discount depth sweet spot.

    Returns:
        Structured dict with TargetSelection data.
    """
    try:
        goal_key = goal.lower() if goal else "boost_revenue"
        affinities = _GOAL_TARGET_AFFINITY.get(
            goal_key,
            _GOAL_TARGET_AFFINITY["boost_revenue"],
        )

        # Build candidate set: "all" is always available, plus provided segments
        candidates: list[str] = ["all"]
        for seg in (customer_segments or []):
            normalized = seg.lower().strip()
            if normalized in affinities and normalized not in candidates:
                candidates.append(normalized)

        # Score each candidate
        scores: dict[str, float] = {}
        for target in candidates:
            score = affinities.get(target, 0.30)

            # Deep discounts favor broader audiences (dilutes brand less
            # when everyone gets it vs. selective deep discounts)
            if sweet_spot_pct >= _DEEP_DISCOUNT_THRESHOLD and target == "all":
                score += 0.10
            elif sweet_spot_pct < _DEEP_DISCOUNT_THRESHOLD and target != "all":
                # Shallow discounts are more effective when targeted
                score += 0.10

            # BOGO and bundle_deal work better with broader audiences
            if discount_type in ("bogo", "bundle_deal") and target == "all":
                score += 0.05

            scores[target] = round(min(score, 1.0), 3)

        # Select winner
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        selected = ranked[0][0]

        reach = _TARGET_REACH.get(selected, 0.10)
        response_rate = _TARGET_RESPONSE_RATE.get(selected, 0.03)

        rationale = _build_rationale(
            selected, goal_key, customer_segments, sweet_spot_pct, ranked[0][1],
        )

        return {
            "status": "success",
            "selection": {
                "target_audience": selected,
                "segment_rationale": rationale,
                "estimated_reach_pct": round(reach, 4),
                "expected_response_rate": round(response_rate, 4),
                "model_note": (
                    "Mistral: target selection based on goal affinity, "
                    "segment availability, and depth/type interaction"
                ),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "selection": {},
            "error": f"Target selection failed: {exc}",
        }


def _build_rationale(
    selected: str,
    goal: str,
    segments: list[str] | None,
    depth: float,
    score: float,
) -> str:
    """Build human-readable rationale."""
    seg_str = ", ".join(segments) if segments else "none specified"
    parts = [
        f"Target '{selected}' selected for goal '{goal}' (score {score:.2f}).",
        f"Available segments: {seg_str}.",
        f"Discount depth {depth:.1%} "
        + ("favors broad targeting." if depth >= _DEEP_DISCOUNT_THRESHOLD else "favors narrow targeting."),
    ]
    return " ".join(parts)
