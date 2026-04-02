"""Shipping Optimization Engine — free-shipping threshold optimizer.

Finds the AOV sweet spot that maximizes profit when offering free shipping
above a threshold.  Models the trade-off between shipping cost absorption
and the incremental revenue from higher cart values.

No LLM calls — pure optimization from order distribution curves.
"""
from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Order-value distribution model
# ---------------------------------------------------------------------------
# We model order values as a log-normal distribution.  The CDF gives us the
# percentage of orders above any given threshold.  Parameters are derived
# from the supplied AOV and typical e-commerce variance.

def _lognormal_cdf(x: float, mu: float, sigma: float) -> float:
    """CDF of log-normal distribution at x."""
    if x <= 0:
        return 0.0
    return 0.5 * (1.0 + math.erf((math.log(x) - mu) / (sigma * math.sqrt(2.0))))


def _lognormal_params(mean: float, cv: float = 0.6) -> tuple[float, float]:
    """Derive mu, sigma of underlying normal from the desired mean and CV."""
    sigma2 = math.log(1.0 + cv * cv)
    sigma = math.sqrt(sigma2)
    mu = math.log(mean) - sigma2 / 2.0
    return mu, sigma


# ---------------------------------------------------------------------------
# Profit model per threshold candidate
# ---------------------------------------------------------------------------

def _evaluate_threshold(
    threshold: float,
    current_aov: float,
    avg_shipping_cost: float,
    monthly_orders: int,
    avg_margin_pct: float,
    mu: float,
    sigma: float,
) -> dict[str, Any]:
    """Evaluate profitability of a single threshold candidate.

    Returns a dict with revenue/cost projections.
    """
    # Fraction of orders that already exceed the threshold
    pct_above = 1.0 - _lognormal_cdf(threshold, mu, sigma)
    pct_above = max(0.01, min(0.99, pct_above))

    # Fraction of orders that will "stretch" to reach the threshold
    # Customers between 80-100% of threshold are likely to add items
    stretch_floor = threshold * 0.80
    pct_in_stretch = _lognormal_cdf(threshold, mu, sigma) - _lognormal_cdf(stretch_floor, mu, sigma)
    pct_in_stretch = max(0.0, pct_in_stretch)
    stretch_conversion = 0.35  # ~35% of stretch-zone customers add to cart

    pct_qualifying = pct_above + pct_in_stretch * stretch_conversion

    # Revenue impact
    # Customers who stretch spend on average (threshold - their original cart)
    avg_stretch_add = threshold - (stretch_floor + threshold) / 2.0
    incremental_revenue = pct_in_stretch * stretch_conversion * avg_stretch_add * monthly_orders

    # Cost: absorb shipping for all qualifying orders
    shipping_absorbed = pct_qualifying * monthly_orders * avg_shipping_cost

    # Margin on incremental revenue
    margin_on_incremental = incremental_revenue * avg_margin_pct

    # Net profit impact
    net_profit = margin_on_incremental - shipping_absorbed

    return {
        "threshold": round(threshold, 2),
        "pct_above": round(pct_above, 4),
        "pct_qualifying": round(pct_qualifying, 4),
        "shipping_absorbed": round(shipping_absorbed, 2),
        "incremental_revenue": round(incremental_revenue, 2),
        "margin_on_incremental": round(margin_on_incremental, 2),
        "net_profit_impact": round(net_profit, 2),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def optimize_threshold(
    avg_order_value: float,
    monthly_orders: int,
    avg_shipping_cost: float,
    avg_margin_pct: float = 0.40,
    current_strategy: str = "flat_rate",
) -> dict[str, Any]:
    """Find the optimal free-shipping threshold.

    Sweeps candidate thresholds from 1.0x to 2.5x AOV and picks the one
    that maximizes net profit impact.

    Args:
        avg_order_value: Current average order value.
        monthly_orders: Monthly order volume.
        avg_shipping_cost: Average shipping cost per order.
        avg_margin_pct: Average gross margin as a decimal.
        current_strategy: Current shipping strategy identifier.

    Returns:
        Structured dict with ThresholdResult fields.
    """
    try:
        aov = max(1.0, float(avg_order_value))
        orders = max(1, int(monthly_orders))
        ship_cost = max(0.01, float(avg_shipping_cost))
        margin = max(0.05, min(0.90, float(avg_margin_pct)))

        mu, sigma = _lognormal_params(aov)

        # Sweep thresholds
        best: dict[str, Any] | None = None
        best_profit = -math.inf

        # Test from 1.0x AOV to 2.5x AOV in $1 increments
        low = max(1.0, aov * 0.8)
        high = aov * 2.5
        step = max(1.0, (high - low) / 100.0)

        candidates: list[dict[str, Any]] = []
        t = low
        while t <= high:
            result = _evaluate_threshold(t, aov, ship_cost, orders, margin, mu, sigma)
            candidates.append(result)
            if result["net_profit_impact"] > best_profit:
                best_profit = result["net_profit_impact"]
                best = result
            t += step

        if best is None:
            best = _evaluate_threshold(aov * 1.3, aov, ship_cost, orders, margin, mu, sigma)

        # Round threshold to .99 for psychology
        raw_threshold = best["threshold"]
        rounded_threshold = math.floor(raw_threshold) + 0.99 if raw_threshold > 10 else round(raw_threshold, 2)

        # Confidence: higher when the profit curve has a clear peak
        profits = [c["net_profit_impact"] for c in candidates]
        profit_range = max(profits) - min(profits) if len(profits) > 1 else 0.0
        # Clear peak = high confidence; flat curve = low confidence
        if profit_range > 0 and best_profit > 0:
            confidence = min(0.95, 0.5 + (best_profit / (profit_range + best_profit)) * 0.45)
        elif best_profit > 0:
            confidence = 0.60
        else:
            confidence = 0.30  # free shipping isn't profitable at any threshold

        target_aov = rounded_threshold * 0.95  # customers will cluster just above

        return {
            "status": "success",
            "threshold": {
                "recommended_threshold": rounded_threshold,
                "current_aov": round(aov, 2),
                "target_aov": round(target_aov, 2),
                "orders_qualifying_pct": best["pct_qualifying"],
                "avg_shipping_cost_absorbed": round(ship_cost, 2),
                "incremental_revenue": best["incremental_revenue"],
                "net_profit_impact": best["net_profit_impact"],
                "confidence": round(confidence, 4),
            },
            "analysis": {
                "candidates_evaluated": len(candidates),
                "best_raw_threshold": raw_threshold,
                "current_strategy": current_strategy,
                "recommendation": "adopt_free_shipping_threshold" if best_profit > 0 else "keep_current_strategy",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "threshold": None,
            "analysis": None,
            "error": f"Threshold optimization failed: {exc}",
        }
