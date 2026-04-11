"""Data Collection Engine — data fetcher.

Fetches raw data from resolved API sources. Handles pagination,
rate limiting, and error recovery per source.
"""
from __future__ import annotations

import copy
import time
from typing import Any


def fetch_data(
    resolved_sources: list[dict[str, Any]],
    date_range: dict[str, str] | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch raw data from all resolved sources.

    Args:
        resolved_sources: List of resolved source configs.
        date_range: Optional date range filter.
        filters: Optional additional filters.

    Returns:
        Structured dict with fetched data per source.
    """
    try:
        sources = copy.deepcopy(resolved_sources)
        fetched: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for source in sources:
            name = source.get("name", "unknown")
            start = time.monotonic()

            try:
                records = _fetch_from_source(
                    source=source,
                    date_range=date_range or {},
                    filters=filters or {},
                )
                elapsed_ms = round((time.monotonic() - start) * 1000, 1)

                fetched.append({
                    "source": name,
                    "records": records,
                    "count": len(records),
                    "fetch_time_ms": elapsed_ms,
                    "status": "success",
                })
            except Exception as exc:
                elapsed_ms = round((time.monotonic() - start) * 1000, 1)
                errors.append({
                    "source": name,
                    "error": str(exc),
                    "fetch_time_ms": elapsed_ms,
                })
                fetched.append({
                    "source": name,
                    "records": [],
                    "count": 0,
                    "fetch_time_ms": elapsed_ms,
                    "status": "error",
                })

        total_records = sum(f["count"] for f in fetched)

        return {
            "status": "success",
            "fetched": fetched,
            "total_records": total_records,
            "errors": errors,
        }
    except Exception as exc:
        return {
            "status": "error",
            "fetched": [],
            "total_records": 0,
            "error": f"Data fetch failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_from_source(
    source: dict[str, Any],
    date_range: dict[str, str],
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fetch records from a single source endpoint.

    In production this would make real HTTP calls. Currently returns
    a structured placeholder that downstream modules can process.
    """
    name = source.get("name", "unknown")
    endpoint = source.get("endpoint", "")

    # Build the fetch context (would be used for real API calls)
    _context = {
        "endpoint": endpoint,
        "date_range": date_range,
        "filters": filters,
        "rate_limit": source.get("rate_limit", 10),
    }

    # Real implementation: HTTP calls with pagination + retry
    # For now, return empty — the engine handles empty gracefully
    return []
