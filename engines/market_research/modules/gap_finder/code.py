"""Gap finder — detect underserved niches and unmet customer needs.

A "gap" is where customer DEMAND exists but SUPPLY is weak:
  - High search volume + few quality products = gap
  - Negative reviews on existing products = improvement opportunity
  - Price gaps (no product between $20-50 in a category)
  - Feature gaps (customers asking for X, nobody sells X)
  - Quality gaps (all products are cheap/low quality, no premium option)

Input contract:  {status, data: {products, reviews, search_data, category}, meta, error}
Output contract: {status, data: {gaps}, meta: {engine, confidence, timestamp}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.helpers import safe_float, safe_int


def find_gaps(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Main gap detection — follows engine contract.

    6 stages: validate → extract → decide → execute → validate_output → return
    """
    # Stage 1: Input validation
    validation = _validate_input(input_payload)
    if not validation["valid"]:
        return _error_output("gap_finder", validation["reason"])

    # Stage 2: Feature extraction (don't mutate input)
    data = copy.deepcopy(input_payload.get("data", {}))
    features = _extract_features(data)

    # Stage 3: Decision logic — identify gaps
    gaps = _detect_gaps(features)

    # Stage 4: Execution — score and rank gaps
    ranked_gaps = _rank_gaps(gaps, features)

    # Stage 5: Output validation
    output_valid = _validate_output(ranked_gaps)
    if not output_valid["valid"]:
        return _error_output("gap_finder", output_valid["reason"])

    # Stage 6: Return structured output
    return {
        "status": "success",
        "data": {
            "gaps": ranked_gaps,
            "total_gaps_found": len(ranked_gaps),
            "high_opportunity": [g for g in ranked_gaps if g["opportunity_score"] >= 70],
            "category": data.get("category", ""),
        },
        "meta": {
            "engine": "gap_finder",
            "confidence": _compute_confidence(features, ranked_gaps),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "features_analyzed": len(features),
        },
        "error": None,
    }


# ── Stage 1: Input Validation ──

