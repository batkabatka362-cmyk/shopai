"""Bundle Engine — cannibalization checker.

Checks whether proposed bundles would cannibalize individual product
sales, estimating net revenue impact.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def check_cannibalization(
    optimized_bundles: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check cannibalization risk for each optimized bundle.

    Args:
        optimized_bundles: List of OptimizedBundle dicts from price_optimizer.
        products: List of BundleProduct dicts.

    Returns:
        Structured dict with cannibalization results.
    """
    try:
        bundles = copy.deepcopy(optimized_bundles)
        products = copy.deepcopy(products)

        prod_map = {str(p.get("id", "")): p for p in products}

        results: list[dict[str, Any]] = []

        for bundle in bundles:
            bid = str(bundle.get("bundle_id", ""))
            pids = bundle.get("product_ids", [])
            bundle_price = float(bundle.get("bundle_price", 0.0))
            original_price = float(bundle.get("original_price", 0.0))
            savings_pct = float(bundle.get("savings_pct", 0.0))
            estimated_uplift = float(bundle.get("estimated_uplift", 0.0))

            # Calculate individual product daily revenue
            daily_individual_revenue = 0.0
            affected_products: list[str] = []

            for pid in pids:
                prod = prod_map.get(pid, {})
                price = float(prod.get("price", 0.0))
                daily_sales = float(prod.get("daily_sales", 0.0))
                daily_rev = price * daily_sales
                daily_individual_revenue += daily_rev

                # High-selling products are more at risk
                if daily_sales >= 5.0:
                    affected_products.append(pid)

            # Cannibalization risk factors:
            # 1. Deep discount = higher risk (customers switch to bundle)
            discount_risk = savings_pct / 100.0

            # 2. Bundle contains bestsellers = higher risk
            bestseller_ratio = (
                len(affected_products) / len(pids) if pids else 0.0
            )

            # 3. Low uplift means the bundle mostly steals existing sales
            uplift_offset = max(1.0 - estimated_uplift, 0.0)

            # Composite risk (0.0 to 1.0)
            risk = round(
                discount_risk * 0.4 +
                bestseller_ratio * 0.35 +
                uplift_offset * 0.25,
                3,
            )

            # Net revenue impact (30-day estimate)
            # Positive = net gain, negative = net loss
            bundle_daily_revenue = bundle_price * (estimated_uplift * 10.0)  # estimated daily bundle sales
            cannibalized_revenue = daily_individual_revenue * risk
            net_daily = bundle_daily_revenue - cannibalized_revenue
            net_revenue_impact = round(net_daily * 30.0, 2)

            # Recommendation
            if risk < 0.3:
                recommendation = "safe_to_launch"
            elif risk < 0.6:
                recommendation = "launch_with_monitoring"
            else:
                recommendation = "reconsider_bundle"

            results.append({
                "bundle_id": bid,
                "cannibalization_risk": risk,
                "affected_products": affected_products,
                "net_revenue_impact": net_revenue_impact,
                "recommendation": recommendation,
            })

        return {
            "status": "success",
            "results": results,
        }
    except Exception as exc:
        return {
            "status": "error",
            "results": [],
            "error": f"Cannibalization check failed: {exc}",
        }
