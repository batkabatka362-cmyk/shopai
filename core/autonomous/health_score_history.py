"""Composite health score history.

The status command computes a 0-100 health score from
alerts, thrashing, pause state, and revenue trend. The
single number is useful in the moment but the TREND
matters more: is operations getting better or worse?

This module persists the score over time so operators can
spot drift before it crosses a threshold.

Pattern matches the other history modules: JSON file at
``data/health_score_history.json``, atomic temp+rename,
fail-open reads, 1000-event cap, Pattern J guard.

Public surface
--------------
- ``HealthScoreSnapshot`` dataclass.
- ``record_snapshot(score, verdict)``.
- ``recent_history(since_seconds)``.
- ``score_trend(window_seconds)``.
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
        "SHOPAI_HEALTH_SCORE_HISTORY_PATH",
        "data/health_score_history.json",
    )
)

_MAX_EVENTS = 1000


@dataclass
class HealthScoreSnapshot:
    score: int
    verdict: str  # "ok" | "warn" | "error" | "unknown"
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
            "health_score_history: load failed (%s)",
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
            "health_score_history: mkdir failed (%s)",
            exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".hs_hist_",
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
            "health_score_history: write failed (%s)",
            exc,
        )


def record_snapshot(
    *,
    score: int,
    verdict: str,
) -> bool:
    """Append a score snapshot. Returns True on write,
    False on test-env / invalid args."""
    if not isinstance(score, int):
        try:
            score = int(score)
        except (TypeError, ValueError):
            return False
    if score < 0 or score > 100:
        return False
    if verdict not in (
        "ok", "warn", "error", "unknown",
    ):
        return False
    if _is_test_environment():
        return False
    event = HealthScoreSnapshot(
        score=score,
        verdict=verdict,
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
    since_seconds: int = 86400 * 7,
    now: float | None = None,
) -> list[HealthScoreSnapshot]:
    """Newest-first events in the window."""
    now = now if now is not None else time.time()
    cutoff = now - since_seconds
    raw = _load_raw()
    events: list[HealthScoreSnapshot] = []
    for r in raw:
        try:
            score = int(r.get("score", 0) or 0)
        except (TypeError, ValueError):
            continue
        verdict = str(r.get("verdict", "") or "")
        ts = float(r.get("recorded_at", 0) or 0)
        if ts < cutoff:
            continue
        events.append(HealthScoreSnapshot(
            score=score,
            verdict=verdict,
            recorded_at=ts,
        ))
    events.reverse()
    events.sort(key=lambda e: -e.recorded_at)
    return events


def score_trend(
    *,
    since_seconds: int = 86400 * 7,
    now: float | None = None,
) -> dict[str, Any]:
    """Compute score trend over window.

    Returns:
      {
        "snapshots": int,
        "first_score": int | None,
        "last_score": int | None,
        "min_score": int | None,
        "max_score": int | None,
        "avg_score": float,
        "delta": int,
      }
    """
    events = recent_history(
        since_seconds=since_seconds, now=now,
    )
    out: dict[str, Any] = {
        "snapshots": len(events),
        "first_score": None,
        "last_score": None,
        "min_score": None,
        "max_score": None,
        "avg_score": 0.0,
        "delta": 0,
    }
    if not events:
        return out
    scores = [e.score for e in events]
    # events newest-first; reverse to get chronological
    first = events[-1]
    last = events[0]
    out["first_score"] = first.score
    out["last_score"] = last.score
    out["min_score"] = min(scores)
    out["max_score"] = max(scores)
    out["avg_score"] = round(
        sum(scores) / len(scores), 1,
    )
    out["delta"] = last.score - first.score
    return out


def clear() -> None:
    if _is_test_environment():
        return
    if _HISTORY_PATH.exists():
        try:
            _HISTORY_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "health_score_history: unlink "
                "raised: %s", exc,
            )


def _reset_for_tests(path: Path | None = None) -> None:
    global _HISTORY_PATH
    if path is not None:
        _HISTORY_PATH = path
