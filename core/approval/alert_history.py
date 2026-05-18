"""Persistent alert-firing history for engine-degradation
detection.

``core.approval.outcome_trends.compute_engine_alerts`` returns
a list of currently-degraded engines per invocation. The CLI
``shopai engine alerts`` shows them. ``daily-brief`` surfaces
them. But neither records WHEN an engine fired -- so the
question "has this engine been degraded for N days running?"
has no answer without external tracking.

This module is that tracking layer. It records each
``EngineAlert`` firing with a timestamp, surfaces "consecutive
runs" per engine, and (optionally, via env var) auto-
quarantines engines that fire repeatedly.

The persistence pattern mirrors ``core.approval.quarantine``:
single JSON file under ``data/alert_history.json``, atomic
write via temp + rename, fail-open semantics (missing /
corrupt file → empty history; the recorder is non-critical).

Public surface:

- ``AlertEvent`` — one alert firing (engine + timestamp + drop)
- ``record_alerts(alerts)`` — append events from a list of
  ``EngineAlert`` instances (from ``outcome_trends``)
- ``recent_history(since_seconds=86400*7)`` — return events
  from the last N seconds
- ``consecutive_runs_per_engine(window_seconds, bucket_seconds)``
  — for each engine, count how many bucketed time slots had
  alerts in the window. Useful for "has this engine been
  degraded N days running?"
- ``clear()`` — wipe the history (operator escape hatch)

Test-environment guard: under pytest, ``record_alerts`` short-
circuits without writing -- prevents test fixtures from
polluting the production alert history (mirrors the
``engines._writeback_recorder`` and ``engines._agi_context``
Pattern J guards).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


_DEFAULT_STATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data" / "alert_history.json"
)
_LOCK = threading.Lock()


@dataclass(frozen=True)
class AlertEvent:
    """One ``EngineAlert`` firing, persisted with timestamp."""

    engine: str
    recorded_at: float
    drop: float
    recent_score: float
    baseline_score: float


def _state_path() -> Path:
    """Same SHOPAI_DATA_DIR override as the quarantine module."""
    data_dir = os.environ.get("SHOPAI_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "alert_history.json"
    return _DEFAULT_STATE_PATH


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw_events() -> list[AlertEvent]:
    """Read the persisted event log. Fails open: missing /
    corrupt / malformed → empty list."""
    path = _state_path()
    try:
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug(
            "alert history read failed (%s); failing open: %s",
            path, exc,
        )
        return []
    if not isinstance(data, list):
        return []
    events: list[AlertEvent] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            events.append(AlertEvent(
                engine=str(entry["engine"]).strip(),
                recorded_at=float(entry["recorded_at"]),
                drop=float(entry.get("drop", 0.0) or 0.0),
                recent_score=float(
                    entry.get("recent_score", 0.0) or 0.0,
                ),
                baseline_score=float(
                    entry.get("baseline_score", 0.0) or 0.0,
                ),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug(
                "alert_history skipping malformed entry "
                "(%s): %s",
                exc, entry,
            )
    return events


def _save_events(events: list[AlertEvent]) -> None:
    """Atomic write via temp + rename. Same pattern as
    ``core.approval.quarantine.save_state``."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(e) for e in events]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        tmp.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)


def record_alerts(
    alerts: Iterable[Any],
    *,
    now: float | None = None,
) -> int:
    """Append the given alerts to persistent history.

    Args:
        alerts: Iterable of ``EngineAlert`` (or any object with
            ``.engine`` / ``.drop`` / ``.recent_score`` /
            ``.baseline_score`` attributes). Mock-friendly --
            we duck-type the fields.
        now: Override timestamp for testing. Defaults to
            ``time.time()``.

    Returns:
        Number of new events appended.

    Test-env guard: under pytest, returns 0 without writing.
    Tests that need to verify recording behaviour install an
    autouse fixture that patches ``_is_test_environment`` to
    return False.
    """
    if _is_test_environment():
        return 0

    if now is None:
        now = time.time()

    new_events: list[AlertEvent] = []
    for a in alerts:
        try:
            new_events.append(AlertEvent(
                engine=str(getattr(a, "engine", "")).strip(),
                recorded_at=float(now),
                drop=float(getattr(a, "drop", 0.0) or 0.0),
                recent_score=float(
                    getattr(a, "recent_score", 0.0) or 0.0,
                ),
                baseline_score=float(
                    getattr(a, "baseline_score", 0.0) or 0.0,
                ),
            ))
        except (TypeError, ValueError) as exc:
            logger.debug(
                "alert_history.record_alerts skipping malformed "
                "alert: %s", exc,
            )
            continue

    if not new_events:
        return 0

    # Drop empty-engine entries -- can't track them per-engine.
    new_events = [e for e in new_events if e.engine]
    if not new_events:
        return 0

    existing = _load_raw_events()
    _save_events(existing + new_events)
    return len(new_events)


def recent_history(
    since_seconds: float = 86400.0 * 7.0,
    *,
    now: float | None = None,
) -> list[AlertEvent]:
    """Events recorded within the last ``since_seconds``.

    Newest-first. Defaults to the last 7 days -- matches the
    baseline window used by ``compute_engine_alerts``.
    """
    if now is None:
        now = time.time()
    cutoff = now - max(0.0, float(since_seconds))
    events = _load_raw_events()
    fresh = [e for e in events if e.recorded_at >= cutoff]
    fresh.sort(key=lambda e: -e.recorded_at)
    return fresh


def consecutive_runs_per_engine(
    *,
    window_seconds: float = 86400.0 * 7.0,
    bucket_seconds: float = 86400.0,
    now: float | None = None,
) -> dict[str, int]:
    """For each engine that fired in the window, count how
    many discrete time buckets had alerts.

    Use case: "has loyalty fired alerts every day for the
    last 7 days?". Call with default ``window_seconds=7
    days``, ``bucket_seconds=1 day`` and check for engines
    where the returned count == 7.

    Multiple alerts within the same bucket count as ONE -- a
    daily-brief that fires twice in the same day shouldn't
    inflate the consecutive count.

    Args:
        window_seconds: How far back to look (default 7 days).
        bucket_seconds: Size of each time slot (default 1 day).
        now: Override timestamp for testing.

    Returns:
        ``{engine: bucket_count}`` for engines with at least
        one alert in the window. Engines with no recent alerts
        are absent from the dict.
    """
    if now is None:
        now = time.time()
    cutoff = now - max(0.0, float(window_seconds))
    events = _load_raw_events()

    # Per engine, set of bucket indices.
    per_engine: dict[str, set[int]] = {}
    for e in events:
        if e.recorded_at < cutoff:
            continue
        if not e.engine:
            continue
        bucket = int(e.recorded_at // float(bucket_seconds))
        per_engine.setdefault(e.engine, set()).add(bucket)

    return {engine: len(buckets) for engine, buckets in per_engine.items()}


def clear() -> None:
    """Wipe persistent alert history (operator escape hatch).

    Useful after fixing the root cause of an alert spike or
    when migrating to a different threshold scheme.
    """
    _save_events([])
