"""Per-cycle fleet revenue snapshot history.

The autonomous loop's outcome metric is REVENUE. Plan
history correlates per-plan revenue delta. But the LOOP's
overall ROI was never captured: did the fleet's total
revenue grow as the loop ran?

This module is that measurement. Each cycle invocation
captures fleet total revenue. The trend over cycles
answers: "is the autonomous loop actually growing
revenue?".

Pattern matches the other history modules: JSON file at
``data/cycle_revenue_history.json``, atomic temp+rename,
fail-open reads, 1000-event cap, Pattern J guard.

Public surface
--------------
- ``RevenueSnapshot`` dataclass.
- ``record_snapshot(fleet_revenue, store_count)``.
- ``recent_history(since_seconds)``.
- ``revenue_trend(window_seconds)`` -- delta + growth %.
- ``clear()``.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_HISTORY_PATH = Path(
    os.environ.get(
        "SHOPAI_CYCLE_REVENUE_HISTORY_PATH",
        "data/cycle_revenue_history.json",
    )
)

_MAX_EVENTS = 1000


@dataclass
class RevenueSnapshot:
    """One fleet-revenue snapshot at cycle start."""

    fleet_revenue: float
    store_count: int
    recorded_at: float


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw() -> list[dict[str, Any]]:
    try:
        if not _HISTORY_PATH.exists():
            return []
        with _HISTORY_PATH.open(
            "r", encoding="utf-8",
        ) as f:
            data = json.load(f)
        if isinstance(data, list):
            return [
                e for e in data if isinstance(e, dict)
            ]
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "cycle_revenue_history: load failed (%s)",
            exc,
        )
        return []


def _atomic_write(entries: list[dict[str, Any]]) -> None:
    try:
        _HISTORY_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "cycle_revenue_history: mkdir failed (%s)",
            exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".cycle_rev_hist_",
            suffix=".json",
            dir=str(_HISTORY_PATH.parent),
        )
        try:
            with os.fdopen(
                fd, "w", encoding="utf-8",
            ) as f:
                json.dump(
                    entries, f, indent=2, default=str,
                )
            os.replace(temp_path_str, _HISTORY_PATH)
        except Exception:
            try:
                os.unlink(temp_path_str)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.debug(
            "cycle_revenue_history: write failed (%s)",
            exc,
        )


def record_snapshot(
    *,
    fleet_revenue: float,
    store_count: int,
) -> bool:
    """Append a revenue snapshot. Returns True on write,
    False on test-env / invalid args."""
    if store_count < 0:
        return False
    if _is_test_environment():
        return False
    event = RevenueSnapshot(
        fleet_revenue=float(fleet_revenue),
        store_count=int(store_count),
        recorded_at=time.time(),
    )
    entries = _load_raw()
    entries.append(asdict(event))
    if len(entries) > _MAX_EVENTS:
        entries = entries[-_MAX_EVENTS:]
    _atomic_write(entries)
    return True


def recent_history(
    *,
    since_seconds: int = 86400 * 30,
    now: float | None = None,
) -> list[RevenueSnapshot]:
    """Newest-first events in the window. Reuses the
    Windows-tie-aware reverse-then-stable-sort pattern."""
    now = now if now is not None else time.time()
    cutoff = now - since_seconds
    raw = _load_raw()
    events: list[RevenueSnapshot] = []
    for r in raw:
        ts = float(r.get("recorded_at", 0) or 0)
        if ts < cutoff:
            continue
        events.append(RevenueSnapshot(
            fleet_revenue=float(
                r.get("fleet_revenue", 0) or 0,
            ),
            store_count=int(
                r.get("store_count", 0) or 0,
            ),
            recorded_at=ts,
        ))
    events.reverse()
    events.sort(key=lambda e: -e.recorded_at)
    return events


def revenue_trend(
    *,
    since_seconds: int = 86400 * 7,
    now: float | None = None,
) -> dict[str, Any]:
    """Compute revenue trend over the window.

    Returns:
      {
        "snapshots": int,
        "first_revenue": float | None,
        "last_revenue": float | None,
        "delta": float,
        "delta_pct": float,
        "first_at": float | None,
        "last_at": float | None,
      }

    Empty window -> all None / 0.
    """
    out: dict[str, Any] = {
        "snapshots": 0,
        "first_revenue": None,
        "last_revenue": None,
        "delta": 0.0,
        "delta_pct": 0.0,
        "first_at": None,
        "last_at": None,
    }
    events = recent_history(
        since_seconds=since_seconds, now=now,
    )
    if not events:
        return out
    # events are newest-first
    last = events[0]
    first = events[-1]
    out["snapshots"] = len(events)
    out["first_revenue"] = first.fleet_revenue
    out["last_revenue"] = last.fleet_revenue
    out["first_at"] = first.recorded_at
    out["last_at"] = last.recorded_at
    delta = last.fleet_revenue - first.fleet_revenue
    out["delta"] = round(delta, 2)
    if first.fleet_revenue > 0:
        out["delta_pct"] = round(
            (delta / first.fleet_revenue) * 100, 2,
        )
    elif last.fleet_revenue > 0:
        out["delta_pct"] = 100.0
    else:
        out["delta_pct"] = 0.0
    return out


def clear() -> None:
    if _is_test_environment():
        return
    if _HISTORY_PATH.exists():
        try:
            _HISTORY_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "cycle_revenue_history: unlink "
                "raised: %s", exc,
            )


def _reset_for_tests(path: Path | None = None) -> None:
    global _HISTORY_PATH
    if path is not None:
        _HISTORY_PATH = path
