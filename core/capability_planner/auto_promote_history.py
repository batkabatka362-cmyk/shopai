"""Persistent log of auto-promote events.

Mirrors ``auto_demote_history`` for the symmetric promote
side. Tracks every auto-promote so operators can audit:

  - "Why is cap X promoted? When did the bridge promote it?"
  - "Has the substrate been growing or shrinking on net?"
  - "Which capabilities cycle promote->demote->promote
    (promote-side thrashing)?"

Public surface
--------------
- ``AutoPromoteEvent``.
- ``record_promote(capability, reason, metrics)``.
- ``recent_history(since_seconds)``.
- ``promote_stats(since_seconds)``.
- ``clear()``.

Pattern J + atomic + fail-open + 1000-cap, same shape as
all the other history modules.
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
        "SHOPAI_AUTO_PROMOTE_HISTORY_PATH",
        "data/auto_promote_history.json",
    )
)

_MAX_EVENTS = 1000


@dataclass
class AutoPromoteEvent:
    capability: str
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
            "auto_promote_history: load failed (%s)", exc,
        )
        return []


def _atomic_write(entries: list[dict[str, Any]]) -> None:
    try:
        _HISTORY_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "auto_promote_history: mkdir failed (%s)",
            exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".auto_promote_hist_",
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
            "auto_promote_history: write failed (%s)", exc,
        )


def record_promote(
    *,
    capability: str,
    reason: str,
    metrics: dict[str, Any] | None = None,
) -> bool:
    """Append a promote event. Returns True on write,
    False on test-env / I/O error / invalid args."""
    if not capability:
        return False
    if _is_test_environment():
        return False
    event = AutoPromoteEvent(
        capability=capability,
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
    capability: str | None = None,
    now: float | None = None,
) -> list[AutoPromoteEvent]:
    """Newest-first events in the window. Optional
    capability filter."""
    now = now if now is not None else time.time()
    cutoff = now - since_seconds
    raw = _load_raw()
    events: list[AutoPromoteEvent] = []
    for r in raw:
        cap = str(r.get("capability", "") or "")
        if not cap:
            continue
        if capability is not None and cap != capability:
            continue
        ts = float(r.get("recorded_at", 0) or 0)
        if ts < cutoff:
            continue
        events.append(AutoPromoteEvent(
            capability=cap,
            reason=str(r.get("reason", "") or ""),
            recorded_at=ts,
            metrics=dict(r.get("metrics", {}) or {}),
        ))
    events.reverse()
    events.sort(key=lambda e: -e.recorded_at)
    return events


def promote_stats(
    *,
    since_seconds: int = 86400 * 7,
    now: float | None = None,
) -> dict[str, Any]:
    """Rollup: total, by_capability (count per cap),
    last_promote_at."""
    events = recent_history(
        since_seconds=since_seconds, now=now,
    )
    out: dict[str, Any] = {
        "total": len(events),
        "by_capability": {},
        "last_promote_at": None,
    }
    if not events:
        return out
    out["last_promote_at"] = events[0].recorded_at
    for e in events:
        out["by_capability"][e.capability] = (
            out["by_capability"].get(e.capability, 0) + 1
        )
    return out


def clear() -> None:
    if _is_test_environment():
        return
    if _HISTORY_PATH.exists():
        try:
            _HISTORY_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "auto_promote_history: unlink raised: %s",
                exc,
            )


def _reset_for_tests(path: Path | None = None) -> None:
    global _HISTORY_PATH
    if path is not None:
        _HISTORY_PATH = path
