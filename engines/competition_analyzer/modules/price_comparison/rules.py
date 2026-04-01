"""
Price Comparison — Rules and Constraints
=========================================
Defines pricing guard rails to prevent destructive pricing decisions.
Rules encode business constraints: margin floors, undercut limits,
premium eligibility criteria, and charm pricing thresholds.
"""

# --- Core Pricing Constraints ---

MAX_UNDERCUT_PERCENT = 20.0
"""Never undercut competitors by more than 20%. Racing to the bottom
destroys margins and signals low quality to customers."""

MIN_MARGIN_PERCENT = 20.0
"""Every price must cover all costs plus a minimum 20% margin.
This ensures business sustainability even under competitive pressure."""

PREMIUM_MIN_RATING = 4.5
"""Premium pricing (above 75th percentile) requires a product rating
of at least 4.5 stars. Without strong reviews, premium price triggers
customer skepticism and high return rates."""

CHARM_PRICE_CEILING = 50.0
"""Charm pricing (ending in .99 or .97) is most effective for products
priced under $50. Above this threshold, round numbers or prestige
pricing ($X.00) performs better."""

MIN_COMPETITOR_PRICES = 3
"""At least 3 competitor prices are needed for a meaningful comparison.
Fewer data points produce unreliable distribution statistics."""

MAX_PRICE_AGE_DAYS = 30
"""Competitor price data older than 30 days should be flagged as stale.
Markets can shift significantly within a month."""

PRICE_FLOOR_MULTIPLIER = 0.80
"""The absolute lowest you should price relative to the market median.
Going below 80% of median signals desperation or quality concerns."""

PRICE_CEILING_MULTIPLIER = 1.50
"""The absolute highest you should price relative to the market median,
unless operating in a verified luxury segment."""


# --- Validation Functions ---

def validate_price_input(input_payload):
    """
    Validate the input payload for the price comparison engine.

    Returns:
        str or None: Error message if invalid, None if valid.
    """
    if not isinstance(input_payload, dict):
        return "Input payload must be a dictionary."

    your_price = input_payload.get("your_price")
    if your_price is None:
        return "Missing required field: your_price."
    try:
        your_price = float(your_price)
    except (TypeError, ValueError):
        return "your_price must be a valid number."
    if your_price <= 0:
        return "your_price must be greater than zero."

    competitor_prices = input_payload.get("competitor_prices")
    if not competitor_prices:
        return "Missing required field: competitor_prices."
    if not isinstance(competitor_prices, (list, tuple)):
        return "competitor_prices must be a list."
    if len(competitor_prices) < MIN_COMPETITOR_PRICES:
        return (
            f"At least {MIN_COMPETITOR_PRICES} competitor prices are required. "
            f"Got {len(competitor_prices)}."
        )
    for i, price in enumerate(competitor_prices):
        try:
            p = float(price)
            if p <= 0:
                return f"competitor_prices[{i}] must be greater than zero."
        except (TypeError, ValueError):
            return f"competitor_prices[{i}] is not a valid number."

    category = input_payload.get("product_category")
    if not category or not isinstance(category, str):
        return "Missing or invalid required field: product_category."

    return None


def check_margin_floor(price, cost_basis):
    """
    Verify that the price meets the minimum margin requirement.

    Args:
        price: The proposed selling price.
        cost_basis: Total cost including product, shipping, fees, etc.

    Returns:
        dict with passes flag, actual_margin, and warning if applicable.
    """
    if cost_basis <= 0:
        return {"passes": False, "actual_margin": None, "warning": "Invalid cost basis."}

    margin = ((price - cost_basis) / price) * 100
    passes = margin >= MIN_MARGIN_PERCENT

    result = {
        "passes": passes,
        "actual_margin_pct": round(margin, 2),
        "required_margin_pct": MIN_MARGIN_PERCENT,
        "min_viable_price": round(cost_basis / (1 - MIN_MARGIN_PERCENT / 100), 2),
    }

    if not passes:
        result["warning"] = (
            f"Price ${price:.2f} yields only {margin:.1f}% margin. "
            f"Minimum required is {MIN_MARGIN_PERCENT}%. "
            f"Raise price to at least ${result['min_viable_price']:.2f}."
        )
    return result


def is_premium_eligible(rating):
    """
    Check whether a product qualifies for premium pricing.

    Args:
        rating: Product's average star rating (0-5 scale).

    Returns:
        dict with eligible flag and reasoning.
    """
    if rating is None or rating == 0:
        return {
            "eligible": False,
            "rating": rating,
            "required_rating": PREMIUM_MIN_RATING,
            "reasoning": "No rating data available. Premium pricing is risky without social proof.",
        }

    eligible = rating >= PREMIUM_MIN_RATING
    if eligible:
        reasoning = (
            f"Rating of {rating} meets the {PREMIUM_MIN_RATING} threshold. "
            "Premium pricing is supported by strong customer satisfaction."
        )
    else:
        reasoning = (
            f"Rating of {rating} is below the {PREMIUM_MIN_RATING} threshold. "
            "Improve product quality and reviews before charging a premium."
        )

    return {
        "eligible": eligible,
        "rating": rating,
        "required_rating": PREMIUM_MIN_RATING,
        "reasoning": reasoning,
    }


def check_undercut_limit(your_price, competitor_median):
    """
    Ensure the proposed price does not undercut competitors excessively.

    Args:
        your_price: Your proposed price.
        competitor_median: The median competitor price.

    Returns:
        dict with passes flag and details.
    """
    if competitor_median <= 0:
        return {"passes": False, "warning": "Invalid competitor median price."}

    undercut_pct = ((competitor_median - your_price) / competitor_median) * 100

    if undercut_pct <= 0:
        return {
            "passes": True,
            "undercut_pct": 0.0,
            "note": "Price is at or above competitor median.",
        }

    passes = undercut_pct <= MAX_UNDERCUT_PERCENT
    result = {
        "passes": passes,
        "undercut_pct": round(undercut_pct, 2),
        "max_allowed_pct": MAX_UNDERCUT_PERCENT,
    }

    if not passes:
        min_price = round(competitor_median * (1 - MAX_UNDERCUT_PERCENT / 100), 2)
        result["warning"] = (
            f"Undercutting by {undercut_pct:.1f}% exceeds the {MAX_UNDERCUT_PERCENT}% limit. "
            f"Minimum recommended price is ${min_price:.2f}. "
            "Excessive undercutting triggers a race to the bottom."
        )
        result["min_recommended_price"] = min_price

    return result
