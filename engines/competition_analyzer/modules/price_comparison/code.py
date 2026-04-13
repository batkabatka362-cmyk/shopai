"""
Price Comparison — Main Entry Point
====================================
Implements the engine contract: {status, data, meta, error}.
Orchestrates distribution analysis, gap detection, trend analysis,
position evaluation, and price-to-value ratio calculation.
"""
import statistics
from datetime import datetime, timezone
from .logic import recommend_price_position, detect_price_war, calculate_price_elasticity_estimate
from .rules import validate_price_input, check_margin_floor, is_premium_eligible
from .data import PERCENTILE_LABELS


def _percentile(sorted_prices, pct):
    """Return the value at the given percentile (0-100)."""
    n = len(sorted_prices)
    idx = (pct / 100.0) * (n - 1)
    lo, hi = int(idx), min(int(idx) + 1, n - 1)
    return round(sorted_prices[lo] * (1 - (idx - lo)) + sorted_prices[hi] * (idx - lo), 2)


def _mode(prices):
    """Most common price, falling back to median if all unique."""
    try:
        return statistics.mode(prices)
    except statistics.StatisticsError:
        return statistics.median(prices)


def _analyze_distribution(all_prices):
    """Compute min, max, median, mode, mean, std_dev, and key percentiles."""
    s = sorted(all_prices)
    return {
        "min": s[0], "max": s[-1],
        "median": round(statistics.median(s), 2),
        "mode": round(_mode(s), 2),
        "mean": round(statistics.mean(s), 2),
        "std_dev": round(statistics.stdev(s), 2) if len(s) > 1 else 0.0,
        "percentiles": {label: _percentile(s, pct) for label, pct in PERCENTILE_LABELS.items()},
        "count": len(s),
    }


def _detect_price_gaps(sorted_prices, min_gap_ratio=0.15):
    """Find price ranges where no competitors have products listed."""
    gaps = []
    for i in range(len(sorted_prices) - 1):
        lo, hi = sorted_prices[i], sorted_prices[i + 1]
        if lo > 0 and (hi - lo) / lo >= min_gap_ratio:
            gaps.append({
                "range_low": round(lo, 2), "range_high": round(hi, 2),
                "gap_size": round(hi - lo, 2),
                "gap_percent": round((hi - lo) / lo * 100, 1),
                "midpoint": round((lo + hi) / 2, 2),
            })
    return sorted(gaps, key=lambda g: g["gap_size"], reverse=True)


def _analyze_trends(price_history):
    """Determine if competitors are raising or lowering prices over time."""
    if not price_history or len(price_history) < 2:
        return {"direction": "stable", "magnitude": 0.0, "periods_analyzed": 0}
    changes = []
    for i in range(1, len(price_history)):
        prev, curr = price_history[i - 1].get("avg_price", 0), price_history[i].get("avg_price", 0)
        if prev > 0:
            changes.append((curr - prev) / prev)
    if not changes:
        return {"direction": "stable", "magnitude": 0.0, "periods_analyzed": 0}
    avg_change = statistics.mean(changes)
    direction = "increasing" if avg_change > 0.02 else ("decreasing" if avg_change < -0.02 else "stable")
    return {
        "direction": direction, "magnitude": round(abs(avg_change) * 100, 2),
        "avg_period_change_pct": round(avg_change * 100, 2),
        "periods_analyzed": len(changes),
        "recent_change_pct": round(changes[-1] * 100, 2),
    }


def _evaluate_position(your_price, dist):
    """Determine where your price sits within the competitor distribution."""
    p = dist["percentiles"]
    if your_price <= p["p25"]:
        label = "budget"
    elif your_price <= p["p50"]:
        label = "below-average"
    elif your_price <= p["p75"]:
        label = "above-average"
    else:
        label = "premium"
    diff = your_price - dist["median"]
    return {
        "your_price": your_price, "position_label": label,
        "distance_from_median": round(diff, 2),
        "pct_from_median": round(diff / dist["median"] * 100, 2) if dist["median"] > 0 else 0.0,
    }


def _price_to_value(prices, ratings, review_counts):
    """Compute price-to-value ratios using ratings and review counts."""
    items = []
    for i in range(min(len(prices), len(ratings))):
        r = ratings[i] if i < len(ratings) else 0
        rv = review_counts[i] if i < len(review_counts) else 0
        vs = (r * 20) + min(rv / 10, 50) if r > 0 else 0
        ptv = round(prices[i] / vs, 2) if vs > 0 else None
        items.append({"price": prices[i], "rating": r, "reviews": rv,
                       "value_score": round(vs, 2), "price_to_value_ratio": ptv})
    ratios = [x["price_to_value_ratio"] for x in items if x["price_to_value_ratio"]]
    return {"items": items, "avg_price_to_value": round(statistics.mean(ratios), 2) if ratios else None}


def compare_prices(input_payload):
    """
    Main engine entry point. Returns {status, data, meta, error}.
    Requires: your_price, competitor_prices, product_category.
    """
    meta = {"module": "price_comparison", "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat()}
    err = validate_price_input(input_payload)
    if err:
        return {"status": "error", "data": None, "meta": meta, "error": err}
    try:
        yp = float(input_payload["your_price"])
        cp = [float(p) for p in input_payload["competitor_prices"]]
        dist = _analyze_distribution(cp + [yp])
        gaps = _detect_price_gaps(sorted(cp))
        trends = _analyze_trends(input_payload.get("price_history"))
        pos = _evaluate_position(yp, dist)
        rats = input_payload.get("competitor_ratings", [])
        revs = input_payload.get("competitor_review_counts", [])
        ptv = _price_to_value(cp, rats, revs)
        cost = input_payload.get("cost_basis")
        data = {
            "distribution": dist, "price_gaps": gaps, "trends": trends,
            "your_position": pos, "price_to_value": ptv,
            "recommendation": recommend_price_position(
                {"distribution": dist, "position": pos, "trends": trends}),
            "price_war_detected": detect_price_war(trends),
            "elasticity_estimate": calculate_price_elasticity_estimate(ptv.get("items", [])),
            "margin_check": check_margin_floor(yp, cost) if cost else None,
            "premium_eligible": is_premium_eligible(input_payload.get("your_rating", 0)),
        }
        meta.update({"competitor_count": len(cp), "gaps_found": len(gaps)})
        return {"status": "success", "data": data, "meta": meta, "error": None}
    except Exception as exc:
        return {"status": "error", "data": None, "meta": meta,
                "error": f"Price comparison failed: {exc}"}
