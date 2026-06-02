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
# W962 race fix: must span the full load+modify+save.
# _LOCK was previously inside _save_events only, which
# only protected the write -- two concurrent record_score
# callers could both load the same `existing` list and
# the second save would clobber the first's append.
_LOCK = threading.RLock()

# W962-36: bound the persisted history. 150 engines x 365
# days = 55K events/year if daily-brief runs nightly. Cap
# at 50K to keep the JSON file under ~10MB without losing a
# year+ of trend data. prune() is the operator's explicit
# nuclear option; this is the silent backstop.
_MAX_EVENTS = 50_000


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
    can't leave a half-truncated file.

    Caller MUST hold ``_LOCK`` -- the lock is acquired by
    record_score / record_scores / prune wrapping their
    load+modify+save sequence. Doing the load outside the
    lock and the save inside it (the original pattern) lets
    two concurrent writers clobber each other's append.

    W962-36: applies the _MAX_EVENTS bound so the on-disk
    file can't grow without limit.
    """
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # W962-36 silent backstop: drop the oldest entries past
    # the cap. Operator-driven prune() is the explicit
    # window-based eviction path.
    if len(events) > _MAX_EVENTS:
        events = events[-_MAX_EVENTS:]
    # Per-pid temp suffix so concurrent processes don't
    # collide on the rename target.
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    payload = [asdict(e) for e in events]
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
    with _LOCK:
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
    with _LOCK:
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
    with _LOCK:
        events = _load_raw_events()
        kept = [e for e in events if e.recorded_at >= cutoff]
        dropped = len(events) - len(kept)
        if dropped:
            _save_events(kept)
    return dropped


@dataclass(frozen=True)
class HealthRegression:
    """One engine flagged as regressing from its baseline score.

    ``drop = baseline_score - latest_score`` (positive means
    the engine got WORSE since the baseline window).
    """

    engine: str
    latest_score: int
    latest_verdict: str
    baseline_score: float
    drop: float
    samples_in_baseline: int


def find_regressions(
    *,
    min_drop: float = 3.0,
    baseline_window_seconds: float = 86400.0 * 7.0,
    latest_window_seconds: float = 86400.0 * 1.0,
    min_baseline_samples: int = 3,
    now: float | None = None,
) -> list[HealthRegression]:
    """Detect engines whose latest score has dropped sharply
    from their recent baseline.

    Compares each engine's MOST RECENT event in the latest
    window against the MEDIAN of events in the baseline window
    (events older than the latest window's start). Engines with
    ``drop >= min_drop`` are flagged.

    Args:
        min_drop: Minimum score-drop in points (e.g. 3.0 means
            "score dropped by 3+ out of 10"). Default 3.
        baseline_window_seconds: Look-back window for the
            baseline median (default 7 days).
        latest_window_seconds: Window for picking the "latest"
            score (default 1 day -- daily-brief records once per
            day on the operator's cron).
        min_baseline_samples: Skip engines with fewer than this
            many events in the baseline (statistically noisy).
            Default 3.
        now: Override for testing.

    Returns:
        List of :class:`HealthRegression`, sorted by drop size
        descending (biggest regression first).
    """
    if now is None:
        now = time.time()
    baseline_cutoff = now - max(0.0, float(baseline_window_seconds))
    latest_cutoff = now - max(0.0, float(latest_window_seconds))

    events = _load_raw_events()
    # Group by engine within the baseline window.
    by_engine: dict[str, list[ScoreEvent]] = {}
    for e in events:
        if e.recorded_at < baseline_cutoff:
            continue
        by_engine.setdefault(e.engine, []).append(e)

    out: list[HealthRegression] = []
    for engine, bucket in by_engine.items():
        latest_candidates = [
            ev for ev in bucket
            if ev.recorded_at >= latest_cutoff
        ]
        if not latest_candidates:
            continue
        latest = max(
            latest_candidates, key=lambda ev: ev.recorded_at,
        )

        # Baseline = events older than the latest window so
        # the latest event itself doesn't skew its own
        # baseline.
        baseline = [
            ev for ev in bucket
            if ev.recorded_at < latest_cutoff
        ]
        if len(baseline) < min_baseline_samples:
            continue

        sorted_scores = sorted(ev.score for ev in baseline)
        mid = len(sorted_scores) // 2
        if len(sorted_scores) % 2 == 1:
            median = float(sorted_scores[mid])
        else:
            median = (
                sorted_scores[mid - 1] + sorted_scores[mid]
            ) / 2.0

        drop = median - latest.score
        if drop < min_drop:
            continue
        out.append(HealthRegression(
            engine=engine,
            latest_score=latest.score,
            latest_verdict=latest.verdict,
            baseline_score=median,
            drop=drop,
            samples_in_baseline=len(baseline),
        ))

    out.sort(key=lambda r: -r.drop)
    return out


@dataclass(frozen=True)
class ChronicWarning:
    """One engine stuck in warning/unhealthy across the
    sample window. Distinct from ``HealthRegression`` --
    a chronic warning is a STATE (consistently sick),
    while a regression is a CHANGE (got worse)."""

    engine: str
    latest_score: int
    latest_verdict: str
    samples: int
    avg_score: float


def find_chronic_warnings(
    *,
    sample_window_seconds: float = 86400.0 * 7.0,
    min_samples: int = 3,
    healthy_score_floor: int = 7,
    now: float | None = None,
) -> list[ChronicWarning]:
    """Detect engines whose last N samples have ALL been
    below the healthy-score floor.

    Complements ``find_regressions``: a regression compares
    baseline-vs-latest (a CHANGE signal), while a chronic
    warning flags engines that have been consistently
    unhealthy across the window (a STATE signal). Both
    matter -- a regression can resolve on its own; a chronic
    warning typically can't.

    Args:
        sample_window_seconds: Look-back window (default 7d).
        min_samples: Minimum number of events in the window
            for the engine to qualify (default 3 -- one or two
            samples is too noisy to call chronic).
        healthy_score_floor: Scores AT OR ABOVE this value
            count as "engine recovered at least once" and
            exempt the engine from chronic flagging.
            Default 7 -- an engine that scored even a single
            7+ in the window isn't truly stuck. Verdict
            bands for reference: 8-10 healthy / 5-7 warning
            / <5 unhealthy; setting floor=8 would treat ANY
            non-healthy sample as chronic-eligible (a
            stricter filter).
        now: Override for testing.

    Returns:
        List of :class:`ChronicWarning`, sorted by latest
        score ascending (sickest first).
    """
    if now is None:
        now = time.time()
    cutoff = now - max(0.0, float(sample_window_seconds))

    events = _load_raw_events()
    by_engine: dict[str, list[ScoreEvent]] = {}
    for e in events:
        if e.recorded_at < cutoff:
            continue
        by_engine.setdefault(e.engine, []).append(e)

    out: list[ChronicWarning] = []
    for engine, bucket in by_engine.items():
        if len(bucket) < min_samples:
            continue
        if any(
            ev.score >= healthy_score_floor for ev in bucket
        ):
            continue
        latest = max(bucket, key=lambda ev: ev.recorded_at)
        avg = sum(ev.score for ev in bucket) / len(bucket)
        out.append(ChronicWarning(
            engine=engine,
            latest_score=latest.score,
            latest_verdict=latest.verdict,
            samples=len(bucket),
            avg_score=round(avg, 1),
        ))

    out.sort(key=lambda c: c.latest_score)
    return out