def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate input follows engine contract."""
    if not isinstance(payload, dict):
        return {"valid": False, "reason": "Input must be a dict"}

    data = payload.get("data")
    if not isinstance(data, dict):
        return {"valid": False, "reason": "Input.data must be a dict"}

    # Need at least one data source
    has_products = bool(data.get("products"))
    has_search = bool(data.get("search_data"))
    has_category = bool(data.get("category"))

    if not (has_products or has_search or has_category):
        return {"valid": False, "reason": "Need at least products, search_data, or category"}

    return {"valid": True, "reason": "OK"}


# ── Stage 2: Feature Extraction ──

def _extract_features(data: dict[str, Any]) -> dict[str, Any]:
    """Extract analyzable features from raw data. Never mutates input."""
    features: dict[str, Any] = {"category": data.get("category", "")}

    # Product features
    products = data.get("products", [])
    if products:
        prices = [safe_float(p.get("price", 0)) for p in products if isinstance(p, dict) and safe_float(p.get("price", 0)) > 0]
        ratings = [safe_float(p.get("rating", 0)) for p in products if isinstance(p, dict) and safe_float(p.get("rating", 0)) > 0]
        review_counts = [safe_int(p.get("review_count", 0)) for p in products if isinstance(p, dict)]

        features["price_range"] = {"min": min(prices) if prices else 0, "max": max(prices) if prices else 0, "avg": sum(prices) / len(prices) if prices else 0}
        features["price_distribution"] = _compute_price_distribution(prices)
        features["avg_rating"] = sum(ratings) / len(ratings) if ratings else 0
        features["avg_review_count"] = sum(review_counts) / len(review_counts) if review_counts else 0
        features["product_count"] = len(products)
        features["low_rated_count"] = sum(1 for r in ratings if r < 3.5)
        features["no_review_count"] = sum(1 for rc in review_counts if rc < 5)

    # Search features
    search_data = data.get("search_data", {})
    if search_data:
        features["search_volume"] = safe_int(search_data.get("monthly_volume", 0))
        features["search_competition"] = search_data.get("competition", "unknown")
        features["related_searches"] = search_data.get("related", [])

    # Review features (negative review analysis)
    reviews = data.get("reviews", [])
    if reviews:
        negative = [r for r in reviews if isinstance(r, dict) and safe_float(r.get("rating", 5)) <= 2]
        features["negative_reviews"] = negative
        features["negative_pct"] = round(len(negative) / max(len(reviews), 1) * 100, 1)
        features["common_complaints"] = _extract_complaints(negative)

    return features


# ── Stage 3: Decision Logic — Gap Detection ──

def _detect_gaps(features: dict[str, Any]) -> list[dict[str, Any]]:
    """Identify specific market gaps from extracted features."""
    gaps = []

    # Gap type 1: Price gap — no products in a price tier
    price_dist = features.get("price_distribution", {})
    for tier, count in price_dist.items():
        if count == 0:
            gaps.append({
                "type": "price_gap",
                "description": f"No products in {tier} price tier",
                "detail": f"Market has products in other tiers but nothing in {tier}",
                "actionable": True,
            })

    # Gap type 2: Quality gap — low average rating
    avg_rating = features.get("avg_rating", 0)
    if 0 < avg_rating < 4.0:
        gaps.append({
            "type": "quality_gap",
            "description": f"Average rating only {avg_rating:.1f}/5 — quality opportunity",
            "detail": "Customers dissatisfied with current options. Premium quality product could win.",
            "actionable": True,
        })

    # Gap type 3: Review gap — products with few reviews (new/untested market)
    no_review_pct = features.get("no_review_count", 0) / max(features.get("product_count", 1), 1) * 100
    if no_review_pct > 50:
        gaps.append({
            "type": "new_market_gap",
            "description": f"{no_review_pct:.0f}% products have <5 reviews — emerging market",
            "detail": "Low review counts suggest new/growing market. Early entry advantage possible.",
            "actionable": True,
        })

    # Gap type 4: Demand-supply mismatch — high search, few products
    search_vol = features.get("search_volume", 0)
    product_count = features.get("product_count", 0)
    if search_vol > 5000 and product_count < 20:
        gaps.append({
            "type": "demand_supply_gap",
            "description": f"High search ({search_vol:,}/month) but only {product_count} products",
            "detail": "Demand exceeds supply — strong entry opportunity.",
            "actionable": True,
        })

    # Gap type 5: Complaint-driven gap — recurring negative feedback
    complaints = features.get("common_complaints", [])
    for complaint in complaints[:3]:
        gaps.append({
            "type": "complaint_gap",
            "description": f"Recurring complaint: {complaint['issue']}",
            "detail": f"Mentioned in {complaint['count']} negative reviews. Fix this → competitive advantage.",
            "actionable": True,
        })

    # Gap type 6: Competition weakness — low-rated competitors dominating
    low_rated = features.get("low_rated_count", 0)
    total = features.get("product_count", 0)
    if total > 0 and low_rated / total > 0.3:
        gaps.append({
            "type": "competitor_weakness",
            "description": f"{low_rated}/{total} products rated below 3.5 stars",
            "detail": "Weak competition — a quality product can easily rank higher.",
            "actionable": True,
        })

    return gaps


# ── Stage 4: Execution — Score and Rank Gaps ──

def _rank_gaps(gaps: list[dict[str, Any]], features: dict[str, Any]) -> list[dict[str, Any]]:
    """Score each gap by opportunity size and actionability."""
    scored = []

    for gap in gaps:
        score = _score_gap(gap, features)
        gap["opportunity_score"] = score
        gap["priority"] = "high" if score >= 70 else "medium" if score >= 40 else "low"
        scored.append(gap)

    scored.sort(key=lambda g: g["opportunity_score"], reverse=True)
    return scored


def _score_gap(gap: dict[str, Any], features: dict[str, Any]) -> int:
    """Score a single gap (0-100)."""
    base_scores = {
        "demand_supply_gap": 85,      # Highest — proven demand, weak supply
        "complaint_gap": 75,           # Actionable — fix known problem
        "quality_gap": 70,             # Good — beat on quality
        "competitor_weakness": 65,     # Solid — weak competition
        "price_gap": 55,               # Moderate — untested price point
        "new_market_gap": 50,          # Risky — unproven market
    }
    score = base_scores.get(gap["type"], 40)

    # Boost for high search volume
    if features.get("search_volume", 0) > 10000:
        score = min(100, score + 10)

    # Boost for actionability
    if gap.get("actionable"):
        score = min(100, score + 5)

    return score


# ── Stage 5: Output Validation ──

def _validate_output(gaps: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate output before returning."""
    if not isinstance(gaps, list):
        return {"valid": False, "reason": "Gaps must be a list"}

    for gap in gaps:
        if not isinstance(gap, dict):
            return {"valid": False, "reason": "Each gap must be a dict"}
        required = ("type", "description", "opportunity_score")
        for field in required:
            if field not in gap:
                return {"valid": False, "reason": f"Gap missing required field: {field}"}

    return {"valid": True, "reason": "OK"}


