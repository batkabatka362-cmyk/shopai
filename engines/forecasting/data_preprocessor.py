"""Forecasting Engine — data preprocessor.

Cleans historical time series data before analysis:
- Sorts by date
- Handles missing values via linear interpolation
- Detects outliers using the IQR method
- Replaces outliers with interpolated values
- Normalizes values for internal calculations

Pure Python — no numpy.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any


def preprocess(
    history: list[dict[str, Any]],
    granularity: str = "daily",
) -> dict[str, Any]:
    """Clean and prepare historical data for forecasting.

    Args:
        history: Raw list of {date, value} dicts.
        granularity: Time granularity — "daily", "weekly", "monthly".

    Returns:
        Structured dict with cleaned data points.
    """
    try:
        if not history:
            return {
                "status": "error",
                "cleaned": [],
                "count": 0,
                "error": "No history data provided",
            }

        raw = copy.deepcopy(history)

        # Parse and sort by date
        parsed = _parse_and_sort(raw)
        if not parsed:
            return {
                "status": "error",
                "cleaned": [],
                "count": 0,
                "error": "Could not parse any dates from history",
            }

        # Fill missing dates via interpolation
        filled = _fill_gaps(parsed, granularity)

        # Detect outliers using IQR
        values = [p["value"] for p in filled]
        q1, q3 = _quartiles(values)
        iqr = q3 - q1
        lower_fence = q1 - 1.5 * iqr
        upper_fence = q3 + 1.5 * iqr

        cleaned: list[dict[str, Any]] = []
        outlier_count = 0

        for i, point in enumerate(filled):
            val = point["value"]
            is_outlier = val < lower_fence or val > upper_fence
            is_interpolated = point.get("interpolated", False)

            if is_outlier:
                outlier_count += 1
                # Replace outlier with interpolated value from neighbors
                val = _interpolate_neighbors(filled, i)
                is_interpolated = True

            cleaned.append({
                "date": point["date"],
                "value": round(val, 4),
                "original_value": round(point["value"], 4),
                "is_interpolated": is_interpolated,
                "is_outlier": is_outlier,
            })

        return {
            "status": "success",
            "cleaned": cleaned,
            "count": len(cleaned),
            "outliers_detected": outlier_count,
            "iqr_lower_fence": round(lower_fence, 4),
            "iqr_upper_fence": round(upper_fence, 4),
        }
    except Exception as exc:
        return {
            "status": "error",
            "cleaned": [],
            "count": 0,
            "error": f"Preprocessing failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_and_sort(
    raw: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Parse date strings and sort chronologically."""
    parsed: list[dict[str, Any]] = []

    for item in raw:
        date_str = str(item.get("date", ""))
        value = item.get("value", 0.0)

        try:
            value = float(value)
        except (ValueError, TypeError):
            continue

        dt = _parse_date(date_str)
        if dt is None:
            continue

        parsed.append({
            "date": dt.strftime("%Y-%m-%d"),
            "value": value,
            "dt": dt,
        })

    parsed.sort(key=lambda p: p["dt"])
    return parsed


def _parse_date(date_str: str) -> datetime | None:
    """Try multiple date formats."""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _fill_gaps(
    points: list[dict[str, Any]],
    granularity: str,
) -> list[dict[str, Any]]:
    """Fill date gaps via linear interpolation."""
    if len(points) < 2:
        return [{"date": p["date"], "value": p["value"]} for p in points]

    delta = _granularity_delta(granularity)
    filled: list[dict[str, Any]] = []
    date_set = {p["dt"] for p in points}
    date_map = {p["dt"]: p["value"] for p in points}

    current = points[0]["dt"]
    end = points[-1]["dt"]

    while current <= end:
        if current in date_set:
            filled.append({
                "date": current.strftime("%Y-%m-%d"),
                "value": date_map[current],
                "interpolated": False,
            })
        else:
            # Find surrounding known values for interpolation
            val = _linear_interpolate_at(points, current)
            filled.append({
                "date": current.strftime("%Y-%m-%d"),
                "value": val,
                "interpolated": True,
            })
        current += delta

    return filled


def _granularity_delta(granularity: str) -> timedelta:
    """Return the timedelta for a given granularity."""
    mapping = {
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
        "monthly": timedelta(days=30),
    }
    return mapping.get(granularity, timedelta(days=1))


def _linear_interpolate_at(
    points: list[dict[str, Any]],
    target_dt: datetime,
) -> float:
    """Linearly interpolate value at target_dt from surrounding points."""
    before = None
    after = None

    for p in points:
        if p["dt"] <= target_dt:
            before = p
        if p["dt"] >= target_dt and after is None:
            after = p

    if before is None and after is not None:
        return after["value"]
    if after is None and before is not None:
        return before["value"]
    if before is None and after is None:
        return 0.0
    if before["dt"] == after["dt"]:
        return before["value"]

    total_days = (after["dt"] - before["dt"]).days
    if total_days == 0:
        return before["value"]

    elapsed_days = (target_dt - before["dt"]).days
    fraction = elapsed_days / total_days
    return before["value"] + fraction * (after["value"] - before["value"])


def _quartiles(values: list[float]) -> tuple[float, float]:
    """Compute Q1 and Q3 using linear interpolation."""
    if not values:
        return 0.0, 0.0

    s = sorted(values)

    def _percentile(data: list[float], pct: float) -> float:
        idx = pct * (len(data) - 1)
        lower = int(idx)
        upper = min(lower + 1, len(data) - 1)
        frac = idx - lower
        return data[lower] + frac * (data[upper] - data[lower])

    return _percentile(s, 0.25), _percentile(s, 0.75)


def _interpolate_neighbors(
    points: list[dict[str, Any]],
    idx: int,
) -> float:
    """Replace an outlier with the average of its non-outlier neighbors."""
    values = [p["value"] for p in points]
    q1, q3 = _quartiles(values)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    left_val = None
    for i in range(idx - 1, -1, -1):
        v = points[i]["value"]
        if lower <= v <= upper:
            left_val = v
            break

    right_val = None
    for i in range(idx + 1, len(points)):
        v = points[i]["value"]
        if lower <= v <= upper:
            right_val = v
            break

    if left_val is not None and right_val is not None:
        return (left_val + right_val) / 2.0
    if left_val is not None:
        return left_val
    if right_val is not None:
        return right_val

    # Fallback: median of all values
    s = sorted(values)
    mid = len(s) // 2
    return s[mid]
