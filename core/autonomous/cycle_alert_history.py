"""Persistent log of cycle-alert firings.

``core.autonomous.cycle_alerts.compute_cycle_alerts``
inspects current state and returns alerts NOW. This module
captures HISTORICAL firings so the operator can answer:

  - "Has low_advance_rate been firing for multiple days?"
  - "How often did substrate_shrinking trigger last week?"
  - "Did the cycle stabilise after I raised the threshold?"

A single alert is a flare; alerts firing on consecutive days
are a real pattern. Same shape as
``core.approval.alert_history`` (engine-level) but scoped to
the cycle layer.

Pattern J test guard short-circuits writes. JSON file,
atomic temp+rename, fail-open reads, 1000-event cap.

Public surface
--------------
- ``CycleAlertEvent`` -- dataclass: kind, detail, metrics,
  recorded_at.
- ``record_alerts(alerts)`` -- append a batch.
- ``recent_history(since_seconds)`` -- newest-first window.
- ``consecutive_days_per_kind(window_seconds,
  bucket_seconds)`` -- per-kind bucket count.
- ``clear()`` -- operator escape hatch.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


_HISTORY_PATH = Path(
    os.environ.get(
        "SHOPAI_CYCLE_ALERT_HISTORY_PATH",
        "data/cycle_alert_history.json",
    )
)

_MAX_EVENTS = 1000


@dataclass
class CycleAlertEvent:
    """One alert firing. ``metrics`` carries the
    structured snapshot that fired the alert (whatever the
    detector captured)."""

    kind: str
    detail: str
    recorded_at: float
    metrics: dict[str, Any] = field(default_factory=dict)


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
            "cycle_alert_history: load failed (%s)", exc,
        )
        return []


def _atomic_write(entries: list[dict[str, Any]]) -> None:
    try:
        _HISTORY_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "cycle_alert_history: mkdir failed (%s)",
            exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".cycle_alert_hist_",
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
            except OSError as cleanup_exc:
                logger.debug(
                    "temp cleanup failed: %s", cleanup_exc,
                )
            raise
    except OSError as exc:
        logger.debug(
            "cycle_alert_history: write failed (%s)", exc,
        )


def record_alerts(alerts: Iterable[Any]) -> bool:
    """Append a batch of alert firings to history.

    Accepts both ``CycleAlert`` (from ``cycle_alerts``) and
    raw dict form to keep the recorder loose.

    Returns True on write, False on test-env / I/O error.
    """
    if _is_test_environment():
        return False
    rows: list[dict[str, Any]] = []
    now = time.time()
    for a in alerts:
        if hasattr(a, "kind") and hasattr(a, "detail"):
            kind = str(a.kind or "")
            detail = str(a.detail or "")
            metrics = dict(
                getattr(a, "metrics", None) or {},
            )
        elif isinstance(a, dict):
            kind = str(a.get("kind", "") or "")
            detail = str(a.get("detail", "") or "")
            metrics = dict(a.get("metrics", {}) or {})
        else:
            continue
        if not kind:
            continue
        rows.append(asdict(CycleAlertEvent(
            kind=kind,
            detail=detail,
            recorded_at=now,
            metrics=metrics,
        )))
    if not rows:
        return False
    entries = _load_raw()
    entries.extend(rows)
    if len(entries) > _MAX_EVENTS:
        entries = entries[-_MAX_EVENTS:]
    _atomic_write(entries)
    return True


def recent_history(
    *,
    since_seconds: int = 86400 * 7,
    now: float | None = None,
) -> list[CycleAlertEvent]:
    """Newest-first events in the window. Reuses the
    Windows-tie-aware reverse-then-stable-sort pattern."""
    now = now if now is not None else time.time()
    cutoff = now - since_seconds
    raw = _load_raw()
    events: list[CycleAlertEvent] = []
    for r in raw:
        kind = str(r.get("kind", "") or "")
        if not kind:
            continue
        ts = float(r.get("recorded_at", 0) or 0)
        if ts < cutoff:
            continue
        events.append(CycleAlertEvent(
            kind=kind,
            detail=str(r.get("detail", "") or ""),
            recorded_at=ts,
            metrics=dict(r.get("metrics", {}) or {}),
        ))
    events.reverse()
    events.sort(key=lambda e: -e.recorded_at)
    return events


def consecutive_days_per_kind(
    *,
    window_seconds: float = 86400 * 7,
    bucket_seconds: float = 86400.0,
    now: float | None = None,
) -> dict[str, int]:
    """Count distinct day-buckets each alert kind has fired
    in over the window.

    Returns ``{kind: bucket_count}``. An alert kind firing
    once a day for 5 days returns 5. Multiple firings in
    the same bucket count as 1.

    The signal: "low_advance_rate appeared on 3 distinct
    days" is a real pattern; "low_advance_rate appeared
    5 times in one hour" might just be cron mis-config.
    """
    now = now if now is not None else time.time()
    cutoff = now - window_seconds
    raw = _load_raw()
    # Per-kind set of bucket indexes
    by_kind: dict[str, set[int]] = {}
    for r in raw:
        kind = str(r.get("kind", "") or "")
        if not kind:
            continue
        ts = float(r.get("recorded_at", 0) or 0)
        if ts < cutoff:
            continue
        bucket = int((now - ts) // bucket_seconds)
        by_kind.setdefault(kind, set()).add(bucket)
    return {k: len(v) for k, v in by_kind.items()}


def clear() -> None:
    """Operator escape hatch -- wipe the history."""
    if _is_test_environment():
        return
    if _HISTORY_PATH.exists():
        try:
            _HISTORY_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "cycle_alert_history: unlink raised: %s",
                exc,
            )


def _reset_for_tests(path: Path | None = None) -> None:
    global _HISTORY_PATH
    if path is not None:
        _HISTORY_PATH = path
