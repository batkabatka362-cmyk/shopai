"""Decision functions for score aggregation.

Provides weight customization by business goal, score conflict detection
between engines, and the core weighted-score computation.
"""

from __future__ import annotations

from typing import Any

from .data import (
    DEFAULT_WEIGHTS,
    GOAL_WEIGHT_PROFILES,
    CONFLICT_THRESHOLDS,
)


def customize_weights(goal: str) -> dict[str, float]:
    """Return engine weights customized for a business goal.

    Args:
        goal: one of "profit", "growth", "balanced", "conservative",
              "trend_focused". Falls back to balanced if unknown.

    Returns:
        Dict mapping engine name to weight (summing to 1.0).
    """
    profile = GOAL_WEIGHT_PROFILES.get(goal)
    if profile is None:
        profile = GOAL_WEIGHT_PROFILES["balanced"]

    # Verify weights sum to 1.0 (fix rounding drift)
    total = sum(profile.values())
    if abs(total - 1.0) > 0.01:
        return {k: round(v / total, 4) for k, v in profile.items()}
    return dict(profile)


def detect_score_conflicts(
    normalized_scores: dict[str, float | None],
) -> list[dict[str, Any]]:
    """Detect conflicting signals between engine scores.

    Flags situations where two engines give contradictory assessments,
    such as high profitability paired with high risk or strong demand
    paired with saturated competition.

    Args:
        normalized_scores: dict of engine_name -> 0-100 normalized score.

    Returns:
        List of conflict dicts with engine pair, severity, and explanation.
    """
    conflicts: list[dict[str, Any]] = []

    scores = {k: v for k, v in normalized_scores.items() if v is not None}

    # --- High profitability + high risk ---
    if "profitability" in scores and "risk" in scores:
        profit = scores["profitability"]
        risk = scores["risk"]
        threshold = CONFLICT_THRESHOLDS["high_profit_high_risk"]
        if profit >= threshold["profit_min"] and risk >= threshold["risk_min"]:
            conflicts.append({
                "type": "high_profit_high_risk",
                "engines": ["profitability", "risk"],
                "scores": {"profitability": profit, "risk": risk},
                "severity": "warning",
                "explanation": (
                    "High projected profitability combined with high risk — "
                    "margins may not be sustainable or risk is underpriced"
                ),
                "recommendation": "Validate profitability assumptions under stress scenarios",
            })

    # --- Strong demand + saturated competition ---
    if "demand" in scores and "competition" in scores:
        demand = scores["demand"]
        comp = scores["competition"]
        threshold = CONFLICT_THRESHOLDS["high_demand_high_competition"]
        if demand >= threshold["demand_min"] and comp <= threshold["competition_max"]:
            conflicts.append({
                "type": "high_demand_high_competition",
                "engines": ["demand", "competition"],
                "scores": {"demand": demand, "competition": comp},
                "severity": "info",
                "explanation": (
                    "Strong demand exists but competition is intense — "
                    "differentiation is essential to capture share"
                ),
                "recommendation": "Focus on unique value proposition or underserved niche",
            })

    # --- Positive trend + declining demand ---
    if "trend" in scores and "demand" in scores:
        trend = scores["trend"]
        demand = scores["demand"]
        threshold = CONFLICT_THRESHOLDS["rising_trend_low_demand"]
        if trend >= threshold["trend_min"] and demand <= threshold["demand_max"]:
            conflicts.append({
                "type": "rising_trend_low_demand",
                "engines": ["trend", "demand"],
                "scores": {"trend": trend, "demand": demand},
                "severity": "info",
                "explanation": (
                    "Trend signals are positive but current demand volume is low — "
                    "this may be an emerging market or a false signal"
                ),
                "recommendation": "Monitor trend trajectory before heavy investment",
            })

    # --- Good market size + filter failure ---
    if "market_size" in scores and "filter" in scores:
        market = scores["market_size"]
        filt = scores["filter"]
        if market >= 60 and filt < 50:
            conflicts.append({
                "type": "good_market_filter_fail",
                "engines": ["market_size", "filter"],
                "scores": {"market_size": market, "filter": filt},
                "severity": "critical",
                "explanation": (
                    "Market looks attractive but product failed filter criteria — "
                    "there may be legal, shipping, or category restrictions"
                ),
                "recommendation": "Resolve filter failures before proceeding regardless of market size",
            })

    # --- Low risk + low profitability ---
    if "risk" in scores and "profitability" in scores:
        risk = scores["risk"]
        profit = scores["profitability"]
        if risk <= 25 and profit <= 30:
            conflicts.append({
                "type": "low_risk_low_reward",
                "engines": ["risk", "profitability"],
                "scores": {"risk": risk, "profitability": profit},
                "severity": "info",
                "explanation": (
                    "Product is low risk but also low reward — safe bet but "
                    "may not be worth the operational effort"
                ),
                "recommendation": "Consider whether capital is better deployed on higher-upside products",
            })

    return conflicts


def compute_weighted_score(
    normalized_scores: dict[str, float | None],
    weights: dict[str, float],
) -> float:
    """Compute the weighted aggregate score from normalized engine scores.

    Only engines present in both normalized_scores (non-None) and weights
    are included. Weights are re-normalized to sum to 1.0 across the
    engines that have actual values.

    Args:
        normalized_scores: engine_name -> 0-100 score or None.
        weights: engine_name -> weight (should sum to ~1.0).

    Returns:
        Weighted score on 0-100 scale.
    """
    active_pairs: list[tuple[float, float]] = []

    for engine, score in normalized_scores.items():
        if score is None:
            continue
        w = weights.get(engine, 0.0)
        if w > 0:
            active_pairs.append((score, w))

    if not active_pairs:
        return 0.0

    total_weight = sum(w for _, w in active_pairs)
    if total_weight <= 0:
        return 0.0

    weighted_sum = sum(score * (w / total_weight) for score, w in active_pairs)
    return round(weighted_sum, 2)