# ── Helpers ──

def _compute_price_distribution(prices: list[float]) -> dict[str, int]:
    """Count products in each price tier."""
    tiers = {
        "budget_under_15": 0,
        "value_15_30": 0,
        "mid_30_60": 0,
        "premium_60_100": 0,
        "luxury_100_plus": 0,
    }
    for p in prices:
        if p < 15:
            tiers["budget_under_15"] += 1
        elif p < 30:
            tiers["value_15_30"] += 1
        elif p < 60:
            tiers["mid_30_60"] += 1
        elif p < 100:
            tiers["premium_60_100"] += 1
        else:
            tiers["luxury_100_plus"] += 1
    return tiers


def _extract_complaints(negative_reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract common complaints from negative reviews."""
    # Simple keyword-based complaint extraction
    complaint_keywords = {
        "shipping": ["shipping", "delivery", "late", "delayed", "slow shipping"],
        "quality": ["cheap", "broke", "flimsy", "poor quality", "fell apart"],
        "sizing": ["size", "too small", "too large", "doesn't fit", "sizing"],
        "not_as_described": ["not as described", "different", "misleading", "doesn't match", "false"],
        "customer_service": ["support", "refund", "return", "response", "customer service"],
        "price": ["overpriced", "expensive", "not worth", "waste of money"],
    }

    counts: dict[str, int] = {}
    for review in negative_reviews:
        text = (review.get("text", "") + " " + review.get("title", "")).lower()
        for issue, keywords in complaint_keywords.items():
            if any(kw in text for kw in keywords):
                counts[issue] = counts.get(issue, 0) + 1

    complaints = [
        {"issue": issue, "count": count}
        for issue, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)
    ]
    return complaints


def _compute_confidence(features: dict[str, Any], gaps: list[dict[str, Any]]) -> float:
    """Confidence in gap analysis (0-1)."""
    data_points = 0
    if features.get("product_count", 0) > 0:
        data_points += 1
    if features.get("search_volume", 0) > 0:
        data_points += 1
    if features.get("negative_reviews"):
        data_points += 1
    if features.get("price_range", {}).get("max", 0) > 0:
        data_points += 1

    base = min(0.9, data_points * 0.25)
    if len(gaps) == 0:
        base *= 0.5  # Low confidence if no gaps found (might be missing data)

    return round(base, 2)


def _error_output(engine: str, reason: str) -> dict[str, Any]:
    """Standard error output following engine contract."""
    return {
        "status": "fail",
        "data": None,
        "meta": {
            "engine": engine,
            "confidence": 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": {"reason": reason},
    }
