"""Seasonal Risk — domain knowledge and heuristics.

Curated insights about seasonal selling, fad products, and cash flow
management that inform risk assessment decisions.
"""
from __future__ import annotations

from typing import Any

SEASONAL_RISK_INSIGHTS: list[dict[str, str]] = [
    {
        "id": "seasonal_margin_trap",
        "insight": (
            "Seasonal products = great margins in peak, zero in trough. "
            "Your annualized margin is much lower than your peak margin."
        ),
        "applies_to": "highly_seasonal",
    },
    {
        "id": "fad_exit_strategy",
        "insight": (
            "Fads last 3-6 months max — plan your exit before your entry. "
            "The biggest losses come from inventory you cannot sell after the wave passes."
        ),
        "applies_to": "fad",
    },
    {
        "id": "cash_reserve_lifeline",
        "insight": (
            "Cash reserve is your lifeline during the off-season. Without 3-4 months "
            "of operating expenses in reserve, a seasonal business is one bad quarter "
            "from insolvency."
        ),
        "applies_to": "highly_seasonal",
    },
    {
        "id": "inventory_timing_window",
        "insight": (
            "Order inventory too early and you tie up cash; order too late and you "
            "miss peak demand. The sweet spot is typically 8-12 weeks before peak."
        ),
        "applies_to": "moderate_seasonal",
    },
    {
        "id": "counter_seasonal_hedge",
        "insight": (
            "Pairing counter-seasonal products (e.g., summer + winter lines) flattens "
            "revenue curves and reduces cash flow risk substantially."
        ),
        "applies_to": "highly_seasonal",
    },
    {
        "id": "trending_vs_permanent",
        "insight": (
            "Distinguish trending demand from permanent demand. Google Trends rising "
            "for 18+ months suggests lasting demand. Under 6 months is likely a fad."
        ),
        "applies_to": "all",
    },
    {
        "id": "weather_dependency",
        "insight": (
            "Weather-dependent products carry double uncertainty: seasonal timing risk "
            "plus unpredictable weather patterns. Budget for a bad-weather year."
        ),
        "applies_to": "outdoor_recreation",
    },
    {
        "id": "off_peak_launch_danger",
        "insight": (
            "Launching a seasonal product off-peak burns cash for months before any "
            "revenue arrives. Always time launches to coincide with demand ramp-up."
        ),
        "applies_to": "highly_seasonal",
    },
]


def get_seasonal_risk_insights(
    classification: str | None = None,
) -> list[dict[str, str]]:
    """Return insights filtered by seasonality classification."""
    if classification is None:
        return list(SEASONAL_RISK_INSIGHTS)
    return [
        i for i in SEASONAL_RISK_INSIGHTS
        if i["applies_to"] in (classification, "all")
    ]


def get_heuristics() -> dict[str, str]:
    """Return quick-reference heuristics for seasonal risk assessment."""
    return {
        "peak_to_trough_low": "Ratio < 2x = low seasonality risk",
        "peak_to_trough_moderate": "Ratio 2-5x = moderate seasonality, plan cash buffer",
        "peak_to_trough_high": "Ratio > 5x = high seasonality, need 4+ months reserve",
        "fad_signal_short_trend": "Google Trends spike < 6 months = likely fad",
        "fad_signal_no_repeat": "No repeat purchase pattern = fad risk",
        "inventory_lead_time": "Order 8-12 weeks before peak, not sooner",
        "cash_reserve_minimum": "Always hold 2x monthly fixed costs during trough",
        "weather_hedge": "Budget assuming 20% worse weather than average",
    }
