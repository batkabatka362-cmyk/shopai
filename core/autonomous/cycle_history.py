"""Autonomous-cycle invocation history.

``shopai autonomous-cycle`` runs the three-phase loop
(ADVANCE / DEFEND / MEASURE) and prints a summary. Until
now the summary was ephemeral -- gone the moment the
terminal scrolled. Operators couldn't answer:

  - How many cycles ran in the last 24 hours?
  - Did the last cycle's ADVANCE phase actually execute or
    refuse on reliability?
  - When was the last successful demote / release?
  - Has the cycle been silently failing for a week?

This module is the persistence layer. Each cycle invocation
writes a CycleEvent capturing its summary; operators can
inspect via ``shopai autonomous-cycle --history``.

Pattern J test guard short-circuits writes under pytest.
Pattern mirrors ``core.approval.alert_history`` exactly:
JSON file, atomic temp+rename, fail-open reads, 1000-event
cap.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# W962-42: span load+modify+save so concurrent record_cycle
# calls don't lose appends. _atomic_write is already atomic;
# the lock fixes the read-modify-write race.
_LOCK = threading.RLock()
from typing import Any

logger = logging.getLogger(__name__)


_HISTORY_PATH = Path(
    os.environ.get(
        "SHOPAI_CYCLE_HISTORY_PATH",
        "data/cycle_history.json",
    )
)

_MAX_EVENTS = 1000


@dataclass
class CycleEvent:
    """One ``shopai autonomous-cycle`` invocation. The
    summary dict carries the per-phase outcome counts; the
    invocation field captures CLI flags so an audit can tell
    a dry-run from an actual write."""

    recorded_at: float
    executed: bool  # whether --yes was set
    advance: dict[str, Any] = field(default_factory=dict)
    defend: dict[str, Any] = field(default_factory=dict)
    correlate: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw() -> list[dict[str, Any]]:
    """Fail-open read."""
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
            "cycle_history: load failed (%s) -- "
            "returning empty", exc,
        )
        return []


def _atomic_write(entries: list[dict[str, Any]]) -> None:
    try:
        _HISTORY_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "cycle_history: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".cycle_hist_",
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
            "cycle_history: write failed (%s)", exc,
        )


def record_cycle(
    *,
    executed: bool,
    advance: dict[str, Any] | None = None,
    defend: dict[str, Any] | None = None,
    correlate: dict[str, Any] | None = None,
    flags: dict[str, Any] | None = None,
) -> bool:
    """Append a cycle event. Returns True on write, False on
    test-env / I/O error."""
    if _is_test_environment():
        return False
    event = CycleEvent(
        recorded_at=time.time(),
        executed=bool(executed),
        advance=dict(advance or {}),
        defend=dict(defend or {}),
        correlate=dict(correlate or {}),
        flags=dict(flags or {}),
    )
    # W962-42: span load+append+write so concurrent
    # record_cycle calls don't clobber each other.
    with _LOCK:
        entries = _load_raw()
        entries.append(asdict(event))
        if len(entries) > _MAX_EVENTS:
            entries = entries[-_MAX_EVENTS:]
        _atomic_write(entries)
    return True


def recent_history(
    *,
    since_seconds: int = 86400 * 7,
    now: float | None = None,
) -> list[CycleEvent]:
    """Newest-first events in the window. Reuses the
    Windows-tie-aware sort pattern from auto_demote_history
    (reverse + stable-sort)."""
    now = now if now is not None else time.time()
    cutoff = now - since_seconds
    raw = _load_raw()
    events: list[CycleEvent] = []
    for r in raw:
        ts = float(r.get("recorded_at", 0) or 0)
        if ts < cutoff:
            continue
        events.append(CycleEvent(
            recorded_at=ts,
            executed=bool(r.get("executed", False)),
            advance=dict(r.get("advance") or {}),
            defend=dict(r.get("defend") or {}),
            correlate=dict(r.get("correlate") or {}),
            flags=dict(r.get("flags") or {}),
        ))
    events.reverse()
    events.sort(key=lambda e: -e.recorded_at)
    return events


def cycle_stats(
    *,
    since_seconds: int = 86400 * 7,
    now: float | None = None,
) -> dict[str, Any]:
    """Rollup stats for the operator's "is the cycle
    healthy?" question. Returns a dict with:

      - total_runs (all invocations in window)
      - executed_runs (--yes only)
      - dry_run_count (--yes absent)
      - last_run_at (most recent timestamp, or None)
      - stores_advanced_total (sum of executed_ok across
        ADVANCE phases)
      - stores_refused_total (sum of refused_reliability)
      - demoted_total (sum across DEFEND phases)
      - released_total (sum across DEFEND phases)
      - correlated_total (sum across MEASURE phases)
    """
    events = recent_history(
        since_seconds=since_seconds, now=now,
    )
    stats: dict[str, Any] = {
        "total_runs": len(events),
        "executed_runs": 0,
        "dry_run_count": 0,
        "last_run_at": None,
        "stores_advanced_total": 0,
        "stores_refused_total": 0,
        "demoted_total": 0,
        "released_total": 0,
        "correlated_total": 0,
    }
    if not events:
        return stats
    stats["last_run_at"] = events[0].recorded_at
    for e in events:
        if e.executed:
            stats["executed_runs"] += 1
        else:
            stats["dry_run_count"] += 1
        adv = e.advance or {}
        stats["stores_advanced_total"] += int(
            adv.get("executed_ok", 0) or 0,
        )
        stats["stores_refused_total"] += int(
            adv.get("refused_reliability", 0) or 0,
        )
        dfn = e.defend or {}
        stats["demoted_total"] += int(
            dfn.get("demoted", 0) or 0,
        )
        stats["released_total"] += int(
            dfn.get("released", 0) or 0,
        )
        cor = e.correlate or {}
        stats["correlated_total"] += int(
            cor.get("correlated", 0) or 0,
        )
    return stats


def per_store_stats(
    *,
    since_seconds: int = 86400 * 7,
    now: float | None = None,
) -> dict[str, dict[str, int]]:
    """Per-store cycle activity rollup. Inspects each event's
    ``advance.per_store`` slice and counts outcomes per store.

    Returns ``{store_id: {executed, refused, errored,
    no_plan, total}}``. Stores that never appeared in any
    cycle aren't in the returned dict.

    The empire-AGI consumer for the world-model "this
    store's cycle activity" sub-view.
    """
    events = recent_history(
        since_seconds=since_seconds, now=now,
    )
    by_store: dict[str, dict[str, int]] = {}
    for ev in events:
        adv = ev.advance or {}
        rows = adv.get("per_store") or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            sid = str(row.get("store_id") or "")
            if not sid:
                continue
            entry = by_store.setdefault(sid, {
                "executed": 0,
                "refused": 0,
                "errored": 0,
                "no_plan": 0,
                "total": 0,
            })
            entry["total"] += 1
            outcome = str(row.get("outcome") or "")
            if outcome == "executed":
                entry["executed"] += 1
            elif outcome == "refused_reliability":
                entry["refused"] += 1
            elif outcome == "errored":
                entry["errored"] += 1
            elif outcome == "no_plan":
                entry["no_plan"] += 1
    return by_store


def clear() -> None:
    """Operator escape hatch -- wipe the history."""
    if _is_test_environment():
        return
    if _HISTORY_PATH.exists():
        try:
            _HISTORY_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "cycle_history: unlink raised: %s", exc,
            )


def _reset_for_tests(path: Path | None = None) -> None:
    """Test-only hook to override the persistence path."""
    global _HISTORY_PATH
    if path is not None:
        _HISTORY_PATH = path
