"""Reference data for score aggregation.

Default weights by goal type, normalization ranges for each engine,
conflict detection thresholds, and minimum confidence requirements.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Default weights for balanced aggregation (must sum to 1.0)
# ---------------------------------------------------------------------------
DEFAULT_WEIGHTS: dict[str, float] = {
    "profitability": 0.25,
    "demand": 0.20,
    "competition": 0.15,
    "risk": 0.15,
    "trend": 0.15,
    "market_size": 0.10,
}

# ---------------------------------------------------------------------------
# Goal-specific weight profiles
# ---------------------------------------------------------------------------
GOAL_WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "balanced": {
        "profitability": 0.25,
        "demand": 0.20,
        "competition": 0.15,
        "risk": 0.15,
        "trend": 0.15,
        "market_size": 0.10,
    },
    "profit": {
        "profitability": 0.35,
        "demand": 0.15,
        "competition": 0.15,
        "risk": 0.15,
        "trend": 0.10,
        "market_size": 0.10,
    },
    "growth": {
        "profitability": 0.15,
        "demand": 0.25,
        "competition": 0.10,
        "risk": 0.10,
        "trend": 0.25,
        "market_size": 0.15,
    },
    "conservative": {
        "profitability": 0.20,
        "demand": 0.15,
        "competition": 0.15,
        "risk": 0.25,
        "trend": 0.10,
        "market_size": 0.15,
    },
    "trend_focused": {
        "profitability": 0.15,
        "demand": 0.20,
        "competition": 0.10,
        "risk": 0.10,
        "trend": 0.30,
        "market_size": 0.15,
    },
}

# ---------------------------------------------------------------------------
# Normalization ranges per engine (min, max of expected raw score)
# Scores outside this range are clamped before normalizing to 0-100.
# ---------------------------------------------------------------------------
NORMALIZATION_RANGES: dict[str, tuple[float, float]] = {
    "profitability": (0, 100),
    "demand": (0, 100),
    "competition": (0, 100),
    "risk": (0, 100),
    "trend": (0, 100),
    "market_size": (0, 100),
    "filter": (0, 100),
}

# ---------------------------------------------------------------------------
# Conflict detection thresholds
# ---------------------------------------------------------------------------
CONFLICT_THRESHOLDS: dict[str, dict[str, float]] = {
    "high_profit_high_risk": {
        "profit_min": 70.0,
        "risk_min": 65.0,
        "description": "Profitable but risky — profits may not be sustainable",
    },
    "high_demand_high_competition": {
        "demand_min": 65.0,
        "competition_max": 35.0,
        "description": "Demand exists but market is crowded — need differentiation",
    },
    "rising_trend_low_demand": {
        "trend_min": 70.0,
        "demand_max": 35.0,
        "description": "Trend is up but volume is still low — could be early or false signal",
    },
    "low_risk_low_reward": {
        "risk_max": 25.0,
        "profit_max": 30.0,
        "description": "Safe but not worth the effort — opportunity cost is real",
    },
}

# ---------------------------------------------------------------------------
# Minimum confidence requirements
# ---------------------------------------------------------------------------
MINIMUM_CONFIDENCE: dict[str, Any] = {
    "min_engines": 3,
    "high_confidence_coverage": 0.85,
    "moderate_confidence_coverage": 0.60,
    "critical_engines": ["profitability", "demand", "risk"],
    "description": (
        "At least 3 engines (including profitability) must provide data. "
        "Coverage of 85%+ of engines yields high confidence; 60-84% moderate; "
        "below 60% is low confidence and should not drive auto-selection."
    ),
}

# ---------------------------------------------------------------------------
# Risk multiplier curve reference
# ---------------------------------------------------------------------------
RISK_MULTIPLIER_CURVE: dict[str, dict[str, float]] = {
    "no_risk": {"risk_score_range": (0, 15), "multiplier": 1.0},
    "low_risk": {"risk_score_range": (15, 35), "multiplier": 0.92},
    "moderate_risk": {"risk_score_range": (35, 55), "multiplier": 0.82},
    "high_risk": {"risk_score_range": (55, 75), "multiplier": 0.70},
    "critical_risk": {"risk_score_range": (75, 100), "multiplier": 0.55},
}

# ---------------------------------------------------------------------------
# Score quality benchmarks
# ---------------------------------------------------------------------------
SCORE_QUALITY_BENCHMARKS: dict[str, dict[str, Any]] = {
    "excellent_product": {
        "unified_score_min": 75,
        "description": "Strong across most dimensions — likely a good pick",
    },
    "good_product": {
        "unified_score_min": 55,
        "description": "Solid but has weaknesses — investigate before committing",
    },
    "marginal_product": {
        "unified_score_min": 40,
        "description": "Borderline — only consider if no better options exist",
    },
    "poor_product": {
        "unified_score_min": 0,
        "description": "Weak scores across the board — skip unless data is incomplete",
    },
}
