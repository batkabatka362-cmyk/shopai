"""
Price Comparison — Business Logic
==================================
Contains recommendation engines, price war detection, and elasticity
estimation. These functions interpret raw analysis into actionable
pricing strategy decisions.
"""

import statistics


def recommend_price_position(analysis):
    """
    Recommend a pricing position: undercut, match, or premium.

    Args:
        analysis: dict with distribution, position, and trends data.

    Returns:
        dict with strategy, reasoning, suggested_range, and confidence.
    """
    distribution = analysis.get("distribution", {})
    position = analysis.get("position", {})
    trends = analysis.get("trends", {})

    median_price = distribution.get("median", 0)
    percentiles = distribution.get("percentiles", {})
    trend_direction = trends.get("direction", "stable")
    position_label = position.get("position_label", "mid-range")

    strategy = "match"
    reasoning = []
    confidence = 0.5

    # If prices are trending down, avoid undercutting further
    if trend_direction == "decreasing":
        reasoning.append("Competitor prices are falling; avoid a race to the bottom.")
        strategy = "match"
        confidence = 0.6

    # If prices are trending up, there is room for premium positioning
    if trend_direction == "increasing":
        reasoning.append("Market prices are rising; premium positioning is viable.")
        strategy = "premium"
        confidence = 0.65

    # If already positioned as budget, recommend matching or moving up
    if position_label == "budget":
        reasoning.append("You are already at the low end; consider moving toward mid-range.")
        strategy = "match"
        confidence = 0.7

    # If positioned as premium, validate with market trends
    if position_label == "premium" and trend_direction != "increasing":
        reasoning.append(
            "Premium position without rising market may limit volume."
        )
        strategy = "match"
        confidence = 0.55

    # Calculate suggested price range based on strategy
    suggested_range = _calculate_suggested_range(strategy, median_price, percentiles)

    return {
        "strategy": strategy,
        "reasoning": reasoning,
        "suggested_range": suggested_range,
        "confidence": round(confidence, 2),
        "position_evaluated": position_label,
        "trend_context": trend_direction,
    }


def _calculate_suggested_range(strategy, median_price, percentiles):
    """Derive a suggested price range from the chosen strategy."""
    p25 = percentiles.get("p25", median_price * 0.85)
    p50 = percentiles.get("p50", median_price)
    p75 = percentiles.get("p75", median_price * 1.15)

    if strategy == "undercut":
        low = round(p25 * 0.85, 2)
        high = round(p25, 2)
    elif strategy == "premium":
        low = round(p75, 2)
        high = round(p75 * 1.20, 2)
    else:  # match
        low = round(p25, 2)
        high = round(p75, 2)
    return {"low": low, "high": high, "anchor": round(p50, 2)}


def detect_price_war(trends):
    """
    Determine if a price war is underway among competitors.

    A price war is detected when prices are decreasing aggressively
    (magnitude > 5% per period) or when there are multiple consecutive
    periods of decline.

    Args:
        trends: dict with direction, magnitude, and periods_analyzed.

    Returns:
        dict with detected flag, severity, and recommended response.
    """
    direction = trends.get("direction", "stable")
    magnitude = trends.get("magnitude", 0)
    periods = trends.get("periods_analyzed", 0)
    recent_change = trends.get("recent_change_pct", 0)

    detected = False
    severity = "none"
    response = "No action needed. Monitor competitor pricing regularly."

    if direction == "decreasing":
        if magnitude > 10:
            detected = True
            severity = "severe"
            response = (
                "Severe price war detected. Do NOT follow competitors down. "
                "Focus on value differentiation, bundling, and customer loyalty. "
                "Protect margins at all costs."
            )
        elif magnitude > 5:
            detected = True
            severity = "moderate"
            response = (
                "Moderate price pressure detected. Consider selective matching "
                "on key products while maintaining margins on the rest. "
                "Increase value-add services to justify price."
            )
        elif magnitude > 2 and periods >= 3:
            detected = True
            severity = "mild"
            response = (
                "Early signs of price competition. Monitor closely. "
                "Prepare a response strategy but do not react prematurely."
            )

    # Accelerating decline is a strong signal
    if recent_change < -8:
        detected = True
        severity = "severe" if severity != "severe" else severity
        response = (
            "Rapid recent price drop detected. Competitors may be "
            "liquidating or aggressively pursuing market share. "
            "Hold your price and compete on value."
        )

    return {
        "detected": detected,
        "severity": severity,
        "recommended_response": response,
        "magnitude_pct": magnitude,
        "periods_declining": periods if direction == "decreasing" else 0,
    }


def calculate_price_elasticity_estimate(price_review_data):
    """
    Estimate how price affects demand using price-review data as a proxy.

    Higher review counts at lower prices suggest elastic demand.
    Stable review counts across price points suggest inelastic demand.

    Args:
        price_review_data: list of dicts with price, reviews, and rating.

    Returns:
        dict with elasticity_label, coefficient, and interpretation.
    """
    if not price_review_data or len(price_review_data) < 3:
        return {
            "elasticity_label": "insufficient_data",
            "coefficient": None,
            "interpretation": "Not enough data points to estimate price elasticity.",
        }

    valid_items = [
        item for item in price_review_data
        if item.get("price") and item.get("reviews") is not None
    ]
    if len(valid_items) < 3:
        return {
            "elasticity_label": "insufficient_data",
            "coefficient": None,
            "interpretation": "Not enough valid data points with price and reviews.",
        }

    prices = [item["price"] for item in valid_items]
    reviews = [item["reviews"] for item in valid_items]

    # Simple correlation as elasticity proxy
    coefficient = _simple_correlation(prices, reviews)

    if coefficient is None:
        label = "indeterminate"
        interpretation = "Could not calculate correlation between price and demand."
    elif coefficient < -0.5:
        label = "elastic"
        interpretation = (
            "Demand appears highly sensitive to price. Lower-priced products "
            "receive significantly more reviews (proxy for sales). Consider "
            "competitive pricing to maximize volume."
        )
    elif coefficient < -0.2:
        label = "moderately_elastic"
        interpretation = (
            "Demand shows some sensitivity to price. There is a moderate "
            "relationship between lower prices and higher sales volume."
        )
    elif coefficient < 0.2:
        label = "inelastic"
        interpretation = (
            "Demand appears insensitive to price. Customers buy regardless "
            "of price point, suggesting brand or quality matters more. "
            "Premium pricing may be viable."
        )
    else:
        label = "veblen"
        interpretation = (
            "Higher prices correlate with more reviews. This may indicate "
            "a prestige or luxury category where higher price signals quality. "
            "Consider premium positioning."
        )

    return {
        "elasticity_label": label,
        "coefficient": round(coefficient, 3) if coefficient is not None else None,
        "interpretation": interpretation,
        "data_points": len(valid_items),
    }


def _simple_correlation(x_values, y_values):
    """Compute Pearson correlation coefficient between two lists."""
    n = len(x_values)
    if n < 2:
        return None
    mean_x = statistics.mean(x_values)
    mean_y = statistics.mean(y_values)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
    denom_x = sum((x - mean_x) ** 2 for x in x_values) ** 0.5
    denom_y = sum((y - mean_y) ** 2 for y in y_values) ** 0.5
    if denom_x == 0 or denom_y == 0:
        return None
    return numerator / (denom_x * denom_y)
