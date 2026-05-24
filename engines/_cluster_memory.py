"""Captain memory -- per-cluster outcome rollup.

Aggregates Pattern Z + ApprovalQueue history at the cluster
level. Captain reads "how has my cluster been performing?"
to inform future decisions.

## Why per-cluster

Today, ``ApprovalQueue.engine_outcome_stats(engine)`` gives
per-ENGINE outcome data. Captain needs per-CLUSTER rollup:
"retention cluster: 87% success, 12% failure, 1% timeout".

Without this, captain can't notice "my cluster is degrading"
or "this cluster is healthy, fire more aggressively."

## Data sources

  ApprovalQueue:
    - per-engine outcome stats (positive/negative/neutral)
    - per-engine fire counts (executed/failed/rejected)

  Pattern Z (via DataArchitecture):
    - per-engine action records (when recorded)

Per-cluster rollup = sum across cluster members.

## What captain decides differently with memory

  - cluster failing recently -> conservative member selection
    (only safest engines this cycle)
  - cluster succeeding -> aggressive member firing
  - specific member underperforming -> exclude that member
    even if signal matches

For v1, the memory is observational -- captain logs cluster
health but doesn't automatically adjust. Adjustment logic
plugs in via MemoryAwareCaptainStrategy (future).

## Pluggable

ClusterMemoryStrategy protocol -- plug in:
  - QueueOutcomeRollup (v1 default, this module)
  - DataArchitectureRollup (when Phase 8 data is rich)
  - ExternalMetricsRollup (revenue attribution from Shopify
    orders -- ultimate ground truth)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from engines._clusters import Cluster, get_cluster


@dataclass
class ClusterHealth:
    """Per-cluster outcome rollup snapshot."""
    cluster: str
    member_count: int
    wired_count: int
    # Outcome stats aggregated across cluster members
    total_executed: int = 0
    total_failed: int = 0
    total_rejected: int = 0
    total_pending: int = 0
    positive_outcomes: int = 0
    negative_outcomes: int = 0
    neutral_outcomes: int = 0
    total_revenue: float = 0.0
    # Per-member breakdown for drill-down
    member_health: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_actions(self) -> int:
        return (
            self.total_executed + self.total_failed
            + self.total_rejected
        )

    @property
    def success_rate(self) -> float:
        """Executed / (executed + failed + rejected) when any."""
        total = self.total_actions
        if total == 0:
            return 0.0
        return round(self.total_executed / total, 3)

    @property
    def positive_ratio(self) -> float:
        """Positive outcome ratio when any outcomes recorded."""
        total_oc = (
            self.positive_outcomes + self.negative_outcomes
            + self.neutral_outcomes
        )
        if total_oc == 0:
            return 0.0
        return round(self.positive_outcomes / total_oc, 3)

    @property
    def health_verdict(self) -> str:
        """Single-word health: healthy / warning / unhealthy / unknown."""
        if self.total_actions == 0:
            return "unknown"
        if self.success_rate >= 0.8:
            return "healthy"
        if self.success_rate >= 0.5:
            return "warning"
        return "unhealthy"


class ClusterMemoryStrategy(Protocol):
    """Pluggable: how to compute cluster health rollup."""

    def health_for(self, cluster: Cluster) -> ClusterHealth:
        ...


class QueueOutcomeRollup:
    """v1 default: aggregate ApprovalQueue stats per cluster."""

    def __init__(self) -> None:
        self._queue_stats: dict[str, dict[str, int]] | None = None
        self._outcomes_cache: dict[str, dict[str, Any]] = {}

    def _load_queue_stats(self) -> dict[str, dict[str, int]]:
        if self._queue_stats is not None:
            return self._queue_stats
        try:
            from core.approval.queue import get_approval_queue
            self._queue_stats = (
                get_approval_queue().stats_by_engine() or {}
            )
        except Exception:  # noqa: BLE001
            self._queue_stats = {}
        return self._queue_stats

    def _load_outcomes(self, engine_name: str) -> dict[str, Any]:
        if engine_name in self._outcomes_cache:
            return self._outcomes_cache[engine_name]
        try:
            from core.approval.queue import get_approval_queue
            outcomes = (
                get_approval_queue().engine_outcome_stats(
                    engine_name,
                ) or {}
            )
        except Exception:  # noqa: BLE001
            outcomes = {}
        self._outcomes_cache[engine_name] = outcomes
        return outcomes

    def _load_wired(self) -> set[str]:
        try:
            from engines._writeback_audit import (
                audit_writeback_coverage,
            )
            wb = audit_writeback_coverage("engines")
            return {
                s.name for s in wb.engines
                if s.status == "wired"
            }
        except Exception:  # noqa: BLE001
            return set()

    def health_for(self, cluster: Cluster) -> ClusterHealth:
        queue_stats = self._load_queue_stats()
        wired = self._load_wired()

        health = ClusterHealth(
            cluster=cluster.name,
            member_count=len(cluster.members),
            wired_count=sum(
                1 for m in cluster.members if m in wired
            ),
        )

        for engine in sorted(cluster.members):
            stats = queue_stats.get(engine, {})
            executed = int(stats.get("executed", 0) or 0)
            failed = int(stats.get("failed", 0) or 0)
            rejected = int(stats.get("rejected", 0) or 0)
            pending = int(stats.get("pending", 0) or 0)

            outcomes = self._load_outcomes(engine)
            pos = int(outcomes.get("positive_count", 0) or 0)
            neg = int(outcomes.get("negative_count", 0) or 0)
            neu = int(outcomes.get("neutral_count", 0) or 0)
            rev = float(outcomes.get("total_revenue", 0.0) or 0.0)

            health.total_executed += executed
            health.total_failed += failed
            health.total_rejected += rejected
            health.total_pending += pending
            health.positive_outcomes += pos
            health.negative_outcomes += neg
            health.neutral_outcomes += neu
            health.total_revenue += rev

            health.member_health.append({
                "engine": engine,
                "wired": engine in wired,
                "executed": executed,
                "failed": failed,
                "rejected": rejected,
                "pending": pending,
                "positive": pos,
                "negative": neg,
                "revenue": rev,
            })

        return health


def cluster_health_rollup(
    cluster_name: str,
    *,
    strategy: ClusterMemoryStrategy | None = None,
) -> ClusterHealth | None:
    """Convenience: compute health for one cluster by name."""
    cluster = get_cluster(cluster_name)
    if cluster is None:
        return None
    strategy = strategy or QueueOutcomeRollup()
    return strategy.health_for(cluster)


def fleet_cluster_health(
    strategy: ClusterMemoryStrategy | None = None,
) -> list[ClusterHealth]:
    """Compute health for ALL clusters. Useful for dashboards
    + Tier 1 orchestrator's per-cluster awareness."""
    from engines._clusters import list_clusters
    strategy = strategy or QueueOutcomeRollup()
    return [strategy.health_for(c) for c in list_clusters()]
