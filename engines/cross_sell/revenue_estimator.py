"""Cross-Sell Engine — revenue estimator.

Estimates the revenue impact of each cross-sell recommendation:
  - Conversion probability (will the customer add this?)
  - AOV increase (how much does this raise the order value?)
  - Margin on the cross-sell item

Model note: no model usage — deterministic estimation from affinity scores
and pricing data.
"""
from __future__ import annotations

import copy
import math
from typing import Any


# ---------------------------------------------------------------------------
# Conversion probability parameters
# ---------------------------------------------------------------------------

_BASE_CONVERSION = 0.08  # 8% base cross-sell conversion rate
_MAX_CONVERSION = 0.45   # cap at 45%


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def estimate_revenue(
    scored_products: list[dict[str, Any]],
    bundles: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Estimate revenue impact for each scored cross-sell candidate.

    Args:
        scored_products: AffinityScore list from affinity_scorer.
        bundles: Bundle list from bundle_builder.
        analysis: PurchaseAnalysis from purchase_analyzer.

    Returns:
        Structured dict with per-product revenue estimates and aggregates.
    """
    try:
        safe_products = copy.deepcopy(scored_products)
        safe_bundles = copy.deepcopy(bundles)
        safe_analysis = copy.deepcopy(analysis)

        total_cart_value = safe_analysis.get("total_cart_value", 0)
        timing = safe_analysis.get("timing_signals", {})
        is_repeat = timing.get("repeat_category_buyer", False)
        past_count = timing.get("past_purchase_count", 0)

        estimates: list[dict[str, Any]] = []

        for product in safe_products:
            pid = product.get("product_id", "")
            price = float(product.get("price", 0))
            margin = float(product.get("margin", 0))
            affinity = float(product.get("total_affinity", 0))

            # --- Conversion probability ---
            conversion = _estimate_conversion(
                affinity=affinity,
                price=price,
                total_cart_value=total_cart_value,
                is_repeat_buyer=is_repeat,
                past_purchase_count=past_count,
                complement_type=product.get("complement_type", ""),
            )

            # --- Expected revenue ---
            expected_revenue = round(price * conversion, 2)

            # --- AOV increase ---
            aov_increase = round(price * conversion, 2)

            # --- Margin on item ---
            margin_on_item = round(price * margin * conversion, 2)

            # --- Factors explaining the estimate ---
            factors = _build_factors(
                affinity, conversion, price, total_cart_value,
                is_repeat, product.get("complement_type", ""),
            )

            estimates.append({
                "product_id": pid,
                "conversion_probability": round(conversion, 4),
                "expected_revenue": expected_revenue,
                "aov_increase": aov_increase,
                "margin_on_item": margin_on_item,
                "factors": factors,
            })

        # Aggregate AOV increase (sum of expected individual increases)
        total_aov_increase = round(
            sum(e["aov_increase"] for e in estimates), 2
        )
        total_expected_revenue = round(
            sum(e["expected_revenue"] for e in estimates), 2
        )

        # Bundle revenue estimates
        bundle_estimates: list[dict[str, Any]] = []
        for bundle in safe_bundles:
            bundle_price = float(bundle.get("bundle_price", 0))
            discount = float(bundle.get("discount_percent", 0))
            # Bundles have higher conversion due to perceived value
            bundle_conversion = min(
                _BASE_CONVERSION * 1.5 + discount * 0.005,
                _MAX_CONVERSION,
            )
            bundle_estimates.append({
                "bundle_id": bundle.get("bundle_id", ""),
                "conversion_probability": round(bundle_conversion, 4),
                "expected_revenue": round(bundle_price * bundle_conversion, 2),
            })

        return {
            "status": "success",
            "estimates": estimates,
            "bundle_estimates": bundle_estimates,
            "aggregate": {
                "total_expected_revenue": total_expected_revenue,
                "total_aov_increase": total_aov_increase,
                "products_evaluated": len(estimates),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "estimates": [],
            "bundle_estimates": [],
            "aggregate": {},
            "error": f"Revenue estimation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _estimate_conversion(
    *,
    affinity: float,
    price: float,
    total_cart_value: float,
    is_repeat_buyer: bool,
    past_purchase_count: int,
    complement_type: str,
) -> float:
    """Estimate conversion probability for a single cross-sell item."""
    conversion = _BASE_CONVERSION

    # Affinity is the strongest predictor
    conversion += affinity * 0.25

    # Price sensitivity: cheaper items relative to cart convert better
    if total_cart_value > 0 and price > 0:
        price_ratio = price / total_cart_value
        if price_ratio <= 0.15:
            conversion += 0.08  # impulse add-on territory
        elif price_ratio <= 0.30:
            conversion += 0.04
        elif price_ratio > 0.60:
            conversion -= 0.04  # expensive cross-sells convert poorly

    # Repeat buyer bonus
    if is_repeat_buyer:
        conversion += 0.05

    # Past purchase experience bonus (diminishing returns)
    if past_purchase_count > 0:
        experience_bonus = min(0.06, math.log1p(past_purchase_count) * 0.02)
        conversion += experience_bonus

    # Complement type bonus
    type_bonuses = {
        "accessory": 0.06,      # accessories convert well
        "care_product": 0.04,   # care products are rational adds
        "companion": 0.03,
        "upgrade": 0.02,
    }
    conversion += type_bonuses.get(complement_type, 0.01)

    return min(max(conversion, 0.01), _MAX_CONVERSION)


def _build_factors(
    affinity: float,
    conversion: float,
    price: float,
    total_cart_value: float,
    is_repeat: bool,
    complement_type: str,
) -> list[str]:
    """Build human-readable factor list for the estimate."""
    factors: list[str] = []

    if affinity >= 0.7:
        factors.append("High product affinity with cart items")
    elif affinity >= 0.4:
        factors.append("Moderate product affinity with cart items")
    else:
        factors.append("Low product affinity — exploratory suggestion")

    if total_cart_value > 0 and price > 0:
        ratio = price / total_cart_value
        if ratio <= 0.15:
            factors.append("Impulse add-on price point")
        elif ratio <= 0.30:
            factors.append("Accessible price relative to cart")
        elif ratio > 0.60:
            factors.append("Higher price point may reduce conversion")

    if is_repeat:
        factors.append("Repeat buyer in this category — higher trust")

    if complement_type == "accessory":
        factors.append("Accessory type — high cross-sell fit")
    elif complement_type == "care_product":
        factors.append("Care product — practical add-on")

    return factors
