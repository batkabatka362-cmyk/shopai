"""
Price Comparison — Main Entry Point
====================================
Implements the engine contract: {status, data, meta, error}.
Orchestrates price distribution analysis, gap detection, trend analysis,
position evaluation, and price-to-value ratio calculation.
"""

import statistics
from datetime import datetime, timezone

from .logic import (
    recommend_price_position,
    detect_price_war,
    calculate_price_elasticity_estimate,
)
from .rules import validate_price_input, check_margin_floor, is_premium_eligible
from .data import PERCENTILE_LABELS


def _calculate_percentile(sorted_prices, percentile):
    """Return the value at the given percentile (0-100) from sorted prices."""
    if not sorted_prices:
        return 0.0
    n = len(sorted_prices)
    idx = (percentile / 100.0) * (n - 1)
    lower = int(idx)
    upper = min(lower + 1, n - 1)
    weight = idx - lower
    return round(sorted_prices[lower] * (1 - weight) + sorted_prices[upper] * weight, 2)


def _calculate_mode(prices):
    """Return the most common price, or the median if no repeats exist."""
    if not prices:
        return 0.0
    try:
        return statistics.mode(prices)
    except statistics.StatisticsError:
        return statistics.median(prices)


def _analyze_distribution(all_prices):
    """Compute min, max, median, mode, and key percentiles."""
    sorted_prices = sorted(all_prices)
    return {
        "min": sorted_prices[0],
        "max": sorted_prices[-1],
        "median": round(statistics.median(sorted_prices), 2),
        "mode": round(_calculate_mode(sorted_prices), 2),
        "mean": round(statistics.mean(sorted_prices), 2),
        "std_dev": round(statistics.stdev(sorted_prices), 2) if len(sorted_prices) > 1 else 0.0,
        "percentiles": {
            label: _calculate_percentile(sorted_prices, pct)
            for label, pct in PERCENTILE_LABELS.items()
        },
        "count": len(sorted_prices),
    }


def _detect_price_gaps(sorted_prices, min_gap_ratio=0.15):
    """Find price ranges where no competitors have products listed."""
    gaps = []
    for i in range(len(sorted_prices) - 1):
        low = sorted_prices[i]
        high = sorted_prices[i + 1]
        gap_size = high - low
        if low > 0 and (gap_size / low) >= min_gap_ratio:
            gaps.append({
                "range_low": round(low, 2),
                "range_high": round(high, 2),
                "gap_size": round(gap_size, 2),
                "gap_percent": round((gap_size / low) * 100, 1),
                "midpoint": round((low + high) / 2, 2),
            })
    return sorted(gaps, key=lambda g: g["gap_size"], reverse=True)


def _analyze_trends(price_history):
    """Determine if competitors are raising or lowering prices over time."""
    if not price_history or len(price_history) < 2:
        return {"direction": "stable", "magnitude": 0.0, "periods_analyzed": 0}
    changes = []
    for i in range(1, len(price_history)):
        prev = price_history[i - 1].get("avg_price", 0)
        curr = price_history[i].get("avg_price", 0)
        if prev > 0:
            changes.append((curr - prev) / prev)
    if not changes:
        return {"direction": "stable", "magnitude": 0.0, "periods_analyzed": 0}
    avg_change = statistics.mean(changes)
    if avg_change > 0.02:
        direction = "increasing"
    elif avg_change < -0.02:
        direction = "decreasing"
    else:
        direction = "stable"
    return {
        "direction": direction,
        "magnitude": round(abs(avg_change) * 100, 2),
        "avg_period_change_pct": round(avg_change * 100, 2),
        "periods_analyzed": len(changes),
        "recent_change_pct": round(changes[-1] * 100, 2) if changes else 0.0,
    }


