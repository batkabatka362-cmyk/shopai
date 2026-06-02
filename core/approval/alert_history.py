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
    """One ``EngineAlert`` firing, persisted with timestamp.

    ``store_id`` is the per-store scope tag. ``None`` means the
    event was recorded fleet-wide (legacy data from before the
    per-store extension, or an alert that didn't have a
    specific store in scope). Per-store queries can filter on
    ``store_id``; queries without that filter aggregate across
    all stores.
    """

    engine: str
    recorded_at: float
    drop: float
    recent_score: float
    baseline_score: float
    store_id: str | None = None


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
            raw_store = entry.get("store_id")
            store_id = (
                str(raw_store).strip() if raw_store else None
            )
            if store_id == "":
                store_id = None
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
                store_id=store_id,
            ))
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug(
                "alert_history skipping malformed entry "
                "(%s): %s",
                exc, entry,
            )
    return events


def _save_events_unlocked(events: list[AlertEvent]) -> None:
    """W962-15: write helper that assumes the caller already
    holds ``_LOCK``. Used by ``record_alerts`` to keep the
    full read-modify-write under one lock acquisition.
    """
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(e) for e in events]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def _save_events(events: list[AlertEvent]) -> None:
    """Atomic write via temp + rename. Same pattern as
    ``core.approval.quarantine.save_state``."""
    with _LOCK:
        _save_events_unlocked(events)


def _resolve_store_id(explicit: str | None) -> str | None:
    """Order: explicit param > active_store thread-local > None.

    Returns ``None`` if no scope is available -- the event still
    gets recorded as fleet-wide (per the AlertEvent.store_id
    default).
    """
    if explicit is not None:
        return str(explicit).strip() or None
    try:
        from core.context.active_store import get_active_store_id
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "alert_history active_store import failed: %s", exc,
        )
        return None
    try:
        sid = get_active_store_id()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "alert_history active_store read raised: %s", exc,
        )
        return None
    return sid


