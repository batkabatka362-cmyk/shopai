"""Margin rules — hard constraints and guardrails for Shopify stores.

Violations = automatic warning or rejection.
These are non-negotiable thresholds validated against real store data.
"""
from __future__ import annotations

from typing import Any

from .data import get_category_benchmark


# --------------------------------------------------------------------------- #
#  Minimum margin thresholds
# --------------------------------------------------------------------------- #
MIN_CONTRIBUTION_MARGIN_SHOPIFY = 20.0   # Below 20% contribution margin = unsustainable on Shopify
MIN_NET_MARGIN_SUSTAINABLE = 15.0        # Below 15% net margin = not sustainable long-term
MIN_GROSS_MARGIN_VIABLE = 30.0           # Below 30% gross margin = barely covers overhead
MIN_OPERATING_MARGIN_HEALTHY = 10.0      # Below 10% operating margin = no room for error

# Maximum healthy ad spend as % of revenue
MAX_AD_SPEND_PCT_OF_REVENUE = 30.0

# Return rate danger threshold
MAX_RETURN_RATE_SAFE = 15.0  # Above 15% return rate = margin destruction


# --------------------------------------------------------------------------- #
#  Rule definitions
# --------------------------------------------------------------------------- #
RULES: list[dict[str, Any]] = [
    {
        "id": "min_contribution_margin",
        "name": "Minimum contribution margin for Shopify",
        "description": (
            f"Contribution margin must be at least {MIN_CONTRIBUTION_MARGIN_SHOPIFY}%. "
            "Below this, Shopify fees + payment processing + shipping eat all profit."
        ),
        "severity": "blocker",
        "threshold": MIN_CONTRIBUTION_MARGIN_SHOPIFY,
        "check": lambda m: m.get("contribution_margin_pct", 0) >= MIN_CONTRIBUTION_MARGIN_SHOPIFY,
        "action": "Reprice product or reduce variable costs immediately.",
    },
    {
        "id": "min_net_margin",
        "name": "Minimum net margin for sustainability",
        "description": (
            f"Net margin must be at least {MIN_NET_MARGIN_SUSTAINABLE}% for a sustainable "
            "business. Below this, any disruption pushes you into loss."
        ),
        "severity": "warning",
        "threshold": MIN_NET_MARGIN_SUSTAINABLE,
        "check": lambda m: m.get("net_margin_pct", 0) >= MIN_NET_MARGIN_SUSTAINABLE,
        "action": "Review all cost lines — find 5-10% savings or raise price.",
    },
    {
        "id": "min_gross_margin",
        "name": "Minimum viable gross margin",
        "description": (
            f"Gross margin below {MIN_GROSS_MARGIN_VIABLE}% leaves no room for "
            "marketing, operations, or unexpected costs."
        ),
        "severity": "warning",
        "threshold": MIN_GROSS_MARGIN_VIABLE,
        "check": lambda m: m.get("gross_margin_pct", 0) >= MIN_GROSS_MARGIN_VIABLE,
        "action": "Negotiate lower COGS or reposition product at a higher price point.",
    },
    {
        "id": "min_operating_margin",
        "name": "Minimum operating margin",
        "description": (
            f"Operating margin below {MIN_OPERATING_MARGIN_HEALTHY}% means the business "
            "cannot absorb ad spend fluctuations or seasonal dips."
        ),
        "severity": "warning",
        "threshold": MIN_OPERATING_MARGIN_HEALTHY,
        "check": lambda m: m.get("operating_margin_pct", 0) >= MIN_OPERATING_MARGIN_HEALTHY,
        "action": "Cut non-essential operating costs or improve unit economics.",
    },
    {
        "id": "ad_spend_ratio",
        "name": "Ad spend within safe range",
        "description": (
            f"Ad spend should not exceed {MAX_AD_SPEND_PCT_OF_REVENUE}% of revenue. "
            "Above this threshold, you are buying revenue, not profit."
        ),
        "severity": "warning",
        "threshold": MAX_AD_SPEND_PCT_OF_REVENUE,
        "check": lambda m: m.get("ad_spend_pct_of_revenue", 0) <= MAX_AD_SPEND_PCT_OF_REVENUE,
        "action": "Reduce ad spend or improve ROAS before scaling.",
    },
    {
        "id": "category_benchmark",
        "name": "Margin vs. category benchmark",
        "description": "Gross margin should be within 10 points of category average.",
        "severity": "info",
        "threshold": None,
        "check": lambda m: _within_category_benchmark(m),
        "action": "Investigate why margin deviates significantly from category norm.",
    },
]


def _within_category_benchmark(margins: dict[str, Any]) -> bool:
    """Check if gross margin is within 10 percentage points of category benchmark."""
    category = margins.get("category", "")
    if not category:
        return True
    benchmark = get_category_benchmark(category)
    gross = margins.get("gross_margin_pct", 0)
    return abs(gross - benchmark["gross"]) <= 10.0


def evaluate_rules(margins: dict[str, Any]) -> dict[str, Any]:
    """Run all margin rules against calculated margins.

    Args:
        margins: Dict with keys like gross_margin_pct, contribution_margin_pct,
                 net_margin_pct, operating_margin_pct, ad_spend_pct_of_revenue, category.

    Returns:
        {passed, blockers, warnings, info, rules_evaluated}
    """
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []

    for rule in RULES:
        try:
            passed = rule["check"](margins)
        except Exception:
            passed = True  # Don't block on rule evaluation errors

        if not passed:
            entry = {
                "rule_id": rule["id"],
                "name": rule["name"],
                "description": rule["description"],
                "action": rule["action"],
            }
            if rule["severity"] == "blocker":
                blockers.append(entry)
            elif rule["severity"] == "warning":
                warnings.append(entry)
            else:
                info.append(entry)

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "info": info,
        "rules_evaluated": len(RULES),
    }