def _evaluate_position(your_price, distribution):
    """Determine where your price sits within the competitor distribution."""
    percentiles = distribution["percentiles"]
    position_label = "mid-range"
    if your_price <= percentiles["p25"]:
        position_label = "budget"
    elif your_price <= percentiles["p50"]:
        position_label = "below-average"
    elif your_price <= percentiles["p75"]:
        position_label = "above-average"
    else:
        position_label = "premium"
    distance_from_median = your_price - distribution["median"]
    pct_from_median = (
        round((distance_from_median / distribution["median"]) * 100, 2)
        if distribution["median"] > 0 else 0.0
    )
    return {
        "your_price": your_price,
        "position_label": position_label,
        "distance_from_median": round(distance_from_median, 2),
        "pct_from_median": pct_from_median,
        "cheaper_than_pct": _rank_percentile(your_price, distribution),
    }


def _rank_percentile(price, distribution):
    """What percent of competitors are more expensive than your price."""
    total = distribution["count"]
    if total == 0:
        return 0.0
    cheaper_count = sum(1 for p in range(total) if distribution["min"] + p <= price)
    return min(round((cheaper_count / total) * 100, 1), 100.0)


def _calculate_price_to_value(prices, ratings, review_counts):
    """Compute price-to-value ratios using ratings and review counts."""
    results = []
    for i in range(min(len(prices), len(ratings))):
        price = prices[i]
        rating = ratings[i] if i < len(ratings) else 0
        reviews = review_counts[i] if i < len(review_counts) else 0
        value_score = (rating * 20) + min(reviews / 10, 50) if rating > 0 else 0
        ptv_ratio = round(price / value_score, 2) if value_score > 0 else None
        results.append({
            "price": price,
            "rating": rating,
            "reviews": reviews,
            "value_score": round(value_score, 2),
            "price_to_value_ratio": ptv_ratio,
        })
    ratios = [r["price_to_value_ratio"] for r in results if r["price_to_value_ratio"]]
    avg_ratio = round(statistics.mean(ratios), 2) if ratios else None
    return {"items": results, "avg_price_to_value": avg_ratio}


def compare_prices(input_payload):
    """
    Main engine entry point. Compares pricing across competitors.

    Args:
        input_payload: dict with keys your_price, competitor_prices,
            product_category, and optional fields.

    Returns:
        dict with {status, data, meta, error} per engine contract.
    """
    meta = {
        "module": "price_comparison",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    validation_error = validate_price_input(input_payload)
    if validation_error:
        return {"status": "error", "data": None, "meta": meta, "error": validation_error}

    try:
        your_price = float(input_payload["your_price"])
        competitor_prices = [float(p) for p in input_payload["competitor_prices"]]
        all_prices = competitor_prices + [your_price]
        sorted_prices = sorted(competitor_prices)

        distribution = _analyze_distribution(all_prices)
        price_gaps = _detect_price_gaps(sorted_prices)
        trends = _analyze_trends(input_payload.get("price_history"))
        position = _evaluate_position(your_price, distribution)

        ratings = input_payload.get("competitor_ratings", [])
        review_counts = input_payload.get("competitor_review_counts", [])
        price_to_value = _calculate_price_to_value(competitor_prices, ratings, review_counts)

        cost_basis = input_payload.get("cost_basis")
        margin_check = check_margin_floor(your_price, cost_basis) if cost_basis else None

        your_rating = input_payload.get("your_rating", 0)
        premium_eligible = is_premium_eligible(your_rating)

        recommendation = recommend_price_position(
            {"distribution": distribution, "position": position, "trends": trends}
        )
        price_war = detect_price_war(trends)
        elasticity = calculate_price_elasticity_estimate(price_to_value.get("items", []))

        data = {
            "distribution": distribution,
            "price_gaps": price_gaps,
            "trends": trends,
            "your_position": position,
            "price_to_value": price_to_value,
            "recommendation": recommendation,
            "price_war_detected": price_war,
            "elasticity_estimate": elasticity,
            "margin_check": margin_check,
            "premium_eligible": premium_eligible,
        }
        meta["competitor_count"] = len(competitor_prices)
        meta["gaps_found"] = len(price_gaps)
        return {"status": "success", "data": data, "meta": meta, "error": None}

    except Exception as exc:
        return {
            "status": "error",
            "data": None,
            "meta": meta,
            "error": f"Price comparison failed: {str(exc)}",
        }
