"""Search trends analysis — detect rising demand from search behavior.

Search volume is the strongest demand signal:
  - Rising search = rising demand (people WANT something)
  - Search intent types: informational, commercial, transactional
  - Long-tail keywords reveal specific needs
  - Keyword clusters reveal category trends

Input: {keywords, category, timeframe}
Output: {trending_keywords, rising_categories, search_insights}
"""
from __future__ import annotations

import copy
import math
import time
from typing import Any

from utils.helpers import safe_float, safe_int


# Search intent classification keywords
INTENT_SIGNALS = {
    "transactional": ["buy", "order", "purchase", "shop", "deal", "discount", "coupon", "price", "cheap", "best", "top", "review"],
    "commercial": ["vs", "compare", "alternative", "which", "recommend", "worth"],
    "informational": ["how to", "what is", "guide", "tutorial", "diy", "tips"],
}

# Known high-growth keyword patterns (2024-2026)
HIGH_GROWTH_PATTERNS = {
    "sustainable": {"growth_range": (30, 80), "categories": ["fashion", "home", "beauty", "food"]},
    "organic": {"growth_range": (20, 50), "categories": ["food", "beauty", "baby", "pet"]},
    "personalized": {"growth_range": (40, 100), "categories": ["jewelry", "gifts", "clothing"]},
    "smart": {"growth_range": (25, 60), "categories": ["home", "electronics", "fitness"]},
    "minimalist": {"growth_range": (30, 70), "categories": ["jewelry", "home", "fashion"]},
    "portable": {"growth_range": (20, 45), "categories": ["electronics", "fitness", "office"]},
    "vegan": {"growth_range": (35, 75), "categories": ["food", "beauty", "fashion"]},
    "ergonomic": {"growth_range": (25, 55), "categories": ["office", "furniture", "tools"]},
}


