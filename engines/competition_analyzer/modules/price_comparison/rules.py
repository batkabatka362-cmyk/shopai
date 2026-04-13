"""
Price Comparison — Rules and Constraints
=========================================
Pricing guard rails to prevent destructive pricing decisions.
Encodes margin floors, undercut limits, premium eligibility, and
charm pricing thresholds.
"""

MAX_UNDERCUT_PERCENT = 20.0
"""Never undercut competitors by more than 20%. Racing to the bottom
destroys margins and signals low quality."""

MIN_MARGIN_PERCENT = 20.0
"""Every price must cover all costs plus a minimum 20% margin."""

PREMIUM_MIN_RATING = 4.5
"""Premium pricing requires >= 4.5 stars. Without strong reviews,
premium price triggers skepticism and high return rates."""

CHARM_PRICE_CEILING = 50.0
"""Charm pricing ($X.99) is most effective under $50. Above that,
round or prestige pricing performs better."""

MIN_COMPETITOR_PRICES = 3
"""At least 3 competitor prices needed for meaningful comparison."""

MAX_PRICE_AGE_DAYS = 30
"""Competitor price data older than 30 days is flagged as stale."""

PRICE_FLOOR_MULTIPLIER = 0.80
"""Lowest recommended price relative to market median."""

PRICE_CEILING_MULTIPLIER = 1.50
"""Highest recommended price relative to market median (non-luxury)."""


def validate_price_input(input_payload):
    """Validate the input payload. Returns error string or None."""
    if not isinstance(input_payload, dict):
        return "Input payload must be a dictionary."
    yp = input_payload.get("your_price")
    if yp is None:
        return "Missing required field: your_price."
    try:
        yp = float(yp)
    except (TypeError, ValueError):
        return "your_price must be a valid number."
    if yp <= 0:
        return "your_price must be greater than zero."

    cp = input_payload.get("competitor_prices")
    if not cp:
        return "Missing required field: competitor_prices."
    if not isinstance(cp, (list, tuple)):
        return "competitor_prices must be a list."
    if len(cp) < MIN_COMPETITOR_PRICES:
        return f"At least {MIN_COMPETITOR_PRICES} competitor prices required. Got {len(cp)}."
    for i, price in enumerate(cp):
        try:
            if float(price) <= 0:
                return f"competitor_prices[{i}] must be greater than zero."
        except (TypeError, ValueError):
            return f"competitor_prices[{i}] is not a valid number."

    cat = input_payload.get("product_category")
    if not cat or not isinstance(cat, str):
        return "Missing or invalid required field: product_category."
    return None


def check_margin_floor(price, cost_basis):
    """Verify that price meets the minimum margin requirement."""
    if cost_basis <= 0:
        return {"passes": False, "actual_margin_pct": None, "warning": "Invalid cost basis."}
    margin = ((price - cost_basis) / price) * 100
    min_price = round(cost_basis / (1 - MIN_MARGIN_PERCENT / 100), 2)
    result = {"passes": margin >= MIN_MARGIN_PERCENT, "actual_margin_pct": round(margin, 2),
              "required_margin_pct": MIN_MARGIN_PERCENT, "min_viable_price": min_price}
    if not result["passes"]:
        result["warning"] = (
            f"Price ${price:.2f} yields only {margin:.1f}% margin. "
            f"Minimum is {MIN_MARGIN_PERCENT}%. Raise to at least ${min_price:.2f}.")
    return result


def is_premium_eligible(rating):
    """Check whether a product qualifies for premium pricing."""
    if not rating:
        return {"eligible": False, "rating": rating, "required_rating": PREMIUM_MIN_RATING,
                "reasoning": "No rating data. Premium pricing is risky without social proof."}
    eligible = rating >= PREMIUM_MIN_RATING
    reasoning = (f"Rating {rating} meets {PREMIUM_MIN_RATING} threshold. Premium supported."
                 if eligible else
                 f"Rating {rating} below {PREMIUM_MIN_RATING}. Improve reviews before premium pricing.")
    return {"eligible": eligible, "rating": rating, "required_rating": PREMIUM_MIN_RATING,
            "reasoning": reasoning}


def check_undercut_limit(your_price, competitor_median):
    """Ensure proposed price does not undercut competitors excessively."""
    if competitor_median <= 0:
        return {"passes": False, "warning": "Invalid competitor median price."}
    undercut_pct = ((competitor_median - your_price) / competitor_median) * 100
    if undercut_pct <= 0:
        return {"passes": True, "undercut_pct": 0.0, "note": "Price is at or above median."}
    passes = undercut_pct <= MAX_UNDERCUT_PERCENT
    result = {"passes": passes, "undercut_pct": round(undercut_pct, 2),
              "max_allowed_pct": MAX_UNDERCUT_PERCENT}
    if not passes:
        mp = round(competitor_median * (1 - MAX_UNDERCUT_PERCENT / 100), 2)
        result["warning"] = (f"Undercutting by {undercut_pct:.1f}% exceeds {MAX_UNDERCUT_PERCENT}% "
                             f"limit. Min recommended: ${mp:.2f}.")
        result["min_recommended_price"] = mp
    return result
