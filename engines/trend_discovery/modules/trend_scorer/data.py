"""Trend scorer data — weights, thresholds, historical accuracy, and portfolio rules.

Core scoring data:
  - Signal weights reflect predictive power of each source
  - Search + marketplace is the strongest combo (demand + purchase proof)
  - Thresholds are calibrated against historical trend outcomes
"""
from __future__ import annotations

from typing import Any


# How much each signal source contributes to the composite score (must sum to 1.0)
SIGNAL_WEIGHTS: dict[str, float] = {
    "search": 0.30,
    "social": 0.25,
    "marketplace": 0.25,
    "emerging": 0.20,
}

# Composite score thresholds for trend classification
SCORE_THRESHOLDS: dict[str, dict[str, Any]] = {
    "exploding": {"min_score": 80, "label": "Exploding", "description": "Rapid growth across multiple signals — act immediately"},
    "strong": {"min_score": 60, "label": "Strong", "description": "Clear upward trajectory — plan product launch"},
    "moderate": {"min_score": 40, "label": "Moderate", "description": "Positive signals but not conclusive — monitor closely"},
    "weak": {"min_score": 20, "label": "Weak", "description": "Early or ambiguous signals — watch and gather more data"},
    "declining": {"min_score": 0, "label": "Declining", "description": "Negative trajectory — avoid or exit"},
}

# Which signal combinations have historically predicted successful trends
HISTORICAL_ACCURACY: dict[str, dict[str, Any]] = {
    "search+marketplace": {
        "accuracy": 0.78,
        "description": "Demand (search) confirmed by purchases (marketplace) — strongest predictor",
        "false_positive_rate": 0.12,
    },
    "search+social+marketplace": {
        "accuracy": 0.85,
        "description": "Triple confirmation — very high confidence",
        "false_positive_rate": 0.08,
    },
    "all_four": {
        "accuracy": 0.91,
        "description": "All sources agree — highest possible confidence",
        "false_positive_rate": 0.05,
    },
    "social_only": {
        "accuracy": 0.35,
        "description": "Social buzz alone — often hype, rarely converts to sustained sales",
        "false_positive_rate": 0.45,
    },
    "emerging_only": {
        "accuracy": 0.42,
        "description": "Early niche signal — promising but unvalidated",
        "false_positive_rate": 0.38,
    },
    "search+social": {
        "accuracy": 0.58,
        "description": "Interest + awareness but no purchase proof yet",
        "false_positive_rate": 0.25,
    },
    "marketplace+emerging": {
        "accuracy": 0.62,
        "description": "Early sales in emerging niche — good but needs more volume",
        "false_positive_rate": 0.22,
    },
}

# Rules governing how to build a diversified trend portfolio
PORTFOLIO_RULES: dict[str, Any] = {
    "max_active_bets": 3,
    "allocation_by_confidence": {
        "high": {"min_pct": 0.40, "max_pct": 0.60, "description": "Largest bets on high-confidence trends"},
        "medium": {"min_pct": 0.20, "max_pct": 0.35, "description": "Moderate bets on promising trends"},
        "low": {"min_pct": 0.10, "max_pct": 0.20, "description": "Small exploratory bets"},
    },
    "diversification": {
        "require_different_categories": True,
        "max_same_category": 2,
        "prefer_different_lifecycles": True,
    },
    "rebalance_trigger": {
        "score_drop_pct": 20,
        "new_higher_opportunity": True,
        "max_hold_days_without_traction": 60,
    },
}


def get_weight(signal_name: str) -> float:
    """Return weight for a signal source, default 0."""
    return SIGNAL_WEIGHTS.get(signal_name, 0.0)


def get_threshold(classification: str) -> int:
    """Return minimum score for a classification tier."""
    tier = SCORE_THRESHOLDS.get(classification)
    return tier["min_score"] if tier else 0


def get_accuracy(combo_key: str) -> dict[str, Any]:
    """Return historical accuracy data for a signal combination."""
    return HISTORICAL_ACCURACY.get(combo_key, {"accuracy": 0.30, "description": "Unknown combination", "false_positive_rate": 0.50})
