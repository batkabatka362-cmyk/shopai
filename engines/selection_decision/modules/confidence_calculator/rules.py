"""Confidence rules — action thresholds and guardrails for decision confidence.

Low confidence  (<40%) = require human review before proceeding
Medium confidence (40-70%) = proceed with monitoring and checkpoints
High confidence  (>70%) = auto-proceed with standard parameters

These thresholds are non-negotiable. Overriding them without justification
leads to costly product failures.
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
#  Confidence classification thresholds
# --------------------------------------------------------------------------- #
CONFIDENCE_LOW_THRESHOLD = 40.0
CONFIDENCE_HIGH_THRESHOLD = 70.0

# Minimum acceptable data quality before any decision
MIN_DATA_QUALITY_SCORE = 30.0

# Minimum signal agreement to trust ranking order
MIN_SIGNAL_AGREEMENT = 25.0

# Score gap below which selection is considered arbitrary
MIN_MEANINGFUL_SCORE_GAP = 3.0


# --------------------------------------------------------------------------- #
#  Rule definitions
# --------------------------------------------------------------------------- #
CONFIDENCE_RULES: list[dict[str, Any]] = [
    {
        "id": "low_confidence_human_review",
        "name": "Low confidence requires human review",
        "description": (
            f"When composite confidence is below {CONFIDENCE_LOW_THRESHOLD}%, "
            "the selection must be reviewed by a human before proceeding. "
            "Auto-proceeding at low confidence leads to costly mistakes."
        ),
        "severity": "blocker",
        "check": lambda ctx: ctx.get("composite_score", 0) >= CONFIDENCE_LOW_THRESHOLD,
        "action": "Escalate to human review. Do not order inventory.",
    },
    {
        "id": "medium_confidence_monitoring",
        "name": "Medium confidence requires monitoring",
        "description": (
            f"Confidence between {CONFIDENCE_LOW_THRESHOLD}% and "
            f"{CONFIDENCE_HIGH_THRESHOLD}% — proceed but set a 2-week "
            "review checkpoint to validate the selection."
        ),
        "severity": "warning",
        "check": lambda ctx: not (
            CONFIDENCE_LOW_THRESHOLD <= ctx.get("composite_score", 0) < CONFIDENCE_HIGH_THRESHOLD
        ),
        "action": "Set monitoring alerts and schedule 2-week review.",
    },
    {
        "id": "min_data_quality",
        "name": "Minimum data quality threshold",
        "description": (
            f"Data quality score must be at least {MIN_DATA_QUALITY_SCORE}. "
            "Below this, too many engines are missing data to make any "
            "meaningful decision."
        ),
        "severity": "blocker",
        "check": lambda ctx: ctx.get("data_quality_score", 0) >= MIN_DATA_QUALITY_SCORE,
        "action": "Gather more data before making a selection decision.",
    },
    {
        "id": "min_signal_agreement",
        "name": "Minimum engine agreement",
        "description": (
            f"Signal agreement must be at least {MIN_SIGNAL_AGREEMENT}. "
            "When engines strongly disagree, the ranking is unreliable."
        ),
        "severity": "warning",
        "check": lambda ctx: ctx.get("signal_agreement_score", 0) >= MIN_SIGNAL_AGREEMENT,
        "action": "Investigate engine conflicts. Understand why engines disagree.",
    },
    {
        "id": "meaningful_score_gap",
        "name": "Score gap must be meaningful",
        "description": (
            f"The gap between #1 and #2 must be at least {MIN_MEANINGFUL_SCORE_GAP}%. "
            "Below this threshold, the selection between top products is "
            "essentially random."
        ),
        "severity": "info",
        "check": lambda ctx: ctx.get("score_gap", 0) >= MIN_MEANINGFUL_SCORE_GAP,
        "action": "Consider the top 2 products equally viable. Choose based on preference.",
    },
]


def evaluate_confidence_rules(context: dict[str, Any]) -> dict[str, Any]:
    """Run all confidence rules against the current context.

    Args:
        context: {
            composite_score: float,
            data_quality_score: float,
            signal_agreement_score: float,
            score_gap: float,
        }

    Returns:
        {passed: bool, blockers: list, warnings: list, info: list, rules_evaluated: int}
    """
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []

    for rule in CONFIDENCE_RULES:
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

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "info": info,
        "rules_evaluated": len(CONFIDENCE_RULES),
    }
