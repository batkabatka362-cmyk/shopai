"""Persistent log of auto-relax / auto-restore actions.

The bridge in ``core.autonomous.auto_relax`` adjusts the
persistent reliability threshold without restart. Without
an audit log, operators couldn't answer: "what did the
bridge do last week?" or "why is my threshold at 0.65?"

This module captures every APPLIED action so the override
file's final value has a paper trail.

Public surface
--------------
- ``RelaxHistoryEvent`` dataclass.
- ``record_action(direction, current_value, proposed_value,
  reason, metrics)`` -- append an event.
- ``recent_history(since_seconds)`` -- newest-first window.
- ``relax_stats(since_seconds)`` -- rollup with relax/
  restore counts.
- ``clear()`` -- operator escape hatch.

Pattern J test guard short-circuits writes; reads still
work for testing. JSON file, atomic temp+rename, fail-open,
1000-event cap.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_HISTORY_PATH = Path(
    os.environ.get(
        "SHOPAI_AUTO_RELAX_HISTORY_PATH",
        "data/auto_relax_history.json",
    )
)

_MAX_EVENTS = 1000


@dataclass
class RelaxHistoryEvent:
    """One applied bridge action."""

    direction: str  # "relax" | "restore"
    current_value: float
    proposed_value: float
    reason: str
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
            "auto_relax_history: load failed (%s)", exc,
        )
        return []


def _atomic_write(entries: list[dict[str, Any]]) -> None:
    try:
        _HISTORY_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "auto_relax_history: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".auto_relax_hist_",
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
            "auto_relax_history: write failed (%s)", exc,
        )


def record_action(
    *,
    direction: str,
    current_value: float,
    proposed_value: float,
    reason: str,
    metrics: dict[str, Any] | None = None,
) -> bool:
    """Append a bridge-action event. Returns True on write,
    False on test-env / I/O error / direction='none'.

    Direction='none' is silently rejected -- only relax /
    restore actions warrant an audit row.
    """
    if direction not in ("relax", "restore"):
        return False
    if _is_test_environment():
        return False
    event = RelaxHistoryEvent(
        direction=direction,
        current_value=float(current_value),
        proposed_value=float(proposed_value),
        reason=reason,
        recorded_at=time.time(),
        metrics=dict(metrics or {}),
    )
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
) -> list[RelaxHistoryEvent]:
    """Newest-first events in the window. Reuses the
    Windows-tie-aware reverse-then-stable-sort pattern."""
    now = now if now is not None else time.time()
    cutoff = now - since_seconds
    raw = _load_raw()
    events: list[RelaxHistoryEvent] = []
    for r in raw:
        direction = str(r.get("direction", "") or "")
        if direction not in ("relax", "restore"):
            continue
        ts = float(r.get("recorded_at", 0) or 0)
        if ts < cutoff:
            continue
        events.append(RelaxHistoryEvent(
            direction=direction,
            current_value=float(
                r.get("current_value", 0) or 0,
            ),
            proposed_value=float(
                r.get("proposed_value", 0) or 0,
            ),
            reason=str(r.get("reason", "") or ""),
            recorded_at=ts,
            metrics=dict(r.get("metrics", {}) or {}),
        ))
    events.reverse()
    events.sort(key=lambda e: -e.recorded_at)
    return events


def relax_stats(
    *,
    since_seconds: int = 86400 * 7,
    now: float | None = None,
) -> dict[str, Any]:
    """Per-window rollup: count of each direction + the
    last event's timestamp + the net change (sum of
    proposed - current, signed)."""
    events = recent_history(
        since_seconds=since_seconds, now=now,
    )
    out: dict[str, Any] = {
        "total": len(events),
        "relax_count": 0,
        "restore_count": 0,
        "last_action_at": None,
        "last_direction": None,
        "net_change": 0.0,
    }
    if not events:
        return out
    out["last_action_at"] = events[0].recorded_at
    out["last_direction"] = events[0].direction
    for e in events:
        if e.direction == "relax":
            out["relax_count"] += 1
        elif e.direction == "restore":
            out["restore_count"] += 1
        out["net_change"] += (
            e.proposed_value - e.current_value
        )
    out["net_change"] = round(out["net_change"], 4)
    return out


def clear() -> None:
    """Operator escape hatch -- wipe the history."""
    if _is_test_environment():
        return
    if _HISTORY_PATH.exists():
        try:
            _HISTORY_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "auto_relax_history: unlink raised: %s",
                exc,
            )


def _reset_for_tests(path: Path | None = None) -> None:
    global _HISTORY_PATH
    if path is not None:
        _HISTORY_PATH = path
