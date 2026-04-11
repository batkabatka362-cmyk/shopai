"""Market Research Engine — output formatting.

Formats all module results into a single structured output
following engine contract: {status, data, meta, error}

Computes overall confidence from individual module confidences.
Generates executive summary from all module results.
"""
from __future__ import annotations

import time
from typing import Any


def format_output(
    engine_name: str,
    results: dict[str, Any],
    category: str,
    elapsed: float,
) -> dict[str, Any]:
    """Format engine output following contract."""
    # Compute overall confidence
    confidence = _compute_overall_confidence(results)

    # Generate executive summary
    summary = _generate_summary(results, category)

    # Compute overall verdict
    verdict = _compute_verdict(results)

    return {
        "status": "success",
        "data": {
            "category": category,
            "verdict": verdict,
            "summary": summary,
            "market_size": results.get("market_size", {}),
            "trends": results.get("trends", {}),
            "seasonality": results.get("seasonality", {}),
            "event_calendar": results.get("event_calendar", []),
            "launch_window": results.get("launch_window", {}),
            "gaps": results.get("gaps", {}),
            "saturation": results.get("saturation", {}),
        },
        "meta": {
            "engine": engine_name,
            "confidence": confidence,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(elapsed, 3),
            "modules_run": len([k for k, v in results.items() if v and not (isinstance(v, dict) and v.get("status") == "no_data")]),
        },
        "error": None,
    }


def _compute_overall_confidence(results: dict[str, Any]) -> float:
    """Average confidence across modules that reported it."""
    confidences = []

    # Market size — always has data (uses benchmarks)
    if results.get("market_size"):
        confidences.append(0.7)

    # Trends
    trends = results.get("trends", {})
    if isinstance(trends, dict) and trends.get("confidence"):
        conf_map = {"high": 0.9, "medium": 0.6, "low": 0.3, "none": 0.1}
        confidences.append(conf_map.get(trends["confidence"], 0.5))

    # Seasonality — always has data (uses benchmarks)
    if results.get("seasonality") and results["seasonality"].get("classification"):
        confidences.append(0.75)

    # Gap finder
    gaps = results.get("gaps", {})
    if isinstance(gaps, dict) and gaps.get("meta", {}).get("confidence"):
        confidences.append(gaps["meta"]["confidence"])

    # Saturation
    saturation = results.get("saturation", {})
    if isinstance(saturation, dict) and saturation.get("meta", {}).get("confidence"):
        confidences.append(saturation["meta"]["confidence"])

    if not confidences:
        return 0.0

    return round(sum(confidences) / len(confidences), 2)


def _generate_summary(results: dict[str, Any], category: str) -> str:
    """One-paragraph executive summary of all research."""
    parts = [f"Market Research Report: {category}"]

    # Market size
    ms = results.get("market_size", {})
    som = ms.get("som", {})
    if som:
        monthly = som.get("monthly_som_usd", {}).get("typical", 0)
        if monthly:
            parts.append(f"Addressable opportunity: ~${monthly:,}/month.")

    # Trends
    trends = results.get("trends", {})
    if isinstance(trends, dict) and trends.get("trend_level"):
        parts.append(f"Market trend: {trends['trend_level']} (score {trends.get('trend_score', 0)}).")

    # Seasonality
    season = results.get("seasonality", {})
    if isinstance(season, dict) and season.get("classification"):
        parts.append(f"Seasonality: {season['classification']}. Best month: {season.get('best_month', '?')}.")

    # Gaps
    gaps = results.get("gaps", {})
    if isinstance(gaps, dict) and gaps.get("data"):
        gap_count = gaps["data"].get("total_gaps_found", 0)
        high = len(gaps["data"].get("high_opportunity", []))
        if gap_count:
            parts.append(f"Gaps found: {gap_count} ({high} high-opportunity).")

    # Saturation
    sat = results.get("saturation", {})
    if isinstance(sat, dict) and sat.get("data"):
        level = sat["data"].get("level", "?")
        can_enter = sat["data"].get("can_enter", True)
        parts.append(f"Saturation: {level}. Entry {'recommended' if can_enter else 'NOT recommended'}.")

    return " ".join(parts)


def _compute_verdict(results: dict[str, Any]) -> dict[str, Any]:
    """Overall market entry verdict from all modules."""
    score = 50  # Start neutral

    # Market size impact
    ms = results.get("market_size", {})
    som = ms.get("som", {})
    if som:
        monthly = som.get("monthly_som_usd", {}).get("typical", 0)
        if monthly > 20000:
            score += 15
        elif monthly > 5000:
            score += 8
        elif monthly > 0:
            score -= 5

    # Trend impact
    trends = results.get("trends", {})
    if isinstance(trends, dict):
        trend_score = trends.get("trend_score", 0)
        if trend_score > 50:
            score += 15
        elif trend_score > 20:
            score += 8
        elif trend_score < -10:
            score -= 15

    # Saturation impact
    sat = results.get("saturation", {})
    if isinstance(sat, dict) and sat.get("data"):
        sat_index = sat["data"].get("saturation_index", 50)
        if sat_index > 70:
            score -= 20
        elif sat_index > 50:
            score -= 10
        elif sat_index < 30:
            score += 10

    # Gap impact
    gaps = results.get("gaps", {})
    if isinstance(gaps, dict) and gaps.get("data"):
        high_gaps = len(gaps["data"].get("high_opportunity", []))
        score += min(15, high_gaps * 5)

    score = max(0, min(100, score))

    if score >= 70:
        verdict = "strong_enter"
        recommendation = "Market research supports entry — proceed with product selection"
    elif score >= 50:
        verdict = "enter_with_caution"
        recommendation = "Opportunity exists but requires focused strategy"
    elif score >= 30:
        verdict = "weak_opportunity"
        recommendation = "Marginal opportunity — consider alternatives"
    else:
        verdict = "avoid"
        recommendation = "Market research does not support entry"

    return {
        "verdict": verdict,
        "score": score,
        "recommendation": recommendation,
    }
