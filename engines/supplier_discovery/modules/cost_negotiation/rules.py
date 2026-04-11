"""Hard rules and constraints for supplier payment and ordering.

These are non-negotiable safeguards that protect the buyer from
common sourcing pitfalls. Every negotiation plan must pass these
checks before being acted on.
"""
from __future__ import annotations

from typing import Any


# --- Hard constraints ---

MAX_UPFRONT_DEPOSIT_PCT = 30
"""Never pay more than 30% upfront as a deposit. The balance should be
due only after production is complete and inspection passes."""

REQUIRE_SAMPLE_BEFORE_ORDER = True
"""Always get a physical sample approved before placing a production order.
No exceptions — even if the supplier has great reviews."""

REQUIRE_INSPECTION_BEFORE_BALANCE = True
"""Require a third-party or self-inspection of the production run before
releasing the remaining balance payment."""

REQUIRE_PAYMENT_PROTECTION = True
"""All payments must go through a protected channel: Trade Assurance,
escrow, Letter of Credit, or PayPal (for smaller amounts). Never send
money via direct wire with no recourse."""

MIN_PAYMENT_MILESTONES = 2
"""Split payment into at least 2 milestones: deposit + balance after
inspection. For orders over $10k, consider 3 milestones."""

MAX_FIRST_ORDER_VALUE_USD = 5000
"""First order with any new supplier should not exceed $5,000 to limit
risk while evaluating quality and reliability."""


# --- Validation functions ---

def validate_deposit_amount(deposit_pct: float, order_value: float = 0) -> dict[str, Any]:
    """Check that the proposed deposit does not exceed the max allowed."""
    if deposit_pct > MAX_UPFRONT_DEPOSIT_PCT:
        return {
            "valid": False,
            "rule": "max_deposit",
            "message": (
                f"Deposit of {deposit_pct}% exceeds maximum of {MAX_UPFRONT_DEPOSIT_PCT}%. "
                f"Counter-offer with {MAX_UPFRONT_DEPOSIT_PCT}% deposit and balance after inspection."
            ),
            "suggested_deposit_pct": MAX_UPFRONT_DEPOSIT_PCT,
        }
    if deposit_pct == 100:
        return {
            "valid": False,
            "rule": "no_full_upfront",
            "message": "Never pay 100% upfront. Insist on milestone-based payments.",
            "suggested_deposit_pct": MAX_UPFRONT_DEPOSIT_PCT,
        }
    return {"valid": True, "rule": "max_deposit", "message": "Deposit amount is acceptable."}


def validate_payment_terms(terms: dict[str, Any]) -> dict[str, Any]:
    """Validate that payment terms meet all safety rules."""
    issues = []

    if not terms.get("has_protection"):
        issues.append({
            "rule": "payment_protection",
            "message": "Payment protection required. Use Trade Assurance, escrow, or LC.",
        })

    milestones = terms.get("milestone_count", 1)
    if milestones < MIN_PAYMENT_MILESTONES:
        issues.append({
            "rule": "min_milestones",
            "message": f"Need at least {MIN_PAYMENT_MILESTONES} payment milestones, got {milestones}.",
        })

    upfront = terms.get("upfront_pct", 0)
    if upfront > MAX_UPFRONT_DEPOSIT_PCT:
        issues.append({
            "rule": "max_deposit",
            "message": f"Upfront payment of {upfront}% exceeds max of {MAX_UPFRONT_DEPOSIT_PCT}%.",
        })

    if not terms.get("inspection_before_balance", False):
        issues.append({
            "rule": "inspection_required",
            "message": "Must include inspection clause before releasing balance payment.",
        })

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "terms_evaluated": terms,
    }


def validate_order_safeguards(order_data: dict[str, Any]) -> dict[str, Any]:
    """Run all safeguard checks on a proposed order."""
    warnings = []
    blockers = []

    # Sample check
    if not order_data.get("sample_approved", False):
        blockers.append("Must approve a physical sample before placing production order.")

    # First order value cap
    order_value = order_data.get("total_order_value", 0)
    is_first_order = order_data.get("is_first_order", True)
    if is_first_order and order_value > MAX_FIRST_ORDER_VALUE_USD:
        warnings.append(
            f"First order value ${order_value:,.0f} exceeds recommended "
            f"max of ${MAX_FIRST_ORDER_VALUE_USD:,.0f}. Consider reducing quantity."
        )

    # Payment protection
    if not order_data.get("payment_protection", False):
        blockers.append("Payment protection (Trade Assurance, escrow, or LC) is required.")

    # Deposit check
    deposit_pct = order_data.get("deposit_pct", 0)
    if deposit_pct > MAX_UPFRONT_DEPOSIT_PCT:
        blockers.append(
            f"Deposit of {deposit_pct}% exceeds maximum of {MAX_UPFRONT_DEPOSIT_PCT}%."
        )

    return {
        "can_proceed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "checks_passed": 4 - len(blockers),
        "checks_total": 4,
    }
