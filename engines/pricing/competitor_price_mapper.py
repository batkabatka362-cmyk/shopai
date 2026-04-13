"""Pricing Engine — competitor price mapper.

Maps competitor prices to compute min, max, average, median, price
distribution buckets, and determines where a proposed price sits
relative to the market.

All math is real — actual statistics, no dummy values.
"""
from __future__ import annotations

import copy
from typing import Any


def map_competitor_prices(
    market: dict[str, Any],
    reference_price: float,
) -> dict[str, Any]:
    """Map competitor prices and determine market positioning.

    Args:
        market: MarketData dict with competitor_prices, avg_market_price, etc.
        reference_price: The price to evaluate position for (e.g. cost floor).

    Returns:
        Structured dict with CompetitorPrices data.
    """
    try:
        mkt = copy.deepcopy(market)
        prices = [float(p) for p in mkt.get("competitor_prices", []) if p > 0]

        if not prices:
            return {
                "status": "success",
                "mapping": {
                    "min_price": 0.0,
                    "max_price": 0.0,
                    "avg_price": 0.0,
                    "median_price": 0.0,
                    "price_distribution": {},
                    "our_position": "unknown",
                    "competitor_count": 0,
                },
            }

        sorted_prices = sorted(prices)
        count = len(sorted_prices)
        min_price = sorted_prices[0]
        max_price = sorted_prices[-1]
        avg_price = sum(sorted_prices) / count
        median_price = _median(sorted_prices)

        # Price distribution: bucket prices into ranges
        distribution = _compute_distribution(sorted_prices)

        # Our position relative to market
        position = _determine_position(reference_price, avg_price)

        return {
            "status": "success",
            "mapping": {
                "min_price": round(min_price, 2),
                "max_price": round(max_price, 2),
                "avg_price": round(avg_price, 2),
                "median_price": round(median_price, 2),
                "price_distribution": distribution,
                "our_position": position,
                "competitor_count": count,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "mapping": {},
            "error": f"Competitor mapping failed: {exc}",
        }


def _median(sorted_prices: list[float]) -> float:
    """Compute median of a sorted list."""
    n = len(sorted_prices)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 0:
        return (sorted_prices[mid - 1] + sorted_prices[mid]) / 2.0
    return sorted_prices[mid]


def _compute_distribution(sorted_prices: list[float]) -> dict[str, int]:
    """Bucket competitor prices into labelled ranges.

    Creates 5 roughly equal-width buckets across the price range.
    """
    if not sorted_prices:
        return {}

    lo = sorted_prices[0]
    hi = sorted_prices[-1]

    if hi <= lo:
        return {"single_price": len(sorted_prices)}

    bucket_width = (hi - lo) / 5.0
    distribution: dict[str, int] = {}

    for i in range(5):
        bucket_lo = lo + i * bucket_width
        bucket_hi = lo + (i + 1) * bucket_width
        label = f"${bucket_lo:.2f}-${bucket_hi:.2f}"
        count = sum(
            1 for p in sorted_prices
            if (bucket_lo <= p < bucket_hi) or (i == 4 and p == bucket_hi)
        )
        if count > 0:
            distribution[label] = count

    return distribution


def _determine_position(our_price: float, avg_price: float) -> str:
    """Classify our price relative to market average."""
    if avg_price <= 0:
        return "unknown"

    ratio = our_price / avg_price

    if ratio < 0.85:
        return "undercut"
    if ratio < 0.95:
        return "below_market"
    if ratio < 1.05:
        return "at_market"
    if ratio < 1.15:
        return "above_market"
    return "premium"
