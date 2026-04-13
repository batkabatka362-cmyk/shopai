"""Dynamic Pricing Engine — impact estimator.

Estimates the revenue and margin impact of a proposed price change,
including volume sensitivity analysis.

1 file = 1 job: impact estimation only.
"""
from __future__ import annotations

import copy
import math
from typing import Any


# ---------------------------------------------------------------------------
# Price elasticity assumptions
# ---------------------------------------------------------------------------

# Default elasticity coefficient: 1% price increase -> ~1.5% volume drop
_DEFAULT_ELASTICITY = -1.5


def estimate_impact(
    adjustment: dict[str, Any],
    signals: dict[str, Any],
    elasticity: float = _DEFAULT_ELASTICITY,
) -> dict[str, Any]:
    """Estimate revenue and margin impact of a price adjustment.

    Uses a simple price-elasticity model to predict volume changes,
    then calculates resulting revenue and margin effects.

    Args:
        adjustment: PriceAdjustment dict from price_adjuster.
        signals: CollectedSignals dict with daily_sales and cogs.
        elasticity: Price elasticity of demand (negative number).

    Returns:
        Structured dict with ImpactEstimate data.
    """
    try:
        adj = copy.deepcopy(adjustment)
        sig = copy.deepcopy(signals)

        product_id = str(adj.get("product_id", "unknown"))
        current_price = float(adj.get("current_price", 0.0))
        new_price = float(adj.get("new_price", 0.0))
        change_pct = float(adj.get("change_pct", 0.0))
        daily_sales = float(sig.get("daily_sales", 0.0))
        cogs = float(sig.get("cogs", 0.0))

        if current_price <= 0 or daily_sales <= 0:
            return {
                "status": "success",
                "estimate": {
                    "product_id": product_id,
                    "current_price": current_price,
                    "new_price": new_price,
                    "change_pct": change_pct,
                    "estimated_daily_revenue_before": 0.0,
                    "estimated_daily_revenue_after": 0.0,
                    "estimated_revenue_change": 0.0,
                    "estimated_margin_before": 0.0,
                    "estimated_margin_after": 0.0,
                    "volume_sensitivity": 0.0,
                    "reason": "Insufficient data for impact estimation",
                },
            }

        # --- Volume change from price elasticity ---
        pct_change_decimal = change_pct / 100.0
        volume_change_pct = elasticity * pct_change_decimal
        new_daily_sales = daily_sales * (1.0 + volume_change_pct)
        new_daily_sales = max(new_daily_sales, 0.0)

        # --- Revenue ---
        revenue_before = current_price * daily_sales
        revenue_after = new_price * new_daily_sales
        revenue_change = revenue_after - revenue_before

        # --- Margin ---
        margin_before = (current_price - cogs) * daily_sales
        margin_after = (new_price - cogs) * new_daily_sales

        # --- Volume sensitivity ---
        # How sensitive is profit to volume changes at this price point
        if daily_sales > 0:
            volume_sensitivity = abs(volume_change_pct / pct_change_decimal) if pct_change_decimal != 0 else 0.0
        else:
            volume_sensitivity = 0.0

        # --- Build reason string ---
        direction = "increase" if change_pct > 0 else "decrease" if change_pct < 0 else "no change"
        reason_parts = [
            f"Price {direction} of {abs(change_pct):.1f}%",
        ]
        if volume_change_pct != 0:
            vol_dir = "increase" if volume_change_pct > 0 else "decrease"
            reason_parts.append(
                f"estimated volume {vol_dir} of {abs(volume_change_pct * 100):.1f}%"
            )
        if revenue_change > 0:
            reason_parts.append(
                f"projected daily revenue gain of ${revenue_change:.2f}"
            )
        elif revenue_change < 0:
            reason_parts.append(
                f"projected daily revenue loss of ${abs(revenue_change):.2f}"
            )

        reason = "; ".join(reason_parts)

        return {
            "status": "success",
            "estimate": {
                "product_id": product_id,
                "current_price": round(current_price, 2),
                "new_price": round(new_price, 2),
                "change_pct": round(change_pct, 2),
                "estimated_daily_revenue_before": round(revenue_before, 2),
                "estimated_daily_revenue_after": round(revenue_after, 2),
                "estimated_revenue_change": round(revenue_change, 2),
                "estimated_margin_before": round(margin_before, 2),
                "estimated_margin_after": round(margin_after, 2),
                "volume_sensitivity": round(volume_sensitivity, 3),
                "reason": reason,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "estimate": {},
            "error": f"Impact estimation failed: {exc}",
        }
