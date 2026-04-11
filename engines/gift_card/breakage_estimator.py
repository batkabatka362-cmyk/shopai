"""Gift Card Engine — breakage estimator.

Estimates breakage (unredeemed value): projects how much
gift card value will never be redeemed based on patterns.
"""
from __future__ import annotations

import copy
from typing import Any


_DEFAULT_BREAKAGE_RATE = 0.06  # Industry average ~6%


def estimate_breakage(
    gift_cards: list[dict[str, Any]],
    program_health: dict[str, Any],
) -> dict[str, Any]:
    """Estimate unredeemed gift card value (breakage).

    Args:
        gift_cards: Gift card records.
        program_health: Program health metrics.

    Returns:
        Structured dict with breakage estimates.
    """
    try:
        cards = copy.deepcopy(gift_cards)
        total_issued = float(program_health.get("total_value_issued", 0))
        outstanding = float(program_health.get("total_outstanding_balance", 0))
        utilization = float(program_health.get("utilization_rate_pct", 0)) / 100

        if total_issued == 0:
            return {
                "status": "success",
                "breakage": {
                    "estimated_breakage_value": 0.0,
                    "breakage_rate_pct": 0.0,
                    "breakage_revenue": 0.0,
                },
            }

        # Estimate breakage rate from observed patterns
        if utilization > 0:
            # Cards that have been around long enough to estimate
            aged_cards = [c for c in cards if c.get("age_days", 0) > 180]
            if aged_cards:
                aged_initial = sum(float(c.get("initial_value", 0)) for c in aged_cards)
                aged_balance = sum(float(c.get("balance", 0)) for c in aged_cards)
                if aged_initial > 0:
                    observed_rate = aged_balance / aged_initial
                    breakage_rate = min(observed_rate, 0.20)  # Cap at 20%
                else:
                    breakage_rate = _DEFAULT_BREAKAGE_RATE
            else:
                breakage_rate = _DEFAULT_BREAKAGE_RATE
        else:
            breakage_rate = _DEFAULT_BREAKAGE_RATE

        estimated_breakage = round(outstanding * breakage_rate, 2)
        breakage_revenue = round(total_issued * breakage_rate, 2)

        return {
            "status": "success",
            "breakage": {
                "estimated_breakage_value": estimated_breakage,
                "breakage_rate_pct": round(breakage_rate * 100, 1),
                "breakage_revenue": breakage_revenue,
                "outstanding_balance": outstanding,
                "method": "observed" if len([c for c in cards if c.get("age_days", 0) > 180]) > 0 else "industry_default",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "breakage": {},
            "error": f"Breakage estimation failed: {exc}",
        }
