"""Conversion optimization logic — find and fix funnel bottlenecks.

Provides:
  - optimize_funnel: identify the biggest drop-off in the funnel
  - estimate_conversion_improvement: model "what if we improve X?"
  - benchmark_conversion: compare our rate against category averages
"""
from __future__ import annotations

from typing import Any

from .data import CATEGORY_CONVERSION_RATES, FUNNEL_STAGE_BENCHMARKS


# Improvement potential per stage (how much can realistically improve)
STAGE_IMPROVEMENT_CEILING = {
    "impression_to_click": {"easy": 0.10, "medium": 0.25, "hard": 0.50},
    "click_to_visit": {"easy": 0.05, "medium": 0.10, "hard": 0.20},
    "visit_to_cart": {"easy": 0.15, "medium": 0.30, "hard": 0.50},
    "cart_to_checkout": {"easy": 0.10, "medium": 0.25, "hard": 0.40},
    "checkout_to_purchase": {"easy": 0.05, "medium": 0.15, "hard": 0.25},
}


def optimize_funnel(funnel_data: dict[str, Any]) -> dict[str, Any]:
    """Find the biggest drop-off in the conversion funnel.

    Args:
        funnel_data: Funnel stage rates from estimate_conversion output.
            Keys: impression_to_click, click_to_visit, visit_to_cart,
                  cart_to_checkout, checkout_to_purchase (as percentages).

    Returns:
        Bottleneck analysis with priority-ranked improvement opportunities.
    """
    stage_names = [
        "impression_to_click", "click_to_visit", "visit_to_cart",
        "cart_to_checkout", "checkout_to_purchase",
    ]

    gaps = []
    for name in stage_names:
        actual = funnel_data.get(name, 0) / 100.0  # Convert from pct
        benchmark = FUNNEL_STAGE_BENCHMARKS.get(name, 0.5)
        gap = benchmark - actual
        gap_pct = (gap / benchmark * 100) if benchmark > 0 else 0

        gaps.append({
            "stage": name,
            "actual_rate": round(actual * 100, 1),
            "benchmark_rate": round(benchmark * 100, 1),
            "gap_pct": round(gap_pct, 1),
            "improvement_potential": _stage_recommendation(name, actual, benchmark),
        })

    # Sort by gap size — biggest gap = biggest opportunity
    gaps.sort(key=lambda g: g["gap_pct"], reverse=True)

    biggest = gaps[0] if gaps else None
    return {
        "bottleneck": biggest["stage"] if biggest else None,
        "bottleneck_gap": biggest["gap_pct"] if biggest else 0,
        "priority_order": gaps,
        "summary": _funnel_summary(gaps),
    }


def estimate_conversion_improvement(changes: dict[str, Any]) -> dict[str, Any]:
    """Model the impact of improving specific funnel stages.

    Args:
        changes: {
            "current_conversion_rate": float,  # Current overall rate (pct)
            "daily_visitors": int,
            "price": float,
            "improvements": [
                {"stage": str, "improvement_pct": float},  # e.g. 10 = 10% better
            ]
        }

    Returns:
        Projected new conversion rate and revenue impact.
    """
    current_rate = changes.get("current_conversion_rate", 2.0) / 100.0
    daily_visitors = changes.get("daily_visitors", 100)
    price = changes.get("price", 30.0)
    improvements = changes.get("improvements", [])

    # Each stage improvement compounds multiplicatively
    combined_multiplier = 1.0
    applied = []

    for imp in improvements:
        stage = imp.get("stage", "")
        imp_pct = imp.get("improvement_pct", 0) / 100.0
        ceiling = STAGE_IMPROVEMENT_CEILING.get(stage, {}).get("hard", 0.5)

        # Cap improvement at realistic ceiling
        capped = min(imp_pct, ceiling)
        combined_multiplier *= (1.0 + capped)
        applied.append({
            "stage": stage,
            "requested_improvement": round(imp_pct * 100, 1),
            "capped_improvement": round(capped * 100, 1),
            "ceiling": round(ceiling * 100, 1),
        })

    new_rate = min(0.25, current_rate * combined_multiplier)
    current_purchases = daily_visitors * current_rate
    new_purchases = daily_visitors * new_rate

    return {
        "current_conversion_rate": round(current_rate * 100, 2),
        "new_conversion_rate": round(new_rate * 100, 2),
        "improvement_factor": round(combined_multiplier, 3),
        "current_daily_purchases": round(current_purchases, 1),
        "new_daily_purchases": round(new_purchases, 1),
        "additional_monthly_revenue": round((new_purchases - current_purchases) * 30 * price, 2),
        "improvements_applied": applied,
    }


def benchmark_conversion(
    our_rate: float, category: str
) -> dict[str, Any]:
    """Compare our conversion rate against category averages.

    Args:
        our_rate: Our conversion rate as percentage (e.g. 2.5 = 2.5%).
        category: Product category for benchmark lookup.

    Returns:
        Comparison with verdict and percentile estimate.
    """
    cat = category.lower().replace(" ", "_").replace("-", "_")
    benchmark = CATEGORY_CONVERSION_RATES.get(cat, 0.025) * 100  # Convert to pct

    ratio = our_rate / benchmark if benchmark > 0 else 1.0

    if ratio >= 1.5:
        verdict = "excellent"
        percentile = 90
        comment = "Significantly above category average — strong execution"
    elif ratio >= 1.1:
        verdict = "above_average"
        percentile = 70
        comment = "Above category average — good performance"
    elif ratio >= 0.9:
        verdict = "average"
        percentile = 50
        comment = "In line with category average — room to optimize"
    elif ratio >= 0.6:
        verdict = "below_average"
        percentile = 25
        comment = "Below category average — significant optimization needed"
    else:
        verdict = "poor"
        percentile = 10
        comment = "Well below average — fundamental issues likely (trust, UX, targeting)"

    return {
        "our_rate": our_rate,
        "category_benchmark": round(benchmark, 2),
        "ratio_to_benchmark": round(ratio, 2),
        "verdict": verdict,
        "estimated_percentile": percentile,
        "comment": comment,
    }


def _stage_recommendation(stage: str, actual: float, benchmark: float) -> str:
    """Generate a recommendation for a funnel stage."""
    if actual >= benchmark:
        return "At or above benchmark — maintain current approach"
    gap = benchmark - actual
    if gap > 0.15:
        return "Major gap — prioritize immediate improvement"
    if gap > 0.05:
        return "Moderate gap — optimize with A/B testing"
    return "Small gap — fine-tune incrementally"


def _funnel_summary(gaps: list[dict[str, Any]]) -> str:
    """Generate human-readable funnel summary."""
    if not gaps:
        return "No funnel data available"
    worst = gaps[0]
    if worst["gap_pct"] <= 0:
        return "All funnel stages at or above benchmark — focus on traffic volume"
    return (
        f"Biggest opportunity: {worst['stage'].replace('_', ' ')} "
        f"({worst['gap_pct']}% below benchmark). "
        f"Fix this first for maximum impact."
    )
