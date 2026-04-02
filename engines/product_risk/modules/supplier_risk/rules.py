"""Supplier risk rules — hard constraints and blockers.

Critical rules that MUST be checked before committing to a supplier setup.
Violations = automatic rejection or mandatory warning.

Key blockers:
  - Never rely on a single supplier for critical products
  - Require backup supplier identified for any product >$5K/month revenue
  - Min 2 months safety stock for overseas suppliers
"""
from __future__ import annotations

from typing import Any


RULES = [
    {
        "id": "single_supplier_blocker",
        "name": "Single supplier dependency",
        "description": (
            "Never rely on a single supplier for products generating significant revenue. "
            "One disruption — factory fire, bankruptcy, trade dispute — stops everything."
        ),
        "check": lambda data: data.get("dimensions", {})
            .get("single_source_dependency", {}).get("score", 0) <= 90,
        "severity": "blocker",
        "action": "BLOCKED: Must identify at least one backup supplier before proceeding.",
    },
    {
        "id": "backup_required",
        "name": "Backup supplier required for critical products",
        "description": (
            "Any product expected to generate >$5K/month MUST have a verified backup "
            "supplier with a tested sample and agreed pricing."
        ),
        "check": lambda data: (
            data.get("alternative_availability", {}).get("alternatives_known", 0) >= 1
        ),
        "severity": "blocker",
        "action": "BLOCKED: No backup supplier identified. Find and test at least one alternative.",
    },
    {
        "id": "overseas_safety_stock",
        "name": "Minimum safety stock for overseas suppliers",
        "description": (
            "Overseas suppliers (especially Asia) require minimum 60 days of safety stock. "
            "Lead times are long and unpredictable — holidays, port delays, customs."
        ),
        "check": lambda data: not (
            data.get("input", {}).get("supplier_region", "asia") in ("asia", "europe")
            and data.get("input", {}).get("safety_stock_days", 60) < 60
        ),
        "severity": "warning",
        "action": "Increase safety stock to minimum 60 days for overseas suppliers.",
    },
    {
        "id": "quality_defect_threshold",
        "name": "Defect rate too high",
        "description": (
            "Defect rate above 5% results in excessive returns, negative reviews, "
            "and customer churn. This destroys long-term viability."
        ),
        "check": lambda data: data.get("dimensions", {})
            .get("quality_consistency", {}).get("score", 0) <= 50,
        "severity": "warning",
        "action": "Defect rate is unacceptable. Require supplier quality improvement plan or switch.",
    },
    {
        "id": "geopolitical_high_risk",
        "name": "High geopolitical risk country",
        "description": (
            "Supplier is in a country with elevated geopolitical risk. "
            "Trade policy changes or sanctions could cut off supply without warning."
        ),
        "check": lambda data: data.get("dimensions", {})
            .get("geopolitical_stability", {}).get("score", 0) <= 70,
        "severity": "warning",
        "action": "Geopolitical risk elevated. Must have a supplier in a different country as backup.",
    },
    {
        "id": "communication_unreliable",
        "name": "Communication too slow",
        "description": (
            "Supplier takes >72 hours to respond on average. "
            "Slow communication amplifies every other risk — problems escalate silently."
        ),
        "check": lambda data: data.get("dimensions", {})
            .get("communication_quality", {}).get("score", 0) <= 65,
        "severity": "info",
        "action": "Establish communication SLA with supplier. Escalate if response time exceeds 48h.",
    },
    {
        "id": "financial_instability",
        "name": "Supplier financial risk",
        "description": (
            "Supplier has been in business for less than 2 years. "
            "Young suppliers have higher failure rates — verify financial health."
        ),
        "check": lambda data: data.get("dimensions", {})
            .get("financial_stability", {}).get("score", 0) <= 70,
        "severity": "warning",
        "action": "Supplier is financially young/unstable. Request business references and financials.",
    },
]


def evaluate_rules(
    assessment_data: dict[str, Any],
    input_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all supplier risk rules against the assessment.

    Args:
        assessment_data: Output from code.assess_supplier_risk()["data"]
        input_payload: Original input payload (for rules that check raw input)

    Returns:
        {passed, blockers, warnings, info, rules_evaluated}
    """
    check_data = dict(assessment_data)
    if input_payload:
        check_data["input"] = input_payload

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []

    for rule in RULES:
        try:
            passed = rule["check"](check_data)
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
