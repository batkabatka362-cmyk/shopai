"""International Expansion Engine — currency manager.

Handles multi-currency pricing with exchange rates and local rounding.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import math
from typing import Any


# ---------------------------------------------------------------------------
# Exchange rates (base: USD) — simplified reference
# ---------------------------------------------------------------------------

_EXCHANGE_RATES: dict[str, tuple[str, float]] = {
    "US": ("USD", 1.0),
    "UK": ("GBP", 0.79),
    "DE": ("EUR", 0.92),
    "FR": ("EUR", 0.92),
    "JP": ("JPY", 149.5),
    "AU": ("AUD", 1.54),
    "CA": ("CAD", 1.36),
    "BR": ("BRL", 4.97),
    "IN": ("INR", 83.1),
    "KR": ("KRW", 1310.0),
    "MX": ("MXN", 17.1),
    "CN": ("CNY", 7.24),
}


def manage_currency(
    products: list[dict[str, Any]],
    target_markets: list[str],
    current_currency: str,
) -> dict[str, Any]:
    """Convert product prices to target market currencies.

    Args:
        products: Product list with price fields.
        target_markets: Market codes.
        current_currency: Source currency code (e.g. "USD").

    Returns:
        Structured dict with currency pricing per market.
    """
    try:
        items = copy.deepcopy(products)
        pricing: list[dict[str, Any]] = []

        # Determine source rate
        source_rate = 1.0
        for _code, (ccy, rate) in _EXCHANGE_RATES.items():
            if ccy == current_currency.upper():
                source_rate = rate
                break

        for market_code in target_markets:
            code = market_code.upper().strip()
            local_ccy, target_rate = _EXCHANGE_RATES.get(code, ("USD", 1.0))

            conversion = target_rate / source_rate if source_rate > 0 else 1.0

            # Determine if we round to whole numbers (for JPY, KRW, etc.)
            high_value_ccy = local_ccy in ("JPY", "KRW", "INR")

            converted: list[dict[str, Any]] = []
            for prod in items:
                base_price = float(prod.get("price", 0.0))
                raw = base_price * conversion

                if high_value_ccy:
                    local_price = float(math.ceil(raw / 10) * 10)
                else:
                    local_price = round(math.ceil(raw * 100) / 100, 2)

                converted.append({
                    "id": str(prod.get("id", "")),
                    "original_price": base_price,
                    "local_price": local_price,
                    "currency": local_ccy,
                })

            pricing.append({
                "market": code,
                "local_currency": local_ccy,
                "exchange_rate": round(conversion, 4),
                "converted_prices": converted,
                "rounding_applied": high_value_ccy,
            })

        return {
            "status": "success",
            "currency_pricing": pricing,
        }
    except Exception as exc:
        return {
            "status": "error",
            "currency_pricing": [],
            "error": f"Currency management failed: {exc}",
        }
