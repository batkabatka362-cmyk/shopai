"""Search volume demand logic — core estimation and ranking functions.

Functions:
  - estimate_demand_from_search: volume + conversion rates -> monthly purchases
  - rank_keywords_by_demand: sort keywords by estimated demand contribution
  - calculate_search_market_share: our share of total keyword search volume
"""
from __future__ import annotations

from typing import Any

from .data import KEYWORD_INTENT_WEIGHTS, get_conversion_rate, get_seasonal_multiplier, classify_intent


def estimate_demand_from_search(
    volume: int,
    conversion_rates: dict[str, float] | None = None,
    category: str = "general",
    intent: str = "commercial",
    month: int | None = None,
    avg_order_value: float = 50.0,
) -> dict[str, Any]:
    """Estimate monthly product demand from keyword search volume.

    Walks the full funnel: searches -> clicks -> visits -> carts -> purchases.
    Adjusts for keyword intent quality and seasonal factors.
    """
    rates = conversion_rates or get_conversion_rate(category)
    intent_multiplier = KEYWORD_INTENT_WEIGHTS.get(intent, 1.0)
    seasonal_factor = get_seasonal_multiplier(month) if month else 1.0

    adjusted_volume = volume * seasonal_factor
    clicks = adjusted_volume * rates.get("search_to_click", 0.11)
    visits = clicks * rates.get("click_to_visit", 0.63)
    carts = visits * rates.get("visit_to_cart", 0.08)
    base_purchases = carts * rates.get("cart_to_purchase", 0.40)
    estimated_purchases = base_purchases * intent_multiplier

    return {
        "raw_volume": volume,
        "seasonal_adjusted_volume": round(adjusted_volume),
        "seasonal_factor": seasonal_factor,
        "intent": intent,
        "intent_multiplier": intent_multiplier,
        "funnel": {
            "searches": round(adjusted_volume),
            "clicks": round(clicks),
            "visits": round(visits),
            "carts": round(carts),
            "purchases": round(estimated_purchases),
        },
        "estimated_monthly_purchases": round(estimated_purchases),
        "estimated_monthly_revenue": round(estimated_purchases * avg_order_value, 2),
        "effective_conversion_rate": round(
            estimated_purchases / max(adjusted_volume, 1) * 100, 4,
        ),
        "conversion_rates_used": rates,
    }


def rank_keywords_by_demand(
    keywords: list[dict[str, Any]],
    category: str = "general",
    avg_order_value: float = 50.0,
) -> list[dict[str, Any]]:
    """Rank keywords by estimated demand contribution (descending).

    Each keyword dict needs: {"keyword": str, "volume": int}.
    Optional: "intent" (auto-classified if missing), "month".
    """
    ranked = []
    for kw in keywords:
        keyword_text = kw.get("keyword", "")
        intent = kw.get("intent") or classify_intent(keyword_text)
        demand = estimate_demand_from_search(
            volume=kw.get("volume", 0), category=category,
            intent=intent, month=kw.get("month"), avg_order_value=avg_order_value,
        )
        ranked.append({
            "keyword": keyword_text,
            "volume": kw.get("volume", 0),
            "intent": intent,
            "estimated_purchases": demand["estimated_monthly_purchases"],
            "estimated_revenue": demand["estimated_monthly_revenue"],
            "effective_conversion_rate": demand["effective_conversion_rate"],
        })

    ranked.sort(key=lambda x: x["estimated_purchases"], reverse=True)
    for i, entry in enumerate(ranked, 1):
        entry["rank"] = i
    return ranked


def calculate_search_market_share(our_volume: int, total_volume: int) -> dict[str, Any]:
    """Calculate our share of total keyword search volume.

    Useful for competitive benchmarking — if competitor keywords dominate
    the search landscape, our addressable slice is smaller.
    """
    if total_volume <= 0:
        return {
            "our_volume": our_volume, "total_volume": total_volume,
            "share_pct": 0.0, "interpretation": "No search volume data available",
        }

    share_pct = round((our_volume / total_volume) * 100, 2)

    if share_pct >= 30:
        interpretation = (
            "Strong search presence — focus on conversion optimization "
            "over keyword expansion."
        )
    elif share_pct >= 15:
        interpretation = (
            "Solid coverage — room to grow by targeting additional "
            "long-tail keywords and content gaps."
        )
    elif share_pct >= 5:
        interpretation = (
            "Moderate coverage — significant untapped demand exists. "
            "Prioritize keyword gap analysis."
        )
    else:
        interpretation = (
            "Low search market share — most demand is captured by "
            "competitors. Major keyword discovery needed."
        )

    return {
        "our_volume": our_volume,
        "total_volume": total_volume,
        "share_pct": share_pct,
        "untapped_volume": total_volume - our_volume,
        "interpretation": interpretation,
    }
