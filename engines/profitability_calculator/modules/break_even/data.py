"""Break-even reference data — launch costs, sales velocity, and setup benchmarks.

Sources: aggregated from Shopify seller communities, Jungle Scout reports,
and e-commerce launch case studies. All figures in USD.
"""
from __future__ import annotations

from typing import Any


# Typical launch costs by product type (USD)
# These represent realistic first-launch budgets for Shopify stores.
LAUNCH_COSTS_BY_PRODUCT_TYPE = {
    "general": {
        "inventory_investment": 1500,
        "marketing_launch_budget": 500,
        "setup_costs": 300,          # Basic photography + listing
        "samples_cost": 100,
        "total_estimate": 2400,
    },
    "apparel": {
        "inventory_investment": 2000,  # Multiple sizes = more SKUs
        "marketing_launch_budget": 800,
        "setup_costs": 500,           # Model photography, lifestyle shots
        "samples_cost": 200,          # Size samples from manufacturer
        "total_estimate": 3500,
    },
    "electronics_accessories": {
        "inventory_investment": 1200,
        "marketing_launch_budget": 600,
        "setup_costs": 250,
        "samples_cost": 150,
        "total_estimate": 2200,
    },
    "health_beauty": {
        "inventory_investment": 1800,
        "marketing_launch_budget": 1000,  # Influencer samples + ads
        "setup_costs": 400,              # Professional product shots
        "samples_cost": 300,             # Testing + influencer gifting
        "total_estimate": 3500,
    },
    "home_decor": {
        "inventory_investment": 2500,    # Bulkier items, higher unit cost
        "marketing_launch_budget": 600,
        "setup_costs": 450,             # Styled photography
        "samples_cost": 150,
        "total_estimate": 3700,
    },
    "jewelry": {
        "inventory_investment": 800,     # Small, high-margin items
        "marketing_launch_budget": 700,
        "setup_costs": 350,             # Macro photography
        "samples_cost": 100,
        "total_estimate": 1950,
    },
    "pet_supplies": {
        "inventory_investment": 1500,
        "marketing_launch_budget": 600,
        "setup_costs": 300,
        "samples_cost": 150,
        "total_estimate": 2550,
    },
    "food_beverage": {
        "inventory_investment": 2000,
        "marketing_launch_budget": 800,
        "setup_costs": 350,
        "samples_cost": 400,            # FDA compliance testing + tasting samples
        "total_estimate": 3550,
    },
    "premium": {
        "inventory_investment": 4000,
        "marketing_launch_budget": 1500,
        "setup_costs": 800,             # Professional studio, video
        "samples_cost": 500,
        "total_estimate": 6800,
    },
}


# Average daily sales velocity by category for NEW Shopify listings
# Based on first 90 days — new listings start slow and ramp up.
# Units per day, not revenue.
DAILY_SALES_VELOCITY_BY_CATEGORY = {
    "electronics": {
        "new_listing": 1.0,    # Day 1-30 average
        "month_2": 2.5,
        "month_3": 4.0,
        "established": 6.0,   # After 6+ months with reviews
    },
    "clothing": {
        "new_listing": 0.8,
        "month_2": 2.0,
        "month_3": 3.5,
        "established": 5.0,
    },
    "health_beauty": {
        "new_listing": 1.5,    # Higher impulse buying
        "month_2": 3.0,
        "month_3": 5.0,
        "established": 8.0,
    },
    "home_garden": {
        "new_listing": 0.7,
        "month_2": 1.5,
        "month_3": 2.5,
        "established": 4.0,
    },
    "pet_supplies": {
        "new_listing": 1.2,
        "month_2": 2.5,
        "month_3": 4.5,
        "established": 7.0,   # Strong repeat purchases
    },
    "jewelry": {
        "new_listing": 0.5,    # Slower — trust-dependent
        "month_2": 1.0,
        "month_3": 2.0,
        "established": 3.5,
    },
    "food_beverage": {
        "new_listing": 1.0,
        "month_2": 2.5,
        "month_3": 5.0,
        "established": 10.0,  # Subscription effect
    },
    "sports_outdoors": {
        "new_listing": 0.8,
        "month_2": 1.8,
        "month_3": 3.0,
        "established": 5.0,
    },
    "general": {
        "new_listing": 1.0,
        "month_2": 2.0,
        "month_3": 3.0,
        "established": 5.0,
    },
}


