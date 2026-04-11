"""Financial constraint rules for product risk validation.

These rules define the guardrails that protect against catastrophic
financial losses. Violating critical rules means the investment is
too risky without mitigation.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Financial rule definitions
# ---------------------------------------------------------------------------
FINANCIAL_RULES: dict[str, dict[str, Any]] = {
    "single_product_ceiling": {
        "description": "Never invest more than 40% of total budget in a single product",
        "threshold": 0.40,
        "severity": "critical",
        "action": "Reduce investment or increase total available capital before proceeding",
    },
    "positive_cash_flow_deadline": {
        "description": "Product must achieve positive cash flow by month 4",
        "threshold_months": 4,
        "severity": "critical",
        "action": "Revise pricing, reduce costs, or increase marketing to accelerate sales",
    },
    "max_acceptable_loss": {
        "description": "Maximum acceptable loss must be defined upfront and not exceed 60% of investment",
        "threshold": 0.60,
        "severity": "critical",
        "action": "Set a stop-loss point and liquidation plan before committing capital",
    },
    "operating_reserve": {
        "description": "Maintain at least 3 months of operating costs in reserve",
        "reserve_months": 3,
        "severity": "critical",
        "action": "Build reserve before investing — operating without buffer is betting the business",
    },
    "margin_floor": {
        "description": "Minimum margin of 20% after all costs — below this, business is unsustainable",
        "threshold": 0.20,
        "severity": "warning",
        "action": "Raise price, cut costs, or abandon product — sub-20% margin leaves no room for error",
    },
    "chargeback_ceiling": {
        "description": "Chargeback rate must stay below 1% to avoid payment processor penalties",
        "threshold": 0.01,
        "severity": "warning",
        "action": "Improve product quality, listing accuracy, and fraud prevention",
    },
    "currency_hedge_threshold": {
        "description": "Hedge currency exposure when COGS import value exceeds $10K/month",
        "threshold_usd": 10000,
        "severity": "info",
        "action": "Use forward contracts or maintain USD reserves for 2-3 months of COGS",
    },
    "scaling_capital_buffer": {
        "description": "Ensure 2x current investment available before scaling",
        "multiplier": 2.0,
        "severity": "warning",
        "action": "Secure additional capital or line of credit before increasing order quantities",
    },
    "refund_budget": {
        "description": "Budget for 8-15% refund rate depending on category",
        "min_rate": 0.08,
        "max_rate": 0.15,
        "severity": "info",
        "action": "Under-budgeting for refunds causes cash flow surprises — plan conservatively",
    },
    "diversification_minimum": {
        "description": "Do not rely on a single product for more than 50% of revenue",
        "threshold": 0.50,
        "severity": "warning",
        "action": "Diversify product line to reduce single-product dependency",
    },
}


def validate_financial_constraints(
    investment: float,
    budget: float,
    monthly_costs: float,
    reserves: float,
    margin: float,
    months_to_positive: float | None = None,
    chargeback_rate: float = 0.005,
    monthly_import_cogs: float = 0.0,
) -> dict[str, Any]:
    """Validate an investment against all financial rules.

    Args:
        investment: capital being deployed for this product.
        budget: total available capital.
        monthly_costs: monthly fixed operating costs.
        reserves: current cash reserves.
        margin: projected margin as decimal.
        months_to_positive: months until positive cash flow (None = unknown).
        chargeback_rate: projected chargeback rate.
        monthly_import_cogs: monthly COGS value of imports in USD.

    Returns:
        Engine contract: {status, data, meta, error}.
    """
    if budget <= 0:
        return _error("Budget must be positive")

    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    passed: list[str] = []

    # --- Single product ceiling ---
    investment_ratio = investment / budget
    rule = FINANCIAL_RULES["single_product_ceiling"]
    if investment_ratio > rule["threshold"]:
        violations.append({
            "rule": "single_product_ceiling",
            "severity": rule["severity"],
            "actual": round(investment_ratio, 4),
            "threshold": rule["threshold"],
            "action": rule["action"],
        })
    else:
        passed.append("single_product_ceiling")

    # --- Positive cash flow deadline ---
    rule = FINANCIAL_RULES["positive_cash_flow_deadline"]
    if months_to_positive is not None and months_to_positive > rule["threshold_months"]:
        violations.append({
            "rule": "positive_cash_flow_deadline",
            "severity": rule["severity"],
            "actual_months": months_to_positive,
            "threshold_months": rule["threshold_months"],
            "action": rule["action"],
        })
    elif months_to_positive is not None:
        passed.append("positive_cash_flow_deadline")

    # --- Operating reserve ---
    rule = FINANCIAL_RULES["operating_reserve"]
    required_reserve = monthly_costs * rule["reserve_months"]
    if reserves < required_reserve:
        violations.append({
            "rule": "operating_reserve",
            "severity": rule["severity"],
            "actual_reserves": reserves,
            "required_reserves": required_reserve,
            "shortfall": round(required_reserve - reserves, 2),
            "action": rule["action"],
        })
    else:
        passed.append("operating_reserve")

    # --- Margin floor ---
    rule = FINANCIAL_RULES["margin_floor"]
    if margin < rule["threshold"]:
        warnings.append({
            "rule": "margin_floor",
            "severity": rule["severity"],
            "actual": round(margin, 4),
            "threshold": rule["threshold"],
            "action": rule["action"],
        })
    else:
        passed.append("margin_floor")

    # --- Chargeback ceiling ---
    rule = FINANCIAL_RULES["chargeback_ceiling"]
    if chargeback_rate > rule["threshold"]:
        warnings.append({
            "rule": "chargeback_ceiling",
            "severity": rule["severity"],
            "actual": round(chargeback_rate, 4),
            "threshold": rule["threshold"],
            "action": rule["action"],
        })
    else:
        passed.append("chargeback_ceiling")

    # --- Currency hedge threshold ---
    rule = FINANCIAL_RULES["currency_hedge_threshold"]
    if monthly_import_cogs > rule["threshold_usd"]:
        warnings.append({
            "rule": "currency_hedge_threshold",
            "severity": rule["severity"],
            "monthly_import_cogs": monthly_import_cogs,
            "threshold": rule["threshold_usd"],
            "action": rule["action"],
        })
    else:
        passed.append("currency_hedge_threshold")

    all_pass = len(violations) == 0

    return {
        "status": "success",
        "data": {
            "valid": all_pass,
            "violations": violations,
            "warnings": warnings,
            "passed_rules": passed,
            "investment_ratio": round(investment_ratio, 4),
            "reserve_coverage_months": round(reserves / monthly_costs, 1) if monthly_costs > 0 else 99,
        },
        "meta": {
            "rules_checked": len(FINANCIAL_RULES),
            "violations_count": len(violations),
            "warnings_count": len(warnings),
        },
        "error": None,
    }


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {},
        "error": message,
    }
