"""Cost constraint rules for cost breakdown validation.

These rules define the guardrails that any viable product must meet.
If a product violates these, it's either mispriced or unsellable.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Cost constraint definitions
# ---------------------------------------------------------------------------
COST_RULES: dict[str, dict[str, Any]] = {
    "total_cost_ceiling": {
        "description": "Total cost per unit must be less than 70% of selling price",
        "threshold": 0.70,
        "severity": "critical",
        "action": "Raise price or reduce costs — margin is unsustainable",
    },
    "payment_fee_fixed": {
        "description": "Payment processing fees are non-negotiable — do not attempt to reduce",
        "negotiable": False,
        "severity": "info",
        "action": "Accept as cost of doing business; optimize other line items",
    },
    "shipping_ceiling": {
        "description": "Shipping cost must be less than 15% of selling price",
        "threshold": 0.15,
        "severity": "warning",
        "action": "Negotiate carrier rates, reduce packaging weight, or increase price",
    },
    "returns_budget": {
        "description": "Returns budget should be 8-12% of revenue",
        "min_rate": 0.08,
        "max_rate": 0.12,
        "severity": "warning",
        "action": "Below 8% means you are under-budgeting for returns; above 12% means quality or listing issues",
    },
    "cogs_ceiling": {
        "description": "COGS should be under 40% of selling price for healthy margins",
        "threshold": 0.40,
        "severity": "warning",
        "action": "Negotiate supplier pricing, find alternative sources, or increase order quantities",
    },
    "ad_cost_ceiling": {
        "description": "Customer acquisition cost should be under 20% of selling price",
        "threshold": 0.20,
        "severity": "warning",
        "action": "Improve ad targeting, optimize conversion funnel, or grow organic channels",
    },
    "packaging_ceiling": {
        "description": "Packaging cost should be under 5% of selling price",
        "threshold": 0.05,
        "severity": "info",
        "action": "Order packaging in bulk or simplify packaging design",
    },
    "warehousing_ceiling": {
        "description": "Warehousing cost should be under 8% of selling price",
        "threshold": 0.08,
        "severity": "info",
        "action": "Improve inventory turnover or renegotiate 3PL rates",
    },
}


def validate_cost_constraints(
    breakdown: dict[str, Any], selling_price: float
) -> dict[str, Any]:
    """Validate a cost breakdown against all defined rules.

    Args:
        breakdown: dict with cost category keys and dollar values.
        selling_price: unit selling price in USD.

    Returns:
        Engine contract: {status, data, meta, error}
    """
    if selling_price <= 0:
        return {
            "status": "error",
            "data": None,
            "meta": {},
            "error": "Selling price must be positive",
        }

    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    passed: list[str] = []

    total_cost = breakdown.get("total_cost_per_unit", 0.0)

    # --- Total cost ceiling ---
    total_ratio = total_cost / selling_price
    rule = COST_RULES["total_cost_ceiling"]
    if total_ratio >= rule["threshold"]:
        violations.append({
            "rule": "total_cost_ceiling",
            "severity": rule["severity"],
            "actual": round(total_ratio, 4),
            "threshold": rule["threshold"],
            "action": rule["action"],
        })
    else:
        passed.append("total_cost_ceiling")

    # --- Shipping ceiling ---
    shipping = breakdown.get("shipping_cost", 0.0)
    shipping_ratio = shipping / selling_price
    rule = COST_RULES["shipping_ceiling"]
    if shipping_ratio > rule["threshold"]:
        warnings.append({
            "rule": "shipping_ceiling",
            "severity": rule["severity"],
            "actual": round(shipping_ratio, 4),
            "threshold": rule["threshold"],
            "action": rule["action"],
        })
    else:
        passed.append("shipping_ceiling")

    # --- COGS ceiling ---
    cogs = breakdown.get("cogs", 0.0)
    cogs_ratio = cogs / selling_price
    rule = COST_RULES["cogs_ceiling"]
    if cogs_ratio > rule["threshold"]:
        warnings.append({
            "rule": "cogs_ceiling",
            "severity": rule["severity"],
            "actual": round(cogs_ratio, 4),
            "threshold": rule["threshold"],
            "action": rule["action"],
        })
    else:
        passed.append("cogs_ceiling")

    # --- Ad cost ceiling ---
    ad_cost = breakdown.get("ad_cost_per_unit", 0.0)
    ad_ratio = ad_cost / selling_price
    rule = COST_RULES["ad_cost_ceiling"]
    if ad_ratio > rule["threshold"]:
        warnings.append({
            "rule": "ad_cost_ceiling",
            "severity": rule["severity"],
            "actual": round(ad_ratio, 4),
            "threshold": rule["threshold"],
            "action": rule["action"],
        })
    else:
        passed.append("ad_cost_ceiling")

    # --- Returns budget range ---
    returns_cost = breakdown.get("return_refund_cost", 0.0)
    returns_ratio = returns_cost / selling_price
    rule = COST_RULES["returns_budget"]
    if returns_ratio < rule["min_rate"]:
        warnings.append({
            "rule": "returns_budget",
            "severity": rule["severity"],
            "detail": "Under-budgeted for returns",
            "actual": round(returns_ratio, 4),
            "range": [rule["min_rate"], rule["max_rate"]],
        })
    elif returns_ratio > rule["max_rate"]:
        warnings.append({
            "rule": "returns_budget",
            "severity": rule["severity"],
            "detail": "Returns cost exceeds healthy budget",
            "actual": round(returns_ratio, 4),
            "range": [rule["min_rate"], rule["max_rate"]],
        })
    else:
        passed.append("returns_budget")

    all_pass = len(violations) == 0

    return {
        "status": "success",
        "data": {
            "valid": all_pass,
            "violations": violations,
            "warnings": warnings,
            "passed_rules": passed,
            "total_cost_ratio": round(total_ratio, 4),
        },
        "meta": {
            "rules_checked": len(COST_RULES),
            "violations_count": len(violations),
            "warnings_count": len(warnings),
        },
        "error": None,
    }
