"""Competitor Analysis Engine — alert builder.

Build competitive alerts from strategies, price changes, and product launches.
"""
from __future__ import annotations

import copy
from typing import Any


def build_alerts(
    **kwargs: Any,
) -> dict[str, Any]:
    """Build competitive alerts.

    Args:
        **kwargs: Must include all prior stage data.

    Returns:
        Structured dict with competitive alerts.
    """
    try:
        strat_data = kwargs.get("strategy_detector_data", {})
        price_data = kwargs.get("price_tracker_data", {})
        prod_data = kwargs.get("product_tracker_data", {})

        strategies = strat_data.get("strategies", [])
        price_changes = price_data.get("price_changes", [])
        new_products = prod_data.get("new_products", [])

        alerts: list[dict[str, Any]] = []

        # Strategy alerts
        for s in strategies:
            if s.get("strategy_type") in ("aggressive_pricing", "expansion"):
                alerts.append({
                    "type": "strategy",
                    "severity": "high",
                    "competitor": s.get("name", ""),
                    "message": f"{s.get('name', '')} detected: {s.get('strategy_type', '')}",
                    "signals": s.get("signals", []),
                })

        # Significant price drops
        for pc in price_changes:
            if pc.get("change_pct", 0) < -10:
                alerts.append({
                    "type": "price_drop",
                    "severity": "medium",
                    "competitor": pc.get("competitor_id", ""),
                    "message": f"Price dropped {abs(pc['change_pct'])}% on product {pc.get('product_id', '')}",
                    "signals": [],
                })

        # New product launches
        for np in new_products:
            alerts.append({
                "type": "new_product",
                "severity": "low",
                "competitor": np.get("competitor_name", ""),
                "message": f"New product: {np.get('product_name', '')} at ${np.get('price', 0)}",
                "signals": [],
            })

        # Sort by severity
        sev_order = {"high": 0, "medium": 1, "low": 2}
        alerts.sort(key=lambda a: sev_order.get(a.get("severity", "low"), 3))

        return {
            "status": "success",
            "result": {
                "strategies": strategies,
                "price_changes": price_changes,
                "new_products": new_products,
                "alerts": alerts,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Alert building failed: {exc}"}
