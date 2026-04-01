"""
knowledge.py — Expert shipping knowledge and heuristics.

Encodes hard-won insights about shipping economics, packaging
pitfalls, and carrier behaviour that inform feasibility decisions.
"""


SHIPPING_HEURISTICS = {
    "heavy_margin_erosion": {
        "rule": "Products over 5kg eat margins on standard shipping",
        "detail": (
            "Most economical ground services price steeply above 5kg. "
            "A 6kg item can cost 40-60% more to ship than a 4kg item. "
            "Always verify that the price point supports the weight tier."
        ),
        "threshold_kg": 5.0,
    },
    "dim_weight_trap": {
        "rule": "Dimensional weight catches oversized lightweight items",
        "detail": (
            "Carriers charge whichever is greater: actual weight or "
            "dimensional weight (L x W x H / divisor).  Large but light "
            "products like lampshades, pillows, or pet beds often ship "
            "at 2-3x their actual weight cost."
        ),
    },
    "lithium_battery_restriction": {
        "rule": "Lithium batteries restricted on air freight",
        "detail": (
            "IATA classifies lithium-ion and lithium-metal batteries as "
            "Class 9 dangerous goods.  Standalone batteries are banned "
            "from passenger aircraft cargo holds.  Equipment containing "
            "batteries may ship air but requires UN3481 documentation."
        ),
    },
    "fragile_return_rate": {
        "rule": "Fragile items correlate with high return rates",
        "detail": (
            "Glass, ceramics, and thin electronics see 3-5x the return "
            "rate of robust goods due to transit damage.  Factor in the "
            "cost of replacement shipping and lost product when "
            "evaluating feasibility."
        ),
    },
    "temperature_sensitive_logistics": {
        "rule": "Temperature-sensitive products require cold-chain logistics",
        "detail": (
            "Items needing refrigeration (2-8 C) or freezing (below 0 C) "
            "demand insulated packaging and expedited transit.  Shipping "
            "cost can be 3-5x standard rates, and spoilage risk makes "
            "long-distance fulfillment economically fragile."
        ),
    },
    "oversized_surcharge": {
        "rule": "Single dimension over 120cm triggers oversized surcharges",
        "detail": (
            "UPS, FedEx, and most regional carriers apply a flat "
            "surcharge ($40-90) for packages where any single dimension "
            "exceeds 120cm or combined L+2(W+H) exceeds 330cm.  This "
            "surcharge alone can make low-price items infeasible."
        ),
    },
    "packaging_optimisation": {
        "rule": "Right-sizing packaging can cut dim weight by 30-50%",
        "detail": (
            "Many sellers use one-size-fits-all boxes, paying for air. "
            "Custom or tiered box sizes, poly mailers for soft goods, "
            "and vacuum-packing compressible items dramatically reduce "
            "dim weight and lower per-unit shipping cost."
        ),
    },
    "international_complexity": {
        "rule": "International shipping adds duties, paperwork, and delays",
        "detail": (
            "Cross-border shipments face customs duties (often 5-25% "
            "of declared value), brokerage fees, longer transit times, "
            "and restricted product categories.  Batteries, liquids, "
            "aerosols, and food are commonly blocked or delayed."
        ),
    },
}


def get_heuristic_warnings(product):
    """Return a list of expert warnings applicable to the product.

    Parameters
    ----------
    product : dict
        Product data with optional keys: weight_kg, dimensions_cm,
        is_fragile, is_hazmat, hazmat_class, temperature_sensitive.

    Returns
    -------
    list[str]  Human-readable warning strings.
    """
    warnings = []
    weight = product.get("weight_kg", 0)
    if weight > SHIPPING_HEURISTICS["heavy_margin_erosion"]["threshold_kg"]:
        warnings.append(SHIPPING_HEURISTICS["heavy_margin_erosion"]["rule"])

    dims = product.get("dimensions_cm", {})
    length = dims.get("length", 0)
    width = dims.get("width", 0)
    height = dims.get("height", 0)
    if length * width * height > 0 and weight > 0:
        dim_weight = (length * width * height) / 5000
        if dim_weight > weight * 1.5:
            warnings.append(SHIPPING_HEURISTICS["dim_weight_trap"]["rule"])

    if product.get("hazmat_class") in ("lithium_ion", "lithium_metal"):
        warnings.append(SHIPPING_HEURISTICS["lithium_battery_restriction"]["rule"])

    if product.get("is_fragile"):
        warnings.append(SHIPPING_HEURISTICS["fragile_return_rate"]["rule"])

    if product.get("temperature_sensitive"):
        warnings.append(SHIPPING_HEURISTICS["temperature_sensitive_logistics"]["rule"])

    if max(length, width, height) > 120:
        warnings.append(SHIPPING_HEURISTICS["oversized_surcharge"]["rule"])

    return warnings


def diagnose_shipping_result(verdict, shipping_pct, warnings):
    """Produce a plain-English diagnostic summary.

    Returns
    -------
    str  Diagnostic paragraph for the meta block.
    """
    if verdict == "infeasible":
        return (
            f"Shipping cost represents {shipping_pct:.1f}% of product price, "
            f"exceeding the 15% feasibility threshold.  "
            f"{len(warnings)} expert warning(s) also flagged."
        )
    if verdict == "marginal":
        return (
            f"Shipping cost is {shipping_pct:.1f}% of price — close to the "
            f"15% ceiling.  Review warnings before committing to this product."
        )
    return (
        f"Shipping cost is {shipping_pct:.1f}% of price — within healthy "
        f"margins.  {len(warnings)} advisory note(s) logged."
    )
