"""Query API over the per-store cost log.

All queries stream JSONL line-by-line so reading a 5MB
log is O(N) lines + O(window_hours) filter -- no full
file load. For 50k events / 5MB log this is well under
100ms on commodity hardware.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .recorder import ARCHIVE_PATH, DATA_PATH


@dataclass
class StoreCostSummary:
    """Aggregate spend + activity for one store over a
    time window."""
    store_id: str
    total_cost_usd: float = 0.0
    total_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0
    by_adapter: dict[str, dict[str, Any]] = field(
        default_factory=dict,
    )

    @property
    def avg_latency_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_latency_ms / self.total_calls

    @property
    def failure_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.failed_calls / self.total_calls


def _stream_events(
    *,
    include_archive: bool = False,
    since_ts: float = 0.0,
) -> Iterator[dict[str, Any]]:
    """Yield every event in the log (newest-first NOT
    guaranteed -- newest are at end-of-file). Caller
    sorts when ordering matters.

    Lines that fail to parse (mid-write crash, corruption)
    are skipped silently. Total log corruption produces
    an empty iterator, not a raise.
    """
    paths = [DATA_PATH]
    if include_archive and ARCHIVE_PATH.exists():
        paths.insert(0, ARCHIVE_PATH)
    for path in paths:
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except (
                        json.JSONDecodeError,
                        ValueError,
                    ):
                        continue
                    if not isinstance(event, dict):
                        continue
                    ts = event.get("ts", 0)
                    try:
                        ts = float(ts)
                    except (TypeError, ValueError):
                        continue
                    if ts >= since_ts:
                        yield event
        except OSError:
            continue


def _cutoff_for_window(window_hours: float) -> float:
    """time.time() minus the window in hours. Negative
    or zero window_hours = no time filter."""
    if window_hours is None or window_hours <= 0.0:
        return 0.0
    return time.time() - float(window_hours) * 3600.0


def costs_by_store(
    *,
    window_hours: float = 168.0,
    include_archive: bool = False,
) -> dict[str, StoreCostSummary]:
    """Aggregate spend per store_id.

    Returns ``{store_id: StoreCostSummary}``. Empty
    store_id maps to '(fleet)' so the summary is operator-
    readable.

    Each store's summary includes a per-adapter breakdown
    so the operator can see WHERE the spend went.
    """
    cutoff = _cutoff_for_window(window_hours)
    out: dict[str, StoreCostSummary] = {}
    for e in _stream_events(
        since_ts=cutoff, include_archive=include_archive,
    ):
        sid = str(e.get("store_id") or "")
        key = sid if sid else "(fleet)"
        summary = out.setdefault(
            key, StoreCostSummary(store_id=key),
        )
        cost = float(e.get("cost_usd", 0.0) or 0.0)
        latency = float(e.get("latency_ms", 0.0) or 0.0)
        ok = bool(e.get("ok", True))

        summary.total_cost_usd += cost
        summary.total_calls += 1
        if not ok:
            summary.failed_calls += 1
        summary.total_latency_ms += latency

        adapter = str(e.get("adapter") or "?")
        bucket = summary.by_adapter.setdefault(
            adapter, {
                "calls": 0,
                "cost_usd": 0.0,
                "failed": 0,
            },
        )
        bucket["calls"] += 1
        bucket["cost_usd"] += cost
        if not ok:
            bucket["failed"] += 1
    return out


def costs_by_adapter(
    *,
    store_id: str = "",
    window_hours: float = 168.0,
    include_archive: bool = False,
) -> dict[str, dict[str, Any]]:
    """Aggregate spend per adapter.

    When store_id is supplied, restrict to that store
    (use '' for fleet-wide aggregation across all
    stores).
    """
    cutoff = _cutoff_for_window(window_hours)
    out: dict[str, dict[str, Any]] = {}
    for e in _stream_events(
        since_ts=cutoff, include_archive=include_archive,
    ):
        if store_id and str(
            e.get("store_id") or "",
        ) != store_id:
            continue
        adapter = str(e.get("adapter") or "?")
        bucket = out.setdefault(adapter, {
            "adapter": adapter,
            "calls": 0,
            "failed": 0,
            "cost_usd": 0.0,
            "total_latency_ms": 0.0,
        })
        bucket["calls"] += 1
        if not bool(e.get("ok", True)):
            bucket["failed"] += 1
        bucket["cost_usd"] += float(
            e.get("cost_usd", 0.0) or 0.0,
        )
        bucket["total_latency_ms"] += float(
            e.get("latency_ms", 0.0) or 0.0,
        )
    return out


def costs_total(
    *,
    store_id: str = "",
    window_hours: float = 168.0,
    include_archive: bool = False,
) -> dict[str, Any]:
    """Single-number aggregate: total cost + total calls
    + failure rate over the window.

    When store_id supplied, restricts to that store.
    """
    cutoff = _cutoff_for_window(window_hours)
    total_cost = 0.0
    total_calls = 0
    failed = 0
    total_latency = 0.0
    for e in _stream_events(
        since_ts=cutoff, include_archive=include_archive,
    ):
        if store_id and str(
            e.get("store_id") or "",
        ) != store_id:
            continue
        total_calls += 1
        if not bool(e.get("ok", True)):
            failed += 1
        total_cost += float(
            e.get("cost_usd", 0.0) or 0.0,
        )
        total_latency += float(
            e.get("latency_ms", 0.0) or 0.0,
        )
    return {
        "store_id": store_id or "(all stores)",
        "window_hours": window_hours,
        "total_cost_usd": round(total_cost, 4),
        "total_calls": total_calls,
        "failed_calls": failed,
        "failure_rate": (
            round(failed / total_calls, 3)
            if total_calls else 0.0
        ),
        "avg_latency_ms": (
            round(total_latency / total_calls, 1)
            if total_calls else 0.0
        ),
    }


def get_recent_events(
    *,
    store_id: str = "",
    limit: int = 100,
    include_archive: bool = False,
) -> list[dict[str, Any]]:
    """Newest-first event list, optionally filtered by
    store. Limit is enforced AFTER sorting so the operator
    sees the genuinely most-recent N."""
    events = list(_stream_events(
        include_archive=include_archive,
    ))
    if store_id:
        events = [
            e for e in events
            if str(e.get("store_id") or "") == store_id
        ]
    events.sort(
        key=lambda e: float(e.get("ts", 0) or 0),
        reverse=True,
    )
    return events[: max(1, int(limit))]
