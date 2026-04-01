"""
code.py — Main entry point for review analysis.

Provides analyze_reviews(input_payload) following the engine contract:
    {status, data, meta, error}
"""

import time
from datetime import datetime, timedelta

from .rules import validate_review_dataset, check_review_authenticity, flag_suspicious_patterns
from .data import get_benchmark_for_category, get_complaint_category


def analyze_reviews(input_payload):
    """Analyze competitor reviews and return structured findings.

    Args:
        input_payload: dict with keys:
            - reviews: list of review dicts (rating, text, date, verified, has_photo, length)
            - category: str product category for benchmark comparison
            - competitor_name: str name of the competitor
            - our_review_count: int (optional) our current review count

    Returns:
        dict following engine contract {status, data, meta, error}
    """
    start_time = time.time()

    try:
        reviews = input_payload.get("reviews", [])
        category = input_payload.get("category", "general")
        competitor_name = input_payload.get("competitor_name", "unknown")

        validation = validate_review_dataset(reviews)
        if not validation["is_valid"]:
            return {
                "status": "error",
                "data": None,
                "meta": {"competitor": competitor_name, "review_count": len(reviews)},
                "error": validation["reason"],
            }

        rating_dist = _compute_rating_distribution(reviews)
        velocity = _compute_review_velocity(reviews)
        sentiment = _compute_sentiment_breakdown(reviews)
        complaints = _extract_complaints(reviews)
        praise = _extract_praise(reviews)
        quality = _compute_review_quality(reviews)
        trust = _compute_trust_score(reviews)
        benchmarks = get_benchmark_for_category(category)

        data = {
            "competitor": competitor_name,
            "total_reviews": len(reviews),
            "rating_distribution": rating_dist,
            "average_rating": _weighted_average_rating(rating_dist),
            "review_velocity": velocity,
            "sentiment_breakdown": sentiment,
            "complaints": complaints,
            "praise": praise,
            "review_quality": quality,
            "trust_score": trust,
            "category_benchmarks": benchmarks,
            "vs_benchmark": _compare_to_benchmark(rating_dist, velocity, benchmarks),
        }

        elapsed = round(time.time() - start_time, 3)
        return {
            "status": "success",
            "data": data,
            "meta": {
                "module": "review_analyzer",
                "version": "1.0.0",
                "processing_time_sec": elapsed,
                "reviews_analyzed": len(reviews),
                "category": category,
            },
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "data": None,
            "meta": {"module": "review_analyzer", "version": "1.0.0"},
            "error": str(exc),
        }


def _compute_rating_distribution(reviews):
    dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in reviews:
        rating = int(r.get("rating", 0))
        if 1 <= rating <= 5:
            dist[rating] += 1
    total = max(sum(dist.values()), 1)
    return {str(k): {"count": v, "pct": round(v / total * 100, 1)} for k, v in dist.items()}


def _weighted_average_rating(dist):
    total_count = sum(d["count"] for d in dist.values())
    if total_count == 0:
        return 0.0
    weighted = sum(int(star) * d["count"] for star, d in dist.items())
    return round(weighted / total_count, 2)


def _compute_review_velocity(reviews):
    dates = []
    for r in reviews:
        d = r.get("date")
        if d:
            try:
                dates.append(datetime.fromisoformat(str(d)))
            except (ValueError, TypeError):
                continue
    if len(dates) < 2:
        return {"reviews_per_month": 0, "trend": "insufficient_data"}
    dates.sort()
    span_days = max((dates[-1] - dates[0]).days, 1)
    span_months = span_days / 30.44
    rpm = round(len(dates) / span_months, 1)
    midpoint = len(dates) // 2
    first_half_span = max((dates[midpoint] - dates[0]).days, 1)
    second_half_span = max((dates[-1] - dates[midpoint]).days, 1)
    first_rate = midpoint / (first_half_span / 30.44)
    second_rate = (len(dates) - midpoint) / (second_half_span / 30.44)
    if second_rate > first_rate * 1.2:
        trend = "accelerating"
    elif second_rate < first_rate * 0.8:
        trend = "decelerating"
    else:
        trend = "stable"
    return {"reviews_per_month": rpm, "trend": trend}


def _compute_sentiment_breakdown(reviews):
    positive = sum(1 for r in reviews if r.get("rating", 0) >= 4)
    negative = sum(1 for r in reviews if r.get("rating", 0) <= 2)
    neutral = len(reviews) - positive - negative
    total = max(len(reviews), 1)
    return {
        "positive": {"count": positive, "pct": round(positive / total * 100, 1)},
        "neutral": {"count": neutral, "pct": round(neutral / total * 100, 1)},
        "negative": {"count": negative, "pct": round(negative / total * 100, 1)},
    }


def _extract_complaints(reviews):
    low_reviews = [r for r in reviews if r.get("rating", 5) <= 2]
    categories = {}
    for r in low_reviews:
        text = r.get("text", "")
        cat = get_complaint_category(text)
        categories.setdefault(cat, []).append(text[:200])
    return {cat: {"count": len(texts), "examples": texts[:3]} for cat, texts in categories.items()}


def _extract_praise(reviews):
    high_reviews = [r for r in reviews if r.get("rating", 0) >= 4]
    themes = {}
    praise_keywords = {
        "quality": ["quality", "well made", "durable", "sturdy", "solid"],
        "value": ["worth", "value", "great price", "affordable", "deal"],
        "design": ["beautiful", "looks great", "stylish", "love the design", "aesthetic"],
        "comfort": ["comfortable", "soft", "fits perfect", "cozy", "smooth"],
        "fast_shipping": ["fast shipping", "quick delivery", "arrived early", "prompt"],
    }
    for r in high_reviews:
        text = r.get("text", "").lower()
        matched = False
        for theme, keywords in praise_keywords.items():
            if any(kw in text for kw in keywords):
                themes.setdefault(theme, []).append(r.get("text", "")[:200])
                matched = True
                break
        if not matched:
            themes.setdefault("general_positive", []).append(r.get("text", "")[:200])
    return {t: {"count": len(txts), "examples": txts[:3]} for t, txts in themes.items()}


def _compute_review_quality(reviews):
    total = max(len(reviews), 1)
    photo_count = sum(1 for r in reviews if r.get("has_photo"))
    verified_count = sum(1 for r in reviews if r.get("verified"))
    lengths = [r.get("length", len(r.get("text", ""))) for r in reviews]
    avg_length = round(sum(lengths) / total, 1) if lengths else 0
    return {
        "photo_review_pct": round(photo_count / total * 100, 1),
        "verified_purchase_pct": round(verified_count / total * 100, 1),
        "avg_review_length": avg_length,
    }


def _compute_trust_score(reviews):
    authenticity_results = [check_review_authenticity(r) for r in reviews]
    suspicious_count = sum(1 for a in authenticity_results if not a["is_authentic"])
    flags = flag_suspicious_patterns(reviews)
    total = max(len(reviews), 1)
    trust_pct = round((1 - suspicious_count / total) * 100, 1)
    return {
        "trust_score_pct": trust_pct,
        "suspicious_review_count": suspicious_count,
        "pattern_flags": flags,
    }


def _compare_to_benchmark(rating_dist, velocity, benchmarks):
    avg = _weighted_average_rating(rating_dist)
    bench_rating = benchmarks.get("avg_rating", 4.0)
    bench_velocity = benchmarks.get("avg_velocity", 10)
    return {
        "rating_vs_benchmark": round(avg - bench_rating, 2),
        "velocity_vs_benchmark": round(velocity["reviews_per_month"] - bench_velocity, 1),
    }
