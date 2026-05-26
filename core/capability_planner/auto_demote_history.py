"""Auto-demote bridge event history.

The override file (``data/capability_overrides.json``) shows
CURRENT state: which capabilities are demoted right now. It
does NOT show history -- if the bridge demotes capability X,
then auto-releases it, then re-demotes it, only the latest
state is visible.

This module is the audit trail. Each demote + release fires
an event; the events persist to ``data/auto_demote_history.json``
so operators can answer:

  - "What has the bridge demoted in the last 24h?"
  - "Has capability X been thrashing (multiple demote-release
    cycles in a short window)?"
  - "How long did capability Y stay demoted before recovering?"

Pattern matches ``core.approval.alert_history`` exactly:
JSON file, atomic temp+rename, fail-open reads, Pattern J
guard short-circuits writes under pytest.

Public surface
--------------
- ``AutoDemoteEvent`` -- dataclass: kind / capability /
  reason / recorded_at.
- ``record_demote(capability, reason)`` -- append a demote
  event.
- ``record_release(capability, reason)`` -- append a release
  event.
- ``recent_history(since_seconds=86400*7)`` -- newest-first
  events in the window.
- ``find_thrashing(window_seconds=86400*7, min_cycles=2)`` --
  capabilities with multiple demote events in the window.
- ``clear()`` -- operator escape hatch.

Storage cap: 1000 events (oldest dropped on overflow). The
bridge fires a handful of events per cycle at most; 1000 is
roughly a year of activity.
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
        "SHOPAI_AUTO_DEMOTE_HISTORY_PATH",
        "data/auto_demote_history.json",
    )
)

_MAX_EVENTS = 1000


@dataclass
class AutoDemoteEvent:
    """One bridge event. ``kind`` is ``"demote"`` or
    ``"release"``. ``reason`` is the operator-readable
    justification (for demotes, mirrors the override file's
    reason; for releases, captures the rate that triggered
    the release)."""

    kind: str  # "demote" | "release"
    capability: str
    reason: str = ""
    recorded_at: float = 0.0


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
            "auto_demote_history: load failed (%s) "
            "-- returning empty", exc,
        )
        return []


def _atomic_write(entries: list[dict[str, Any]]) -> None:
    try:
        _HISTORY_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "auto_demote_history: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".auto_demote_hist_",
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
            "auto_demote_history: write failed (%s)", exc,
        )


def _append_event(event: AutoDemoteEvent) -> bool:
    if _is_test_environment():
        return False
    entries = _load_raw()
    entries.append(asdict(event))
    # Cap at MAX_EVENTS oldest-first
    if len(entries) > _MAX_EVENTS:
        entries = entries[-_MAX_EVENTS:]
    _atomic_write(entries)
    return True


def record_demote(
    capability: str, reason: str = "",
) -> bool:
    """Append a demote event. Returns True on write,
    False on test-env / I/O error."""
    if not capability:
        return False
    return _append_event(AutoDemoteEvent(
        kind="demote",
        capability=capability,
        reason=reason,
        recorded_at=time.time(),
    ))


def record_release(
    capability: str, reason: str = "",
) -> bool:
    """Append a release event."""
    if not capability:
        return False
    return _append_event(AutoDemoteEvent(
        kind="release",
        capability=capability,
        reason=reason,
        recorded_at=time.time(),
    ))


def recent_history(
    *,
    since_seconds: int = 86400 * 7,
    now: float | None = None,
) -> list[AutoDemoteEvent]:
    """Newest-first events in the window.

    On Windows ``time.time()`` resolution can mean two adjacent
    record_* calls get the same timestamp. To produce a stable
    "newest-first" order, we reverse the file-order list FIRST
    (later file position = newer event), then sort by
    ``-recorded_at`` with Python's stable sort. When timestamps
    tie, the later-recorded event wins.
    """
    now = now if now is not None else time.time()
    cutoff = now - since_seconds
    raw = _load_raw()
    events: list[AutoDemoteEvent] = []
    for r in raw:
        kind = str(r.get("kind", "") or "")
        cap = str(r.get("capability", "") or "")
        if kind not in ("demote", "release") or not cap:
            continue
        ts = float(r.get("recorded_at", 0) or 0)
        if ts < cutoff:
            continue
        events.append(AutoDemoteEvent(
            kind=kind,
            capability=cap,
            reason=str(r.get("reason", "") or ""),
            recorded_at=ts,
        ))
    # Reverse so file-order-later events come FIRST, then
    # stable-sort by timestamp desc -- ties break by file
    # position (later wins).
    events.reverse()
    events.sort(key=lambda e: -e.recorded_at)
    return events


def find_thrashing(
    *,
    window_seconds: int = 86400 * 7,
    min_cycles: int = 2,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Capabilities that have been demoted multiple times in
    the window -- a signal that the bridge keeps catching
    them but they keep recovering enough to trigger release.

    A "cycle" is a demote event. ``min_cycles=2`` means a
    capability needs to have been demoted at least twice in
    the window to count as thrashing.

    Returns list of ``{capability, demote_count,
    release_count, first_demote_at, last_demote_at}`` sorted
    by demote_count desc. Watch this list -- thrashing means
    the underlying issue isn't actually fixed; the
    capability oscillates around the recovery threshold.
    """
    events = recent_history(
        since_seconds=window_seconds, now=now,
    )
    by_cap: dict[str, dict[str, Any]] = {}
    for e in events:
        cap = e.capability
        if cap not in by_cap:
            by_cap[cap] = {
                "capability": cap,
                "demote_count": 0,
                "release_count": 0,
                "first_demote_at": None,
                "last_demote_at": None,
            }
        if e.kind == "demote":
            by_cap[cap]["demote_count"] += 1
            if (
                by_cap[cap]["first_demote_at"] is None
                or e.recorded_at
                < by_cap[cap]["first_demote_at"]
            ):
                by_cap[cap]["first_demote_at"] = (
                    e.recorded_at
                )
            if (
                by_cap[cap]["last_demote_at"] is None
                or e.recorded_at
                > by_cap[cap]["last_demote_at"]
            ):
                by_cap[cap]["last_demote_at"] = (
                    e.recorded_at
                )
        else:
            by_cap[cap]["release_count"] += 1
    rows = [
        row for row in by_cap.values()
        if row["demote_count"] >= max(1, int(min_cycles))
    ]
    rows.sort(
        key=lambda r: (
            -r["demote_count"], r["capability"],
        ),
    )
    return rows


def clear() -> None:
    """Operator escape hatch -- wipe the history."""
    if _is_test_environment():
        return
    if _HISTORY_PATH.exists():
        try:
            _HISTORY_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "auto_demote_history: unlink raised: %s",
                exc,
            )


def _reset_for_tests(path: Path | None = None) -> None:
    """Test-only hook to override the persistence path."""
    global _HISTORY_PATH
    if path is not None:
        _HISTORY_PATH = path
