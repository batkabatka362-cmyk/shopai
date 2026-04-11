"""
knowledge.py — Expert filtering heuristics and diagnostic rules.

Encodes practitioner wisdom about Shopify product selection so the
engine can surface actionable warnings alongside raw filter results.
"""

# ── Heuristic rule bank ───────────────────────────────────────────
# Each entry: condition description, severity, advice.
FILTERING_HEURISTICS = [
    {
        "id": "high_rejection_rate",
        "condition": "Rejection rate > 70%",
        "severity": "warning",
        "advice": (
            "Criteria are too strict for this product set. "
            "Consider loosening margin or price thresholds."
        ),
    },
    {
        "id": "very_high_rejection_rate",
        "condition": "Rejection rate > 90%",
        "severity": "critical",
        "advice": (
            "Almost nothing passes. The criteria likely don't match "
            "the product source. Re-evaluate category or supplier."
        ),
    },
    {
        "id": "low_margin_warning",
        "condition": "Margin < 20%",
        "severity": "info",
        "advice": (
            "Products under 20% margin are rarely worth selling on "
            "Shopify after factoring in ads, returns, and platform fees."
        ),
    },
    {
        "id": "heavy_product_shipping",
        "condition": "Weight > 5 kg",
        "severity": "warning",
        "advice": (
            "Products over 5 kg create shipping cost problems. Carriers "
            "charge dimensional or actual weight premiums that eat margin."
        ),
    },
    {
        "id": "cheap_product_profitability",
        "condition": "Price < $10",
        "severity": "warning",
        "advice": (
            "Products under $10 are very hard to profit from after "
            "advertising spend. CPA often exceeds the item price."
        ),
    },
    {
        "id": "no_reviews_risk",
        "condition": "Review count = 0",
        "severity": "info",
        "advice": (
            "Zero reviews signal an unproven product. Social proof is "
            "critical for Shopify conversion rates."
        ),
    },
    {
        "id": "low_rating_conversion",
        "condition": "Rating < 3.0",
        "severity": "warning",
        "advice": (
            "Products rated below 3.0 have poor conversion rates. "
            "Customers increasingly check reviews before purchasing."
        ),
    },
    {
        "id": "price_ceiling_margin",
        "condition": "Price > $200",
        "severity": "info",
        "advice": (
            "High-ticket items can work but need strong trust signals, "
            "longer sales cycles, and higher ad budgets to convert."
        ),
    },
    {
        "id": "all_accepted",
        "condition": "Rejection rate = 0%",
        "severity": "info",
        "advice": (
            "Every product passed. Criteria may be too loose — tighter "
            "filters usually improve overall catalog quality."
        ),
    },
]


def diagnose_filter_results(rejection_rate, rejection_breakdown):
    """Run heuristic checks against the filter outcome.

    Parameters
    ----------
    rejection_rate : float  (0.0 – 1.0)
    rejection_breakdown : dict  {reason_tag: count}

    Returns
    -------
    list[dict]  Triggered heuristics with id, severity, advice.
    """
    triggered = []

    if rejection_rate == 0.0:
        triggered.append(_pick("all_accepted"))

    if rejection_rate > 0.90:
        triggered.append(_pick("very_high_rejection_rate"))
    elif rejection_rate > 0.70:
        triggered.append(_pick("high_rejection_rate"))

    if rejection_breakdown.get("margin", 0) > 0:
        triggered.append(_pick("low_margin_warning"))

    if rejection_breakdown.get("weight", 0) > 0:
        triggered.append(_pick("heavy_product_shipping"))

    if rejection_breakdown.get("price", 0) > 0:
        triggered.append(_pick("cheap_product_profitability"))

    if rejection_breakdown.get("rating", 0) > 0:
        triggered.append(_pick("low_rating_conversion"))

    if rejection_breakdown.get("review", 0) > 0:
        triggered.append(_pick("no_reviews_risk"))

    return [h for h in triggered if h is not None]


def _pick(heuristic_id):
    """Retrieve a heuristic entry by id."""
    for h in FILTERING_HEURISTICS:
        if h["id"] == heuristic_id:
            return {"id": h["id"], "severity": h["severity"], "advice": h["advice"]}
    return None


def get_heuristic_warnings(product):
    """Return applicable heuristic warnings for a single product.

    Useful for annotating individual items before or after filtering.

    Parameters
    ----------
    product : dict

    Returns
    -------
    list[str]  Warning messages.
    """
    warnings = []

    margin = product.get("margin_pct")
    if margin is not None and margin < 20:
        warnings.append(
            f"Margin {margin:.1f}% is below the 20% Shopify viability threshold."
        )

    price = product.get("price")
    if price is not None:
        if price < 10:
            warnings.append(
                f"Price ${price:.2f} is under $10 — hard to profit after ad spend."
            )
        if price > 200:
            warnings.append(
                f"Price ${price:.2f} is over $200 — needs strong trust signals to convert."
            )

    weight = product.get("weight_kg")
    if weight is not None and weight > 5:
        warnings.append(
            f"Weight {weight}kg exceeds 5kg — expect elevated shipping costs."
        )

    rating = product.get("rating")
    if rating is not None and rating < 3.0:
        warnings.append(
            f"Rating {rating} is below 3.0 — poor conversion expected."
        )

    reviews = product.get("review_count")
    if reviews is not None and reviews == 0:
        warnings.append("Zero reviews — unproven product, low social proof.")

    return warnings
