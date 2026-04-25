"""
logic.py — Decision functions for shipping method, margin impact, and packaging.

Higher-level reasoning that combines data, rules, and knowledge
to produce actionable recommendations.
"""

from .data import (
    DIM_WEIGHT_DIVISORS, INTERNATIONAL_COST_MULTIPLIER,
    get_shipping_cost_estimate, get_hazmat_info,
)
from .rules import check_weight_limit
from .utils import billable_weight as _billable_weight


def recommend_shipping_method(product):
    """Recommend the best carrier and method for a product.

    Returns  {carrier, method, estimated_cost, billable_weight_kg, notes}
    """
    weight = product.get("weight_kg", 0)
    dims = product.get("dimensions_cm", {})
    hazmat = product.get("hazmat_class", "none")
    is_intl = product.get("is_international", False)

    billable = _billable_weight(weight, dims)
    notes = []

    hazmat_info = get_hazmat_info(hazmat)
    if not hazmat_info["air_allowed"]:
        notes.append(f"{hazmat_info['label']}: air methods excluded")

    best_cost = get_shipping_cost_estimate(billable, "standard")
    if is_intl:
        best_cost *= INTERNATIONAL_COST_MULTIPLIER
        notes.append("International multiplier applied")

    preferred = ["dhl_express", "ups", "fedex", "usps"] if is_intl else ["usps", "ups", "fedex", "dhl_express"]
    chosen = preferred[0]
    for carrier in preferred:
        if check_weight_limit(billable, carrier)[0]:
            chosen = carrier
            break

    if billable > weight * 1.3:
        notes.append(f"Dim weight ({billable:.1f}kg) exceeds actual ({weight}kg) — consider smaller packaging")

    return {
        "carrier": chosen, "method": "standard",
        "estimated_cost": round(best_cost, 2),
        "billable_weight_kg": round(billable, 2), "notes": notes,
    }


def calculate_shipping_margin_impact(product, shipping_cost):
    """Evaluate how shipping cost affects product profitability.

    Returns  {shipping_pct, margin_before, margin_after, impact_severity, detail}
    """
    price = product.get("price", 0)
    if price <= 0:
        return {"shipping_pct": 100.0, "margin_before": 0.0, "margin_after": -100.0,
                "impact_severity": "critical",
                "detail": "Product price is zero or negative — cannot evaluate margin."}

    from utils.finance import margin_pct
    shipping_pct = (shipping_cost / price) * 100
    cost = product.get("cost", price * 0.6)
    margin_before = margin_pct(price, cost, require_cost=False, precision=None)
    margin_after = margin_before - shipping_pct

    if shipping_pct > 15:
        severity, detail = "critical", f"Shipping consumes {shipping_pct:.1f}% of price, leaving {margin_after:.1f}% margin. Not viable."
    elif shipping_pct > 10:
        severity, detail = "warning", f"Shipping is {shipping_pct:.1f}% of price — margin drops to {margin_after:.1f}%. Consider negotiating carrier rates."
    else:
        severity, detail = "healthy", f"Shipping is {shipping_pct:.1f}% of price. Margin remains {margin_after:.1f}%."

    return {
        "shipping_pct": round(shipping_pct, 2), "margin_before": round(margin_before, 2),
        "margin_after": round(margin_after, 2), "impact_severity": severity, "detail": detail,
    }


def optimize_packaging(dimensions):
    """Suggest packaging adjustments to minimise dimensional weight.

    Returns  {current_dim_weight, optimised_dim_weight, savings_pct, recommendations}
    """
    length = dimensions.get("length", 0)
    width = dimensions.get("width", 0)
    height = dimensions.get("height", 0)
    divisor = DIM_WEIGHT_DIVISORS.get("ups", 5000)

    current_dw = (length * width * height) / divisor if divisor else 0
    recommendations = []

    # Tighter-fit box (10% reduction per side)
    tight_l, tight_w, tight_h = round(length * 0.9, 1), round(width * 0.9, 1), round(height * 0.9, 1)
    tight_dw = (tight_l * tight_w * tight_h) / divisor if divisor else 0

    if tight_dw < current_dw:
        pct = ((current_dw - tight_dw) / current_dw) * 100
        recommendations.append(f"Right-size box to ~{tight_l} x {tight_w} x {tight_h} cm (saves {pct:.0f}% dim weight)")

    if height <= 8 and length <= 40 and width <= 30:
        recommendations.append("Product fits a poly mailer — eliminates box dim weight entirely")

    sorted_dims = sorted([length, width, height])
    if sorted_dims[2] > sorted_dims[0] * 3:
        recommendations.append("Longest dimension is 3x+ the shortest — explore folding or disassembly packaging")

    if height > 15 and width > 15:
        recommendations.append("If product is compressible (textiles, bedding), vacuum-seal to reduce height by up to 60%")

    savings_pct = ((current_dw - tight_dw) / current_dw * 100) if current_dw > 0 else 0.0
    return {
        "current_dim_weight_kg": round(current_dw, 2),
        "optimised_dim_weight_kg": round(tight_dw, 2),
        "savings_pct": round(savings_pct, 1),
        "recommendations": recommendations,
    }
