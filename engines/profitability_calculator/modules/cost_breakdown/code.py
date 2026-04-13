"""Main cost breakdown calculator.

Computes every cost component of selling a product and returns a full
breakdown with the engine contract: {status, data, meta, error}.
"""

from __future__ import annotations

from typing import Any

from .data import (
    PAYMENT_PROCESSING_RATES,
    DEFAULT_PAYMENT_PROVIDER,
    SHOPIFY_PLAN_FEES,
    DEFAULT_SHOPIFY_PLAN,
    DEFAULT_INVENTORY_TURNOVER_DAYS,
    DUTY_DE_MINIMIS_USD,
    WAREHOUSE_RATES,
    get_shipping_rate,
    get_packaging_cost,
    get_duty_rate,
    get_insurance_rate,
)


def calculate_cost_breakdown(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Calculate the full cost breakdown for selling one unit of a product.

    Args:
        input_payload: dict with keys:
            - selling_price (float): retail price in USD (required)
            - cogs (float): cost of goods / product cost (required)
            - weight_kg (float): product weight in kg (default 0.5)
            - package_size (str): tiny|small|medium|large|oversized|fragile|premium
            - monthly_order_volume (int): total orders per month (default 100)
            - monthly_ad_spend (float): total ad budget per month (default 0)
            - payment_provider (str): key from PAYMENT_PROCESSING_RATES
            - shopify_plan (str): basic|shopify|advanced|plus
            - return_rate (float): 0-1, default 0.08
            - return_shipping_cost (float): cost to ship a return (default: same as outbound)
            - is_imported (bool): subject to customs duties (default False)
            - duty_category (str): product category for duty lookup
            - international_shipping (bool): default False
            - fragile (bool): requires fragile insurance (default False)
            - cubic_feet_per_unit (float): storage volume (default 0.5)
            - inventory_turnover_days (int): days of stock on hand (default 45)
            - order_quantity (int): packaging order qty for volume discount (default 100)

    Returns:
        Engine contract dict {status, data, meta, error}.
    """
    try:
        # --- Extract and validate inputs ---
        selling_price = input_payload.get("selling_price")
        cogs = input_payload.get("cogs")

        if selling_price is None or cogs is None:
            return _error("selling_price and cogs are required fields")
        if selling_price <= 0:
            return _error("selling_price must be positive")
        if cogs < 0:
            return _error("cogs cannot be negative")

        weight_kg = input_payload.get("weight_kg", 0.5)
        package_size = input_payload.get("package_size", "medium")
        monthly_orders = input_payload.get("monthly_order_volume", 100)
        monthly_ad_spend = input_payload.get("monthly_ad_spend", 0.0)
        provider = input_payload.get("payment_provider", DEFAULT_PAYMENT_PROVIDER)
        plan = input_payload.get("shopify_plan", DEFAULT_SHOPIFY_PLAN)
        return_rate = input_payload.get("return_rate", 0.08)
        is_imported = input_payload.get("is_imported", False)
        duty_category = input_payload.get("duty_category", "general")
        international = input_payload.get("international_shipping", False)
        fragile = input_payload.get("fragile", False)
        cuft = input_payload.get("cubic_feet_per_unit", 0.5)
        turnover_days = input_payload.get("inventory_turnover_days", DEFAULT_INVENTORY_TURNOVER_DAYS)
        order_qty = input_payload.get("order_quantity", 100)

        # --- 1. COGS (product cost) ---
        cost_cogs = round(cogs, 2)

        # --- 2. Shipping to customer ---
        cost_shipping = round(get_shipping_rate(weight_kg, international), 2)

        # --- 3. Packaging cost ---
        cost_packaging = round(get_packaging_cost(package_size, order_qty), 2)

        # --- 4. Payment processing fee ---
        rates = PAYMENT_PROCESSING_RATES.get(
            provider, PAYMENT_PROCESSING_RATES[DEFAULT_PAYMENT_PROVIDER]
        )
        cost_payment = round(selling_price * rates["percent"] + rates["fixed"], 2)

        # --- 5. Shopify subscription fee allocation ---
        plan_data = SHOPIFY_PLAN_FEES.get(plan, SHOPIFY_PLAN_FEES[DEFAULT_SHOPIFY_PLAN])
        cost_shopify = round(plan_data["monthly"] / max(monthly_orders, 1), 2)

        # --- 6. Ad cost per unit (CAC) ---
        cost_ads = round(monthly_ad_spend / max(monthly_orders, 1), 2)

        # --- 7. Return/refund cost ---
        return_shipping = input_payload.get("return_shipping_cost", cost_shipping)
        # Cost = return_rate × (return shipping + restocking labor + depreciation)
        restocking_labor = WAREHOUSE_RATES["returns_processing"]
        depreciation = cogs * 0.15  # 15% value loss on returned items
        cost_returns = round(
            return_rate * (return_shipping + restocking_labor + depreciation), 2
        )

        # --- 8. Warehousing cost per unit ---
        months_in_storage = turnover_days / 30.0
        storage_cost = cuft * WAREHOUSE_RATES["storage_per_cuft_month"] * months_in_storage
        pick_pack = WAREHOUSE_RATES["pick_and_pack_base"] + WAREHOUSE_RATES["pick_and_pack_per_item"]
        receiving = WAREHOUSE_RATES["receiving_per_unit"]
        cost_warehouse = round(storage_cost + pick_pack + receiving, 2)

        # --- 9. Customs duties ---
        if is_imported and selling_price >= DUTY_DE_MINIMIS_USD:
            duty_rate = get_duty_rate(duty_category)
            cost_duties = round(cogs * duty_rate, 2)  # duty on declared cost, not retail
        elif is_imported:
            # Below de minimis but still track as zero
            cost_duties = 0.0
        else:
            cost_duties = 0.0

        # --- 10. Insurance ---
        insurance_rate = get_insurance_rate(selling_price, international, fragile)
        cost_insurance = round(selling_price * insurance_rate, 2)

        # --- Total ---
        total_cost = round(
            cost_cogs + cost_shipping + cost_packaging + cost_payment
            + cost_shopify + cost_ads + cost_returns + cost_warehouse
            + cost_duties + cost_insurance,
            2,
        )

        # --- Build breakdown with percentages ---
        categories = {
            "cogs": cost_cogs,
            "shipping_cost": cost_shipping,
            "packaging_cost": cost_packaging,
            "payment_processing_fee": cost_payment,
            "shopify_fee_allocation": cost_shopify,
            "ad_cost_per_unit": cost_ads,
            "return_refund_cost": cost_returns,
            "warehousing_cost": cost_warehouse,
            "customs_duties": cost_duties,
            "insurance": cost_insurance,
        }

        breakdown_detail: list[dict[str, Any]] = []
        biggest_driver = ("", 0.0)

        for name, amount in categories.items():
            pct_of_price = round(amount / selling_price, 4) if selling_price else 0
            breakdown_detail.append({
                "category": name,
                "amount_usd": amount,
                "percent_of_price": pct_of_price,
            })
            if amount > biggest_driver[1]:
                biggest_driver = (name, amount)

        profit_per_unit = round(selling_price - total_cost, 2)
        margin_pct = round(profit_per_unit / selling_price, 4) if selling_price else 0

        return {
            "status": "success",
            "data": {
                "selling_price": selling_price,
                "total_cost_per_unit": total_cost,
                "profit_per_unit": profit_per_unit,
                "margin_percent": margin_pct,
                "breakdown": breakdown_detail,
                "biggest_cost_driver": {
                    "category": biggest_driver[0],
                    "amount_usd": biggest_driver[1],
                    "percent_of_price": round(biggest_driver[1] / selling_price, 4),
                },
            },
            "meta": {
                "payment_provider": provider,
                "shopify_plan": plan,
                "return_rate": return_rate,
                "is_imported": is_imported,
                "international_shipping": international,
                "monthly_order_volume": monthly_orders,
            },
            "error": None,
        }

    except Exception as exc:
        return _error(f"Calculation failed: {exc}")


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {},
        "error": message,
    }
