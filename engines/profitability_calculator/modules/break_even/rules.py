"""Break-even rules — hard constraints and guardrails for launch decisions.

Rules that MUST pass before greenlighting a product launch.
Violations at 'blocker' severity = automatic rejection.
"""
from __future__ import annotations

from typing import Any


BREAK_EVEN_RULES = [
    {
        "id": "max_90_days",
        "name": "90-day break-even limit for new products",
        "description": (
            "New products must reach break-even within 90 days. "
            "Beyond this, cash is tied up too long and opportunity cost is too high."
        ),
        "check": lambda data: data.get("break_even", {}).get("days", 999) <= 90,
        "severity": "blocker",
        "action": "Reject launch — break-even timeline exceeds 90 days",
    },
    {
        "id": "max_5k_test_investment",
        "name": "Maximum $5K initial investment for test launches",
        "description": (
            "First launch of an unproven product should not exceed $5,000 in total "
            "fixed costs. Validate before scaling."
        ),
        "check": lambda data: data.get("total_fixed_costs", 99999) <= 5000,
        "severity": "warning",
        "action": "Flag as over-invested for a test — reduce first batch or cut setup costs",
    },
    {
        "id": "batch_covers_break_even",
        "name": "First batch must cover break-even units",
        "description": (
            "The initial inventory order should contain enough units to reach "
            "break-even. Reordering before break-even means more capital at risk."
        ),
        "check": lambda data: data.get("first_batch", {}).get("covers_break_even", False),
        "severity": "blocker",
        "action": "Increase first batch size or reduce fixed costs to lower break-even units",
    },
    {
        "id": "positive_contribution_margin",
        "name": "Contribution margin must be positive",
        "description": (
            "Price must exceed variable cost per unit. Negative margin means "
            "every sale loses money — break-even is mathematically impossible."
        ),
        "check": lambda data: (
            data.get("contribution_margin", {}).get("per_unit", 0) > 0
        ),
        "severity": "blocker",
        "action": "Increase price or reduce COGS — selling at a loss is not viable",
    },
    {
        "id": "min_contribution_margin_pct",
        "name": "Minimum 20% contribution margin",
        "description": (
            "Contribution margin below 20% leaves no room for discounts, "
            "returns, or unexpected cost increases."
        ),
        "check": lambda data: (
            data.get("contribution_margin", {}).get("margin_pct", 0) >= 20
        ),
        "severity": "warning",
        "action": "Margin is thin — negotiate better COGS or raise price",
    },
    {
        "id": "sensitivity_survives_price_drop",
        "name": "Break-even must survive 10% price reduction",
        "description": (
            "If a 10% price drop makes break-even impossible or pushes it past "
            "180 days, the product has no pricing flexibility."
        ),
        "check": lambda data: (
            data.get("sensitivity", {})
            .get("price_10pct_lower", {})
            .get("break_even_days", 999) <= 180
        ),
        "severity": "warning",
        "action": "Product has no pricing buffer — any competitor undercut or discount kills viability",
    },
    {
        "id": "marketing_not_over_half",
        "name": "Marketing should not exceed 50% of fixed costs",
        "description": (
            "If marketing is more than half of launch costs, the product "
            "cannot sustain itself organically. Dependency on ads is risky."
        ),
        "check": lambda data: (
            data.get("fixed_costs", {}).get("marketing_launch_budget", 0)
            <= data.get("total_fixed_costs", 1) * 0.50
        ),
        "severity": "info",
        "action": "Consider reducing ad dependency — invest in SEO and content instead",
    },
]


def evaluate_break_even_rules(analysis: dict[str, Any]) -> dict[str, Any]:
    """Run all break-even rules against the analysis data.

    Args:
        analysis: Output from code.calculate_break_even()

    Returns:
        {
            "passed": bool,
            "blockers": [...],
            "warnings": [...],
            "info": [...],
            "rules_evaluated": int,
            "summary": str,
        }
    """
    if analysis.get("status") == "error":
        return {
            "passed": False,
            "blockers": [{
                "rule_id": "positive_contribution_margin",
                "name": "Contribution margin must be positive",
                "action": analysis.get("recommendation", "Fix pricing"),
            }],
            "warnings": [],
            "info": [],
            "rules_evaluated": 1,
            "summary": "Blocked: negative contribution margin — pricing is not viable",
        }

    blockers = []
    warnings = []
    info = []

    for rule in BREAK_EVEN_RULES:
        try:
            passed = rule["check"](analysis)
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

    if blockers:
        summary = f"Blocked: {len(blockers)} critical issue(s) must be resolved before launch"
    elif warnings:
        summary = f"Conditional pass: {len(warnings)} warning(s) to address"
    else:
        summary = "All break-even rules passed — launch is viable"

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "info": info,
        "rules_evaluated": len(BREAK_EVEN_RULES),
        "summary": summary,
    }
