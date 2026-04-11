"""Decision logic for cost negotiation.

Pure functions that evaluate supplier data, pricing, and terms
to recommend negotiation strategies and calculate true costs.
"""
from __future__ import annotations

from typing import Any

from .data import VOLUME_DISCOUNT_CURVES


def decide_negotiation_strategy(
    supplier_data: dict[str, Any],
    target_price: float,
) -> dict[str, Any]:
    """Decide which negotiation approach to use based on supplier profile."""
    response_time = supplier_data.get("avg_response_hours", 24)
    years_in_business = supplier_data.get("years_in_business", 1)
    transaction_count = supplier_data.get("transaction_count", 0)
    current_quote = supplier_data.get("quoted_price", target_price * 1.3)
    gap_pct = (current_quote - target_price) / max(current_quote, 0.01) * 100

    # Pick primary strategy based on gap and supplier profile
    if gap_pct > 30:
        primary = "anchor_and_walk"
        reasoning = "Price gap over 30% — anchor aggressively low and be prepared to walk away"
    elif gap_pct > 15:
        primary = "competitive_leverage"
        reasoning = "Moderate gap — present competing quotes to drive price down"
    elif gap_pct > 5:
        primary = "value_add_negotiation"
        reasoning = "Small gap — negotiate value-adds (free shipping, extended warranty) instead of price"
    else:
        primary = "relationship_building"
        reasoning = "Price is near target — focus on building long-term partnership for future orders"

    # Secondary tactics based on supplier profile
    tactics = []
    if response_time < 4:
        tactics.append("Supplier is responsive — push for quick back-and-forth rounds")
    if years_in_business > 5:
        tactics.append("Established supplier — leverage their desire for stable, repeat buyers")
    if transaction_count < 50:
        tactics.append("Newer supplier — they may accept lower margins to build reviews")
    if transaction_count > 500:
        tactics.append("High-volume supplier — they have room to discount on large orders")

    return {
        "primary_strategy": primary,
        "reasoning": reasoning,
        "gap_pct": round(gap_pct, 1),
        "tactics": tactics,
        "estimated_achievable_discount": _estimate_discount(gap_pct, supplier_data),
    }


def _estimate_discount(gap_pct: float, supplier_data: dict[str, Any]) -> float:
    """Estimate realistic discount percentage achievable through negotiation."""
    base_discount = min(gap_pct * 0.6, 25.0)  # Can usually close 60% of the gap, max 25%
    if supplier_data.get("transaction_count", 0) < 50:
        base_discount *= 1.15  # Newer suppliers more flexible
    if supplier_data.get("competitor_count", 0) > 3:
        base_discount *= 1.1  # Competition helps
    return round(min(base_discount, 30.0), 1)


def calculate_volume_discount(
    base_price: float,
    quantities: list[int],
) -> list[dict[str, Any]]:
    """Estimate discount curve for increasing order quantities.

    Uses standard volume discount curves: larger orders get progressively
    better pricing due to reduced per-unit overhead and setup amortization.
    """
    if base_price <= 0:
        return []

    tiers = []
    base_qty = max(quantities[0], 1) if quantities else 100

    for qty in sorted(quantities):
        multiplier = qty / base_qty
        # Find the applicable discount tier from curves
        discount_pct = 0.0
        for threshold, discount_range in sorted(VOLUME_DISCOUNT_CURVES.items()):
            if multiplier >= threshold:
                discount_pct = (discount_range["min"] + discount_range["max"]) / 2
        discounted_price = round(base_price * (1 - discount_pct / 100), 2)
        total_cost = round(discounted_price * qty, 2)
        savings_per_unit = round(base_price - discounted_price, 2)
        tiers.append({
            "quantity": qty,
            "unit_price": discounted_price,
            "discount_pct": round(discount_pct, 1),
            "total_cost": total_cost,
            "savings_per_unit": savings_per_unit,
        })

    return tiers


def evaluate_payment_terms(
    options: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score and rank payment term options by favorability for the buyer.

    Considers: cash flow impact, risk exposure, supplier trust signal,
    and potential for additional discount.
    """
    scored = []
    for opt in options:
        term_type = opt.get("type", "unknown")
        score = 50  # baseline

        # Cash flow — later payment is better for buyer
        days_to_pay = opt.get("days_to_pay", 0)
        score += min(days_to_pay * 0.5, 20)  # up to +20 for longer terms

        # Risk exposure — lower upfront is safer
        upfront_pct = opt.get("upfront_pct", 100)
        score -= upfront_pct * 0.3  # penalize high upfront

        # Protection mechanisms
        if opt.get("has_escrow") or opt.get("has_trade_assurance"):
            score += 15
        if opt.get("has_inspection_clause"):
            score += 10
        if opt.get("has_refund_guarantee"):
            score += 10

        # Discount offered for early payment
        early_discount = opt.get("early_pay_discount_pct", 0)
        score += early_discount * 3  # weight discounts positively

        recommendation = "preferred" if score >= 70 else "acceptable" if score >= 50 else "avoid"
        scored.append({
            **opt,
            "score": round(score, 1),
            "recommendation": recommendation,
            "reasoning": _payment_reasoning(term_type, upfront_pct, score),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def _payment_reasoning(term_type: str, upfront_pct: float, score: float) -> str:
    if upfront_pct >= 100:
        return "Full upfront payment — maximum risk. Avoid unless supplier is highly trusted."
    if upfront_pct <= 30 and score >= 70:
        return "Low deposit with protection — good balance of risk and supplier commitment."
    if term_type == "letter_of_credit":
        return "LC provides bank-backed guarantee — strong protection for both parties."
    return f"Moderate terms — upfront exposure of {upfront_pct}%. Ensure inspection clause."


def calculate_total_landed_cost(
    unit_cost: float,
    shipping: float,
    duties: float,
    insurance: float,
) -> dict[str, float]:
    """Calculate the true total landed cost per unit.

    Landed cost = unit price + shipping + import duties + insurance.
    This is the real cost basis for margin calculations.
    """
    total = round(unit_cost + shipping + duties + insurance, 2)
    return {
        "unit_cost": round(unit_cost, 2),
        "shipping": round(shipping, 2),
        "duties": round(duties, 2),
        "insurance": round(insurance, 2),
        "total_landed_cost": total,
        "cost_multiplier": round(total / max(unit_cost, 0.01), 2),
    }
