"""Product Research Engine — finds winning products for dropshipping.

Analyzes market trends, competitor data, and product metrics to identify
high-potential products worth selling.

Input: {products, market_data, competitors, niche, criteria}
Output: {status, data: {winners, opportunities, trends, scores}, meta, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.finance import margin as _margin

ENGINE_NAME = "product_research"


class ProductResearchEngine:
    """Wrapper class for registry compatibility."""
    ENGINE_NAME = ENGINE_NAME
    engine_name = ENGINE_NAME

    def run(self, input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        return run(input_data)


def _fail(msg: str, start: float) -> dict[str, Any]:
    return {
        "status": "error",
        "data": {},
        "meta": {"engine": ENGINE_NAME, "timestamp": time.time(),
                 "elapsed_seconds": round(time.monotonic() - start, 3)},
        "error": msg,
    }


def run(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    start = time.monotonic()
    data = copy.deepcopy(input_data or {})

    # Propagate upstream failures instead of silently returning success
    if data.get("status") == "fail":
        return _fail(data.get("error") or "Upstream failure", start)

    products = data.get("products", [])
    niche = data.get("niche", "")
    criteria = data.get("criteria", {})

    # Stage 1: Score products for winning potential
    scored_products = _score_products(products, criteria)

    # Stage 2: Identify market opportunities
    opportunities = _find_opportunities(products, data.get("market_data", {}))

    # Stage 3: Trend analysis
    trends = _analyze_trends(data.get("trends", []), niche)

    # Stage 4: AI reasoning (if available)
    ai_analysis = _ai_evaluate(scored_products[:10], niche)

    # Stage 5: Final ranking
    winners = _rank_winners(scored_products, ai_analysis)

    # Phase 7: optional winner-tag apply. Opt-in via
    # data.apply_winner_tags=True. See winner_applier for
    # filter logic (verdict in {strong_buy, buy}). Empty
    # list when not opted in OR when no winners matched.
    tagged_winners: list[dict[str, Any]] = []
    if bool(data.get("apply_winner_tags")):
        try:
            from .winner_applier import apply_winner_tags
            tagged_winners = apply_winner_tags(
                winners[:20], products,
            )
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).debug(
                "product_research: apply loop raised: %s", exc,
            )

    elapsed = round(time.monotonic() - start, 3)
    return {
        "status": "success",
        "data": {
            "winners": winners[:20],
            "opportunities": opportunities,
            "trends": trends,
            "total_evaluated": len(products),
            "winning_count": len([w for w in winners if w.get("verdict") in ("strong_buy", "buy")]),
            "ai_enhanced": ai_analysis.get("source") != "heuristic" if ai_analysis else False,
            "tagged_winners": tagged_winners,
        },
        "meta": {"engine": ENGINE_NAME, "timestamp": time.time(), "elapsed_seconds": elapsed},
        "error": None,
    }


def _score_products(products: list[dict], criteria: dict) -> list[dict[str, Any]]:
    """Score each product on winning potential."""
    min_margin = criteria.get("min_margin", 0.3)
    min_price = criteria.get("min_price", 15)
    max_price = criteria.get("max_price", 100)

    scored = []
    for p in products:
        score = 0
        factors = {}

        price = float(p.get("price", 0) or 0)
        cost = float(p.get("cost", 0) or 0)
        name = p.get("name", p.get("title", "Unknown"))

        # Price range check
        if min_price <= price <= max_price:
            factors["price_range"] = {"score": 10, "detail": f"${price} in sweet spot"}
            score += 10
        elif price < min_price:
            factors["price_range"] = {"score": 0, "detail": f"${price} too low"}
        else:
            factors["price_range"] = {"score": 5, "detail": f"${price} above ideal range"}
            score += 5

        # Margin analysis
        margin = _margin(price, cost, default=-1.0)
        if margin >= 0:
            if margin >= 0.6:
                factors["margin"] = {"score": 25, "detail": f"{margin:.0%} excellent margin"}
                score += 25
            elif margin >= min_margin:
                factors["margin"] = {"score": 15, "detail": f"{margin:.0%} good margin"}
                score += 15
            else:
                factors["margin"] = {"score": 0, "detail": f"{margin:.0%} below {min_margin:.0%} target"}

        # Demand signals
        search_volume = int(p.get("search_volume", 0) or 0)
        if search_volume > 10000:
            factors["demand"] = {"score": 20, "detail": f"{search_volume:,} monthly searches"}
            score += 20
        elif search_volume > 5000:
            factors["demand"] = {"score": 12, "detail": f"{search_volume:,} monthly searches"}
            score += 12
        elif search_volume > 1000:
            factors["demand"] = {"score": 5, "detail": f"{search_volume:,} monthly searches"}
            score += 5

        # Competition
        competition = float(p.get("competition", 5) or 5)
        if competition < 3:
            factors["competition"] = {"score": 20, "detail": f"Low ({competition}/10)"}
            score += 20
        elif competition < 5:
            factors["competition"] = {"score": 12, "detail": f"Moderate ({competition}/10)"}
            score += 12
        elif competition < 7:
            factors["competition"] = {"score": 5, "detail": f"High ({competition}/10)"}
            score += 5

        # Social proof
        rating = float(p.get("rating", 0) or 0)
        reviews = int(p.get("reviews", 0) or 0)
        if rating >= 4.5 and reviews > 100:
            factors["social_proof"] = {"score": 15, "detail": f"{rating}★ ({reviews} reviews)"}
            score += 15
        elif rating >= 4.0 and reviews > 50:
            factors["social_proof"] = {"score": 8, "detail": f"{rating}★ ({reviews} reviews)"}
            score += 8

        # Weight / shipping
        weight = float(p.get("weight", 0) or 0)
        if 0 < weight < 0.5:
            factors["shipping"] = {"score": 10, "detail": f"{weight}kg light, cheap to ship"}
            score += 10
        elif weight < 2:
            factors["shipping"] = {"score": 5, "detail": f"{weight}kg moderate"}
            score += 5

        # Verdict
        if score >= 70:
            verdict = "strong_buy"
        elif score >= 50:
            verdict = "buy"
        elif score >= 30:
            verdict = "consider"
        else:
            verdict = "skip"

        scored.append({
            "product": name,
            "id": p.get("id", ""),
            "score": score,
            "verdict": verdict,
            "price": price,
            "cost": cost,
            "margin": _margin(price, cost, precision=3),
            "factors": factors,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def _find_opportunities(products: list[dict], market_data: dict) -> list[dict[str, Any]]:
    """Identify market gaps and opportunities."""
    opportunities = []

    # Find categories with few products
    categories: dict[str, int] = {}
    for p in products:
        cat = p.get("category", p.get("product_type", "other"))
        categories[cat] = categories.get(cat, 0) + 1

    # High-margin low-competition products
    high_margin = [p for p in products
                   if float(p.get("price", 0) or 0) > 0
                   and float(p.get("cost", 0) or 0) > 0
                   and (float(p.get("price", 0)) - float(p.get("cost", 0))) / float(p.get("price", 0)) > 0.5
                   and float(p.get("competition", 10) or 10) < 5]

    if high_margin:
        opportunities.append({
            "type": "high_margin_low_competition",
            "count": len(high_margin),
            "detail": f"{len(high_margin)} products with >50% margin and low competition",
            "products": [p.get("name", p.get("title", "")) for p in high_margin[:5]],
        })

    # Trending categories from market data
    trending = market_data.get("trending_categories", [])
    for trend in trending[:3]:
        opportunities.append({
            "type": "trending_category",
            "category": trend.get("name", ""),
            "growth": trend.get("growth", ""),
            "detail": f"Category growing: {trend.get('name', '')}",
        })

    return opportunities


def _analyze_trends(trends: list[dict], niche: str) -> list[dict[str, Any]]:
    """Analyze market trends."""
    if not trends:
        return [
            {"type": "general", "trend": "Growing demand for unique/personalized products", "confidence": 0.6},
            {"type": "general", "trend": "Social media driving impulse purchases", "confidence": 0.7},
            {"type": "general", "trend": "Sustainability becoming a purchase factor", "confidence": 0.5},
        ]
    return trends[:10]


def _ai_evaluate(top_products: list[dict], niche: str) -> dict[str, Any]:
    """Use AI reasoning if available."""
    try:
        from core.ai.reasoning import ai_reason
        return ai_reason(
            "product_evaluation",
            products=top_products,
            niche=niche,
            task_detail="Evaluate these products for dropshipping potential. Consider margin, demand, competition, and trend alignment.",
        )
    except Exception:
        return {"source": "heuristic", "analysis": "AI evaluation not available"}


def _rank_winners(scored: list[dict], ai_analysis: dict) -> list[dict[str, Any]]:
    """Final ranking combining scores with AI analysis."""
    # Merge AI recommendations if available
    ai_recs = ai_analysis.get("recommendations", [])
    ai_boost = {}
    for rec in ai_recs:
        product = rec.get("product", "")
        if product:
            ai_boost[product] = rec.get("confidence", 0) * 10

    for item in scored:
        boost = ai_boost.get(item["product"], 0)
        if boost:
            item["score"] += int(boost)
            item["ai_boosted"] = True

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored
