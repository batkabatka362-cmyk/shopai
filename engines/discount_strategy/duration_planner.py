"""Discount Strategy Engine — duration planner.

Plans discount duration: flash (4hr), daily (24hr), weekend (48hr),
weekly (168hr), seasonal (336hr+) — with urgency optimization.

Duration selection considers:
  - Goal urgency (clear_inventory needs fast action)
  - Inventory pressure
  - Discount depth (deeper discounts should run shorter to limit exposure)
  - Target audience (narrow targets may need longer windows)
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Duration presets
# ---------------------------------------------------------------------------

_DURATION_PRESETS: dict[str, dict[str, Any]] = {
    "flash": {
        "hours": 4,
        "label": "flash",
        "start_time": "10:00-12:00",    # mid-morning peak
        "base_urgency": 0.95,
    },
    "daily": {
        "hours": 24,
        "label": "daily",
        "start_time": "00:00-06:00",    # midnight launch for full day
        "base_urgency": 0.75,
    },
    "weekend": {
        "hours": 48,
        "label": "weekend",
        "start_time": "Friday 18:00",   # Friday evening start
        "base_urgency": 0.55,
    },
    "weekly": {
        "hours": 168,
        "label": "weekly",
        "start_time": "Monday 00:00",   # week start
        "base_urgency": 0.35,
    },
    "seasonal": {
        "hours": 336,
        "label": "seasonal",
        "start_time": "Campaign launch date",
        "base_urgency": 0.15,
    },
}

# ---------------------------------------------------------------------------
# Goal-to-duration affinity
# ---------------------------------------------------------------------------

_GOAL_DURATION_AFFINITY: dict[str, list[str]] = {
    "clear_inventory": ["daily", "weekend", "flash"],
    "boost_revenue": ["weekend", "weekly", "daily"],
    "acquire_customers": ["weekly", "weekend", "seasonal"],
    "reactivate": ["weekend", "weekly", "daily"],
}


def plan_duration(
    goal: str,
    inventory_days: int,
    sweet_spot_pct: float,
    target_audience: str,
) -> dict[str, Any]:
    """Plan the discount duration and timing.

    Args:
        goal: Business goal.
        inventory_days: Days of inventory remaining.
        sweet_spot_pct: Discount depth sweet spot.
        target_audience: Selected target audience.

    Returns:
        Structured dict with DurationPlan data.
    """
    try:
        goal_key = goal.lower() if goal else "boost_revenue"

        # --- Score each duration option ---
        scores: dict[str, float] = {}

        preference_order = _GOAL_DURATION_AFFINITY.get(
            goal_key,
            _GOAL_DURATION_AFFINITY["boost_revenue"],
        )

        for dur_key, preset in _DURATION_PRESETS.items():
            score = 0.50  # base

            # Goal preference bonus
            if dur_key in preference_order:
                rank = preference_order.index(dur_key)
                score += (len(preference_order) - rank) * 0.15

            # Inventory pressure: low inventory favors shorter durations
            if inventory_days <= 7:
                if dur_key in ("flash", "daily"):
                    score += 0.25
                elif dur_key == "weekend":
                    score += 0.10
            elif inventory_days <= 30:
                if dur_key in ("daily", "weekend"):
                    score += 0.15
            elif inventory_days > 60:
                if dur_key in ("weekly", "seasonal"):
                    score += 0.15

            # Deep discounts should run shorter (limit financial exposure)
            if sweet_spot_pct >= 0.30:
                if dur_key in ("flash", "daily"):
                    score += 0.15
                elif dur_key in ("weekly", "seasonal"):
                    score -= 0.15

            # Narrow targeting needs longer windows for reach
            if target_audience != "all":
                if dur_key in ("weekend", "weekly"):
                    score += 0.10
                elif dur_key == "flash":
                    score -= 0.10

            scores[dur_key] = round(max(score, 0.0), 3)

        # Select winner
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        selected_key = ranked[0][0]
        preset = _DURATION_PRESETS[selected_key]

        urgency_score = _compute_urgency(
            preset["base_urgency"], inventory_days, sweet_spot_pct,
        )

        rationale = (
            f"Duration '{preset['label']}' ({preset['hours']}h) selected for goal '{goal_key}'. "
            f"Inventory pressure: {inventory_days} days remaining. "
            f"Discount depth {sweet_spot_pct:.1%} "
            + ("favors shorter window to limit exposure." if sweet_spot_pct >= 0.25 else "allows longer window.")
            + f" Urgency score: {urgency_score:.2f}."
        )

        return {
            "status": "success",
            "plan": {
                "duration_hours": preset["hours"],
                "duration_label": preset["label"],
                "start_time": preset["start_time"],
                "urgency_score": round(urgency_score, 4),
                "urgency_rationale": rationale,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "plan": {},
            "error": f"Duration planning failed: {exc}",
        }


def _compute_urgency(
    base_urgency: float,
    inventory_days: int,
    depth_pct: float,
) -> float:
    """Compute final urgency score combining base, inventory, and depth."""
    # Inventory modifier
    if inventory_days <= 7:
        inv_mod = 0.20
    elif inventory_days <= 14:
        inv_mod = 0.10
    elif inventory_days <= 30:
        inv_mod = 0.0
    else:
        inv_mod = -0.10

    # Depth modifier: deeper discounts are more urgent (time-limited)
    depth_mod = depth_pct * 0.30  # 30% depth -> +0.09

    urgency = base_urgency + inv_mod + depth_mod
    return max(0.0, min(1.0, urgency))
