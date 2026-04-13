"""Search volume analysis — estimate product demand from keyword search data.

Main entry point: analyze_search_volume(input_payload)
Engine contract: returns {status, data, meta, error}
"""
from __future__ import annotations

import statistics
import time
from typing import Any

from .data import SEARCH_VOLUME_BENCHMARKS, classify_intent, get_seasonal_multiplier
from .logic import estimate_demand_from_search, rank_keywords_by_demand
from .rules import evaluate_rules


def analyze_search_volume(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Analyze keyword search volume to estimate product demand."""
    start_time = time.time()
    try:
        keywords_raw = input_payload.get("keywords", [])
        category = input_payload.get("category", "general")
        aov = input_payload.get("avg_order_value", 50.0)
        month = input_payload.get("month")
        monthly_volumes = input_payload.get("monthly_volumes")

        if not keywords_raw:
            return _error_response("No keywords provided in input_payload", start_time)

        keywords = _enrich_keywords(keywords_raw)
        aggregate_volume = sum(kw.get("volume", 0) for kw in keywords)
        volume_tier = _classify_volume_tier(aggregate_volume)
        stability = _compute_stability(monthly_volumes)
        ranked = rank_keywords_by_demand(keywords, category=category, avg_order_value=aov)
        funnel = _aggregate_funnel(keywords, category, month, aov)
        seasonal_factor = get_seasonal_multiplier(month) if month else 1.0

        # Rules validation
        rules_result = evaluate_rules({
            "aggregate_volume": aggregate_volume,
            "keywords": keywords,
            "volume_cv": stability.get("coefficient_of_variation", 0),
            "consecutive_decline_months": stability.get("consecutive_decline_months", 0),
            "seasonal_adjusted": month is not None,
            "estimated_conversion": funnel.get("effective_conversion_rate", 0.02) / 100,
        })

        data = {
            "aggregate_volume": aggregate_volume,
            "volume_tier": volume_tier,
            "seasonal_factor": seasonal_factor,
            "seasonal_adjusted_volume": round(aggregate_volume * seasonal_factor),
            "volume_stability": stability,
            "funnel_summary": funnel,
            "ranked_keywords": ranked,
            "top_keywords": ranked[:5],
            "rules_evaluation": rules_result,
            "demand_summary": {
                "estimated_monthly_purchases": funnel.get("total_purchases", 0),
                "estimated_monthly_revenue": funnel.get("total_revenue", 0),
                "volume_classification": volume_tier["label"],
                "viable": rules_result["passed"],
            },
        }

        return {
            "status": "success",
            "data": data,
            "meta": {
                "module": "search_volume",
                "keywords_analyzed": len(keywords),
                "category": category,
                "elapsed_seconds": round(time.time() - start_time, 4),
            },
            "error": None,
        }
    except Exception as exc:
        return _error_response(str(exc), start_time)


def _enrich_keywords(keywords_raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add intent classification to keywords that lack it."""
    result = []
    for kw in keywords_raw:
        entry = dict(kw)
        if not entry.get("intent"):
            entry["intent"] = classify_intent(entry.get("keyword", ""))
        result.append(entry)
    return result


def _classify_volume_tier(volume: int) -> dict[str, Any]:
    """Classify aggregate search volume into a demand tier."""
    for tier in ("high", "medium", "low", "insufficient"):
        if volume >= SEARCH_VOLUME_BENCHMARKS[tier]["min"]:
            info = SEARCH_VOLUME_BENCHMARKS[tier]
            return {"tier": tier, "label": info["label"], "competition": info["competition"]}
    return {"tier": "insufficient", "label": "Too low", "competition": "none"}


def _compute_stability(monthly_volumes: list[int] | None) -> dict[str, Any]:
    """Compute search volume stability from monthly history."""
    if not monthly_volumes or len(monthly_volumes) < 2:
        return {"has_history": False, "coefficient_of_variation": 0.0, "consecutive_decline_months": 0}

    mean_vol = statistics.mean(monthly_volumes)
    stdev_vol = statistics.stdev(monthly_volumes)
    cv = stdev_vol / max(mean_vol, 1)

    # Count consecutive declining months from most recent
    decline_count = 0
    for i in range(len(monthly_volumes) - 1, 0, -1):
        if monthly_volumes[i] < monthly_volumes[i - 1]:
            decline_count += 1
        else:
            break

    return {"has_history": True, "months_of_data": len(monthly_volumes),
            "mean_volume": round(mean_vol), "stdev_volume": round(stdev_vol),
            "coefficient_of_variation": round(cv, 3),
            "consecutive_decline_months": decline_count,
            "trend": "declining" if decline_count >= 3 else "stable_or_growing"}


def _aggregate_funnel(
    keywords: list[dict[str, Any]], category: str, month: int | None, aov: float,
) -> dict[str, Any]:
    """Aggregate funnel estimates across all keywords."""
    totals = {"searches": 0, "clicks": 0, "visits": 0, "carts": 0, "purchases": 0}
    total_revenue = 0.0

    for kw in keywords:
        demand = estimate_demand_from_search(
            volume=kw.get("volume", 0), category=category,
            intent=kw.get("intent", "commercial"), month=month, avg_order_value=aov,
        )
        for key in totals:
            totals[key] += demand.get("funnel", {}).get(key, 0)
        total_revenue += demand.get("estimated_monthly_revenue", 0)

    eff_rate = (totals["purchases"] / max(totals["searches"], 1)) * 100
    return {**{f"total_{k}": v for k, v in totals.items()},
            "total_revenue": round(total_revenue, 2),
            "effective_conversion_rate": round(eff_rate, 4)}


def _error_response(message: str, start_time: float) -> dict[str, Any]:
    """Build a standard error response."""
    return {
        "status": "error", "data": None,
        "meta": {"module": "search_volume", "elapsed_seconds": round(time.time() - start_time, 4)},
        "error": message,
    }
