"""Ranking constraint rules for product selection.

These rules define the hard requirements a product must meet to be
included in the ranking, and the conditions under which ranking
results should be trusted or questioned.
"""

from __future__ import annotations

from typing import Any

from .data import MINIMUM_VIABLE_SCORE

# ---------------------------------------------------------------------------
# Ranking rule definitions
# ---------------------------------------------------------------------------
RANKING_RULES: dict[str, dict[str, Any]] = {
    "minimum_score": {
        "description": "Product must score at least 40 to be considered for ranking",
        "threshold": MINIMUM_VIABLE_SCORE,
        "severity": "critical",
        "action": "Products below minimum score are disqualified — improve or discard",
    },
    "positive_profitability": {
        "description": "Product must have positive projected profitability",
        "severity": "critical",
        "action": "Cannot rank unprofitable products — fix pricing, costs, or supplier terms",
    },
    "risk_not_critical": {
        "description": "Products with critical risk level are excluded from ranking",
        "severity": "critical",
        "action": "Mitigate critical risks before product can be considered for selection",
    },
    "minimum_products_for_comparison": {
        "description": "At least 2 products needed for meaningful ranking comparison",
        "threshold": 2,
        "severity": "warning",
        "action": "Add more product candidates — ranking one product is not a comparison",
    },
    "maximum_products_for_efficiency": {
        "description": "Ranking more than 20 products is wasteful — pre-filter first",
        "threshold": 20,
        "severity": "info",
        "action": "Use filter engine to reduce candidates to top 10-15 before ranking",
    },
    "confidence_gate": {
        "description": "Products with low confidence should be flagged in ranking",
        "min_confidence": "moderate",
        "severity": "warning",
        "action": "Low-confidence products may rank incorrectly — gather more data",
    },
    "score_freshness": {
        "description": "Rankings based on stale scores (>30 days) are unreliable",
        "max_age_days": 30,
        "severity": "warning",
        "action": "Re-run upstream engines before trusting ranking for decision-making",
    },
    "tier_distribution_check": {
        "description": "If all products are in the same tier, data may lack discriminating power",
        "severity": "info",
        "action": "Consider adding more evaluation dimensions to differentiate products",
    },
}


def validate_ranking_inputs(
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate product list against ranking rules.

    Args:
        products: list of product dicts with unified_score and metadata.

    Returns:
        Dict with valid flag, violations, warnings, and whether to block.
    """
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    passed: list[str] = []
    block = False

    # --- Minimum products for comparison ---
    rule = RANKING_RULES["minimum_products_for_comparison"]
    qualified_count = sum(
        1 for p in products
        if p.get("unified_score", 0) >= MINIMUM_VIABLE_SCORE
        and p.get("risk_level", "moderate") != "critical"
        and p.get("profitability_positive", True)
    )

    if qualified_count < 1:
        violations.append({
            "rule": "no_qualified_products",
            "severity": "critical",
            "action": "No products meet minimum ranking criteria",
        })
        block = True
    elif qualified_count < rule["threshold"]:
        warnings.append({
            "rule": "minimum_products_for_comparison",
            "severity": rule["severity"],
            "qualified_count": qualified_count,
            "threshold": rule["threshold"],
            "action": rule["action"],
        })
    else:
        passed.append("minimum_products_for_comparison")

    # --- Maximum products for efficiency ---
    rule = RANKING_RULES["maximum_products_for_efficiency"]
    if len(products) > rule["threshold"]:
        warnings.append({
            "rule": "maximum_products_for_efficiency",
            "severity": rule["severity"],
            "product_count": len(products),
            "threshold": rule["threshold"],
            "action": rule["action"],
        })
    else:
        passed.append("maximum_products_for_efficiency")

    # --- Check for low-confidence products ---
    low_confidence_count = sum(
        1 for p in products
        if p.get("confidence", {}).get("level") == "low"
    )
    if low_confidence_count > 0:
        warnings.append({
            "rule": "confidence_gate",
            "severity": "warning",
            "low_confidence_count": low_confidence_count,
            "action": RANKING_RULES["confidence_gate"]["action"],
        })
    else:
        passed.append("confidence_gate")

    # --- Score distribution check ---
    scores = [p.get("unified_score", 0) for p in products if p.get("unified_score", 0) > 0]
    if scores and len(scores) >= 3:
        spread = max(scores) - min(scores)
        if spread < 10:
            warnings.append({
                "rule": "tier_distribution_check",
                "severity": "info",
                "score_spread": round(spread, 1),
                "action": RANKING_RULES["tier_distribution_check"]["action"],
            })
        else:
            passed.append("tier_distribution_check")

    return {
        "valid": len(violations) == 0,
        "block": block,
        "violations": violations,
        "warnings": warnings,
        "passed_rules": passed,
        "qualified_count": qualified_count,
        "total_products": len(products),
    }


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {},
        "error": message,
    }
