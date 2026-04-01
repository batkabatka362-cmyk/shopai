"""Seasonality detection — identify when products sell best and worst.

E-commerce seasonality is multi-layered:
  1. Annual events (Christmas, Black Friday, Valentine's)
  2. Monthly patterns (payday spikes, month-end dips)
  3. Weekly cycles (Sunday browsing, Tuesday purchasing)
  4. Category-specific (swimwear=summer, coats=winter, fitness=January)
  5. Weather-driven (rain→indoor products, heat→cooling products)

This module computes seasonality profiles and optimal timing windows.
"""
from __future__ import annotations

import math
import time
from typing import Any

from utils.helpers import safe_float


def compute_seasonality_profile(
    monthly_sales: list[float] | None = None,
    category: str = "",
) -> dict[str, Any]:
    """Compute seasonality profile from sales data or category benchmarks.

    Args:
        monthly_sales: 12 values (Jan-Dec) of relative sales volume.
                       If None, uses category benchmark.
        category: Product category for benchmark lookup.

    Returns:
        Profile with peak/trough months, variability index, and recommendations.
    """
    if monthly_sales and len(monthly_sales) == 12:
        data = monthly_sales
    else:
        data = _get_category_seasonality(category)

    avg = sum(data) / 12
    if avg <= 0:
        return {"status": "no_data", "category": category}

    # Normalize to index (100 = average month)
    index = [round(v / avg * 100, 1) for v in data]

    # Find peaks and troughs
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    peaks = []
    troughs = []
    for i, val in enumerate(index):
        if val >= 120:
            peaks.append({"month": month_names[i], "month_num": i + 1, "index": val})
        elif val <= 80:
            troughs.append({"month": month_names[i], "month_num": i + 1, "index": val})

    peaks.sort(key=lambda p: p["index"], reverse=True)
    troughs.sort(key=lambda t: t["index"])

    # Variability index (coefficient of variation)
    std_dev = math.sqrt(sum((v - avg) ** 2 for v in data) / 12)
    variability = round(std_dev / avg * 100, 1)

    # Seasonality classification
    if variability > 40:
        classification = "highly_seasonal"
    elif variability > 20:
        classification = "moderately_seasonal"
    elif variability > 10:
        classification = "slightly_seasonal"
    else:
        classification = "non_seasonal"

    return {
        "category": category,
        "monthly_index": dict(zip(month_names, index)),
        "peaks": peaks,
        "troughs": troughs,
        "variability_index": variability,
        "classification": classification,
        "best_month": peaks[0]["month"] if peaks else month_names[index.index(max(index))],
        "worst_month": troughs[0]["month"] if troughs else month_names[index.index(min(index))],
        "peak_to_trough_ratio": round(max(index) / max(min(index), 1), 1),
    }


