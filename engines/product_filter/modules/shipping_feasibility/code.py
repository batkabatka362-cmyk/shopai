"""
code.py — Main entry point for shipping feasibility evaluation.

Accepts an input payload describing a product and returns an
engine-contract response with a feasibility verdict.
"""

from .data import get_shipping_cost_estimate, get_hazmat_info, DIM_WEIGHT_DIVISORS
from .rules import (
    MAX_SHIPPING_COST_PCT,
    MARGINAL_SHIPPING_COST_PCT,
    check_weight_limit,
    check_size_constraints,
    check_hazmat_restrictions,
    check_battery_rules,
    check_liquid_restrictions,
    check_fragile_requirements,
    compute_surcharges,
)
from .logic import (
    recommend_shipping_method,
    calculate_shipping_margin_impact,
    optimize_packaging,
)
from .knowledge import get_heuristic_warnings, diagnose_shipping_result


def _billable_weight(weight_kg, dimensions_cm, divisor=5000):
    """Return the greater of actual weight and dimensional weight."""
    l = dimensions_cm.get("length", 0)
    w = dimensions_cm.get("width", 0)
    h = dimensions_cm.get("height", 0)
    dim_weight = (l * w * h) / divisor if divisor else weight_kg
    return max(weight_kg, dim_weight)


def _evaluate_product(product):
    """Run all shipping checks on a single product.

    Returns
    -------
    dict  Per-product evaluation result.
    """
    weight = product.get("weight_kg", 0)
    dims = product.get("dimensions_cm", {})
    price = product.get("price", 0)
    hazmat = product.get("hazmat_class", "none")

    issues = []
    flags = []

    # Weight check
    weight_ok, weight_msg = check_weight_limit(weight)
    if not weight_ok:
        issues.append(weight_msg)

    # Size check
    size_ok, size_issues, _ = check_size_constraints(dims)
    issues.extend(size_issues)

    # Hazmat check
    hazmat_ok, hazmat_msg = check_hazmat_restrictions(hazmat)
    if not hazmat_ok:
        issues.append(hazmat_msg)
        flags.append("hazmat_air_restricted")

    # Battery rules
    battery = check_battery_rules(product)
    if battery["restriction"]:
        flags.append("battery_restricted")

    # Liquid rules
    liquid = check_liquid_restrictions(product)
    if liquid["requirements"]:
        flags.append("liquid_handling_required")

    # Fragile rules
    fragile = check_fragile_requirements(product)
    if fragile["is_fragile"]:
        flags.append("fragile_special_packaging")

    # Temperature sensitivity
    if product.get("temperature_sensitive"):
        flags.append("cold_chain_required")

    # Cost calculation
    divisor = DIM_WEIGHT_DIVISORS.get("ups", 5000)
    billable = _billable_weight(weight, dims, divisor)
    base_cost = get_shipping_cost_estimate(billable, "standard")
    surcharge_total, surcharge_breakdown = compute_surcharges(product, dims)
    total_cost = base_cost + surcharge_total

    # International multiplier
    if product.get("is_international"):
        from .data import INTERNATIONAL_COST_MULTIPLIER
        total_cost *= INTERNATIONAL_COST_MULTIPLIER

    # Shipping as % of price
    shipping_pct = (total_cost / price * 100) if price > 0 else 100.0

    # Verdict
    if shipping_pct > MAX_SHIPPING_COST_PCT or issues:
        verdict = "infeasible"
    elif shipping_pct > MARGINAL_SHIPPING_COST_PCT or len(flags) >= 3:
        verdict = "marginal"
    else:
        verdict = "feasible"

    # Recommendations
    method_rec = recommend_shipping_method(product)
    margin_impact = calculate_shipping_margin_impact(product, total_cost)
    packaging_rec = optimize_packaging(dims) if dims else {}
    warnings = get_heuristic_warnings(product)

    return {
        "verdict": verdict,
        "shipping_cost_usd": round(total_cost, 2),
        "shipping_pct_of_price": round(shipping_pct, 2),
        "billable_weight_kg": round(billable, 2),
        "issues": issues,
        "flags": flags,
        "surcharges": surcharge_breakdown,
        "recommended_method": method_rec,
        "margin_impact": margin_impact,
        "packaging_optimisation": packaging_rec,
        "warnings": warnings,
    }


def check_shipping_feasibility(input_payload):
    """Evaluate shipping feasibility for one or more products.

    Parameters
    ----------
    input_payload : dict
        - product  : dict       — single product (used if 'products' absent)
        - products : list[dict] — batch mode
        Each product dict should include:
            price, weight_kg, dimensions_cm ({length, width, height}),
            and optionally: hazmat_class, is_fragile, is_liquid,
            temperature_sensitive, is_international, destination_country.

    Returns
    -------
    dict  Engine contract: {status, data, meta, error}
    """
    try:
        products = input_payload.get("products")
        if not products:
            single = input_payload.get("product")
            if not single or not isinstance(single, dict):
                return {
                    "status": "error",
                    "data": None,
                    "meta": {},
                    "error": "Provide 'product' (dict) or 'products' (list).",
                }
            products = [single]

        results = []
        verdicts = {"feasible": 0, "marginal": 0, "infeasible": 0}

        for product in products:
            evaluation = _evaluate_product(product)
            verdicts[evaluation["verdict"]] += 1
            results.append({
                "product": product,
                "evaluation": evaluation,
            })

        total = len(products)
        feasible_rate = verdicts["feasible"] / total if total else 0.0

        # Aggregate diagnostic
        avg_pct = (
            sum(r["evaluation"]["shipping_pct_of_price"] for r in results) / total
            if total else 0.0
        )
        summary_verdict = (
            "feasible" if feasible_rate >= 0.8
            else "marginal" if feasible_rate >= 0.5
            else "infeasible"
        )
        diagnostic = diagnose_shipping_result(
            summary_verdict, avg_pct,
            [w for r in results for w in r["evaluation"]["warnings"]],
        )

        return {
            "status": "success",
            "data": {
                "evaluations": results,
                "summary_verdict": summary_verdict,
            },
            "meta": {
                "total_products": total,
                "verdicts": verdicts,
                "feasible_rate": round(feasible_rate, 4),
                "avg_shipping_pct": round(avg_pct, 2),
                "diagnostic": diagnostic,
            },
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "data": None,
            "meta": {},
            "error": str(exc),
        }
