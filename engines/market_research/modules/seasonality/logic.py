"""Seasonality decision logic — timing and inventory planning.

Uses seasonality profiles to make decisions about:
  - When to increase/decrease inventory
  - When to boost/reduce ad spend
  - When to launch new products
  - When to run clearance sales
"""
from __future__ import annotations

import time
from typing import Any


def plan_seasonal_strategy(
    profile: dict[str, Any],
    current_month: int | None = None,
) -> dict[str, Any]:
    """Create a seasonal strategy based on the category's pattern.

    Returns month-by-month action plan for the next 12 months.
    """
    if current_month is None:
        current_month = time.localtime().tm_mon

    monthly_index = profile.get("monthly_index", {})
    classification = profile.get("classification", "non_seasonal")
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    plan = []
    for i in range(12):
        month_num = ((current_month - 1 + i) % 12) + 1
        month_name = month_names[month_num - 1]
        index = monthly_index.get(month_name, 100)

        actions = _month_actions(index, month_num, classification)
        plan.append({
            "month": month_name,
            "month_num": month_num,
            "months_from_now": i,
            "seasonal_index": index,
            "inventory_action": actions["inventory"],
            "marketing_action": actions["marketing"],
            "pricing_action": actions["pricing"],
            "priority": actions["priority"],
        })

    return {
        "classification": classification,
        "current_month": month_names[current_month - 1],
        "monthly_plan": plan,
        "immediate_actions": plan[0] if plan else {},
        "next_peak": _find_next_event(plan, "peak"),
        "next_trough": _find_next_event(plan, "trough"),
    }


def calculate_inventory_multiplier(
    seasonal_index: float,
    safety_buffer: float = 0.20,
) -> dict[str, Any]:
    """Calculate how much to adjust inventory for a given month.

    Args:
        seasonal_index: 100 = average. 150 = 50% above average.
        safety_buffer: Extra stock % for safety (default 20%).

    Returns:
        Inventory multiplier and reorder timing.
    """
    base_multiplier = seasonal_index / 100
    with_buffer = base_multiplier * (1 + safety_buffer)

    if seasonal_index >= 150:
        urgency = "critical"
        prep_weeks = 8
        note = "Major peak — order inventory 8 weeks ahead. Stock-out risk very high."
    elif seasonal_index >= 120:
        urgency = "high"
        prep_weeks = 6
        note = "Above-average month — increase inventory 6 weeks ahead."
    elif seasonal_index >= 90:
        urgency = "normal"
        prep_weeks = 4
        note = "Average month — maintain standard inventory levels."
    elif seasonal_index >= 70:
        urgency = "low"
        prep_weeks = 2
        note = "Below-average month — reduce orders, avoid overstock."
    else:
        urgency = "minimal"
        prep_weeks = 0
        note = "Slow month — consider clearance to free up capital."

    return {
        "seasonal_index": seasonal_index,
        "inventory_multiplier": round(with_buffer, 2),
        "urgency": urgency,
        "prep_weeks_before": prep_weeks,
        "note": note,
    }


def calculate_ad_spend_multiplier(
    seasonal_index: float,
    base_monthly_budget: float = 1000,
) -> dict[str, Any]:
    """Calculate how much to adjust ad spend for a given month.

    During peaks: increase spend (more demand to capture).
    During troughs: decrease spend (lower conversion rates).
    """
    if seasonal_index >= 150:
        multiplier = 2.5
        strategy = "aggressive"
        note = "Peak season — maximize capture. ROAS typically highest now."
    elif seasonal_index >= 120:
        multiplier = 1.5
        strategy = "increased"
        note = "Above average — increase spend to capture growing demand."
    elif seasonal_index >= 90:
        multiplier = 1.0
        strategy = "maintain"
        note = "Normal period — maintain standard spend."
    elif seasonal_index >= 70:
        multiplier = 0.7
        strategy = "reduced"
        note = "Below average — reduce spend, focus on retention."
    else:
        multiplier = 0.4
        strategy = "minimal"
        note = "Slow season — minimal spend, focus on content/SEO instead."

    return {
        "seasonal_index": seasonal_index,
        "ad_multiplier": multiplier,
        "strategy": strategy,
        "suggested_budget": round(base_monthly_budget * multiplier, 2),
        "note": note,
    }


def should_launch_now(
    profile: dict[str, Any],
    current_month: int | None = None,
) -> dict[str, Any]:
    """Is now a good time to launch a new product in this category?"""
    if current_month is None:
        current_month = time.localtime().tm_mon

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    current_name = month_names[current_month - 1]
    index = profile.get("monthly_index", {}).get(current_name, 100)

    peaks = profile.get("peaks", [])
    peak_months = [p["month_num"] for p in peaks]

    # Best to launch 2-3 months BEFORE peak (build reviews and momentum)
    months_to_peak = None
    for pm in peak_months:
        delta = (pm - current_month) % 12
        if months_to_peak is None or delta < months_to_peak:
            months_to_peak = delta

    if months_to_peak is not None and 2 <= months_to_peak <= 4:
        verdict = "ideal"
        reason = f"Peak in {months_to_peak} months — perfect time to build momentum"
    elif index >= 110:
        verdict = "good"
        reason = "Currently in high-demand period — launch benefits from existing traffic"
    elif index >= 90:
        verdict = "acceptable"
        reason = "Average period — launch is fine, but won't get seasonal boost"
    elif months_to_peak is not None and months_to_peak <= 1:
        verdict = "too_late"
        reason = "Peak is imminent — not enough time to build reviews. Wait for next cycle"
    else:
        verdict = "poor"
        reason = "Low season — delay launch to capture better demand"

    return {
        "verdict": verdict,
        "reason": reason,
        "current_month": current_name,
        "current_index": index,
        "months_to_peak": months_to_peak,
    }


def _month_actions(index: float, month_num: int, classification: str) -> dict[str, Any]:
    """Determine actions for a specific month based on seasonal index."""
    if index >= 140:
        return {
            "inventory": "Stock 2x normal. Emergency reorder plan ready.",
            "marketing": "Max ad spend. Retarget all visitors. Email blast.",
            "pricing": "Hold or increase prices — demand supports premium.",
            "priority": "peak",
        }
    if index >= 115:
        return {
            "inventory": "Stock 1.5x normal.",
            "marketing": "Increase ad spend 50%. Launch seasonal campaigns.",
            "pricing": "Maintain prices. Create bundles for higher AOV.",
            "priority": "high",
        }
    if index >= 85:
        return {
            "inventory": "Maintain normal levels.",
            "marketing": "Standard campaigns. Focus on content and SEO.",
            "pricing": "Standard pricing. Test small promotions.",
            "priority": "normal",
        }
    if index >= 65:
        return {
            "inventory": "Reduce orders 30%. Clear slow movers.",
            "marketing": "Reduce ad spend. Focus on email to existing customers.",
            "pricing": "Consider 10-15% discounts to maintain velocity.",
            "priority": "low",
        }
    return {
        "inventory": "Minimal orders. Run clearance on aging stock.",
        "marketing": "Minimal spend. Content creation for next peak.",
        "pricing": "Aggressive clearance — 30-50% off aging inventory.",
        "priority": "trough",
    }


def _find_next_event(plan: list[dict], event_type: str) -> dict[str, Any] | None:
    """Find the next peak or trough in the plan."""
    for entry in plan[1:]:  # Skip current month
        if entry["priority"] == event_type:
            return {
                "month": entry["month"],
                "months_away": entry["months_from_now"],
                "index": entry["seasonal_index"],
            }
    return None
