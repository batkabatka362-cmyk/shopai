"""Confidence data — calibration benchmarks, historical baselines, thresholds.

Reference data for translating raw confidence factors into calibrated
confidence scores. Based on aggregated e-commerce product selection outcomes.
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
#  Factor weights for composite confidence score
# --------------------------------------------------------------------------- #
CONFIDENCE_WEIGHTS: dict[str, float] = {
    "data_quality": 0.30,
    "signal_agreement": 0.25,
    "historical_accuracy": 0.25,
    "score_gap": 0.20,
}

# --------------------------------------------------------------------------- #
#  Calibration benchmarks — how raw confidence maps to real-world accuracy
# --------------------------------------------------------------------------- #
CALIBRATION_BENCHMARKS: list[dict[str, Any]] = [
    {
        "raw_range": (0, 20),
        "calibrated_accuracy": 0.35,
        "label": "very_low",
        "description": "Essentially a coin flip. Data is sparse or contradictory.",
    },
    {
        "raw_range": (20, 40),
        "calibrated_accuracy": 0.50,
        "label": "low",
        "description": "Slight edge over random. Needs more data or human judgment.",
    },
    {
        "raw_range": (40, 60),
        "calibrated_accuracy": 0.65,
        "label": "medium",
        "description": "Reasonable confidence. Monitor closely after selection.",
    },
    {
        "raw_range": (60, 80),
        "calibrated_accuracy": 0.78,
        "label": "high",
        "description": "Strong signal alignment and data coverage. Safe to proceed.",
    },
    {
        "raw_range": (80, 100),
        "calibrated_accuracy": 0.88,
        "label": "very_high",
        "description": "Exceptional data quality and engine consensus. Rare in practice.",
    },
]

# --------------------------------------------------------------------------- #
#  Historical accuracy baselines by category
# --------------------------------------------------------------------------- #
HISTORICAL_ACCURACY_BASELINES: dict[str, dict[str, float]] = {
    "electronics":     {"accuracy": 62.0, "sample_size": 450, "recency_months": 6},
    "clothing":        {"accuracy": 55.0, "sample_size": 620, "recency_months": 4},
    "health_beauty":   {"accuracy": 68.0, "sample_size": 380, "recency_months": 5},
    "home_garden":     {"accuracy": 60.0, "sample_size": 290, "recency_months": 8},
    "sports_outdoors": {"accuracy": 58.0, "sample_size": 210, "recency_months": 7},
    "pet_supplies":    {"accuracy": 64.0, "sample_size": 175, "recency_months": 6},
    "jewelry":         {"accuracy": 52.0, "sample_size": 140, "recency_months": 9},
    "toys_games":      {"accuracy": 57.0, "sample_size": 320, "recency_months": 5},
    "general":         {"accuracy": 58.0, "sample_size": 1000, "recency_months": 6},
}

# --------------------------------------------------------------------------- #
#  Signal agreement thresholds
# --------------------------------------------------------------------------- #
SIGNAL_AGREEMENT_THRESHOLDS: dict[str, Any] = {
    "strong_agreement": 80.0,
    "moderate_agreement": 55.0,
    "weak_agreement": 30.0,
    "max_acceptable_std_dev": 25.0,
    "min_engines_for_agreement": 3,
    "critical_pair_weight": 1.5,
    "critical_pairs": [
        ("profitability", "demand"),
        ("risk", "profitability"),
        ("trend", "demand"),
    ],
}


def get_calibration_for_raw(raw_confidence: float) -> dict[str, Any]:
    """Return the calibration benchmark matching a raw confidence value."""
    clamped = max(0.0, min(100.0, raw_confidence))
    for bench in CALIBRATION_BENCHMARKS:
        lo, hi = bench["raw_range"]
        if lo <= clamped < hi:
            return bench
    return CALIBRATION_BENCHMARKS[-1]


def get_historical_baseline(category: str) -> dict[str, float]:
    """Return historical accuracy baseline for a product category."""
    key = category.lower().replace(" ", "_").replace("-", "_")
    if key in HISTORICAL_ACCURACY_BASELINES:
        return HISTORICAL_ACCURACY_BASELINES[key]
    for k in HISTORICAL_ACCURACY_BASELINES:
        if k in key or key in k:
            return HISTORICAL_ACCURACY_BASELINES[k]
    return HISTORICAL_ACCURACY_BASELINES["general"]
