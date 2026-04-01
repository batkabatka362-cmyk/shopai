"""
logic.py — Decision functions for shipping method, margin impact, and packaging.

Higher-level reasoning that combines data, rules, and knowledge
to produce actionable recommendations.
"""

from .data import (
    CARRIER_LIMITS,
    DIM_WEIGHT_DIVISORS,
    COST_BY_WEIGHT_TIER,
    INTERNATIONAL_COST_MULTIPLIER,
    get_shipping_cost_estimate,
    get_hazmat_info,
)
from .rules import (
    check_hazmat_restrictions,
    check_weight_limit,
    check_size_constraints,
)


def _billable_weight(weight_kg, dimensions_cm, divisor=5000):
    """Return the greater of actual weight and dimensional weight."""
    length = dimensions_cm.get("length", 0)
    width = dimensions_cm.get("width", 0)
    height = dimensions_cm.get("height", 0)
    dim_weight = (length * width * height) / divisor if divisor else weight_kg
    return max(weight_kg, dim_weight)


def recommend_shipping_method(product):
    """Recommend the best carrier and method for a product.

    Parameters
    ----------
    product : dict
        Keys: weight_kg, dimensions_cm, hazmat_class, price,
              is_international, destination_country.

    Returns
    -------
    dict  {carrier, method, estimated_cost, notes}
    """
    weight = product.get("weight_kg", 0)
    dims = product.get("dimensions_cm", {})
    hazmat = product.get("hazmat_class", "none")
    is_intl = product.get("is_international", False)

    billable = _billable_weight(weight, dims)
    notes = []

    # Determine viable methods based on hazmat
    hazmat_info = get_hazmat_info(hazmat)
    viable_methods = ["standard"]
    if hazmat_info["air_allowed"]:
        viable_methods.extend(["express", "overnight"])
    else:
        notes.append(f"{hazmat_info['label']}: air methods excluded")

    # Pick cheapest viable method
    best_method = viable_methods[0]
    best_cost = get_shipping_cost_estimate(billable, best_method)

    if is_intl:
        best_cost *= INTERNATIONAL_COST_MULTIPLIER
        notes.append("International multiplier applied")

    # Carrier selection: prefer cheapest that accepts the weight
    preferred_order = ["usps", "ups", "fedex", "dhl_express"]
    if is_intl:
        preferred_order = ["dhl_express", "ups", "fedex", "usps"]

    chosen_carrier = preferred_order[0]
    for carrier in preferred_order:
        ok, _ = check_weight_limit(billable, carrier)
        if ok:
            chosen_carrier = carrier
            break

    if billable > weight * 1.3:
        notes.append(
            f"Dim weight ({billable:.1f}kg) exceeds actual ({weight}kg) — "
            f"consider smaller packaging"
        )

    return {
        "carrier": chosen_carrier,
        "method": best_method,
        "estimated_cost": round(best_cost, 2),
        "billable_weight_kg": round(billable, 2),
        "notes": notes,
    }


def calculate_shipping_margin_impact(product, shipping_cost):
    """Evaluate how shipping cost affects product profitability.

    Parameters
    ----------
    product : dict        Must contain 'price'; optionally 'cost', 'margin_pct'.
    shipping_cost : float  Total estimated shipping cost in USD.

    Returns
    -------
    dict  {shipping_pct, margin_before, margin_after, impact_severity, detail}
    """
    price = product.get("price", 0)
    if price <= 0:
        return {
            "shipping_pct": 100.0,
            "margin_before": 0.0,
            "margin_after": -100.0,
            "impact_severity": "critical",
            "detail": "Product price is zero or negative — cannot evaluate margin.",
        }

    shipping_pct = (shipping_cost / price) * 100
    cost = product.get("cost", price * 0.6)  # assume 40% margin if unknown
    margin_before = ((price - cost) / price) * 100
    margin_after = margin_before - shipping_pct

    if shipping_pct > 15:
        severity = "critical"
        detail = (
            f"Shipping consumes {shipping_pct:.1f}% of price, "
            f"leaving {margin_after:.1f}% margin.  Not viable."
        )
    elif shipping_pct > 10:
        severity = "warning"
        detail = (
            f"Shipping is {shipping_pct:.1f}% of price — margin drops to "
            f"{margin_after:.1f}%.  Consider negotiating carrier rates."
        )
    else:
        severity = "healthy"
        detail = (
            f"Shipping is {shipping_pct:.1f}% of price.  "
            f"Margin remains {margin_after:.1f}%."
        )

    return {
        "shipping_pct": round(shipping_pct, 2),
        "margin_before": round(margin_before, 2),
        "margin_after": round(margin_after, 2),
        "impact_severity": severity,
        "detail": detail,
    }


def optimize_packaging(dimensions):
    """Suggest packaging adjustments to minimise dimensional weight.

    Parameters
    ----------
    dimensions : dict  {length, width, height} in cm.

    Returns
    -------
    dict  {current_dim_weight, optimised_dim_weight, savings_pct,
           recommendations}
    """
    length = dimensions.get("length", 0)
    width = dimensions.get("width", 0)
    height = dimensions.get("height", 0)
    divisor = DIM_WEIGHT_DIVISORS.get("ups", 5000)

    current_vol = length * width * height
    current_dw = current_vol / divisor if divisor else 0

    recommendations = []

    # Rule: reduce each dimension by 10% if possible (tighter fit)
    tight_l = round(length * 0.9, 1)
    tight_w = round(width * 0.9, 1)
    tight_h = round(height * 0.9, 1)
    tight_vol = tight_l * tight_w * tight_h
    tight_dw = tight_vol / divisor if divisor else 0

    if tight_dw < current_dw:
        recommendations.append(
            f"Right-size box to ~{tight_l} x {tight_w} x {tight_h} cm "
            f"(saves {((current_dw - tight_dw) / current_dw) * 100:.0f}% dim weight)"
        )

    # Rule: if height is less than 8cm, consider poly mailer
    if height <= 8 and length <= 40 and width <= 30:
        recommendations.append(
            "Product fits a poly mailer — eliminates box dim weight entirely"
        )

    # Rule: if one dimension is disproportionately large, flag it
    sorted_dims = sorted([length, width, height])
    if sorted_dims[2] > sorted_dims[0] * 3:
        recommendations.append(
            "Longest dimension is 3x+ the shortest — explore folding, "
            "disassembly, or telescoping packaging"
        )

    # Rule: vacuum-packing for compressible goods
    if height > 15 and width > 15:
        recommendations.append(
            "If product is compressible (textiles, bedding), "
            "vacuum-seal to reduce height by up to 60%"
        )

    savings_pct = (
        ((current_dw - tight_dw) / current_dw * 100) if current_dw > 0 else 0.0
    )

    return {
        "current_dim_weight_kg": round(current_dw, 2),
        "optimised_dim_weight_kg": round(tight_dw, 2),
        "savings_pct": round(savings_pct, 1),
        "recommendations": recommendations,
    }