def compute_event_calendar(year: int | None = None) -> list[dict[str, Any]]:
    """Generate e-commerce event calendar with prep timelines.

    Each event includes: when it happens, when to start preparing,
    what actions to take, and estimated revenue impact.
    """
    if year is None:
        year = time.localtime().tm_year

    events = [
        {
            "name": "New Year / Resolution Season",
            "date_range": f"{year}-01-01 to {year}-01-15",
            "month": 1, "day_start": 1, "day_end": 15,
            "prep_start_weeks": 3,
            "categories_boosted": ["fitness", "health_beauty", "organization", "self_improvement"],
            "revenue_lift_pct": 30,
            "actions": ["Launch fitness/health campaigns", "New year bundle deals", "Resolution-themed content"],
        },
        {
            "name": "Valentine's Day",
            "date_range": f"{year}-02-10 to {year}-02-14",
            "month": 2, "day_start": 10, "day_end": 14,
            "prep_start_weeks": 4,
            "categories_boosted": ["jewelry", "flowers", "chocolate", "personalized_gifts", "lingerie"],
            "revenue_lift_pct": 45,
            "actions": ["Gift guides", "Couples bundles", "Last-minute shipping options", "Personalization"],
        },
        {
            "name": "Mother's Day",
            "date_range": f"{year}-05-08 to {year}-05-12",
            "month": 5, "day_start": 8, "day_end": 12,
            "prep_start_weeks": 4,
            "categories_boosted": ["jewelry", "skincare", "flowers", "home_decor", "personalized_gifts"],
            "revenue_lift_pct": 35,
            "actions": ["Mom gift guides", "Free gift wrapping", "Heartfelt email campaigns"],
        },
        {
            "name": "Father's Day",
            "date_range": f"{year}-06-12 to {year}-06-16",
            "month": 6, "day_start": 12, "day_end": 16,
            "prep_start_weeks": 3,
            "categories_boosted": ["electronics", "tools", "outdoor", "grooming", "sports"],
            "revenue_lift_pct": 25,
            "actions": ["Dad gift guides", "Bundle deals", "Practical gift themes"],
        },
        {
            "name": "Back to School",
            "date_range": f"{year}-07-20 to {year}-08-31",
            "month": 8, "day_start": 1, "day_end": 31,
            "prep_start_weeks": 6,
            "categories_boosted": ["electronics", "clothing", "office_supplies", "backpacks", "dorm"],
            "revenue_lift_pct": 40,
            "actions": ["Student discounts", "Bundle deals", "Dorm essentials collections", "Parent-targeted ads"],
        },
        {
            "name": "Halloween",
            "date_range": f"{year}-10-15 to {year}-10-31",
            "month": 10, "day_start": 15, "day_end": 31,
            "prep_start_weeks": 4,
            "categories_boosted": ["costumes", "decorations", "candy", "pet_costumes", "party_supplies"],
            "revenue_lift_pct": 35,
            "actions": ["Themed collections", "Last-minute costume deals", "Pet costume marketing"],
        },
        {
            "name": "Black Friday / Cyber Week",
            "date_range": f"{year}-11-25 to {year}-12-02",
            "month": 11, "day_start": 25, "day_end": 30,
            "prep_start_weeks": 8,
            "categories_boosted": ["ALL"],
            "revenue_lift_pct": 150,
            "actions": [
                "Start email teasers 2 weeks early",
                "Prepare doorbuster deals (loss leaders)",
                "Increase ad budget 3-5x",
                "Ensure inventory covers 3x normal volume",
                "Test site load capacity",
                "Prepare cart recovery sequences",
            ],
        },
        {
            "name": "Cyber Monday",
            "date_range": f"{year}-12-01 to {year}-12-03",
            "month": 12, "day_start": 1, "day_end": 3,
            "prep_start_weeks": 8,
            "categories_boosted": ["electronics", "software", "digital_products", "subscriptions"],
            "revenue_lift_pct": 120,
            "actions": ["Digital-first deals", "Free shipping", "Flash sales every 2 hours"],
        },
        {
            "name": "Christmas / Holiday Season",
            "date_range": f"{year}-12-01 to {year}-12-25",
            "month": 12, "day_start": 1, "day_end": 25,
            "prep_start_weeks": 10,
            "categories_boosted": ["ALL"],
            "revenue_lift_pct": 100,
            "actions": [
                "Gift guides by recipient (him, her, kids, pets)",
                "Shipping deadline countdown",
                "Gift cards for late shoppers",
                "Holiday themed packaging",
                "12 days of deals campaigns",
            ],
        },
        {
            "name": "Post-Holiday Clearance",
            "date_range": f"{year}-12-26 to {year + 1}-01-10",
            "month": 12, "day_start": 26, "day_end": 31,
            "prep_start_weeks": 2,
            "categories_boosted": ["ALL"],
            "revenue_lift_pct": 40,
            "actions": ["Clearance sales (40-60% off)", "Gift card redemption campaigns", "New year upsells"],
        },
    ]

    return events


def compute_optimal_launch_window(
    category: str,
    prep_time_weeks: int = 4,
) -> dict[str, Any]:
    """When is the best time to launch a product in this category?

    Considers: seasonal peaks, event proximity, competition timing.
    """
    profile = compute_seasonality_profile(category=category)
    events = compute_event_calendar()

    if profile.get("status") == "no_data":
        return {"status": "no_data", "recommendation": "Launch anytime — no strong seasonality detected"}

    peaks = profile.get("peaks", [])
    best_month = peaks[0]["month_num"] if peaks else 1

    # Launch should be prep_time_weeks BEFORE peak
    launch_month = ((best_month - 1 - (prep_time_weeks // 4)) % 12) + 1
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    # Find relevant events near peak
    nearby_events = [
        e for e in events
        if abs(e["month"] - best_month) <= 1 or (best_month == 12 and e["month"] == 1)
    ]

    return {
        "category": category,
        "peak_month": month_names[best_month - 1],
        "recommended_launch_month": month_names[launch_month - 1],
        "prep_time_weeks": prep_time_weeks,
        "reasoning": f"Peak sales in {month_names[best_month - 1]}. "
                     f"Launch {prep_time_weeks} weeks earlier in {month_names[launch_month - 1]} "
                     f"to build momentum and reviews.",
        "nearby_events": [{"name": e["name"], "month": e["month"]} for e in nearby_events],
        "avoid_months": [t["month"] for t in profile.get("troughs", [])],
        "seasonality": profile["classification"],
    }


def _get_category_seasonality(category: str) -> list[float]:
    """Get monthly sales pattern for a category (index, Jan-Dec)."""
    from .data import CATEGORY_SEASONAL_PATTERNS
    cat = category.lower().replace(" ", "_").replace("-", "_")

    if cat in CATEGORY_SEASONAL_PATTERNS:
        return CATEGORY_SEASONAL_PATTERNS[cat]

    # Fuzzy match
    for key in CATEGORY_SEASONAL_PATTERNS:
        if cat in key or key in cat:
            return CATEGORY_SEASONAL_PATTERNS[key]

    # Default: slight Q4 bias (most e-commerce)
    return [85, 80, 90, 95, 95, 90, 85, 90, 95, 100, 130, 165]
