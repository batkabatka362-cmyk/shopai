"""Final selector rules — hard constraints for the selection decision.

Selected product must pass all filter gates. Confidence must exceed 40%.
Risk must not be critical. Profitability must be positive. These rules
are the last line of defense before committing resources.
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
#  Selection gate thresholds
# --------------------------------------------------------------------------- #
MIN_CONFIDENCE_FOR_SELECTION = 40.0
MIN_UNIFIED_SCORE = 30.0
MIN_PROFITABILITY_SCORE = 20.0
MAX_ACCEPTABLE_RISK = "high"  # "critical" is not acceptable

# Confidence threshold for auto-proceed (no human review)
AUTO_PROCEED_CONFIDENCE = 70.0

# Minimum backup product score as % of primary
BACKUP_MIN_RATIO = 0.60


# --------------------------------------------------------------------------- #
#  Rule definitions
# --------------------------------------------------------------------------- #
SELECTION_RULES: list[dict[str, Any]] = [
    {
        "id": "min_confidence",
        "name": "Minimum confidence for selection",
        "description": (
            f"Confidence must be at least {MIN_CONFIDENCE_FOR_SELECTION}% to proceed "
            "with a selection. Below this, the decision is essentially a guess."
        ),
        "severity": "blocker",
        "check": lambda ctx: ctx.get("confidence_score", 0) >= MIN_CONFIDENCE_FOR_SELECTION,
        "action": (
            "Gather more data or broaden your product candidate pool. "
            "Do not commit inventory at this confidence level."
        ),
    },
    {
        "id": "no_critical_risk",
        "name": "No critical-level risk",
        "description": (
            "Selected product must not have critical risk. Critical risk "
            "means legal issues, supply chain collapse, or market exit "
            "that could destroy the business."
        ),
        "severity": "blocker",
        "check": lambda ctx: not ctx.get("has_critical_risk", False),
        "action": "Reject this product. Move to backup or restart search.",
    },
    {
        "id": "min_unified_score",
        "name": "Minimum viable product score",
        "description": (
            f"Unified score must be at least {MIN_UNIFIED_SCORE}. Below this, "
            "the product has too many weaknesses across dimensions."
        ),
        "severity": "blocker",
        "check": lambda ctx: (
            ctx.get("product", {}).get("unified_score", 0) >= MIN_UNIFIED_SCORE
        ),
        "action": "This product is not viable. Explore different product categories.",
    },
    {
        "id": "positive_profitability",
        "name": "Profitability must be positive",
        "description": (
            f"Profitability score must be at least {MIN_PROFITABILITY_SCORE}. "
            "Selling a product at a loss is not a business — it is a hobby."
        ),
        "severity": "blocker",
        "check": lambda ctx: (ctx.get("profitability_score") or 0) >= MIN_PROFITABILITY_SCORE,
        "action": "Renegotiate supplier pricing or find a higher-margin alternative.",
    },
    {
        "id": "auto_proceed_check",
        "name": "Auto-proceed confidence check",
        "description": (
            f"Confidence above {AUTO_PROCEED_CONFIDENCE}% qualifies for "
            "auto-proceed without human review. Below this, monitoring is required."
        ),
        "severity": "info",
        "check": lambda ctx: ctx.get("confidence_score", 0) >= AUTO_PROCEED_CONFIDENCE,
        "action": "Set up monitoring dashboard and 2-week review checkpoint.",
    },
]


def evaluate_selection_rules(context: dict[str, Any]) -> dict[str, Any]:
    """Run all selection rules against the decision context.

    Args:
        context: {
            product: dict (the selected product),
            confidence_score: float,
            has_critical_risk: bool,
            profitability_score: float,
        }

    Returns:
        {passed: bool, blockers: list, warnings: list, info: list,
         rules_evaluated: int, can_auto_proceed: bool}
    """
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []

    for rule in SELECTION_RULES:
        try:
            passed = rule["check"](context)
        except Exception:
            passed = True

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

    all_passed = len(blockers) == 0
    can_auto = (
        all_passed
        and context.get("confidence_score", 0) >= AUTO_PROCEED_CONFIDENCE
    )

    return {
        "passed": all_passed,
        "blockers": blockers,
        "warnings": warnings,
        "info": info,
        "rules_evaluated": len(SELECTION_RULES),
        "can_auto_proceed": can_auto,
    }
