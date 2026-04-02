"""Reference data for financial risk assessment.

Capital loss probabilities, cash flow benchmarks, margin erosion rates,
and chargeback rate benchmarks. All figures based on e-commerce industry data.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Capital loss probabilities by product type (% chance of losing investment)
# ---------------------------------------------------------------------------
CAPITAL_LOSS_PROBABILITIES: dict[str, dict[str, Any]] = {
    "trending_fad": {
        "total_loss_prob": 0.35,
        "partial_loss_prob": 0.30,
        "break_even_prob": 0.20,
        "profit_prob": 0.15,
        "description": "Fad products have high failure rate — timing is everything",
    },
    "seasonal": {
        "total_loss_prob": 0.20,
        "partial_loss_prob": 0.25,
        "break_even_prob": 0.25,
        "profit_prob": 0.30,
        "description": "Seasonal products carry inventory risk if window is missed",
    },
    "evergreen": {
        "total_loss_prob": 0.10,
        "partial_loss_prob": 0.15,
        "break_even_prob": 0.25,
        "profit_prob": 0.50,
        "description": "Evergreen products have steady demand but slower ramp-up",
    },
    "commodity": {
        "total_loss_prob": 0.15,
        "partial_loss_prob": 0.25,
        "break_even_prob": 0.30,
        "profit_prob": 0.30,
        "description": "Commodity products face race-to-bottom pricing pressure",
    },
    "innovative": {
        "total_loss_prob": 0.25,
        "partial_loss_prob": 0.20,
        "break_even_prob": 0.20,
        "profit_prob": 0.35,
        "description": "Innovative products have market education costs but higher upside",
    },
    "private_label": {
        "total_loss_prob": 0.15,
        "partial_loss_prob": 0.20,
        "break_even_prob": 0.25,
        "profit_prob": 0.40,
        "description": "Private label has brand-building costs but better long-term margins",
    },
}

# ---------------------------------------------------------------------------
# Cash flow recovery benchmarks (months to positive cash flow)
# ---------------------------------------------------------------------------
CASH_FLOW_BENCHMARKS: dict[str, dict[str, Any]] = {
    "fast_mover": {
        "months_to_positive": (1, 2),
        "typical_investment": (1000, 5000),
        "description": "Low MOQ, fast turnover, immediate demand",
    },
    "standard": {
        "months_to_positive": (2, 4),
        "typical_investment": (3000, 15000),
        "description": "Typical private label or wholesale product",
    },
    "slow_ramp": {
        "months_to_positive": (4, 8),
        "typical_investment": (10000, 50000),
        "description": "Products requiring brand building or market education",
    },
    "capital_intensive": {
        "months_to_positive": (6, 12),
        "typical_investment": (25000, 100000),
        "description": "Custom manufacturing, tooling, or certification costs",
    },
}

# ---------------------------------------------------------------------------
# Margin erosion rates (% margin loss per month due to competition)
# ---------------------------------------------------------------------------
MARGIN_EROSION_RATES: dict[str, dict[str, float]] = {
    "high_competition": {"monthly_erosion": 0.02, "annual_erosion": 0.20, "stabilization_floor": 0.10},
    "moderate_competition": {"monthly_erosion": 0.01, "annual_erosion": 0.10, "stabilization_floor": 0.20},
    "low_competition": {"monthly_erosion": 0.005, "annual_erosion": 0.05, "stabilization_floor": 0.30},
    "differentiated": {"monthly_erosion": 0.003, "annual_erosion": 0.03, "stabilization_floor": 0.35},
    "patented": {"monthly_erosion": 0.001, "annual_erosion": 0.01, "stabilization_floor": 0.40},
}

# ---------------------------------------------------------------------------
# Chargeback / refund rate benchmarks by category
# ---------------------------------------------------------------------------
CHARGEBACK_BENCHMARKS: dict[str, dict[str, float]] = {
    "clothing": {"refund_rate": 0.15, "chargeback_rate": 0.008, "fraud_rate": 0.012},
    "electronics": {"refund_rate": 0.08, "chargeback_rate": 0.010, "fraud_rate": 0.015},
    "supplements": {"refund_rate": 0.10, "chargeback_rate": 0.015, "fraud_rate": 0.010},
    "cosmetics": {"refund_rate": 0.06, "chargeback_rate": 0.005, "fraud_rate": 0.008},
    "home_decor": {"refund_rate": 0.07, "chargeback_rate": 0.004, "fraud_rate": 0.006},
    "toys": {"refund_rate": 0.05, "chargeback_rate": 0.003, "fraud_rate": 0.005},
    "food": {"refund_rate": 0.04, "chargeback_rate": 0.003, "fraud_rate": 0.004},
    "jewelry": {"refund_rate": 0.12, "chargeback_rate": 0.020, "fraud_rate": 0.025},
    "general": {"refund_rate": 0.08, "chargeback_rate": 0.008, "fraud_rate": 0.010},
}

# ---------------------------------------------------------------------------
# Currency volatility data (annual standard deviation for common trade pairs)
# ---------------------------------------------------------------------------
CURRENCY_VOLATILITY: dict[str, float] = {
    "USD_CNY": 0.04,
    "USD_INR": 0.05,
    "USD_EUR": 0.07,
    "USD_GBP": 0.08,
    "USD_JPY": 0.09,
    "USD_VND": 0.03,
    "USD_THB": 0.05,
    "USD_MXN": 0.10,
}

DEFAULT_CURRENCY_PAIR = "USD_CNY"


def get_loss_probability(product_type: str) -> dict[str, Any]:
    """Return capital loss probability for a product type."""
    return CAPITAL_LOSS_PROBABILITIES.get(
        product_type, CAPITAL_LOSS_PROBABILITIES["evergreen"]
    )


def get_chargeback_rates(category: str) -> dict[str, float]:
    """Return chargeback and refund benchmarks for a category."""
    return CHARGEBACK_BENCHMARKS.get(category, CHARGEBACK_BENCHMARKS["general"])


def get_currency_volatility(pair: str) -> float:
    """Return annualized volatility for a currency pair."""
    return CURRENCY_VOLATILITY.get(pair, CURRENCY_VOLATILITY[DEFAULT_CURRENCY_PAIR])


def get_margin_erosion(competition_level: str) -> dict[str, float]:
    """Return margin erosion rates for a competition level."""
    return MARGIN_EROSION_RATES.get(
        competition_level, MARGIN_EROSION_RATES["moderate_competition"]
    )
