"""
Constraints and validation rules for MOQ decisions.
Each rule returns True when the constraint is satisfied.
"""

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Maximum share of total budget that may be locked in a single MOQ purchase.
MAX_INVENTORY_INVESTMENT_PCT = 0.40

# Maximum months of inventory a single MOQ order should represent.
MAX_MONTHS_INVENTORY = 6

# Minimum expected sell-through rate (0-1) before committing to an MOQ.
MIN_SELL_THROUGH_RATE = 0.60

# After paying for the MOQ, at least this fraction of total budget must remain
# as a cash reserve for ads, returns, and operating costs.
CASH_RESERVE_REQUIREMENT_PCT = 0.25

# Maximum acceptable capital-at-risk as a percentage of budget.
MAX_CAPITAL_AT_RISK_PCT = 0.15

# Minimum gross margin per unit required to justify the order.
MIN_GROSS_MARGIN_PCT = 0.30

# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def validate_moq_against_budget(investment, budget):
    """True if MOQ investment stays within the allowed budget share."""
    if budget <= 0:
        return False
    return (investment / budget) <= MAX_INVENTORY_INVESTMENT_PCT


def validate_inventory_months(months_of_stock):
    """True if inventory duration is at or below the maximum."""
    return months_of_stock <= MAX_MONTHS_INVENTORY


def validate_sell_through(sell_through_est):
    """True if expected sell-through meets the minimum threshold."""
    return sell_through_est >= MIN_SELL_THROUGH_RATE


def check_cash_reserve(investment, budget):
    """True if enough cash remains after the purchase to cover operations."""
    if budget <= 0:
        return False
    remaining = budget - investment
    return (remaining / budget) >= CASH_RESERVE_REQUIREMENT_PCT


def validate_capital_at_risk(capital_at_risk, budget):
    """True if the capital at risk is within acceptable limits."""
    if budget <= 0:
        return False
    return (capital_at_risk / budget) <= MAX_CAPITAL_AT_RISK_PCT


def validate_gross_margin(sell_price, unit_cost):
    """True if per-unit gross margin percentage meets the minimum."""
    if sell_price <= 0:
        return False
    margin_pct = (sell_price - unit_cost) / sell_price
    return margin_pct >= MIN_GROSS_MARGIN_PCT


def evaluate_all_constraints(investment, budget, months_of_stock,
                             sell_through_est, capital_at_risk,
                             sell_price, unit_cost):
    """
    Run every constraint and return a summary dict.
    Keys are rule names; values are booleans.
    """
    return {
        "budget_ok": validate_moq_against_budget(investment, budget),
        "inventory_months_ok": validate_inventory_months(months_of_stock),
        "sell_through_ok": validate_sell_through(sell_through_est),
        "cash_reserve_ok": check_cash_reserve(investment, budget),
        "capital_at_risk_ok": validate_capital_at_risk(capital_at_risk, budget),
        "gross_margin_ok": validate_gross_margin(sell_price, unit_cost),
    }


def constraints_passing_count(results):
    """Return (passing, total) from an evaluate_all_constraints result."""
    total = len(results)
    passing = sum(1 for v in results.values() if v)
    return passing, total


def format_constraint_report(results):
    """Human-readable multi-line report of constraint outcomes."""
    lines = []
    labels = {
        "budget_ok": "Budget allocation",
        "inventory_months_ok": "Inventory duration",
        "sell_through_ok": "Sell-through rate",
        "cash_reserve_ok": "Cash reserve",
        "capital_at_risk_ok": "Capital at risk",
        "gross_margin_ok": "Gross margin",
    }
    for key, passed in results.items():
        status = "PASS" if passed else "FAIL"
        label = labels.get(key, key)
        lines.append(f"  [{status}] {label}")
    passing, total = constraints_passing_count(results)
    lines.append(f"\n  Result: {passing}/{total} constraints satisfied.")
    return "\n".join(lines)
