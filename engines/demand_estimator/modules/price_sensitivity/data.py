"""Price sensitivity data — elasticity benchmarks and reference tables.

Sources: economic research, e-commerce industry benchmarks, pricing studies.
Elasticity values are negative (price up → demand down).
"""
from __future__ import annotations

import time
from typing import Any


# Price elasticity of demand by product category
# |PED| < 1 = inelastic, |PED| > 1 = elastic
CATEGORY_ELASTICITY = {
    "electronics": -1.2,         # Somewhat elastic — many alternatives
    "clothing": -1.0,            # Unit elastic overall, varies by brand
    "home_garden": -0.8,         # Somewhat inelastic — functional purchases
    "health_beauty": -0.6,       # Inelastic — brand loyalty, routine purchases
    "sports_outdoors": -1.1,     # Somewhat elastic — discretionary
    "toys_games": -1.3,          # Elastic — highly discretionary
    "pet_supplies": -0.4,        # Very inelastic — pet owners don't skimp
    "office_supplies": -0.3,     # Very inelastic — necessity purchases
    "automotive": -0.7,          # Inelastic — need-based
    "food_beverage": -0.5,       # Inelastic — staples and consumables
    "baby": -0.3,                # Very inelastic — parents prioritize baby
    "jewelry": -1.5,             # Elastic — luxury, highly discretionary
    "books": -1.4,               # Elastic — many substitutes (digital, library)
    "arts_crafts": -1.1,         # Somewhat elastic — hobby spending
    "luxury": -1.8,              # Highly elastic — pure discretionary
    "general": -1.0,             # Default unit elastic
}

# Customer segment elasticity multipliers
SEGMENT_ELASTICITY_MULTIPLIERS = {
    "price_conscious": 1.5,      # 50% more elastic — very price sensitive
    "mid_market": 1.0,           # Baseline
    "premium": 0.6,              # 40% less elastic — less price sensitive
    "luxury": 0.4,               # 60% less elastic — brand/status driven
    "bargain_hunter": 2.0,       # 2x elastic — buys only on deals
}

# Competitor price impact on our demand
COMPETITOR_PRICE_IMPACT = {
    "cross_elasticity": {
        "direct_substitute": 0.8,     # If competitor drops 10%, we lose 8% demand
        "partial_substitute": 0.4,    # If competitor drops 10%, we lose 4%
        "weak_substitute": 0.15,      # Minimal cross-impact
        "complement": -0.2,           # Competitor price drop helps us
    },
    "response_lag_days": {
        "commodity": 1,               # Must respond immediately
        "branded": 7,                 # Can wait a week
        "differentiated": 30,         # Can largely ignore competitor pricing
    },
}

# Willingness-to-pay distributions by category (USD)
WILLINGNESS_TO_PAY = {
    "electronics": {
        "percentiles": {"p10": 15, "p25": 30, "p50": 75, "p75": 150, "p90": 300},
        "median_monthly_spend": 45,
    },
    "clothing": {
        "percentiles": {"p10": 10, "p25": 25, "p50": 50, "p75": 100, "p90": 200},
        "median_monthly_spend": 80,
    },
    "health_beauty": {
        "percentiles": {"p10": 8, "p25": 15, "p50": 30, "p75": 55, "p90": 100},
        "median_monthly_spend": 50,
    },
    "pet_supplies": {
        "percentiles": {"p10": 10, "p25": 20, "p50": 40, "p75": 70, "p90": 120},
        "median_monthly_spend": 75,
    },
    "home_garden": {
        "percentiles": {"p10": 12, "p25": 25, "p50": 50, "p75": 100, "p90": 250},
        "median_monthly_spend": 55,
    },
    "sports_outdoors": {
        "percentiles": {"p10": 15, "p25": 30, "p50": 60, "p75": 120, "p90": 250},
        "median_monthly_spend": 60,
    },
    "jewelry": {
        "percentiles": {"p10": 20, "p25": 50, "p50": 100, "p75": 250, "p90": 500},
        "median_monthly_spend": 35,
    },
    "general": {
        "percentiles": {"p10": 10, "p25": 20, "p50": 40, "p75": 80, "p90": 150},
        "median_monthly_spend": 50,
    },
}

# Price-demand curve parameters (for modeling)
PRICE_DEMAND_CURVES = {
    "linear": {"description": "Q = a - bP (simple, works for small ranges)"},
    "constant_elasticity": {"description": "Q = aP^e (works across wider ranges)"},
    "logistic": {"description": "Q = Qmax / (1 + e^(k(P-P0))) (S-curve with ceiling)"},
}


class PriceRecord:
    """A single price sensitivity analysis record."""

    def __init__(
        self,
        category: str,
        price: float,
        elasticity: float,
        daily_units: int,
        optimal_price: float = 0.0,
        timestamp: float | None = None,
    ) -> None:
        self.category = category
        self.price = price
        self.elasticity = elasticity
        self.daily_units = daily_units
        self.optimal_price = optimal_price
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "price": self.price,
            "elasticity": self.elasticity,
            "daily_units": self.daily_units,
            "optimal_price": self.optimal_price,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PriceRecord:
        return cls(
            category=data["category"],
            price=data["price"],
            elasticity=data["elasticity"],
            daily_units=data["daily_units"],
            optimal_price=data.get("optimal_price", 0.0),
            timestamp=data.get("timestamp"),
        )


def get_category_elasticity(category: str) -> float:
    """Get benchmark price elasticity for a category."""
    return CATEGORY_ELASTICITY.get(category, -1.0)


def get_willingness_distribution(category: str) -> dict[str, Any]:
    """Get willingness-to-pay distribution for a category."""
    return WILLINGNESS_TO_PAY.get(category, WILLINGNESS_TO_PAY["general"])


def get_competitor_impact(substitute_type: str = "partial_substitute") -> float:
    """Get cross-price elasticity for a given substitute type."""
    return COMPETITOR_PRICE_IMPACT["cross_elasticity"].get(substitute_type, 0.4)
