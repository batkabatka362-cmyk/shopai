"""Engine outcome trend detection — recent vs baseline comparison.

The CLI's ``shopai engine alerts`` (PR #276) implements
degradation detection inline: for each engine, aggregate outcomes
over a recent window + a baseline window, alert when the recent
outcome_score drops below baseline by ``threshold``.

This module extracts that logic into a pure data-producing
function so other callers can consume it without re-implementing:

  - ``shopai daily-brief`` (future PR) — surface degradation
    alerts in the morning rollup
  - ``core.world_model._section_engine_alerts`` (future) — flag
    quietly-degrading engines in per-store snapshots
  - Autonomous-loop trigger (future) — auto-quarantine engines
    whose outcomes degrade past a threshold

The CLI handler can adopt this module in a follow-up; doing it
here would conflict with any in-flight cli.py PRs.

Architecture: recent window is INCLUDED in baseline (recent is a
subset of baseline). Comparison is "recent vs the full historical
context including recent" — stable when recent activity is
sparse. Alternative "recent vs baseline-minus-recent" amplifies
noise when recent dominates the polarised count.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EngineAlert:
    """One engine flagged for outcome-score degradation.

    Fields mirror the JSON envelope shape from ``shopai engine
    alerts`` so callers don't have to translate. Frozen so a
    caller's downstream pipeline can't accidentally mutate the
    detection result.

    ``store_id`` carries the per-store scope when the alert
    was computed via ``compute_engine_alerts_per_store``;
    ``None`` for fleet-wide alerts (the default).
    """

    engine: str
    recent_executed: int
    baseline_executed: int
    recent_score: float
    baseline_score: float
    recent_polarised: int
    baseline_polarised: int
    drop: float
    detail: str
    kind: str = "outcome_score_degraded"
    store_id: str | None = None


def compute_engine_alerts(
    queue: Any,
    *,
    recent_hours: float = 24.0,
    baseline_hours: float = 168.0,
    threshold: float = 0.2,
    min_recent: int = 3,
) -> list[EngineAlert]:
    """Detect engines whose recent outcome score has degraded.

    Args:
        queue: ApprovalQueue (or compatible) -- must expose
            ``_conn`` for SQL access and ``get_outcomes(id)``.
        recent_hours: Window scored against the baseline
            (default 24h).
        baseline_hours: Full historical context (default 168h =
            7 days). MUST exceed ``recent_hours``.
        threshold: Score-drop threshold (default 0.2 = 20pp).
            ``baseline_score - recent_score >= threshold``
            triggers the alert.
        min_recent: Minimum polarised outcomes in BOTH windows
            for the comparison to count (default 3). Below this,
            the signal is too noisy to alert on.

    Returns:
        List of :class:`EngineAlert`, ranked by drop size (
        largest first). Empty list when nothing flagged.

    Raises:
        ValueError: when ``baseline_hours <= recent_hours``
            (would make recent overlap baseline fully).
        Other exceptions from the queue are NOT caught -- callers
        decide how to handle them. The CLI handler wraps this
        call in its own try/except.
    """
    if baseline_hours <= recent_hours:
        raise ValueError(
            "baseline_hours must exceed recent_hours"
        )

    # Aggregate via the shared rollup utility -- this is the
    # second consumer (engine alerts CLI was the first).
    from core.approval.outcome_aggregator import aggregate_outcomes

    now = time.time()
    recent_cutoff = now - recent_hours * 3600.0
    baseline_cutoff = now - baseline_hours * 3600.0

    per_engine: dict[str, dict] = {}

    def _bucket(name: str) -> dict:
        if name not in per_engine:
            per_engine[name] = {
                "recent_outcomes": [],
                "baseline_outcomes": [],
                "recent_executed": 0,
                "baseline_executed": 0,
            }
        return per_engine[name]

    with queue._conn:
        rows = queue._conn.execute(
            """SELECT id, engine, decided_at
               FROM pending_actions
               WHERE status = 'executed'
                 AND decided_at >= ?""",
            (baseline_cutoff,),
        ).fetchall()

    for r in rows:
        engine = r["engine"] or "(unknown)"
        b = _bucket(engine)
        b["baseline_executed"] += 1
        decided_at = float(r["decided_at"] or 0)
        is_recent = decided_at >= recent_cutoff
        if is_recent:
            b["recent_executed"] += 1
        try:
            outcomes = queue.get_outcomes(r["id"]) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "outcome_trends get_outcomes raised: %s", exc,
            )
            outcomes = []
        b["baseline_outcomes"].extend(outcomes)
        if is_recent:
            b["recent_outcomes"].extend(outcomes)

    alerts: list[EngineAlert] = []
    for engine, b in per_engine.items():
        recent_stats = aggregate_outcomes(b["recent_outcomes"])
        baseline_stats = aggregate_outcomes(b["baseline_outcomes"])
        recent_polarised = (
            recent_stats.positive + recent_stats.negative
        )
        baseline_polarised = (
            baseline_stats.positive + baseline_stats.negative
        )

        if recent_polarised < min_recent:
            continue
        if baseline_polarised < min_recent:
            continue
        if (
            recent_stats.outcome_score is None
            or baseline_stats.outcome_score is None
        ):
            continue

        drop = (
            baseline_stats.outcome_score
            - recent_stats.outcome_score
        )
        if drop < threshold:
            continue

        alerts.append(EngineAlert(
            engine=engine,
            recent_executed=b["recent_executed"],
            baseline_executed=b["baseline_executed"],
            recent_score=recent_stats.outcome_score,
            baseline_score=baseline_stats.outcome_score,
            recent_polarised=recent_polarised,
            baseline_polarised=baseline_polarised,
            drop=drop,
            detail=(
                f"{recent_stats.outcome_score:.0%} recent vs "
                f"{baseline_stats.outcome_score:.0%} baseline "
                f"(drop {drop:.0%})"
            ),
        ))

    alerts.sort(key=lambda a: -a.drop)
    return alerts


def compute_engine_alerts_per_store(
    queue: Any,
    *,
    recent_hours: float = 24.0,
    baseline_hours: float = 168.0,
    threshold: float = 0.2,
    min_recent: int = 3,
) -> list[EngineAlert]:
    """Per-(engine, store_id) degradation detector.

    Same logic as ``compute_engine_alerts`` but the
    aggregation buckets are ``(engine, store_id)`` pairs
    instead of just engines. Catches "engine X's score
    dropped on store_a specifically" -- the empire-AGI pivot.

    Rows with ``store_id=None`` (pre-PR-#239 or unscoped)
    bucket under ``(engine, None)`` -- effectively the
    fleet-wide path. Operators can filter them out client-
    side.

    Returns:
        List of :class:`EngineAlert` with ``store_id`` set,
        ranked by drop size (largest first). An engine
        degrading on multiple stores produces multiple
        alerts -- one per (engine, store) pair.

    Raises:
        ValueError: when ``baseline_hours <= recent_hours``.
        Queue exceptions propagate.
    """
    if baseline_hours <= recent_hours:
        raise ValueError(
            "baseline_hours must exceed recent_hours"
        )

    from core.approval.outcome_aggregator import aggregate_outcomes

    now = time.time()
    recent_cutoff = now - recent_hours * 3600.0
    baseline_cutoff = now - baseline_hours * 3600.0

    per_pair: dict[tuple[str, str | None], dict] = {}

    def _bucket(engine: str, store_id: str | None) -> dict:
        key = (engine, store_id)
        if key not in per_pair:
            per_pair[key] = {
                "recent_outcomes": [],
                "baseline_outcomes": [],
                "recent_executed": 0,
                "baseline_executed": 0,
            }
        return per_pair[key]

    with queue._conn:
        rows = queue._conn.execute(
            """SELECT id, engine, store_id, decided_at
               FROM pending_actions
               WHERE status = 'executed'
                 AND decided_at >= ?""",
            (baseline_cutoff,),
        ).fetchall()

    for r in rows:
        engine = r["engine"] or "(unknown)"
        try:
            store_id = r["store_id"]
        except (IndexError, KeyError):
            # Pre-#239 schema without store_id column
            store_id = None
        b = _bucket(engine, store_id)
        b["baseline_executed"] += 1
        decided_at = float(r["decided_at"] or 0)
        is_recent = decided_at >= recent_cutoff
        if is_recent:
            b["recent_executed"] += 1
        try:
            outcomes = queue.get_outcomes(r["id"]) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "outcome_trends_per_store get_outcomes "
                "raised: %s", exc,
            )
            outcomes = []
        b["baseline_outcomes"].extend(outcomes)
        if is_recent:
            b["recent_outcomes"].extend(outcomes)

    alerts: list[EngineAlert] = []
    for (engine, store_id), b in per_pair.items():
        recent_stats = aggregate_outcomes(b["recent_outcomes"])
        baseline_stats = aggregate_outcomes(b["baseline_outcomes"])
        recent_polarised = (
            recent_stats.positive + recent_stats.negative
        )
        baseline_polarised = (
            baseline_stats.positive + baseline_stats.negative
        )

        if recent_polarised < min_recent:
            continue
        if baseline_polarised < min_recent:
            continue
        if (
            recent_stats.outcome_score is None
            or baseline_stats.outcome_score is None
        ):
            continue

        drop = (
            baseline_stats.outcome_score
            - recent_stats.outcome_score
        )
        if drop < threshold:
            continue

        scope_label = (
            f"@{store_id}" if store_id else " (fleet)"
        )
        alerts.append(EngineAlert(
            engine=engine,
            store_id=store_id,
            recent_executed=b["recent_executed"],
            baseline_executed=b["baseline_executed"],
            recent_score=recent_stats.outcome_score,
            baseline_score=baseline_stats.outcome_score,
            recent_polarised=recent_polarised,
            baseline_polarised=baseline_polarised,
            drop=drop,
            detail=(
                f"{recent_stats.outcome_score:.0%} recent vs "
                f"{baseline_stats.outcome_score:.0%} baseline "
                f"(drop {drop:.0%}){scope_label}"
            ),
        ))

    alerts.sort(key=lambda a: -a.drop)
    return alerts
