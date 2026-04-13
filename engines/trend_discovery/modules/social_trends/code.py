"""Social trends analysis — detect trending products from social media virality.

Social platforms are the fastest demand signal:
  - TikTok virality can sell out products in 24 hours
  - Instagram saves = purchase intent signal
  - Pinterest trends are search-driven and most sustainable
  - YouTube long-form reviews drive high-ticket purchases

Input: {products, platforms, timeframe}
Output: {viral_products, platform_breakdown, social_insights}
"""
from __future__ import annotations

import copy
import math
import time
from typing import Any

from utils.helpers import safe_float, safe_int


HASHTAG_SIGNALS = {
    "purchase_intent": [
        "tiktokmademebuyit", "amazonfind", "amazonmusthave", "musthave",
        "wishlist", "addtocart", "shutupandtakemymoney", "worthit",
    ],
    "review": [
        "honestreviews", "productreview", "unboxing", "tryon", "getreadywithme",
    ],
    "trending": [
        "trending", "viral", "viralproduct", "fyp", "foryoupage", "explorepage",
    ],
}

PLATFORM_WEIGHTS = {
    "tiktok": 1.3,
    "instagram": 1.0,
    "pinterest": 0.9,
    "youtube": 1.1,
}


def analyze_social_trends(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Analyze social media trends — engine contract."""
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
            "engine": "social_trends",
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
    if not (data.get("products") or data.get("hashtags") or data.get("category")):
        return {"valid": False, "reason": "Need products, hashtags, or category"}
    return {"valid": True, "reason": "OK"}


def _extract_features(data: dict[str, Any]) -> dict[str, Any]:
    features: dict[str, Any] = {"category": data.get("category", "")}

    products = data.get("products", [])
    if isinstance(products, list):
        features["products"] = []
        for p in products:
            if isinstance(p, dict):
                platforms = p.get("platforms", {})
                features["products"].append({
                    "name": str(p.get("name", p.get("product", ""))),
                    "tiktok": _normalize_platform(platforms.get("tiktok", {}), "tiktok"),
                    "instagram": _normalize_platform(platforms.get("instagram", {}), "instagram"),
                    "pinterest": _normalize_platform(platforms.get("pinterest", {}), "pinterest"),
                    "youtube": _normalize_platform(platforms.get("youtube", {}), "youtube"),
                    "hashtags": p.get("hashtags", []),
                    "creator_tier": str(p.get("creator_tier", "mixed")).lower(),
                    "first_seen_days_ago": safe_int(p.get("first_seen_days_ago", 0)),
                })
            elif isinstance(p, str):
                features["products"].append({
                    "name": p, "tiktok": {}, "instagram": {},
                    "pinterest": {}, "youtube": {}, "hashtags": [],
                    "creator_tier": "unknown", "first_seen_days_ago": 0,
                })

    features["timeframe"] = data.get("timeframe", "7_days")
    return features


def _normalize_platform(raw: dict[str, Any], platform: str) -> dict[str, Any]:
    """Extract platform-specific engagement metrics."""
    if platform == "tiktok":
        return {
            "views": safe_int(raw.get("views", 0)),
            "shares": safe_int(raw.get("shares", 0)),
            "comments": safe_int(raw.get("comments", 0)),
            "videos": safe_int(raw.get("videos", raw.get("video_count", 0))),
            "views_per_hour": safe_float(raw.get("views_per_hour", 0)),
        }
    elif platform == "instagram":
        return {
            "saves": safe_int(raw.get("saves", 0)),
            "shares": safe_int(raw.get("shares", 0)),
            "comments": safe_int(raw.get("comments", 0)),
            "posts": safe_int(raw.get("posts", raw.get("post_count", 0))),
            "reels_views": safe_int(raw.get("reels_views", 0)),
        }
    elif platform == "pinterest":
        return {
            "pins": safe_int(raw.get("pins", 0)),
            "repins": safe_int(raw.get("repins", raw.get("saves", 0))),
            "clicks": safe_int(raw.get("clicks", raw.get("outbound_clicks", 0))),
            "impressions": safe_int(raw.get("impressions", 0)),
        }
    else:  # youtube
        return {
            "views": safe_int(raw.get("views", 0)),
            "likes": safe_int(raw.get("likes", 0)),
            "comments": safe_int(raw.get("comments", 0)),
            "videos": safe_int(raw.get("videos", raw.get("video_count", 0))),
        }


def _analyze(features: dict[str, Any]) -> dict[str, Any]:
    products = features.get("products", [])
    scored = []

    for product in products:
        virality = _virality_score(product)
        platform_spread = _platform_spread(product)
        hashtag_intent = _hashtag_purchase_intent(product.get("hashtags", []))
        engagement_velocity = _engagement_velocity(product)

        scored.append({
            **product,
            "virality_score": virality,
            "platform_spread": platform_spread,
            "hashtag_purchase_intent": hashtag_intent,
            "engagement_velocity": engagement_velocity,
            "composite_score": _composite_score(virality, platform_spread, hashtag_intent, engagement_velocity),
        })

    scored.sort(key=lambda p: p["composite_score"], reverse=True)

    viral = [p for p in scored if p["composite_score"] >= 60]
    emerging = [p for p in scored if 30 <= p["composite_score"] < 60]
    low = [p for p in scored if p["composite_score"] < 30]

    return {"viral": viral, "emerging": emerging, "low_signal": low}


def _generate_insights(analysis: dict[str, Any], features: dict[str, Any]) -> dict[str, Any]:
    viral = analysis["viral"]
    emerging = analysis["emerging"]

    opportunities = []
    for p in viral[:5]:
        platforms_active = [name for name in ["tiktok", "instagram", "pinterest", "youtube"]
                           if _platform_has_activity(p.get(name, {}))]
        opportunities.append({
            "product": p["name"],
            "virality_score": p["virality_score"],
            "composite_score": p["composite_score"],
            "platforms_active": platforms_active,
            "platform_spread": p["platform_spread"],
            "creator_tier": p["creator_tier"],
            "action": _recommend_action(p),
        })

    watch_list = []
    for p in emerging[:5]:
        watch_list.append({
            "product": p["name"],
            "composite_score": p["composite_score"],
            "reason": "Emerging engagement — monitor for 48-72 hours",
        })

    return {
        "category": features.get("category", ""),
        "total_products_analyzed": len(features.get("products", [])),
        "viral_count": len(viral),
        "emerging_count": len(emerging),
        "top_opportunities": opportunities,
        "watch_list": watch_list,
        "recommendation": _overall_recommendation(viral, emerging),
    }


def _virality_score(product: dict[str, Any]) -> int:
    """Score virality across all platforms (0-100)."""
    score = 0.0

    # TikTok contribution (0-35) — fastest virality signal
    tt = product.get("tiktok", {})
    tt_views = tt.get("views", 0)
    if tt_views > 0:
        score += min(25, math.log1p(tt_views) / math.log1p(10_000_000) * 25)
        tt_shares = tt.get("shares", 0)
        if tt_shares > 0:
            share_rate = tt_shares / max(tt_views, 1)
            score += min(10, share_rate * 500)

    # Instagram contribution (0-25)
    ig = product.get("instagram", {})
    ig_saves = ig.get("saves", 0)
    ig_shares = ig.get("shares", 0)
    if ig_saves + ig_shares > 0:
        score += min(15, math.log1p(ig_saves) / math.log1p(100_000) * 15)
        score += min(10, math.log1p(ig_shares) / math.log1p(50_000) * 10)

    # Pinterest contribution (0-20) — intent-driven
    pt = product.get("pinterest", {})
    pt_repins = pt.get("repins", 0)
    pt_clicks = pt.get("clicks", 0)
    if pt_repins + pt_clicks > 0:
        score += min(12, math.log1p(pt_repins) / math.log1p(50_000) * 12)
        score += min(8, math.log1p(pt_clicks) / math.log1p(20_000) * 8)

    # YouTube contribution (0-20) — authority signal
    yt = product.get("youtube", {})
    yt_views = yt.get("views", 0)
    if yt_views > 0:
        score += min(15, math.log1p(yt_views) / math.log1p(5_000_000) * 15)
        yt_likes = yt.get("likes", 0)
        if yt_likes > 0:
            like_rate = yt_likes / max(yt_views, 1)
            score += min(5, like_rate * 100)

    return round(min(100, score))


def _platform_spread(product: dict[str, Any]) -> int:
    """Count how many platforms have meaningful activity (0-4)."""
    count = 0
    if product.get("tiktok", {}).get("views", 0) > 1000:
        count += 1
    if product.get("instagram", {}).get("saves", 0) + product.get("instagram", {}).get("shares", 0) > 100:
        count += 1
    if product.get("pinterest", {}).get("repins", 0) > 50:
        count += 1
    if product.get("youtube", {}).get("views", 0) > 5000:
        count += 1
    return count


def _hashtag_purchase_intent(hashtags: list[str]) -> float:
    """Score purchase intent from hashtags (0.0-1.0)."""
    if not hashtags:
        return 0.0
    normalized = [h.lower().replace("#", "").replace(" ", "") for h in hashtags]
    purchase_matches = sum(1 for h in normalized if h in HASHTAG_SIGNALS["purchase_intent"])
    review_matches = sum(1 for h in normalized if h in HASHTAG_SIGNALS["review"])
    intent = (purchase_matches * 1.0 + review_matches * 0.5) / max(len(normalized), 1)
    return round(min(1.0, intent), 2)


def _engagement_velocity(product: dict[str, Any]) -> float:
    """Measure how fast engagement is growing (views/hour normalized)."""
    tt_vph = product.get("tiktok", {}).get("views_per_hour", 0)
    days = max(product.get("first_seen_days_ago", 1), 1)
    recency_bonus = max(0, 1.0 - (days / 30))  # newer = higher bonus
    velocity = math.log1p(tt_vph) / math.log1p(100_000)
    return round(min(1.0, velocity + recency_bonus * 0.3), 2)


def _composite_score(virality: int, spread: int, hashtag_intent: float, velocity: float) -> int:
    """Weighted composite score (0-100)."""
    score = (
        virality * 0.40
        + (spread / 4 * 100) * 0.25
        + hashtag_intent * 100 * 0.15
        + velocity * 100 * 0.20
    )
    return round(min(100, max(0, score)))


def _platform_has_activity(metrics: dict[str, Any]) -> bool:
    return any(v > 0 for v in metrics.values() if isinstance(v, (int, float)))


def _recommend_action(product: dict[str, Any]) -> str:
    score = product["composite_score"]
    spread = product["platform_spread"]
    if score >= 80 and spread >= 3:
        return "URGENT: Multi-platform viral — source product immediately"
    if score >= 70:
        return "HIGH PRIORITY: Strong virality — begin product research now"
    if score >= 60:
        return "ACT SOON: Growing trend — validate demand within 48 hours"
    return "MONITOR: Track engagement trajectory for 3-5 days"


def _overall_recommendation(viral: list, emerging: list) -> str:
    if len(viral) >= 3:
        return "Multiple viral products detected — prioritize top 2 by platform spread and act fast."
    if len(viral) >= 1:
        return "Viral product detected — validate supply chain feasibility before committing."
    if len(emerging) >= 3:
        return "Several emerging trends — monitor daily, be ready to move in 48-72 hours."
    if len(emerging) >= 1:
        return "Early signals detected — add to watchlist and check back in 24 hours."
    return "No strong social signals at this time — revisit with fresh data."


def _confidence(features: dict[str, Any]) -> float:
    products = features.get("products", [])
    if not products:
        return 0.1
    with_platforms = sum(1 for p in products if _platform_has_activity(p.get("tiktok", {}))
                        or _platform_has_activity(p.get("instagram", {})))
    richness = with_platforms / max(len(products), 1)
    return round(min(0.95, 0.2 + richness * 0.5 + min(len(products) / 20, 0.25)), 2)


def _validate_output(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"valid": False, "reason": "Output must be dict"}
    if "top_opportunities" not in data:
        return {"valid": False, "reason": "Missing top_opportunities"}
    return {"valid": True, "reason": "OK"}


def _error_output(reason: str) -> dict[str, Any]:
    return {
        "status": "fail", "data": None,
        "meta": {"engine": "social_trends", "confidence": 0,
                 "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "error": {"reason": reason},
    }