def record_alerts(
    alerts: Iterable[Any],
    *,
    now: float | None = None,
    store_id: str | None = None,
) -> int:
    """Append the given alerts to persistent history.

    Args:
        alerts: Iterable of ``EngineAlert`` (or any object with
            ``.engine`` / ``.drop`` / ``.recent_score`` /
            ``.baseline_score`` attributes). Mock-friendly --
            we duck-type the fields.
        now: Override timestamp for testing. Defaults to
            ``time.time()``.
        store_id: Per-store scope tag. When omitted, this falls
            back to the ``active_store`` thread-local (set by
            the autonomous loop). ``None`` means fleet-wide.

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

    resolved_store = _resolve_store_id(store_id)

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
                store_id=resolved_store,
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

    # W962-15 + W962-16 bugfix: widen the lock to span
    # read-modify-write so concurrent invocations
    # (daily-brief + cycle-run firing simultaneously) don't
    # lose-update each other. Pre-fix the lock was inside
    # `_save_events` only -- another writer could load the
    # same `existing` snapshot and overwrite freshly-saved
    # rows.
    # Also: cap retained events at _MAX_ALERT_HISTORY
    # (1000, mirroring the Phase 11 convention) so the
    # JSON file doesn't grow unboundedly.
    _MAX_ALERT_HISTORY = 5000
    with _LOCK:
        existing = _load_raw_events()
        combined = existing + new_events
        if len(combined) > _MAX_ALERT_HISTORY:
            combined = combined[-_MAX_ALERT_HISTORY:]
        _save_events_unlocked(combined)
    return len(new_events)


def recent_history(
    since_seconds: float = 86400.0 * 7.0,
    *,
    now: float | None = None,
    store_id: str | None = None,
) -> list[AlertEvent]:
    """Events recorded within the last ``since_seconds``.

    Newest-first. Defaults to the last 7 days -- matches the
    baseline window used by ``compute_engine_alerts``.

    Args:
        since_seconds: Look-back window.
        now: Override for testing.
        store_id: If supplied, only return events whose
            ``store_id`` matches (None = fleet-wide events,
            otherwise the exact store). Omit for ALL events
            regardless of scope.
    """
    if now is None:
        now = time.time()
    cutoff = now - max(0.0, float(since_seconds))
    events = _load_raw_events()
    fresh = [e for e in events if e.recorded_at >= cutoff]
    if store_id is not None:
        # Strict match: explicit store filter doesn't pick up
        # fleet-wide (None) events.
        fresh = [e for e in fresh if e.store_id == store_id]
    fresh.sort(key=lambda e: -e.recorded_at)
    return fresh


def consecutive_runs_per_engine(
    *,
    window_seconds: float = 86400.0 * 7.0,
    bucket_seconds: float = 86400.0,
    now: float | None = None,
    store_id: str | None = None,
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
        store_id: Per-store filter. When supplied, ONLY events
            tagged with this store contribute. When omitted,
            aggregates ACROSS all stores (matches pre-per-store
            behaviour for backward compat).

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
        if store_id is not None and e.store_id != store_id:
            continue
        bucket = int(e.recorded_at // float(bucket_seconds))
        per_engine.setdefault(e.engine, set()).add(bucket)

    # W962-76: cap bucket count at window/bucket. Epoch-anchored
    # buckets straddling the cutoff can yield window_seconds /
    # bucket_seconds + 1 distinct buckets (e.g., a 7-day window
    # straddling the UTC-midnight of day 0 hits both day 0 AND
    # day 7 -- 8 distinct buckets). Operators expect the result
    # to align with "N consecutive days," so clamp to N.
    max_buckets = max(1, int(float(window_seconds) / float(bucket_seconds)))
    return {
        engine: min(len(buckets), max_buckets)
        for engine, buckets in per_engine.items()
    }


def consecutive_runs_per_engine_store(
    *,
    window_seconds: float = 86400.0 * 7.0,
    bucket_seconds: float = 86400.0,
    now: float | None = None,
) -> dict[tuple[str, str | None], int]:
    """Per-(engine, store_id) bucketed-run count.

    Use case: empire-AGI 'engine X has been alert-firing every
    day on store A but is healthy on store B'. The bridge can
    then quarantine just store A's enqueues for engine X.

    Returns:
        ``{(engine, store_id): bucket_count}``. ``store_id``
        can be None (fleet-wide events from before the per-
        store extension). Engines with no alerts in the window
        are absent.
    """
    if now is None:
        now = time.time()
    cutoff = now - max(0.0, float(window_seconds))
    events = _load_raw_events()

    per_pair: dict[tuple[str, str | None], set[int]] = {}
    for e in events:
        if e.recorded_at < cutoff:
            continue
        if not e.engine:
            continue
        bucket = int(e.recorded_at // float(bucket_seconds))
        per_pair.setdefault((e.engine, e.store_id), set()).add(bucket)

    # W962-76: cap at window/bucket. See note on the sibling
    # consecutive_runs_per_engine.
    max_buckets = max(1, int(float(window_seconds) / float(bucket_seconds)))
    return {
        key: min(len(buckets), max_buckets)
        for key, buckets in per_pair.items()
    }


def clear() -> None:
    """Wipe persistent alert history (operator escape hatch).

    Useful after fixing the root cause of an alert spike or
    when migrating to a different threshold scheme.
    """
    _save_events([])


def prune(
    *,
    older_than_seconds: float,
    now: float | None = None,
) -> int:
    """Drop events older than the cutoff. Returns count removed.

    Finer scalpel than ``clear()`` for ops hygiene:

      - ``clear()`` wipes everything, including the recent
        firings the bridge needs to decide whether to pause.
      - ``prune(older_than_seconds=86400*30)`` keeps the last
        30 days and drops the rest -- the file stays useful but
        doesn't grow unboundedly.

    Safe to run periodically (e.g. cron after daily-brief): the
    bridge only ever looks back ``window_days`` (default 7), so
    any data older than that is dead weight.

    Args:
        older_than_seconds: Events older than this cutoff are
            removed. Must be positive.
        now: Override timestamp for testing.

    Returns:
        Number of events removed.
    """
    if older_than_seconds <= 0:
        raise ValueError(
            "older_than_seconds must be positive",
        )
    if now is None:
        now = time.time()
    cutoff = now - float(older_than_seconds)
    events = _load_raw_events()
    kept = [e for e in events if e.recorded_at >= cutoff]
    removed = len(events) - len(kept)
    if removed > 0:
        _save_events(kept)
    return removed
