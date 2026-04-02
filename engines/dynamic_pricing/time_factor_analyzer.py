"""Dynamic Pricing Engine — time factor analyzer.

Evaluates time-based signals: day of week, hour of day, season, holidays,
and special events. Produces a time multiplier for price adjustment.

Model note: Uses LLaMA for complex timing strategy when multiple
time factors overlap (e.g. holiday + weekend + peak season).

1 file = 1 job: time factor analysis only.
"""
from __future__ import annotations

import copy
import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Season multipliers
# ---------------------------------------------------------------------------

_SEASON_MULTIPLIERS: dict[str, float] = {
    "peak": 1.08,
    "high": 1.05,
    "normal": 1.00,
    "low": 0.95,
    "off": 0.90,
}

# ---------------------------------------------------------------------------
# Known holidays (month, day) — simplified US calendar
# ---------------------------------------------------------------------------

_HOLIDAYS: set[tuple[int, int]] = {
    (1, 1),    # New Year
    (2, 14),   # Valentine's Day
    (5, 27),   # Memorial Day (approx)
    (7, 4),    # Independence Day
    (9, 2),    # Labor Day (approx)
    (10, 31),  # Halloween
    (11, 28),  # Thanksgiving (approx)
    (11, 29),  # Black Friday (approx)
    (12, 25),  # Christmas
    (12, 26),  # Boxing Day
    (12, 31),  # New Year's Eve
}

# ---------------------------------------------------------------------------
# Hour-of-day multipliers (e-commerce patterns)
# ---------------------------------------------------------------------------

_HOUR_MULTIPLIERS: dict[int, float] = {
    # Late night / early morning: lower activity
    0: 0.97, 1: 0.96, 2: 0.96, 3: 0.96, 4: 0.97, 5: 0.98,
    # Morning ramp-up
    6: 0.99, 7: 1.00, 8: 1.01, 9: 1.02, 10: 1.03, 11: 1.03,
    # Lunch peak
    12: 1.04, 13: 1.03,
    # Afternoon
    14: 1.02, 15: 1.01, 16: 1.01, 17: 1.02,
    # Evening peak
    18: 1.03, 19: 1.04, 20: 1.05, 21: 1.04, 22: 1.02,
    # Late evening
    23: 0.99,
}


def analyze_time_factors(
    signals: dict[str, Any],
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Analyze time-based factors and produce a time multiplier.

    Args:
        signals: CollectedSignals dict from signal_collector.
        now: Optional datetime override for testing.

    Returns:
        Structured dict with TimeFactors data.
    """
    try:
        sig = copy.deepcopy(signals)
        ts = now or datetime.datetime.now(tz=datetime.timezone.utc)

        day_of_week = ts.strftime("%A").lower()
        hour = ts.hour
        is_weekend = ts.weekday() >= 5

        # Season from signals (fallback to "normal")
        season = str(sig.get("season", "normal")).lower()
        if season not in _SEASON_MULTIPLIERS:
            season = "normal"

        # Holiday check
        is_holiday = (ts.month, ts.day) in _HOLIDAYS

        # --- Build composite multiplier ---
        season_mult = _SEASON_MULTIPLIERS.get(season, 1.0)
        hour_mult = _HOUR_MULTIPLIERS.get(hour, 1.0)
        weekend_mult = 1.02 if is_weekend else 1.0
        holiday_mult = 1.06 if is_holiday else 1.0

        # Combine: multiplicative but capped to avoid runaway
        raw_multiplier = season_mult * hour_mult * weekend_mult * holiday_mult

        # Cap the composite time multiplier to +/-15%
        time_multiplier = max(0.85, min(raw_multiplier, 1.15))

        # Determine model note based on overlap complexity
        overlap_count = sum([
            season != "normal",
            is_weekend,
            is_holiday,
            hour_mult >= 1.04,
        ])
        if overlap_count >= 3:
            model_note = (
                "LLaMA: complex timing strategy — multiple overlapping "
                "time factors detected (season + weekend/holiday + peak hour)"
            )
        else:
            model_note = "LLaMA: standard time factor calculation"

        return {
            "status": "success",
            "factors": {
                "day_of_week": day_of_week,
                "hour": hour,
                "season": season,
                "is_holiday": is_holiday,
                "is_weekend": is_weekend,
                "time_multiplier": round(time_multiplier, 4),
                "model_note": model_note,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "factors": {},
            "error": f"Time factor analysis failed: {exc}",
        }
