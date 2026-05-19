"""Persistent log of engine_health scores over time.

``core.approval.engine_health.score_engine`` (PR #337) returns
the CURRENT verdict for an engine. That's enough for "right now"
queries but says nothing about the trajectory: is loyalty
recovering or getting worse? Has discount_strategy been stable
at score 4 for the past week, or is it a fresh degradation?

This module is the trajectory recorder. Persistence is a flat
JSON log at ``data/engine_health_history.json`` (or
``SHOPAI_DATA_DIR/engine_health_history.json``), mirroring the
shape of ``core.approval.alert_history``:

* Append-only on record (no in-place updates).
* Reads return a typed dataclass list.
* Per-engine recent filter for trend queries.
* Pattern J guard: under pytest, ``record_score`` short-circuits
  to keep tests from polluting the persistent file. Tests that
  need to verify recording behaviour patch
  ``_is_test_environment`` to return False.

The intended writer is ``shopai daily-brief`` (one append per
engine per run). The intended readers are:

* ``shopai engine pulse <engine> --history`` -- prints the
  trend.
* ``shopai engine alerts`` -- could highlight "score has been
  unhealthy for 5 days running" (future).
* Observability dashboards.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


_DEFAULT_STATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data" / "engine_health_history.json"
)
_LOCK = threading.Lock()


@dataclass(frozen=True)
class ScoreEvent:
    """One engine_health score recorded at a point in time."""

    engine: str
    recorded_at: float
    score: int
    verdict: str


def _state_path() -> Path:
    """Honors ``SHOPAI_DATA_DIR`` like the rest of the
    persistence layer."""
    data_dir = os.environ.get("SHOPAI_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "engine_health_history.json"
    return _DEFAULT_STATE_PATH


def _is_test_environment() -> bool:
    """Pattern J guard -- under pytest, ``record_score`` should
    not write to the persistent file. Tests that need writing
    patch this to return False."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw_events() -> list[ScoreEvent]:
    """Read the persisted log. Fails open: missing / corrupt
    file returns empty list."""
    path = _state_path()
    try:
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug(
            "engine_health_history read failed (%s); "
            "failing open: %s", path, exc,
        )
        return []
    if not isinstance(data, list):
        return []
    out: list[ScoreEvent] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(ScoreEvent(
                engine=str(entry.get("engine", "")).strip(),
                recorded_at=float(
                    entry.get("recorded_at", 0.0) or 0.0,
                ),
                score=int(entry.get("score", 0) or 0),
                verdict=str(entry.get("verdict", "")).strip(),
            ))
        except (TypeError, ValueError) as exc:
            logger.debug(
                "engine_health_history skipping malformed "
                "entry: %s", exc,
            )
            continue
    return out


def _save_events(events: list[ScoreEvent]) -> None:
    """Atomic write via temp + rename so a crash mid-write
    can't leave a half-truncated file."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = [asdict(e) for e in events]
    with _LOCK:
        tmp.write_text(
            json.dumps(payload, indent=2), encoding="utf-8",
        )
        tmp.replace(path)


def record_score(
    engine: str,
    *,
    score: int,
    verdict: str,
    now: float | None = None,
) -> bool:
    """Append a single engine_health score event to the log.

    Args:
        engine: Engine name.
        score: Integer 1..10 score from
            ``engine_health.score_engine``.
        verdict: One of ``"healthy"`` / ``"warning"`` /
            ``"unhealthy"``.
        now: Override timestamp; defaults to ``time.time()``.

    Returns:
        ``True`` when the event was appended, ``False`` when
        skipped (Pattern J guard or empty engine).
    """
    if _is_test_environment():
        return False
    engine = (engine or "").strip()
    if not engine:
        return False
    if now is None:
        now = time.time()
    event = ScoreEvent(
        engine=engine,
        recorded_at=float(now),
        score=int(score),
        verdict=verdict,
    )
    existing = _load_raw_events()
    _save_events(existing + [event])
    return True


def record_scores(
    entries: Iterable[dict],
    *,
    now: float | None = None,
) -> int:
    """Batch variant of :func:`record_score`.

    Args:
        entries: iterable of ``{engine, score, verdict}`` dicts.
            Any entry missing a field is silently skipped.
        now: Override timestamp applied to every event.

    Returns:
        Count of events actually appended (0 under pytest).
    """
    if _is_test_environment():
        return 0
    if now is None:
        now = time.time()
    new_events: list[ScoreEvent] = []
    for entry in entries:
        try:
            engine = str(entry.get("engine", "")).strip()
            if not engine:
                continue
            new_events.append(ScoreEvent(
                engine=engine,
                recorded_at=float(now),
                score=int(entry.get("score", 0) or 0),
                verdict=str(
                    entry.get("verdict", "") or "",
                ).strip(),
            ))
        except (TypeError, ValueError, AttributeError) as exc:
            logger.debug(
                "engine_health_history.record_scores "
                "skipping malformed entry: %s", exc,
            )
            continue
    if not new_events:
        return 0
    existing = _load_raw_events()
    _save_events(existing + new_events)
    return len(new_events)


def recent_history(
    engine: str | None = None,
    *,
    since_seconds: float = 86400.0 * 30.0,
    now: float | None = None,
) -> list[ScoreEvent]:
    """Read events recorded within ``since_seconds``.

    Newest-first. Default window is 30 days -- enough to see a
    monthly trend without dragging in stale legacy entries.

    Args:
        engine: Optional engine filter. When supplied, only that
            engine's events are returned.
        since_seconds: Look-back window.
        now: Override for testing.
    """
    if now is None:
        now = time.time()
    cutoff = now - max(0.0, float(since_seconds))
    events = _load_raw_events()
    out = [e for e in events if e.recorded_at >= cutoff]
    if engine is not None:
        out = [e for e in out if e.engine == engine]
    out.sort(key=lambda e: -e.recorded_at)
    return out


def latest_per_engine(
    *,
    since_seconds: float = 86400.0 * 30.0,
    now: float | None = None,
) -> dict[str, ScoreEvent]:
    """Return the most recent event per engine within the
    window. Useful for "current state plus trajectory" views.
    """
    out: dict[str, ScoreEvent] = {}
    for e in recent_history(
        since_seconds=since_seconds, now=now,
    ):
        if e.engine not in out:
            out[e.engine] = e
    return out


def clear() -> None:
    """Operator nuclear option: wipe the persisted history.

    Use case: rotating ops cycles where the prior history is no
    longer relevant. Mirror of ``alert_history.clear``.
    """
    path = _state_path()
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.debug(
            "engine_health_history.clear failed: %s", exc,
        )


def prune(
    *,
    older_than_seconds: float = 86400.0 * 90.0,
    now: float | None = None,
) -> int:
    """Drop events older than ``older_than_seconds``.

    Returns the count of events dropped. Default 90-day window.
    Routine ops hygiene -- the JSON log will grow without bound
    otherwise.
    """
    if now is None:
        now = time.time()
    cutoff = now - max(0.0, float(older_than_seconds))
    events = _load_raw_events()
    kept = [e for e in events if e.recorded_at >= cutoff]
    dropped = len(events) - len(kept)
    if dropped:
        _save_events(kept)
    return dropped
