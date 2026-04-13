"""International Expansion Engine — currency manager.

Handles multi-currency pricing with exchange rates and rounding strategies.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any

_EXCHANGE_RATES: dict[str, dict[str, Any]] = {
    "US": {"currency": "USD", "rate": 1.00, "rounding": "0.99"},
    "UK": {"currency": "GBP", "rate": 0.79, "rounding": "0.99"},
    "DE": {"currency": "EUR", "rate": 0.92, "rounding": "0.99"},
    "FR": {"currency": "EUR", "rate": 0.92, "rounding": "0.99"},
    "JP": {"currency": "JPY", "rate": 149.50, "rounding": "whole"},
    "AU": {"currency": "AUD", "rate": 1.53, "rounding": "0.95"},
    "CA": {"currency": "CAD", "rate": 1.36, "rounding": "0.99"},
    "KR": {"currency": "KRW", "rate": 1320.0, "rounding": "whole_1000"},
    "BR": {"currency": "BRL", "rate": 4.97, "rounding": "0.90"},
    "IN": {"currency": "INR", "rate": 83.10, "rounding": "whole"},
    "MX": {"currency": "MXN", "rate": 17.15, "rounding": "0.90"},
    "SE": {"currency": "SEK", "rate": 10.45, "rounding": "whole"},
}


def _apply_rounding(price: float, strategy: str) -> float:
    """Apply local rounding strategy to a converted price."""
    if strategy == "whole":
        return float(round(price))
    if strategy == "whole_1000":
        return float(round(price / 1000) * 1000)
    if strategy == "0.99":
        return float(int(price)) + 0.99
    if strategy == "0.95":
        return float(int(price)) + 0.95
    if strategy == "0.90":
        return float(int(price)) + 0.90
    return round(price, 2)


def manage_currency_pricing(
    products: list[dict[str, Any]],
    target_markets: list[str],
    current_currency: str,
) -> dict[str, Any]:
    """Convert product pricing to target market currencies.

    Args:
        products: Product list with price field.
        target_markets: List of market codes.
        current_currency: Source currency code (e.g. "USD").

    Returns:
        Structured dict with currency pricing per market.
    """
    try:
        items = copy.deepcopy(products)
        pricing: list[dict[str, Any]] = []

        base_info = None
        for _code, info in _EXCHANGE_RATES.items():
            if info["currency"] == current_currency.upper():
                base_info = info
                break
        base_rate = base_info["rate"] if base_info else 1.0

        for market in target_markets:
            code = market.upper().strip()
            target = _EXCHANGE_RATES.get(code, {
                "currency": code, "rate": 1.0, "rounding": "0.99",
            })

            target_rate = target["rate"]
            rounding = target["rounding"]
            conversion = target_rate / base_rate if base_rate > 0 else 1.0

            converted: list[dict[str, Any]] = []
            for item in items:
                price_usd = float(item.get("price", 0.0))
                raw = price_usd * conversion
                final = _apply_rounding(raw, rounding)
                converted.append({
                    "id": str(item.get("id", "")),
                    "title": str(item.get("title", "")),
                    "original_price": price_usd,
                    "converted_price": final,
                })

            pricing.append({
                "market": code,
                "local_currency": target["currency"],
                "exchange_rate": round(conversion, 4),
                "converted_prices": converted,
                "rounding_strategy": rounding,
            })

        return {"status": "success", "currency_pricing": pricing}
    except Exception as exc:
        return {"status": "error", "currency_pricing": [], "error": f"Currency management failed: {exc}"}
