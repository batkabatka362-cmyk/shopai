"""Time-windowed outcome view.

Existing ``ApprovalQueue.engine_outcome_stats`` gives ALL-
TIME outcome rollup. Captain memory needs **recent** outcome
trends -- "is this engine improving / degrading?".

This module provides:
  - per-engine outcomes for the last N hours
  - per-cluster rollups for the last N hours
  - per-store outcome attribution by time window

Joins ``action_outcomes`` with ``pending_actions`` on
``action_id`` + filters by ``recorded_at >= cutoff``.

Used by:
  - MemoryAwareCaptainStrategy (future enhancement: time-
    windowed memory instead of all-time)
  - ``shopai outcomes report`` CLI (next commit)
  - Tier 1 orchestrator trend detection
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OutcomeWindow:
    """Outcome rollup for a (scope, time-window) tuple."""
    scope: str  # "engine:loyalty" or "cluster:retention" or "store:X"
    window_hours: float
    cutoff_at: float
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    total_revenue: float = 0.0
    sample_rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_outcomes(self) -> int:
        return (
            self.positive_count + self.negative_count
            + self.neutral_count
        )

    @property
    def positive_ratio(self) -> float:
        polarized = self.positive_count + self.negative_count
        if polarized == 0:
            return 0.0
        return round(self.positive_count / polarized, 3)

    @property
    def is_trending_positive(self) -> bool:
        return (
            self.total_outcomes >= 3
            and self.positive_ratio >= 0.7
        )

    @property
    def is_trending_negative(self) -> bool:
        return (
            self.total_outcomes >= 3
            and self.positive_ratio <= 0.3
        )


def _safe_metrics(metrics_json: str | None) -> dict[str, Any]:
    if not metrics_json:
        return {}
    try:
        parsed = json.loads(metrics_json)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _get_queue() -> Any:
    try:
        from core.approval.queue import get_approval_queue
        return get_approval_queue()
    except Exception:  # noqa: BLE001
        return None


def engine_outcomes_window(
    engine_name: str,
    *,
    window_hours: float = 168.0,  # 7 days default
    store_id: str | None = None,
) -> OutcomeWindow:
    """Return outcomes for one engine within the last
    ``window_hours``.

    Args:
        engine_name: Engine to aggregate.
        window_hours: Cutoff -- how many hours back.
        store_id: Optional per-store filter.

    Returns:
        Populated :class:`OutcomeWindow`.
    """
    cutoff = time.time() - (window_hours * 3600.0)
    scope = f"engine:{engine_name}"
    if store_id:
        scope += f"@{store_id}"

    out = OutcomeWindow(
        scope=scope,
        window_hours=window_hours,
        cutoff_at=cutoff,
    )

    queue = _get_queue()
    if queue is None:
        return out

    if store_id is None:
        query = (
            """SELECT o.polarity, o.metrics_json, o.recorded_at,
                      o.topic
               FROM action_outcomes o
               INNER JOIN pending_actions p
                 ON p.id = o.action_id
               WHERE p.engine = ?
                 AND o.recorded_at >= ?
               ORDER BY o.recorded_at DESC"""
        )
        params: tuple = (engine_name, cutoff)
    else:
        query = (
            """SELECT o.polarity, o.metrics_json, o.recorded_at,
                      o.topic
               FROM action_outcomes o
               INNER JOIN pending_actions p
                 ON p.id = o.action_id
               WHERE p.engine = ?
                 AND p.store_id = ?
                 AND o.recorded_at >= ?
               ORDER BY o.recorded_at DESC"""
        )
        params = (engine_name, store_id, cutoff)

    try:
        from core.approval.queue import _LOCK
        with _LOCK:
            rows = queue._conn.execute(query, params).fetchall()
    except Exception:  # noqa: BLE001
        return out

    for r in rows:
        polarity = r["polarity"]
        if polarity == "positive":
            out.positive_count += 1
        elif polarity == "negative":
            out.negative_count += 1
        else:
            out.neutral_count += 1
        metrics = _safe_metrics(r["metrics_json"])
        try:
            rev = float(metrics.get("revenue", 0.0) or 0.0)
        except (TypeError, ValueError):
            rev = 0.0
        out.total_revenue += rev
        if len(out.sample_rows) < 5:
            out.sample_rows.append({
                "polarity": polarity,
                "topic": r["topic"],
                "recorded_at": r["recorded_at"],
                "revenue": rev,
            })

    return out


def cluster_outcomes_window(
    cluster_name: str,
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> OutcomeWindow:
    """Roll up engine outcomes across a cluster's members
    within the time window."""
    from engines._clusters import get_cluster

    cutoff = time.time() - (window_hours * 3600.0)
    scope = f"cluster:{cluster_name}"
    if store_id:
        scope += f"@{store_id}"

    out = OutcomeWindow(
        scope=scope, window_hours=window_hours, cutoff_at=cutoff,
    )
    cluster = get_cluster(cluster_name)
    if cluster is None:
        return out

    for member in cluster.members:
        member_window = engine_outcomes_window(
            member, window_hours=window_hours, store_id=store_id,
        )
        out.positive_count += member_window.positive_count
        out.negative_count += member_window.negative_count
        out.neutral_count += member_window.neutral_count
        out.total_revenue += member_window.total_revenue

    return out


def fleet_outcomes_window(
    *,
    window_hours: float = 168.0,
) -> list[OutcomeWindow]:
    """Per-cluster outcome rollup across the whole fleet."""
    from engines._clusters import list_clusters

    return [
        cluster_outcomes_window(c.name, window_hours=window_hours)
        for c in list_clusters()
    ]