def analyze_search_trends(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Analyze search trends — engine contract."""
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
            "engine": "search_trends",
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
    if not (data.get("keywords") or data.get("category")):
        return {"valid": False, "reason": "Need keywords or category"}
    return {"valid": True, "reason": "OK"}


def _extract_features(data: dict[str, Any]) -> dict[str, Any]:
    features: dict[str, Any] = {"category": data.get("category", "")}

    keywords = data.get("keywords", [])
    if isinstance(keywords, list):
        features["keywords"] = []
        for kw in keywords:
            if isinstance(kw, dict):
                features["keywords"].append({
                    "keyword": str(kw.get("keyword", kw.get("term", ""))),
                    "volume": safe_int(kw.get("volume", kw.get("search_volume", 0))),
                    "growth_pct": safe_float(kw.get("growth_pct", kw.get("growth", 0))),
                    "cpc": safe_float(kw.get("cpc", 0)),
                    "competition": str(kw.get("competition", "medium")).lower(),
                })
            elif isinstance(kw, str):
                features["keywords"].append({"keyword": kw, "volume": 0, "growth_pct": 0, "cpc": 0, "competition": "unknown"})

    features["timeframe"] = data.get("timeframe", "12_months")
    return features


def _analyze(features: dict[str, Any]) -> dict[str, Any]:
    keywords = features.get("keywords", [])
    category = features.get("category", "")

    trending = []
    declining = []
    stable = []

    for kw in keywords:
        growth = kw["growth_pct"]
        scored = {
            **kw,
            "trend_score": _keyword_trend_score(kw),
            "intent": _classify_intent(kw["keyword"]),
            "opportunity_score": _keyword_opportunity(kw),
        }

        if growth > 20:
            trending.append(scored)
        elif growth < -10:
            declining.append(scored)
        else:
            stable.append(scored)

    trending.sort(key=lambda k: k["trend_score"], reverse=True)
    declining.sort(key=lambda k: k["growth_pct"])

    # Category pattern matching
    category_patterns = _match_category_patterns(category)

    return {
        "trending": trending,
        "declining": declining,
        "stable": stable,
        "category_patterns": category_patterns,
    }


def _generate_insights(analysis: dict[str, Any], features: dict[str, Any]) -> dict[str, Any]:
    trending = analysis["trending"]
    declining = analysis["declining"]
    category = features.get("category", "")

    # Top opportunities
    opportunities = []
    for kw in trending[:5]:
        opportunities.append({
            "keyword": kw["keyword"],
            "trend_score": kw["trend_score"],
            "opportunity_score": kw["opportunity_score"],
            "volume": kw["volume"],
            "growth": f"+{kw['growth_pct']:.0f}%",
            "intent": kw["intent"],
            "action": _recommend_action(kw),
        })

    # Warnings (declining keywords)
    warnings = []
    for kw in declining[:3]:
        warnings.append({
            "keyword": kw["keyword"],
            "decline": f"{kw['growth_pct']:.0f}%",
            "action": "Reduce investment in this keyword",
        })

    return {
        "category": category,
        "total_keywords_analyzed": len(features.get("keywords", [])),
        "trending_count": len(trending),
        "declining_count": len(declining),
        "top_opportunities": opportunities,
        "warnings": warnings,
        "category_patterns": analysis["category_patterns"],
        "recommendation": _overall_recommendation(trending, declining),
    }


def _keyword_trend_score(kw: dict[str, Any]) -> int:
    """Score keyword trendiness (0-100)."""
    score = 0
    growth = kw["growth_pct"]
    volume = kw["volume"]

    # Growth component (0-50)
    if growth > 0:
        score += min(50, math.log1p(growth) / math.log1p(200) * 50)

    # Volume component (0-30) — high volume + growth = strong signal
    if volume > 0:
        score += min(30, math.log1p(volume) / math.log1p(50000) * 30)

    # Low competition bonus (0-20)
    comp = kw.get("competition", "medium")
    if comp == "low":
        score += 20
    elif comp == "medium":
        score += 10

    return round(min(100, score))


def _keyword_opportunity(kw: dict[str, Any]) -> int:
    """Opportunity = trend_score weighted by commercial intent and CPC."""
    base = _keyword_trend_score(kw)
    intent = _classify_intent(kw["keyword"])

    # Commercial/transactional intent = higher opportunity
    if intent == "transactional":
        base = min(100, int(base * 1.3))
    elif intent == "commercial":
        base = min(100, int(base * 1.15))

    # CPC signals advertiser confidence
    cpc = kw.get("cpc", 0)
    if 0.5 < cpc < 3.0:
        base = min(100, base + 5)  # Sweet spot — advertisers spending but not crazy

    return base


def _classify_intent(keyword: str) -> str:
    kw_lower = keyword.lower()
    for intent, signals in INTENT_SIGNALS.items():
        if any(s in kw_lower for s in signals):
            return intent
    return "informational"


def _match_category_patterns(category: str) -> list[dict[str, Any]]:
    """Match category against known high-growth patterns."""
    cat_lower = category.lower()
    matches = []
    for pattern, info in HIGH_GROWTH_PATTERNS.items():
        if any(cat in cat_lower for cat in info["categories"]):
            matches.append({
                "pattern": pattern,
                "expected_growth": f"{info['growth_range'][0]}-{info['growth_range'][1]}%",
                "relevant_categories": info["categories"],
            })
    return matches


def _recommend_action(kw: dict[str, Any]) -> str:
    score = kw["opportunity_score"]
    if score >= 70:
        return "HIGH PRIORITY: Create product targeting this keyword immediately"
    if score >= 50:
        return "MEDIUM: Research product options for this keyword"
    return "MONITOR: Track this keyword for 30 days before acting"


def _overall_recommendation(trending: list, declining: list) -> str:
    if len(trending) > 5:
        return "Strong trending signals — multiple opportunities available. Focus on top 3."
    if len(trending) > 2:
        return "Moderate trending signals — 2-3 actionable opportunities."
    if len(trending) > 0:
        return "Few trending signals — investigate further before committing."
    if len(declining) > len(trending):
        return "More declining than rising keywords — category may be past peak."
    return "Insufficient data for strong recommendation."


def _confidence(features: dict[str, Any]) -> float:
    kw_count = len(features.get("keywords", []))
    with_volume = sum(1 for k in features.get("keywords", []) if k.get("volume", 0) > 0)
    if kw_count == 0:
        return 0.1
    data_richness = with_volume / kw_count
    return round(min(0.95, 0.3 + data_richness * 0.5 + min(kw_count / 20, 0.15)), 2)


def _validate_output(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"valid": False, "reason": "Output must be dict"}
    if "top_opportunities" not in data:
        return {"valid": False, "reason": "Missing top_opportunities"}
    return {"valid": True, "reason": "OK"}


def _error_output(reason: str) -> dict[str, Any]:
    return {"status": "fail", "data": None, "meta": {"engine": "search_trends", "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": {"reason": reason}}
