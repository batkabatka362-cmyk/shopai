"""
code.py — Main entry point for shipping feasibility evaluation.

Accepts an input payload describing a product and returns an
engine-contract response with a feasibility verdict.
"""

from .data import get_shipping_cost_estimate, DIM_WEIGHT_DIVISORS, INTERNATIONAL_COST_MULTIPLIER
from .rules import (
    MAX_SHIPPING_COST_PCT, MARGINAL_SHIPPING_COST_PCT,
    check_weight_limit, check_size_constraints, check_hazmat_restrictions,
    check_battery_rules, check_liquid_restrictions,
    check_fragile_requirements, compute_surcharges,
)
from .logic import recommend_shipping_method, calculate_shipping_margin_impact, optimize_packaging
from .knowledge import get_heuristic_warnings, diagnose_shipping_result


def _billable_weight(weight_kg, dims, divisor=5000):
    """Return the greater of actual weight and dimensional weight."""
    vol = dims.get("length", 0) * dims.get("width", 0) * dims.get("height", 0)
    dim_wt = vol / divisor if divisor else weight_kg
    return max(weight_kg, dim_wt)


def _evaluate_product(product):
    """Run all shipping checks on a single product."""
    weight = product.get("weight_kg", 0)
    dims = product.get("dimensions_cm", {})
    price = product.get("price", 0)
    issues, flags = [], []

    wt_ok, wt_msg = check_weight_limit(weight)
    if not wt_ok:
        issues.append(wt_msg)

    _, size_issues, _ = check_size_constraints(dims)
    issues.extend(size_issues)

    hz_ok, hz_msg = check_hazmat_restrictions(product.get("hazmat_class", "none"))
    if not hz_ok:
        issues.append(hz_msg)
        flags.append("hazmat_air_restricted")

    if check_battery_rules(product)["restriction"]:
        flags.append("battery_restricted")
    if check_liquid_restrictions(product)["requirements"]:
        flags.append("liquid_handling_required")
    if check_fragile_requirements(product)["is_fragile"]:
        flags.append("fragile_special_packaging")
    if product.get("temperature_sensitive"):
        flags.append("cold_chain_required")

    # Cost calculation
    billable = _billable_weight(weight, dims, DIM_WEIGHT_DIVISORS.get("ups", 5000))
    base_cost = get_shipping_cost_estimate(billable, "standard")
    surcharge_total, surcharge_bd = compute_surcharges(product, dims)
    total_cost = base_cost + surcharge_total
    if product.get("is_international"):
        total_cost *= INTERNATIONAL_COST_MULTIPLIER

    shipping_pct = (total_cost / price * 100) if price > 0 else 100.0

    if shipping_pct > MAX_SHIPPING_COST_PCT or issues:
        verdict = "infeasible"
    elif shipping_pct > MARGINAL_SHIPPING_COST_PCT or len(flags) >= 3:
        verdict = "marginal"
    else:
        verdict = "feasible"

    return {
        "verdict": verdict,
        "shipping_cost_usd": round(total_cost, 2),
        "shipping_pct_of_price": round(shipping_pct, 2),
        "billable_weight_kg": round(billable, 2),
        "issues": issues, "flags": flags, "surcharges": surcharge_bd,
        "recommended_method": recommend_shipping_method(product),
        "margin_impact": calculate_shipping_margin_impact(product, total_cost),
        "packaging_optimisation": optimize_packaging(dims) if dims else {},
        "warnings": get_heuristic_warnings(product),
    }


def check_shipping_feasibility(input_payload):
    """Evaluate shipping feasibility for one or more products.

    Parameters
    ----------
    input_payload : dict
        - product  : dict       — single product (used if 'products' absent)
        - products : list[dict] — batch mode

    Returns
    -------
    dict  Engine contract: {status, data, meta, error}
    """
    try:
        products = input_payload.get("products")
        if not products:
            single = input_payload.get("product")
            if not single or not isinstance(single, dict):
                return {"status": "error", "data": None, "meta": {},
                        "error": "Provide 'product' (dict) or 'products' (list)."}
            products = [single]

        results, verdicts = [], {"feasible": 0, "marginal": 0, "infeasible": 0}
        for product in products:
            ev = _evaluate_product(product)
            verdicts[ev["verdict"]] += 1
            results.append({"product": product, "evaluation": ev})

        total = len(products)
        feasible_rate = verdicts["feasible"] / total if total else 0.0
        avg_pct = sum(r["evaluation"]["shipping_pct_of_price"] for r in results) / total if total else 0.0
        summary = "feasible" if feasible_rate >= 0.8 else "marginal" if feasible_rate >= 0.5 else "infeasible"
        all_warnings = [w for r in results for w in r["evaluation"]["warnings"]]

        return {
            "status": "success",
            "data": {"evaluations": results, "summary_verdict": summary},
            "meta": {
                "total_products": total, "verdicts": verdicts,
                "feasible_rate": round(feasible_rate, 4),
                "avg_shipping_pct": round(avg_pct, 2),
                "diagnostic": diagnose_shipping_result(summary, avg_pct, all_warnings),
            },
            "error": None,
        }
    except Exception as exc:
        return {"status": "error", "data": None, "meta": {}, "error": str(exc)}
