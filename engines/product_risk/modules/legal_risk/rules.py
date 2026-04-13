"""Legal constraint rules for product risk validation.

These rules define hard blockers and required compliance checks.
Products violating critical rules must not be listed until resolved.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Legal rule definitions
# ---------------------------------------------------------------------------
LEGAL_RULES: dict[str, dict[str, Any]] = {
    "unresolvable_legal_block": {
        "description": "Block products with unresolvable legal issues (banned substances, prohibited items)",
        "severity": "critical",
        "action": "Do not proceed — product cannot legally be sold in this market",
        "auto_block": True,
    },
    "fda_supplement_required": {
        "description": "Supplements must have FDA-compliant labeling and GMP manufacturing",
        "applies_to": ["supplements"],
        "severity": "critical",
        "action": "Obtain GMP certification and create compliant supplement facts panel before listing",
        "auto_block": True,
    },
    "fda_cosmetic_required": {
        "description": "Cosmetics must comply with MoCRA registration and ingredient disclosure",
        "applies_to": ["cosmetics", "beauty"],
        "severity": "critical",
        "action": "Complete MoCRA facility registration and safety substantiation",
        "auto_block": True,
    },
    "cpsc_children_required": {
        "description": "Children's products must pass CPSC testing and have a CPC",
        "applies_to": ["children_products", "children_toys"],
        "severity": "critical",
        "action": "Complete CPSIA testing at accredited lab and file Children's Product Certificate",
        "auto_block": True,
    },
    "fcc_electronics_required": {
        "description": "Electronic devices must have FCC certification for RF emissions",
        "applies_to": ["electronics"],
        "severity": "critical",
        "action": "Obtain FCC certification (intentional or unintentional radiator) before import/sale",
        "auto_block": True,
    },
    "health_claims_substantiation": {
        "description": "Health and efficacy claims must be substantiated with evidence",
        "applies_to": ["supplements", "cosmetics", "food", "medical_devices"],
        "severity": "warning",
        "action": "Remove or substantiate all health claims per FTC guidelines; 'structure/function' claims only for supplements",
    },
    "trademark_clearance": {
        "description": "Product name and branding must not infringe existing trademarks",
        "severity": "warning",
        "action": "Conduct USPTO trademark search before finalizing brand identity",
    },
    "liability_insurance_recommended": {
        "description": "Product liability insurance strongly recommended for physical products",
        "severity": "info",
        "action": "Obtain general product liability policy ($1M coverage minimum)",
        "threshold_monthly_revenue": 5000,
    },
    "import_documentation": {
        "description": "Imported products require proper customs documentation and classification",
        "severity": "warning",
        "action": "Obtain correct HTS code, ensure proper labeling with country of origin",
    },
    "platform_compliance": {
        "description": "Product must comply with all target platform policies",
        "severity": "critical",
        "action": "Review platform-specific restricted and prohibited product lists before listing",
        "auto_block": True,
    },
}

# Categories that are always blocked
PROHIBITED_CATEGORIES: list[str] = [
    "weapons_firearms",
    "controlled_substances",
    "counterfeit_goods",
    "recalled_products",
    "unlicensed_pharmaceuticals",
    "surveillance_equipment",
]


def validate_legal_constraints(
    category: str,
    risk_data: dict[str, Any],
    monthly_revenue: float = 0.0,
) -> dict[str, Any]:
    """Validate a product against all legal rules.

    Args:
        category: product category string.
        risk_data: the 'data' dict from assess_legal_risk result.
        monthly_revenue: projected monthly revenue in USD.

    Returns:
        Engine contract: {status, data, meta, error}.
    """
    if category in PROHIBITED_CATEGORIES:
        return {
            "status": "success",
            "data": {
                "valid": False,
                "blocked": True,
                "block_reason": f"Category '{category}' is prohibited — cannot be sold on any platform",
                "violations": [{"rule": "unresolvable_legal_block", "severity": "critical"}],
                "warnings": [],
                "passed_rules": [],
            },
            "meta": {"rules_checked": 1, "category": category},
            "error": None,
        }

    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    passed: list[str] = []

    dimensions = risk_data.get("dimensions", {})

    for rule_id, rule in LEGAL_RULES.items():
        applies_to = rule.get("applies_to", [])

        # Skip rules that do not apply to this category
        if applies_to and category not in applies_to:
            passed.append(rule_id)
            continue

        # Check category-specific mandatory rules
        triggered = False
        if rule_id == "health_claims_substantiation" and dimensions.get("advertising_claims", 0) >= 40:
            triggered = True
        elif rule_id == "trademark_clearance" and dimensions.get("ip_infringement", 0) >= 30:
            triggered = True
        elif rule_id == "liability_insurance_recommended":
            threshold = rule.get("threshold_monthly_revenue", 5000)
            if monthly_revenue >= threshold and dimensions.get("product_liability", 0) >= 30:
                triggered = True
        elif rule_id == "import_documentation" and dimensions.get("import_restrictions", 0) >= 25:
            triggered = True
        elif rule_id == "platform_compliance" and dimensions.get("platform_policy", 0) >= 25:
            triggered = True
        elif rule.get("auto_block") and applies_to and category in applies_to:
            triggered = True

        if triggered:
            entry = {
                "rule": rule_id,
                "severity": rule["severity"],
                "action": rule["action"],
            }
            if rule["severity"] == "critical":
                violations.append(entry)
            else:
                warnings.append(entry)
        else:
            passed.append(rule_id)

    blocked = any(v["severity"] == "critical" for v in violations)

    return {
        "status": "success",
        "data": {
            "valid": len(violations) == 0,
            "blocked": blocked,
            "block_reason": violations[0]["action"] if blocked else None,
            "violations": violations,
            "warnings": warnings,
            "passed_rules": passed,
        },
        "meta": {
            "rules_checked": len(LEGAL_RULES),
            "violations_count": len(violations),
            "warnings_count": len(warnings),
            "category": category,
        },
        "error": None,
    }