# Setup cost benchmarks — what sellers actually pay for launch preparation
SETUP_COST_BENCHMARKS = {
    "product_photography": {
        "diy_smartphone": {"cost": 0, "quality": "basic", "note": "Free but looks amateur"},
        "diy_lightbox": {"cost": 50, "quality": "decent", "note": "Good for small products"},
        "freelance_photographer": {"cost": 150, "quality": "good", "note": "5-10 product photos"},
        "professional_studio": {"cost": 400, "quality": "excellent", "note": "Lifestyle + white bg"},
        "video_included": {"cost": 800, "quality": "premium", "note": "Photos + product video"},
    },
    "listing_creation": {
        "self_written": {"cost": 0, "time_hours": 4, "note": "OK if you write well"},
        "copywriter_basic": {"cost": 50, "note": "Title + bullet points + description"},
        "copywriter_seo": {"cost": 150, "note": "SEO-optimized with keyword research"},
        "full_listing_service": {"cost": 300, "note": "Copy + SEO + A+ content design"},
    },
    "branding": {
        "logo_fiverr": {"cost": 25, "note": "Basic logo — fine for testing"},
        "logo_99designs": {"cost": 300, "note": "Professional logo with revisions"},
        "brand_package": {"cost": 800, "note": "Logo + colors + fonts + brand guidelines"},
    },
    "samples_shipping": {
        "china_standard": {"cost": 30, "days": 20, "note": "Sea mail — cheap but slow"},
        "china_express": {"cost": 80, "days": 7, "note": "DHL/FedEx from China"},
        "domestic": {"cost": 15, "days": 3, "note": "US supplier samples"},
    },
}


def get_launch_cost_estimate(product_type: str) -> dict[str, Any]:
    """Get estimated launch costs for a product type."""
    costs = LAUNCH_COSTS_BY_PRODUCT_TYPE.get(
        product_type, LAUNCH_COSTS_BY_PRODUCT_TYPE["general"]
    )
    return {
        "product_type": product_type,
        **costs,
        "note": "Estimates based on typical Shopify store launches. Actual costs vary.",
    }


def get_sales_velocity(category: str, stage: str = "new_listing") -> float:
    """Get expected daily sales velocity for a category and store stage."""
    velocities = DAILY_SALES_VELOCITY_BY_CATEGORY.get(
        category, DAILY_SALES_VELOCITY_BY_CATEGORY["general"]
    )
    return velocities.get(stage, velocities["new_listing"])


def estimate_ramp_timeline(category: str, target_daily_units: float) -> dict[str, Any]:
    """Estimate how long to reach a target daily sales volume."""
    velocities = DAILY_SALES_VELOCITY_BY_CATEGORY.get(
        category, DAILY_SALES_VELOCITY_BY_CATEGORY["general"]
    )

    if target_daily_units <= velocities["new_listing"]:
        return {"months_to_target": 0.5, "stage": "achievable_at_launch"}
    elif target_daily_units <= velocities["month_2"]:
        return {"months_to_target": 2, "stage": "month_2_velocity"}
    elif target_daily_units <= velocities["month_3"]:
        return {"months_to_target": 3, "stage": "month_3_velocity"}
    elif target_daily_units <= velocities["established"]:
        return {"months_to_target": 6, "stage": "established_velocity"}
    else:
        return {
            "months_to_target": 12,
            "stage": "above_benchmarks",
            "note": f"Target ({target_daily_units}/day) exceeds category benchmarks",
        }
