"""Volume projection engine — project daily/weekly/monthly/quarterly sales volume.

Combines multiple demand signals into a unified volume projection:
  - Search demand (keyword volume -> purchase intent)
  - Conversion rate (what % of visitors actually buy)
  - Price sensitivity (how price affects volume)
  - Trend momentum (is demand growing or shrinking?)

Outputs three scenarios:
  - Pessimistic: 60% of expected (what if things go poorly)
  - Expected: most likely volume
  - Optimistic: 140% of expected (what if things go well)
"""
from __future__ import annotations

from typing import Any

from .data import (
    GROWTH_RAMP_BY_CATEGORY,
    SEASONAL_ADJUSTMENTS,
    get_growth_multiplier,
)


def project_volume(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Project sales volume from combined demand signals.

    Args:
        input_payload: {
            "search_volume_monthly": int,       # Monthly keyword search volume
            "conversion_rate": float,           # Expected conversion (0-1), e.g. 0.02
            "price": float,                     # Selling price
            "price_elasticity": float | None,   # Price sensitivity (-2.0 to 0), default -1.5
            "trend_momentum": float | None,     # Monthly growth rate, e.g. 0.05 = 5%/mo
            "category": str,                    # Product category
            "product_age_months": int | None,   # How long product has been live (0 = new)
            "target_month": int | None,         # Month of year (1-12) for seasonal adj
        }

    Returns:
        Engine contract: {status, data, meta, error}
    """
    try:
        search_volume = input_payload["search_volume_monthly"]
        conversion_rate = input_payload["conversion_rate"]
        price = input_payload["price"]
        category = input_payload.get("category", "general")
        product_age = input_payload.get("product_age_months", 0)
        target_month = input_payload.get("target_month")
        price_elasticity = input_payload.get("price_elasticity", -1.5)
        trend_momentum = input_payload.get("trend_momentum", 0.0)

        # Step 1: Base volume from search demand and conversion
        base_monthly = _base_volume_from_search(search_volume, conversion_rate)

        # Step 2: Apply price sensitivity adjustment
        price_adjusted = _apply_price_sensitivity(base_monthly, price, price_elasticity)

        # Step 3: Apply trend momentum
        trend_adjusted = _apply_trend_momentum(price_adjusted, trend_momentum)

        # Step 4: Apply growth ramp for new products
        ramp_adjusted = _apply_growth_ramp(trend_adjusted, product_age, category)

        # Step 5: Apply seasonal adjustment
        seasonal_adjusted = _apply_seasonal_adjustment(ramp_adjusted, category, target_month)

        # Step 6: Build three scenarios
        expected_monthly = max(0, round(seasonal_adjusted, 1))
        scenarios = _build_scenarios(expected_monthly)

        # Step 7: Project across time horizons
        projections = _build_time_projections(expected_monthly, scenarios)

        return {
            "status": "ok",
            "data": {
                "scenarios": scenarios,
                "projections": projections,
                "expected_monthly_volume": expected_monthly,
                "expected_monthly_revenue": round(expected_monthly * price, 2),
            },
            "meta": {
                "base_monthly_volume": round(base_monthly, 1),
                "price_adjustment_factor": round(price_adjusted / max(base_monthly, 0.1), 3),
                "trend_adjustment_factor": round(trend_adjusted / max(price_adjusted, 0.1), 3),
                "ramp_multiplier": get_growth_multiplier(category, product_age),
                "seasonal_factor": _get_seasonal_factor(category, target_month),
                "category": category,
                "product_age_months": product_age,
            },
            "error": None,
        }

    except KeyError as exc:
        return {
            "status": "error",
            "data": None,
            "meta": None,
            "error": f"Missing required field: {exc}",
        }
    except Exception as exc:
        return {
            "status": "error",
            "data": None,
            "meta": None,
            "error": f"Volume projection failed: {exc}",
        }


def _base_volume_from_search(search_volume: int, conversion_rate: float) -> float:
    """Estimate monthly unit sales from search volume and conversion rate."""
    click_through_rate = 0.35  # ~35% of searchers click a product listing
    visitors = search_volume * click_through_rate
    return visitors * conversion_rate


def _apply_price_sensitivity(base_volume: float, price: float, elasticity: float) -> float:
    """Adjust volume based on price sensitivity.

    Uses a reference price of $30 (median e-commerce product).
    Elasticity of -1.5 means: 10% price increase -> 15% volume drop.
    """
    reference_price = 30.0
    if price <= 0:
        return base_volume
    price_ratio = price / reference_price
    adjustment = price_ratio ** elasticity
    # Clamp adjustment to avoid extreme distortion
    adjustment = max(0.1, min(5.0, adjustment))
    return base_volume * adjustment


def _apply_trend_momentum(volume: float, monthly_growth_rate: float) -> float:
    """Adjust volume based on current trend momentum.

    Positive momentum boosts volume; negative reduces it.
    Capped at +/- 50% to avoid runaway projections.
    """
    clamped_rate = max(-0.50, min(0.50, monthly_growth_rate))
    return volume * (1.0 + clamped_rate)


def _apply_growth_ramp(volume: float, product_age_months: int, category: str) -> float:
    """Apply growth ramp for new products.

    Month 1 = 40% of steady state. Ramps up to 100% over time.
    """
    multiplier = get_growth_multiplier(category, product_age_months)
    return volume * multiplier


def _get_seasonal_factor(category: str, target_month: int | None) -> float:
    """Get seasonal adjustment factor."""
    if target_month is None:
        return 1.0
    cat_key = category.lower().replace(" ", "_")
    factors = SEASONAL_ADJUSTMENTS.get(cat_key, SEASONAL_ADJUSTMENTS["general"])
    month_idx = max(0, min(11, target_month - 1))
    return factors[month_idx]


def _apply_seasonal_adjustment(
    volume: float, category: str, target_month: int | None
) -> float:
    """Adjust volume for seasonality based on category and month."""
    factor = _get_seasonal_factor(category, target_month)
    return volume * factor


def _build_scenarios(expected_monthly: float) -> dict[str, Any]:
    """Build pessimistic / expected / optimistic scenarios."""
    return {
        "pessimistic": {
            "monthly_units": round(expected_monthly * 0.60, 1),
            "label": "Worst realistic case (60% of expected)",
        },
        "expected": {
            "monthly_units": expected_monthly,
            "label": "Most likely scenario",
        },
        "optimistic": {
            "monthly_units": round(expected_monthly * 1.40, 1),
            "label": "Best realistic case (140% of expected)",
        },
    }


def _build_time_projections(
    expected_monthly: float, scenarios: dict[str, Any]
) -> dict[str, Any]:
    """Project volume across daily, weekly, monthly, quarterly horizons."""
    result = {}
    for scenario_name, scenario in scenarios.items():
        monthly = scenario["monthly_units"]
        result[scenario_name] = {
            "daily": round(monthly / 30, 2),
            "weekly": round(monthly / 4.33, 1),
            "monthly": monthly,
            "quarterly": round(monthly * 3, 1),
        }
    return result
