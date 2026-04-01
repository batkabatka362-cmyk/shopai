"""Marketplace trends analysis — detect trending products from bestseller lists.

Marketplace bestseller ranks (BSR) are the most reliable demand signal:
  - Amazon BSR moves within hours of real purchases
  - Shopify trending stores reveal DTC winners
  - Etsy trending captures handmade/unique product demand

Input: {products, marketplace, timeframe}
Output: {trending_products, new_bestsellers, cross_marketplace, velocity_scores}
"""
from __future__ import annotations

import copy
import math
import time
from typing import Any

from utils.helpers import safe_float, safe_int


MARKETPLACE_WEIGHTS = {
    "amazon": 1.3,
    "shopify": 1.0,
    "etsy": 0.9,
}


def analyze_marketplace_trends(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Analyze marketplace bestseller trends — engine contract."""
    validation = _validate_input(input_payload)
    if not validation["valid"]:
        return _error_output(validation["reason"])

    data = copy.deepcopy(input_payload.get("data", {}))
    features = _extract_features(data)
    analysis = _analyze(features)
    insights = _generate_insights(analysis, features)

    output_check = _validate_output(insights)
    if not output_check["valid"]:
        return _error_output(output_check["reason"])

    return {
        "status": "success",
        "data": insights,
        "meta": {
            "engine": "marketplace_trends",
            "confidence": _confidence(features),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": None,
    }


def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"valid": False, "reason": "Input must be dict"}
    data = payload.get("data")
    if not isinstance(data, dict):
        return {"valid": False, "reason": "Input.data must be dict"}
    if not (data.get("products") or data.get("category") or data.get("marketplace")):
        return {"valid": False, "reason": "Need products, category, or marketplace"}
    return {"valid": True, "reason": "OK"}


def _extract_features(data: dict[str, Any]) -> dict[str, Any]:
    features: dict[str, Any] = {
        "category": data.get("category", ""),
        "marketplace": data.get("marketplace", "amazon"),
        "timeframe": data.get("timeframe", "7_days"),
    }

    products = data.get("products", [])
    if isinstance(products, list):
        features["products"] = []
        for p in products:
            if isinstance(p, dict):
                features["products"].append({
                    "name": str(p.get("name", p.get("product", ""))),
                    "asin": str(p.get("asin", "")),
                    "current_bsr": safe_int(p.get("current_bsr", p.get("bsr", 0))),
                    "previous_bsr": safe_int(p.get("previous_bsr", 0)),
                    "bsr_history": p.get("bsr_history", []),
                    "price": safe_float(p.get("price", 0)),
                    "review_count": safe_int(p.get("review_count", 0)),
                    "rating": safe_float(p.get("rating", 0)),
                    "category": str(p.get("category", data.get("category", ""))),
                    "marketplaces": p.get("marketplaces", {}),
                    "first_seen_days_ago": safe_int(p.get("first_seen_days_ago", 0)),
                    "is_new_arrival": bool(p.get("is_new_arrival", False)),
                })
            elif isinstance(p, str):
                features["products"].append({
                    "name": p, "asin": "", "current_bsr": 0,
                    "previous_bsr": 0, "bsr_history": [], "price": 0,
                    "review_count": 0, "rating": 0, "category": "",
                    "marketplaces": {}, "first_seen_days_ago": 0,
                    "is_new_arrival": False,
                })
    return features


def _analyze(features: dict[str, Any]) -> dict[str, Any]:
    products = features.get("products", [])
    scored = []

    for product in products:
        bsr_velocity = _bsr_velocity_score(product)
        rank_improvement = _rank_improvement(product)
        cross_mkt = _cross_marketplace_score(product)
        newness_bonus = _newness_score(product)

        composite = _composite_score(bsr_velocity, rank_improvement, cross_mkt, newness_bonus)
        scored.append({
            **product,
            "bsr_velocity": bsr_velocity,
            "rank_improvement": rank_improvement,
            "cross_marketplace_score": cross_mkt,
            "newness_bonus": newness_bonus,
            "composite_score": composite,
        })

    scored.sort(key=lambda p: p["composite_score"], reverse=True)

    trending = [p for p in scored if p["composite_score"] >= 60]
    rising = [p for p in scored if 30 <= p["composite_score"] < 60]
    stable = [p for p in scored if p["composite_score"] < 30]

    return {"trending": trending, "rising": rising, "stable": stable}


def _generate_insights(analysis: dict[str, Any], features: dict[str, Any]) -> dict[str, Any]:
    trending = analysis["trending"]
    rising = analysis["rising"]

    top_opportunities = []
    for p in trending[:5]:
        marketplaces_active = [name for name, data in p.get("marketplaces", {}).items()
                               if isinstance(data, dict) and data.get("rank", 0) > 0]
        if not marketplaces_active and p.get("current_bsr", 0) > 0:
            marketplaces_active = [features.get("marketplace", "amazon")]
        top_opportunities.append({
            "product": p["name"],
            "current_bsr": p["current_bsr"],
            "bsr_velocity": p["bsr_velocity"],
            "composite_score": p["composite_score"],
            "marketplaces_active": marketplaces_active,
            "cross_marketplace_score": p["cross_marketplace_score"],
            "is_new_arrival": p["is_new_arrival"],
            "action": _recommend_action(p),
        })

    watch_list = []
    for p in rising[:5]:
        watch_list.append({
            "product": p["name"],
            "composite_score": p["composite_score"],
            "reason": "BSR improving — monitor for sustained movement over 3-7 days",
        })

    return {
        "category": features.get("category", ""),
        "marketplace": features.get("marketplace", "amazon"),
        "total_products_analyzed": len(features.get("products", [])),
        "trending_count": len(trending),
        "rising_count": len(rising),
        "top_opportunities": top_opportunities,
        "watch_list": watch_list,
        "recommendation": _overall_recommendation(trending, rising),
    }


def _bsr_velocity_score(product: dict[str, Any]) -> int:
    """Score how fast BSR is improving (0-100)."""
    current = product.get("current_bsr", 0)
    previous = product.get("previous_bsr", 0)
    history = product.get("bsr_history", [])

    if current <= 0:
        return 0

    score = 0.0

    # Absolute rank quality (lower BSR = more sales)
    if current <= 100:
        score += 30
    elif current <= 1000:
        score += 25
    elif current <= 5000:
        score += 18
    elif current <= 20000:
        score += 10
    elif current <= 100000:
        score += 5

    # Rank improvement velocity
    if previous > 0 and current < previous:
        improvement_pct = (previous - current) / previous
        score += min(40, improvement_pct * 100)

    # History trend — consistent improvement across snapshots
    if len(history) >= 3:
        improvements = sum(1 for i in range(1, len(history))
                          if safe_int(history[i]) < safe_int(history[i - 1]) and safe_int(history[i]) > 0)
        consistency = improvements / max(len(history) - 1, 1)
        score += consistency * 30

    return round(min(100, score))


def _rank_improvement(product: dict[str, Any]) -> float:
    """Calculate percentage rank improvement (0.0-1.0)."""
    current = product.get("current_bsr", 0)
    previous = product.get("previous_bsr", 0)
    if previous <= 0 or current <= 0:
        return 0.0
    if current >= previous:
        return 0.0
    return round(min(1.0, (previous - current) / previous), 3)


def _cross_marketplace_score(product: dict[str, Any]) -> int:
    """Score cross-marketplace presence (0-100)."""
    marketplaces = product.get("marketplaces", {})
    if not marketplaces:
        return 0

    active_count = 0
    total_score = 0.0

    for mkt, data in marketplaces.items():
        if not isinstance(data, dict):
            continue
        rank = safe_int(data.get("rank", data.get("bsr", 0)))
        if rank > 0:
            active_count += 1
            weight = MARKETPLACE_WEIGHTS.get(mkt.lower(), 1.0)
            # Better rank = higher contribution
            if rank <= 1000:
                total_score += 30 * weight
            elif rank <= 10000:
                total_score += 20 * weight
            else:
                total_score += 10 * weight

    # Bonus for multi-marketplace presence
    if active_count >= 3:
        total_score *= 1.3
    elif active_count >= 2:
        total_score *= 1.15

    return round(min(100, total_score))


def _newness_score(product: dict[str, Any]) -> int:
    """Bonus for new arrivals climbing BSR fast (0-30)."""
    if not product.get("is_new_arrival", False):
        return 0
    days = max(product.get("first_seen_days_ago", 30), 1)
    current_bsr = product.get("current_bsr", 999999)

    # New product with strong BSR = strong signal
    if days <= 7 and current_bsr <= 5000:
        return 30
    elif days <= 14 and current_bsr <= 10000:
        return 20
    elif days <= 30 and current_bsr <= 50000:
        return 10
    return 5


def _composite_score(velocity: int, improvement: float, cross_mkt: int, newness: int) -> int:
    """Weighted composite score (0-100)."""
    score = (
        velocity * 0.40
        + improvement * 100 * 0.20
        + cross_mkt * 0.25
        + newness * (100 / 30) * 0.15
    )
    return round(min(100, max(0, score)))


def _recommend_action(product: dict[str, Any]) -> str:
    score = product["composite_score"]
    cross = product["cross_marketplace_score"]
    if score >= 80 and cross >= 50:
        return "URGENT: Cross-marketplace bestseller — validate margins and source now"
    if score >= 70:
        return "HIGH PRIORITY: Strong BSR velocity — research suppliers within 48 hours"
    if score >= 60:
        return "ACT SOON: Rising bestseller — verify demand sustainability this week"
    return "MONITOR: Track BSR trajectory for 5-7 days before committing"


def _overall_recommendation(trending: list, rising: list) -> str:
    if len(trending) >= 3:
        return "Multiple bestseller trends detected — prioritize top 2 by cross-marketplace confirmation."
    if len(trending) >= 1:
        return "Trending bestseller found — validate supply chain and margin before entry."
    if len(rising) >= 3:
        return "Several products rising in BSR — monitor daily for breakout movement."
    if len(rising) >= 1:
        return "Early BSR movement detected — add to watchlist, revisit in 3-5 days."
    return "No significant BSR movements at this time — revisit with fresh data."


def _confidence(features: dict[str, Any]) -> float:
    products = features.get("products", [])
    if not products:
        return 0.1
    with_bsr = sum(1 for p in products if p.get("current_bsr", 0) > 0)
    richness = with_bsr / max(len(products), 1)
    with_history = sum(1 for p in products if len(p.get("bsr_history", [])) >= 3)
    depth = with_history / max(len(products), 1)
    return round(min(0.95, 0.15 + richness * 0.40 + depth * 0.30 + min(len(products) / 20, 0.10)), 2)


def _validate_output(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"valid": False, "reason": "Output must be dict"}
    if "top_opportunities" not in data:
        return {"valid": False, "reason": "Missing top_opportunities"}
    return {"valid": True, "reason": "OK"}


def _error_output(reason: str) -> dict[str, Any]:
    return {
        "status": "fail", "data": None,
        "meta": {"engine": "marketplace_trends", "confidence": 0,
                 "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "error": {"reason": reason},
    }
