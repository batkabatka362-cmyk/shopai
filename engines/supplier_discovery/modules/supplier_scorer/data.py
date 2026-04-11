"""Supplier scorer data — benchmarks, red flags, country risk, and scoring weights.

Core scoring data:
  - Dimension weights reflect importance for e-commerce sourcing
  - Red flag indicators detect scams and unreliable suppliers
  - Country risk scores adjust for geopolitical and logistics factors
  - Source-type benchmarks set expectations per supplier channel
"""
from __future__ import annotations

from typing import Any


# Weight of each scoring dimension in the composite score (must sum to 1.0)
DIMENSION_WEIGHTS: dict[str, float] = {
    "price_competitiveness": 0.25,
    "quality_rating": 0.25,
    "reliability": 0.20,
    "communication": 0.10,
    "moq_flexibility": 0.10,
    "payment_terms": 0.10,
}

# Benchmarks per supplier source type — what "good" looks like for each channel
SOURCE_BENCHMARKS: dict[str, dict[str, Any]] = {
    "alibaba": {
        "expected_price_pct_of_retail": (0.15, 0.30),
        "acceptable_lead_days": (21, 45),
        "min_acceptable_rating": 4.0,
        "typical_moq": 500,
        "expected_response_hours": 24,
        "trade_assurance_required": True,
    },
    "domestic_wholesale": {
        "expected_price_pct_of_retail": (0.40, 0.55),
        "acceptable_lead_days": (3, 14),
        "min_acceptable_rating": 4.2,
        "typical_moq": 25,
        "expected_response_hours": 8,
        "trade_assurance_required": False,
    },
    "private_label": {
        "expected_price_pct_of_retail": (0.18, 0.35),
        "acceptable_lead_days": (30, 60),
        "min_acceptable_rating": 4.3,
        "typical_moq": 1000,
        "expected_response_hours": 24,
        "trade_assurance_required": True,
    },
    "dropship": {
        "expected_price_pct_of_retail": (0.30, 0.50),
        "acceptable_lead_days": (7, 21),
        "min_acceptable_rating": 4.0,
        "typical_moq": 1,
        "expected_response_hours": 12,
        "trade_assurance_required": False,
    },
}

# Red flag indicators — each has a severity weight used in scam detection
RED_FLAG_INDICATORS: dict[str, dict[str, Any]] = {
    "price_too_low": {
        "description": "Unit price below 10% of market average — likely bait-and-switch",
        "severity": 0.9,
        "check_field": "price_vs_market_pct",
        "threshold": 0.10,
        "direction": "below",
    },
    "no_factory_photos": {
        "description": "No factory or production photos — may be a trading company or scam",
        "severity": 0.6,
        "check_field": "has_factory_photos",
        "threshold": False,
        "direction": "equals",
    },
    "new_account": {
        "description": "Account less than 1 year old — unproven track record",
        "severity": 0.5,
        "check_field": "account_age_years",
        "threshold": 1.0,
        "direction": "below",
    },
    "no_trade_assurance": {
        "description": "No Trade Assurance or payment protection — high risk for prepayment",
        "severity": 0.7,
        "check_field": "has_trade_assurance",
        "threshold": False,
        "direction": "equals",
    },
    "fake_reviews": {
        "description": "Review pattern suggests fake reviews (all 5-star, generic text, burst timing)",
        "severity": 0.8,
        "check_field": "review_authenticity_score",
        "threshold": 0.4,
        "direction": "below",
    },
    "no_export_license": {
        "description": "Claims to export but no visible export license or certification",
        "severity": 0.5,
        "check_field": "has_export_license",
        "threshold": False,
        "direction": "equals",
    },
    "pressure_tactics": {
        "description": "Uses urgency pressure (limited time pricing, threatening to sell to competitor)",
        "severity": 0.7,
        "check_field": "uses_pressure_tactics",
        "threshold": True,
        "direction": "equals",
    },
    "inconsistent_moq": {
        "description": "MOQ keeps changing between conversations — unreliable or dishonest",
        "severity": 0.6,
        "check_field": "moq_consistency",
        "threshold": False,
        "direction": "equals",
    },
}

# Country risk scores: 0 = highest risk, 100 = lowest risk
COUNTRY_RISK_SCORES: dict[str, dict[str, Any]] = {
    "CN": {"score": 60, "label": "China", "notes": "Largest supplier base but quality variance is high; use Trade Assurance"},
    "IN": {"score": 55, "label": "India", "notes": "Strong in textiles and jewelry; communication can be slower"},
    "VN": {"score": 65, "label": "Vietnam", "notes": "Rising manufacturing hub; good for apparel and electronics"},
    "TH": {"score": 68, "label": "Thailand", "notes": "Reliable for food, beauty, and rubber products"},
    "US": {"score": 90, "label": "United States", "notes": "Premium pricing but highest reliability and legal protection"},
    "DE": {"score": 92, "label": "Germany", "notes": "Excellent quality standards; premium cost"},
    "TR": {"score": 58, "label": "Turkey", "notes": "Good for textiles and home goods; currency volatility risk"},
    "PK": {"score": 45, "label": "Pakistan", "notes": "Low cost textiles; logistics and payment reliability concerns"},
    "BD": {"score": 42, "label": "Bangladesh", "notes": "Very low cost garments; lead times and quality control challenges"},
    "MX": {"score": 70, "label": "Mexico", "notes": "Nearshoring advantage for US sellers; growing manufacturing base"},
    "PL": {"score": 78, "label": "Poland", "notes": "Competitive EU manufacturing; good for cosmetics and furniture"},
    "TW": {"score": 82, "label": "Taiwan", "notes": "High-quality electronics and precision parts"},
}

# Tier classification thresholds based on composite score
TIER_THRESHOLDS: dict[str, dict[str, Any]] = {
    "gold": {"min_score": 80, "label": "Gold", "description": "Top-tier supplier — prioritize and build long-term relationship"},
    "silver": {"min_score": 60, "label": "Silver", "description": "Solid supplier — suitable for regular orders with monitoring"},
    "bronze": {"min_score": 40, "label": "Bronze", "description": "Acceptable with caveats — use for backup or small orders only"},
    "unverified": {"min_score": 0, "label": "Unverified", "description": "Insufficient data or low scores — require samples and due diligence"},
}


def get_weight(dimension: str) -> float:
    """Return weight for a scoring dimension, default 0."""
    return DIMENSION_WEIGHTS.get(dimension, 0.0)


def get_benchmark(source_type: str) -> dict[str, Any]:
    """Return benchmark data for a supplier source type."""
    return SOURCE_BENCHMARKS.get(source_type, SOURCE_BENCHMARKS["alibaba"])


def get_country_risk(country_code: str) -> dict[str, Any]:
    """Return country risk profile. Defaults to moderate risk for unknown countries."""
    return COUNTRY_RISK_SCORES.get(
        country_code.upper(),
        {"score": 50, "label": "Unknown", "notes": "No data — treat as moderate risk"},
    )


def get_tier(composite_score: float) -> dict[str, Any]:
    """Return tier classification for a given composite score."""
    for tier_key in ("gold", "silver", "bronze", "unverified"):
        tier = TIER_THRESHOLDS[tier_key]
        if composite_score >= tier["min_score"]:
            return {"tier": tier_key, **tier}
    return {"tier": "unverified", **TIER_THRESHOLDS["unverified"]}
