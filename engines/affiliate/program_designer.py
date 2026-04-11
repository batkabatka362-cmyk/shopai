"""Affiliate Engine — program designer.

Designs commission structure with tiers, cookie duration, and rules
based on product margins and industry benchmarks.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Industry benchmarks
# ---------------------------------------------------------------------------

_DEFAULT_COOKIE_DAYS = 30
_MIN_COMMISSION_PCT = 3.0
_MAX_COMMISSION_PCT = 30.0


def design_program(
    products: list[dict[str, Any]],
    commission_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Design an affiliate program with commission tiers and rules.

    Args:
        products: List of AffiliateProduct dicts.
        commission_rules: List of existing CommissionRule dicts.

    Returns:
        Structured dict with program design.
    """
    try:
        products = copy.deepcopy(products)
        rules = copy.deepcopy(commission_rules)

        # Calculate average margin to set sustainable commission rates
        margins = [float(p.get("margin_pct", 30.0)) for p in products]
        avg_margin = sum(margins) / len(margins) if margins else 30.0

        # Commission should be ~30-50% of margin to stay profitable
        base_commission = round(avg_margin * 0.35, 1)
        base_commission = max(min(base_commission, _MAX_COMMISSION_PCT), _MIN_COMMISSION_PCT)

        # Build tiers if not provided
        if rules:
            commission_tiers = [
                {
                    "tier_name": str(r.get("tier", f"tier_{i}")),
                    "min_sales": float(r.get("min_sales", 0.0)),
                    "commission_pct": float(r.get("commission_pct", base_commission)),
                    "bonus": float(r.get("bonus", 0.0)),
                }
                for i, r in enumerate(rules)
            ]
        else:
            commission_tiers = [
                {
                    "tier_name": "bronze",
                    "min_sales": 0.0,
                    "commission_pct": round(base_commission, 1),
                    "bonus": 0.0,
                },
                {
                    "tier_name": "silver",
                    "min_sales": 5000.0,
                    "commission_pct": round(base_commission * 1.2, 1),
                    "bonus": 50.0,
                },
                {
                    "tier_name": "gold",
                    "min_sales": 15000.0,
                    "commission_pct": round(base_commission * 1.4, 1),
                    "bonus": 150.0,
                },
                {
                    "tier_name": "platinum",
                    "min_sales": 50000.0,
                    "commission_pct": round(base_commission * 1.6, 1),
                    "bonus": 500.0,
                },
            ]

        # Program rules
        program_rules = [
            "No self-referrals allowed",
            "Commission paid on confirmed orders only",
            "Returns deducted from commission within 30-day window",
            "Prohibited: paid search bidding on brand terms",
            "Minimum payout threshold: $50",
        ]

        program: dict[str, Any] = {
            "commission_tiers": commission_tiers,
            "cookie_duration_days": _DEFAULT_COOKIE_DAYS,
            "rules": program_rules,
        }

        return {
            "status": "success",
            "program": program,
        }
    except Exception as exc:
        return {
            "status": "error",
            "program": {},
            "error": f"Program design failed: {exc}",
        }
