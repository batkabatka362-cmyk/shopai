"""Competitor Analysis Engine — strategy detector.

Detect competitor strategies from observable signals.
"""
from __future__ import annotations

import copy
from typing import Any


def detect_strategies(
    **kwargs: Any,
) -> dict[str, Any]:
    """Detect competitor strategies.

    Args:
        **kwargs: Must include 'competitors' list and 'tracked_products' list.

    Returns:
        Structured dict with detected strategies.
    """
    try:
        competitors = copy.deepcopy(kwargs.get("competitors", []))
        tracked_products = kwargs.get("tracked_products", [])

        strategies: list[dict[str, Any]] = []

        for comp in competitors:
            cid = str(comp.get("id", "unknown"))
            name = comp.get("name", cid)
            signals: list[str] = []
            strategy_type = "maintain"

            # Detect pricing strategy
            recent_price_changes = comp.get("recent_price_changes", [])
            if recent_price_changes:
                drops = sum(1 for p in recent_price_changes if p.get("direction") == "down")
                raises = sum(1 for p in recent_price_changes if p.get("direction") == "up")
                if drops > raises:
                    signals.append("Aggressive price cutting")
                    strategy_type = "aggressive_pricing"
                elif raises > drops:
                    signals.append("Premium pricing strategy")
                    strategy_type = "premium_positioning"

            # Detect product expansion
            new_products = comp.get("new_products_30d", 0)
            if new_products > 5:
                signals.append("Rapid product expansion")
                strategy_type = "expansion"
            elif new_products > 0:
                signals.append("Moderate product additions")

            # Detect marketing intensity
            ad_spend_change = float(comp.get("ad_spend_change_pct", 0))
            if ad_spend_change > 20:
                signals.append("Increasing marketing spend")
            elif ad_spend_change < -20:
                signals.append("Reducing marketing — possible retreat")

            strategies.append({
                "competitor_id": cid,
                "name": name,
                "strategy_type": strategy_type,
                "signals": signals if signals else ["No clear strategy signals detected"],
            })

        return {
            "status": "success",
            "result": {"strategies": strategies},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Strategy detection failed: {exc}"}
