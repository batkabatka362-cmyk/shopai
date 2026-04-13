"""Supplier risk data — country scores, failure rates, and lead time benchmarks.

Contains:
  - Country risk scores for major sourcing regions
  - Supplier failure rates by type and region
  - Lead time variance by region and shipping method
"""
from __future__ import annotations

from typing import Any


# Country risk scores for e-commerce sourcing (0-100, higher = more risk)
COUNTRY_RISK_SCORES = {
    "china": {
        "risk_score": 50,
        "level": "moderate",
        "factors": [
            "Trade tensions and tariff uncertainty",
            "Chinese New Year causes 4-6 weeks annual disruption",
            "Strong manufacturing base but IP protection concerns",
        ],
        "tariff_risk": "high",
        "lead_time_days": {"sea": 30, "air": 10},
    },
    "vietnam": {
        "risk_score": 35,
        "level": "low_moderate",
        "factors": [
            "Growing manufacturing hub — less trade tension than China",
            "Improving infrastructure but still developing",
            "Lower labor costs, competitive pricing",
        ],
        "tariff_risk": "low",
        "lead_time_days": {"sea": 35, "air": 12},
    },
    "india": {
        "risk_score": 55,
        "level": "moderate_high",
        "factors": [
            "Bureaucratic complexity and customs delays",
            "Quality variance is higher than China average",
            "Growing capacity but infrastructure still catching up",
        ],
        "tariff_risk": "moderate",
        "lead_time_days": {"sea": 35, "air": 12},
    },
    "taiwan": {
        "risk_score": 45,
        "level": "moderate",
        "factors": [
            "High quality manufacturing, especially electronics",
            "Geopolitical tension with China creates uncertainty",
            "Higher costs than mainland China",
        ],
        "tariff_risk": "moderate",
        "lead_time_days": {"sea": 28, "air": 8},
    },
    "turkey": {
        "risk_score": 50,
        "level": "moderate",
        "factors": [
            "Strong in textiles and home goods",
            "Currency volatility affects pricing stability",
            "Closer to US/EU than Asian alternatives",
        ],
        "tariff_risk": "moderate",
        "lead_time_days": {"sea": 25, "air": 8},
    },
    "mexico": {
        "risk_score": 30,
        "level": "low",
        "factors": [
            "USMCA trade agreement = favorable tariffs",
            "Short lead times compared to Asia",
            "Growing nearshoring trend favors Mexican suppliers",
        ],
        "tariff_risk": "low",
        "lead_time_days": {"sea": 7, "air": 3},
    },
    "usa": {
        "risk_score": 10,
        "level": "very_low",
        "factors": [
            "No tariff or trade risk",
            "Fastest lead times",
            "Highest production costs",
        ],
        "tariff_risk": "none",
        "lead_time_days": {"ground": 5, "air": 2},
    },
    "bangladesh": {
        "risk_score": 60,
        "level": "moderate_high",
        "factors": [
            "Very low costs but quality oversight is essential",
            "Infrastructure and port capacity limitations",
            "Strong in garments but limited in other categories",
        ],
        "tariff_risk": "low",
        "lead_time_days": {"sea": 40, "air": 14},
    },
    "south_korea": {
        "risk_score": 25,
        "level": "low",
        "factors": [
            "High quality, advanced manufacturing",
            "Strong IP protection",
            "Higher costs but reliable",
        ],
        "tariff_risk": "low",
        "lead_time_days": {"sea": 25, "air": 7},
    },
    "thailand": {
        "risk_score": 35,
        "level": "low_moderate",
        "factors": [
            "Stable manufacturing environment",
            "Good quality control in established factories",
            "Competitive pricing for mid-range products",
        ],
        "tariff_risk": "low",
        "lead_time_days": {"sea": 32, "air": 11},
    },
}

# Supplier failure rates by type (annual probability of significant disruption)
SUPPLIER_FAILURE_RATES = {
    "trading_company": {
        "failure_rate_pct": 8.0,
        "description": "Trading companies fail more often — they don't control production",
    },
    "small_factory": {
        "failure_rate_pct": 6.0,
        "description": "Small factories (<50 workers) have cash flow vulnerabilities",
    },
    "medium_factory": {
        "failure_rate_pct": 3.0,
        "description": "Medium factories (50-500 workers) are more stable",
    },
    "large_factory": {
        "failure_rate_pct": 1.5,
        "description": "Large factories are stable but may deprioritize small orders",
    },
    "domestic_supplier": {
        "failure_rate_pct": 4.0,
        "description": "Domestic suppliers have moderate failure rates but faster recovery",
    },
}

# Lead time variance by region (days of typical deviation from quoted lead time)
LEAD_TIME_VARIANCE = {
    "china": {"avg_variance_days": 7, "max_variance_days": 21, "reliability": "moderate"},
    "vietnam": {"avg_variance_days": 10, "max_variance_days": 25, "reliability": "moderate"},
    "india": {"avg_variance_days": 14, "max_variance_days": 35, "reliability": "low"},
    "mexico": {"avg_variance_days": 3, "max_variance_days": 10, "reliability": "high"},
    "usa": {"avg_variance_days": 2, "max_variance_days": 7, "reliability": "very_high"},
    "taiwan": {"avg_variance_days": 5, "max_variance_days": 14, "reliability": "high"},
    "turkey": {"avg_variance_days": 8, "max_variance_days": 20, "reliability": "moderate"},
    "bangladesh": {"avg_variance_days": 14, "max_variance_days": 30, "reliability": "low"},
    "south_korea": {"avg_variance_days": 4, "max_variance_days": 10, "reliability": "high"},
    "thailand": {"avg_variance_days": 7, "max_variance_days": 18, "reliability": "moderate"},
}


def get_country_risk(country: str) -> dict[str, Any]:
    """Get risk profile for a sourcing country."""
    return COUNTRY_RISK_SCORES.get(country.lower().replace(" ", "_"), {
        "risk_score": 50,
        "level": "unknown",
        "factors": ["No specific data available for this country"],
        "tariff_risk": "unknown",
        "lead_time_days": {"sea": 35, "air": 12},
    })


def get_lead_time_variance(country: str) -> dict[str, Any]:
    """Get lead time variance data for a sourcing country."""
    return LEAD_TIME_VARIANCE.get(country.lower().replace(" ", "_"), {
        "avg_variance_days": 10,
        "max_variance_days": 25,
        "reliability": "unknown",
    })


def get_supplier_failure_rate(supplier_type: str) -> dict[str, Any]:
    """Get failure rate for a supplier type."""
    return SUPPLIER_FAILURE_RATES.get(supplier_type, {
        "failure_rate_pct": 5.0,
        "description": "Unknown supplier type — assume moderate risk",
    })
