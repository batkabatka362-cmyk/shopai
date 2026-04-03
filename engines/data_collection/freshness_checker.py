"""Data Collection Engine — freshness checker.

Checks data freshness per source by analyzing record timestamps.
Flags stale sources and computes freshness scores.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# ---------------------------------------------------------------------------
# Freshness thresholds
# ---------------------------------------------------------------------------

_STALE_THRESHOLD_HOURS = 24.0
_WARN_THRESHOLD_HOURS = 12.0


def check_freshness(
    fetched_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check data freshness for all fetched sources.

    Args:
        fetched_sources: List of FetchedSourceData dicts.

    Returns:
        Structured dict with freshness reports per source.
    """
    try:
        sources = copy.deepcopy(fetched_sources)
        reports: dict[str, dict[str, Any]] = {}
        stale_count = 0

        now_ts = time.time()

        for source_data in sources:
            source_name = source_data.get("source", "unknown")
            records = source_data.get("records", [])

            latest_ts = _find_latest_timestamp(records)
            if latest_ts:
                age_hours = round((now_ts - latest_ts) / 3600.0, 2)
            else:
                # No records — treat as maximally stale
                age_hours = _STALE_THRESHOLD_HOURS * 2

            is_stale = age_hours > _STALE_THRESHOLD_HOURS

            # Freshness score: 1.0 = perfectly fresh, 0.0 = very stale
            if age_hours <= 0:
                freshness_score = 1.0
            elif age_hours >= _STALE_THRESHOLD_HOURS * 2:
                freshness_score = 0.0
            else:
                freshness_score = round(
                    max(0.0, 1.0 - (age_hours / (_STALE_THRESHOLD_HOURS * 2))),
                    3,
                )

            if is_stale:
                stale_count += 1

            latest_str = (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(latest_ts))
                if latest_ts else "unknown"
            )

            reports[source_name] = {
                "source": source_name,
                "latest_record_ts": latest_str,
                "age_hours": age_hours,
                "is_stale": is_stale,
                "freshness_score": freshness_score,
            }

        return {
            "status": "success",
            "reports": reports,
            "stale_count": stale_count,
            "total_sources": len(reports),
        }
    except Exception as exc:
        return {
            "status": "error",
            "reports": {},
            "error": f"Freshness check failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_latest_timestamp(records: list[dict[str, Any]]) -> float | None:
    """Find the latest timestamp across all records."""
    latest: float | None = None

    for record in records:
        ts_str = (
            record.get("timestamp")
            or record.get("created_at")
            or record.get("updated_at")
        )
        if not ts_str:
            continue

        try:
            ts = _parse_timestamp(str(ts_str))
            if ts is not None and (latest is None or ts > latest):
                latest = ts
        except Exception:
            continue

    return latest


def _parse_timestamp(ts_str: str) -> float | None:
    """Parse a timestamp string to epoch float."""
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return time.mktime(time.strptime(ts_str, fmt))
        except ValueError:
            continue
    return None
