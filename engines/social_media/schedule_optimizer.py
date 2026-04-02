"""Social Media Engine — schedule optimizer.

Optimizes posting schedule by selecting the best time slots per platform,
applying frequency caps, and resolving cross-platform conflicts (posts
too close together).

Model note: Uses Qwen for structured schedule optimization.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Optimal time slots per platform (ranked best to worst)
# ---------------------------------------------------------------------------

_OPTIMAL_TIMES: dict[str, list[str]] = {
    "instagram": ["18:00", "21:00", "12:00", "09:00", "15:00"],
    "facebook": ["13:00", "16:00", "09:00", "11:00", "19:00"],
    "tiktok": ["19:00", "22:00", "12:00", "07:00", "15:00"],
    "pinterest": ["20:00", "14:00", "08:00", "21:00", "11:00"],
    "twitter": ["08:00", "12:00", "17:00", "09:00", "13:00"],
}

_DEFAULT_TIMES = ["09:00", "12:00", "18:00"]

_PRIORITY_MAP = {0: "high", 1: "high", 2: "medium", 3: "medium", 4: "low"}

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# ---------------------------------------------------------------------------
# Frequency caps (max posts per day per platform)
# ---------------------------------------------------------------------------

_FREQUENCY_CAPS: dict[str, int] = {
    "instagram": 2,
    "facebook": 1,
    "tiktok": 3,
    "pinterest": 5,
    "twitter": 5,
}

_DEFAULT_CAP = 2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def optimize_schedule(
    calendar_entries: list[dict[str, Any]],
    platform_analyses: list[dict[str, Any]],
    engagement_predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Optimize the posting schedule for maximum engagement.

    Args:
        calendar_entries: Entries from the content calendar builder.
        platform_analyses: Per-platform analysis data.
        engagement_predictions: Per-post engagement predictions.

    Returns:
        Structured dict with optimized schedule slots and metadata.
    """
    try:
        calendar_entries = copy.deepcopy(calendar_entries)

        slots: list[dict[str, Any]] = []
        conflicts_resolved = 0
        used_slots: dict[str, set[str]] = {}  # "day" -> set of times already used

        for i, entry in enumerate(calendar_entries):
            platform = str(entry.get("platform", "")).lower().strip()
            day = str(entry.get("day", "monday")).lower().strip()

            # Pick optimal time avoiding conflicts
            optimal_times = list(_OPTIMAL_TIMES.get(platform, _DEFAULT_TIMES))
            original_time = str(entry.get("time_slot", optimal_times[0] if optimal_times else "12:00"))

            day_key = f"{day}"
            if day_key not in used_slots:
                used_slots[day_key] = set()

            # Check frequency cap
            platform_day_key = f"{platform}_{day}"
            platform_day_count = sum(
                1 for s in slots
                if s.get("platform") == platform and s.get("day") == day
            )
            cap = _FREQUENCY_CAPS.get(platform, _DEFAULT_CAP)

            if platform_day_count >= cap:
                # Move to next available day
                day = _find_next_day(day, platform, slots, cap)
                conflicts_resolved += 1

            # Find best available time slot
            chosen_time = original_time
            slot_key = f"{day}_{chosen_time}"
            if slot_key in used_slots.get(day, set()):
                chosen_time = _find_available_time(
                    optimal_times, day, used_slots.get(day, set()),
                )
                conflicts_resolved += 1

            if day not in used_slots:
                used_slots[day] = set()
            used_slots[day].add(f"{day}_{chosen_time}")

            # Determine priority based on engagement prediction
            priority = _determine_priority(engagement_predictions, i)

            slot: dict[str, Any] = {
                "platform": platform,
                "day": day,
                "time": chosen_time,
                "priority": priority,
            }
            slots.append(slot)

        # Sort by day order then time
        slots.sort(key=lambda s: (_DAYS.index(s["day"]) if s["day"] in _DAYS else 7, s["time"]))

        frequency_caps = {p: _FREQUENCY_CAPS.get(p, _DEFAULT_CAP) for p in set(s["platform"] for s in slots)}

        return {
            "status": "success",
            "schedule": {
                "slots": slots,
                "conflicts_resolved": conflicts_resolved,
                "frequency_caps": frequency_caps,
                "model_note": "Qwen: structured schedule optimization",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "schedule": {},
            "error": f"Schedule optimization failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_next_day(
    current_day: str,
    platform: str,
    existing_slots: list[dict[str, Any]],
    cap: int,
) -> str:
    """Find the next day that hasn't hit the frequency cap for this platform."""
    current_idx = _DAYS.index(current_day) if current_day in _DAYS else 0

    for offset in range(1, 8):
        candidate = _DAYS[(current_idx + offset) % 7]
        count = sum(
            1 for s in existing_slots
            if s.get("platform") == platform and s.get("day") == candidate
        )
        if count < cap:
            return candidate

    return current_day  # fallback


def _find_available_time(
    optimal_times: list[str],
    day: str,
    used: set[str],
) -> str:
    """Find the best available time slot for a given day."""
    for t in optimal_times:
        key = f"{day}_{t}"
        if key not in used:
            return t
    # Fallback: offset from first optimal time
    return optimal_times[0] if optimal_times else "12:00"


def _determine_priority(
    predictions: list[dict[str, Any]],
    index: int,
) -> str:
    """Determine priority based on predicted engagement rate."""
    if index >= len(predictions):
        return "medium"

    rate = predictions[index].get("engagement_rate", 0.0)
    if rate >= 0.08:
        return "high"
    if rate >= 0.04:
        return "medium"
    return "low"
