"""
Price Comparison — Business Logic
==================================
Recommendation engines, price war detection, and elasticity estimation.
Interprets raw analysis into actionable pricing strategy decisions.
"""
import statistics


def recommend_price_position(analysis):
    """
    Recommend a pricing position: undercut, match, or premium.
    Returns dict with strategy, reasoning, suggested_range, and confidence.
    """
    dist = analysis.get("distribution", {})
    pos = analysis.get("position", {})
    trends = analysis.get("trends", {})
    median = dist.get("median", 0)
    pcts = dist.get("percentiles", {})
    trend_dir = trends.get("direction", "stable")
    pos_label = pos.get("position_label", "mid-range")

    strategy, reasoning, confidence = "match", [], 0.5

    if trend_dir == "decreasing":
        reasoning.append("Competitor prices are falling; avoid a race to the bottom.")
        confidence = 0.6
    if trend_dir == "increasing":
        reasoning.append("Market prices are rising; premium positioning is viable.")
        strategy, confidence = "premium", 0.65
    if pos_label == "budget":
        reasoning.append("You are at the low end; consider moving toward mid-range.")
        strategy, confidence = "match", 0.7
    if pos_label == "premium" and trend_dir != "increasing":
        reasoning.append("Premium position without rising market may limit volume.")
        strategy, confidence = "match", 0.55

    p25 = pcts.get("p25", median * 0.85)
    p50 = pcts.get("p50", median)
    p75 = pcts.get("p75", median * 1.15)
    if strategy == "undercut":
        rng = {"low": round(p25 * 0.85, 2), "high": round(p25, 2), "anchor": round(p50, 2)}
    elif strategy == "premium":
        rng = {"low": round(p75, 2), "high": round(p75 * 1.20, 2), "anchor": round(p50, 2)}
    else:
        rng = {"low": round(p25, 2), "high": round(p75, 2), "anchor": round(p50, 2)}

    return {"strategy": strategy, "reasoning": reasoning, "suggested_range": rng,
            "confidence": round(confidence, 2), "position_evaluated": pos_label,
            "trend_context": trend_dir}


def detect_price_war(trends):
    """
    Determine if a price war is underway among competitors.
    Detected when prices decline aggressively (>5%/period) or for 3+ periods.
    """
    direction = trends.get("direction", "stable")
    magnitude = trends.get("magnitude", 0)
    periods = trends.get("periods_analyzed", 0)
    recent = trends.get("recent_change_pct", 0)

    detected, severity = False, "none"
    response = "No action needed. Monitor competitor pricing regularly."

    if direction == "decreasing":
        if magnitude > 10:
            detected, severity = True, "severe"
            response = ("Severe price war. Do NOT follow competitors down. "
                        "Focus on value differentiation and protect margins.")
        elif magnitude > 5:
            detected, severity = True, "moderate"
            response = ("Moderate price pressure. Selectively match on key products "
                        "while maintaining margins on the rest.")
        elif magnitude > 2 and periods >= 3:
            detected, severity = True, "mild"
            response = ("Early signs of price competition. Monitor closely "
                        "and prepare a response strategy.")

    if recent < -8:
        detected, severity = True, max(severity, "severe")
        response = ("Rapid recent price drop. Competitors may be liquidating. "
                    "Hold your price and compete on value.")

    return {"detected": detected, "severity": severity, "recommended_response": response,
            "magnitude_pct": magnitude,
            "periods_declining": periods if direction == "decreasing" else 0}


def calculate_price_elasticity_estimate(price_review_data):
    """
    Estimate how price affects demand using price-review data as a proxy.
    Higher review counts at lower prices suggest elastic demand.
    """
    valid = [x for x in (price_review_data or [])
             if x.get("price") and x.get("reviews") is not None]
    if len(valid) < 3:
        return {"elasticity_label": "insufficient_data", "coefficient": None,
                "interpretation": "Not enough data points to estimate price elasticity."}

    prices = [x["price"] for x in valid]
    reviews = [x["reviews"] for x in valid]
    coeff = _correlation(prices, reviews)

    if coeff is None:
        label, interp = "indeterminate", "Could not calculate price-demand correlation."
    elif coeff < -0.5:
        label = "elastic"
        interp = ("Demand is highly price-sensitive. Lower-priced products get "
                  "significantly more sales. Consider competitive pricing for volume.")
    elif coeff < -0.2:
        label = "moderately_elastic"
        interp = ("Moderate price sensitivity. Some relationship between "
                  "lower prices and higher sales volume.")
    elif coeff < 0.2:
        label = "inelastic"
        interp = ("Demand is insensitive to price. Quality and brand matter more. "
                  "Premium pricing may be viable.")
    else:
        label = "veblen"
        interp = ("Higher prices correlate with more sales. This may be a prestige "
                  "category where price signals quality. Consider premium positioning.")

    return {"elasticity_label": label,
            "coefficient": round(coeff, 3) if coeff is not None else None,
            "interpretation": interp, "data_points": len(valid)}


def _correlation(x_vals, y_vals):
    """Pearson correlation coefficient between two lists."""
    n = len(x_vals)
    if n < 2:
        return None
    mx, my = statistics.mean(x_vals), statistics.mean(y_vals)
    num = sum((x - mx) * (y - my) for x, y in zip(x_vals, y_vals))
    dx = sum((x - mx) ** 2 for x in x_vals) ** 0.5
    dy = sum((y - my) ** 2 for y in y_vals) ** 0.5
    return num / (dx * dy) if dx and dy else None
