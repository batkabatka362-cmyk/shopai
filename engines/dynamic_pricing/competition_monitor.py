"""Dynamic Pricing Engine — competition monitor.

Tracks competitor price positions, calculates gap percentages, and
determines competitive pressure level.

1 file = 1 job: competition analysis only.
"""
from __future__ import annotations

import copy
from typing import Any


def monitor_competition(
    signals: dict[str, Any],
) -> dict[str, Any]:
    """Analyze competitor pricing relative to our current price.

    Args:
        signals: CollectedSignals dict from signal_collector.

    Returns:
        Structured dict with CompetitionSnapshot data.
    """
    try:
        sig = copy.deepcopy(signals)

        current_price = float(sig.get("current_price", 0.0))
        competitor_prices = sig.get("competitor_prices", [])

        # Handle empty competitor list
        if not competitor_prices:
            return {
                "status": "success",
                "snapshot": {
                    "avg_competitor_price": 0.0,
                    "min_competitor_price": 0.0,
                    "max_competitor_price": 0.0,
                    "competitor_count": 0,
                    "our_position": "no_data",
                    "price_gap_pct": 0.0,
                    "competitive_pressure": 0.0,
                },
            }

        prices = [float(p) for p in competitor_prices if float(p) > 0]
        if not prices:
            return {
                "status": "success",
                "snapshot": {
                    "avg_competitor_price": 0.0,
                    "min_competitor_price": 0.0,
                    "max_competitor_price": 0.0,
                    "competitor_count": 0,
                    "our_position": "no_data",
                    "price_gap_pct": 0.0,
                    "competitive_pressure": 0.0,
                },
            }

        avg_price = sum(prices) / len(prices)
        min_price = min(prices)
        max_price = max(prices)
        competitor_count = len(prices)

        # --- Our position relative to competitors ---
        if current_price <= 0:
            our_position = "unknown"
            price_gap_pct = 0.0
        elif current_price < min_price:
            our_position = "lowest"
            price_gap_pct = _pct_diff(current_price, avg_price)
        elif current_price > max_price:
            our_position = "highest"
            price_gap_pct = _pct_diff(current_price, avg_price)
        elif current_price <= avg_price:
            our_position = "below_average"
            price_gap_pct = _pct_diff(current_price, avg_price)
        else:
            our_position = "above_average"
            price_gap_pct = _pct_diff(current_price, avg_price)

        # --- Competitive pressure ---
        # Higher when we are priced above competitors
        # Range: 0.0 (no pressure) to 1.0 (extreme pressure)
        if avg_price <= 0 or current_price <= 0:
            competitive_pressure = 0.0
        else:
            ratio = current_price / avg_price
            if ratio <= 0.90:
                # We are well below average — low pressure
                competitive_pressure = 0.0
            elif ratio <= 1.0:
                # Slightly below average — mild pressure
                competitive_pressure = (ratio - 0.90) / 0.10 * 0.3
            elif ratio <= 1.10:
                # Slightly above average — moderate pressure
                competitive_pressure = 0.3 + (ratio - 1.0) / 0.10 * 0.3
            elif ratio <= 1.25:
                # Above average — high pressure
                competitive_pressure = 0.6 + (ratio - 1.10) / 0.15 * 0.3
            else:
                # Way above — max pressure
                competitive_pressure = 1.0

        return {
            "status": "success",
            "snapshot": {
                "avg_competitor_price": round(avg_price, 2),
                "min_competitor_price": round(min_price, 2),
                "max_competitor_price": round(max_price, 2),
                "competitor_count": competitor_count,
                "our_position": our_position,
                "price_gap_pct": round(price_gap_pct, 2),
                "competitive_pressure": round(competitive_pressure, 3),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "snapshot": {},
            "error": f"Competition monitoring failed: {exc}",
        }


def _pct_diff(our_price: float, reference: float) -> float:
    """Calculate percentage difference from reference.

    Positive = we are above reference, negative = below.
    """
    if reference <= 0:
        return 0.0
    return round((our_price - reference) / reference * 100, 2)
