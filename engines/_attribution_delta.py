"""Cycle-over-cycle revenue delta + regression detection.

Wave 11 persists attribution snapshots. Wave 12 makes the
time-series *consumable*: compute deltas between two
snapshots, flag clusters / engines that regressed, surface
alerts.

## Why deltas matter

Snapshot history alone is data. Operators need answers:

  - "Did last cycle improve revenue?"
  - "Which cluster's revenue dropped the most?"
  - "Alert me when attribution_rate falls 20% week-over-week"

The deterministic v1 here:

  1. Compute (latest, prior) snapshot pair (filterable by store).
  2. Diff per-cluster + per-engine attribution.
  3. Emit:
       - overall_delta_pct (+/- %)
       - per_cluster_deltas sorted by abs(change) desc
       - regression_alerts (clusters/engines with > N% drop)

## Substrate-first

`AttributionDelta` is a pure data type -- the strategy that
*reads* it (alerting, auto-pause, operator narrative) plugs in
on top. No model required for v1; future waves can layer
LLM-based root-cause analysis on the same delta shape.

## When the heuristic is wrong

  - First-time orders skew rates downward (denominator grows).
  - Single-cycle spikes look like regressions next cycle.
  - Multi-day comparison would be cleaner than cycle-to-cycle
    (one cycle ~= 1h, day comparison ~= 24x cycles).

For now, alerts use a configurable threshold and require >= N
attributed_orders on both sides so noise doesn't fire alerts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engines._attribution_snapshot import (
    AttributionSnapshot,
    recent_snapshots,
)


# Default threshold: alert when revenue drops >= 25% AND both
# snapshots had >= 3 attributed orders (so single-order
# fluctuations don't fire). Both knobs are configurable per-call.
_DEFAULT_REGRESSION_PCT = 0.25
_DEFAULT_MIN_ORDERS = 3


@dataclass
class ClusterDelta:
    cluster: str
    prior_revenue: float
    latest_revenue: float
    prior_orders: int
    latest_orders: int

    @property
    def revenue_delta(self) -> float:
        return round(self.latest_revenue - self.prior_revenue, 2)

    @property
    def revenue_delta_pct(self) -> float | None:
        """% change in revenue. None when prior was zero (can't
        divide). Use revenue_delta when prior is zero."""
        if self.prior_revenue == 0:
            return None
        return round(
            (self.latest_revenue - self.prior_revenue)
            / self.prior_revenue,
            3,
        )

    @property
    def direction(self) -> str:
        """up / down / flat / new / dropped."""
        if self.prior_revenue == 0 and self.latest_revenue == 0:
            return "flat"
        if self.prior_revenue == 0:
            return "new"
        if self.latest_revenue == 0:
            return "dropped"
        if self.latest_revenue > self.prior_revenue:
            return "up"
        if self.latest_revenue < self.prior_revenue:
            return "down"
        return "flat"


@dataclass
class EngineDelta:
    engine: str
    cluster: str | None
    prior_revenue: float
    latest_revenue: float
    prior_orders: int
    latest_orders: int

    @property
    def revenue_delta(self) -> float:
        return round(self.latest_revenue - self.prior_revenue, 2)

    @property
    def revenue_delta_pct(self) -> float | None:
        if self.prior_revenue == 0:
            return None
        return round(
            (self.latest_revenue - self.prior_revenue)
            / self.prior_revenue,
            3,
        )

    @property
    def direction(self) -> str:
        if self.prior_revenue == 0 and self.latest_revenue == 0:
            return "flat"
        if self.prior_revenue == 0:
            return "new"
        if self.latest_revenue == 0:
            return "dropped"
        if self.latest_revenue > self.prior_revenue:
            return "up"
        if self.latest_revenue < self.prior_revenue:
            return "down"
        return "flat"


@dataclass
class RegressionAlert:
    scope: str  # "cluster" or "engine"
    name: str
    prior_revenue: float
    latest_revenue: float
    delta_pct: float
    reason: str


@dataclass
class AttributionDelta:
    """Diff between two attribution snapshots."""
    prior_snapshot_id: str
    latest_snapshot_id: str
    prior_captured_at: float
    latest_captured_at: float
    prior_total_revenue: float
    latest_total_revenue: float
    prior_attributed_revenue: float
    latest_attributed_revenue: float
    per_cluster: list[ClusterDelta] = field(default_factory=list)
    per_engine: list[EngineDelta] = field(default_factory=list)
    alerts: list[RegressionAlert] = field(default_factory=list)

    @property
    def overall_revenue_delta(self) -> float:
        return round(
            self.latest_attributed_revenue
            - self.prior_attributed_revenue,
            2,
        )

    @property
    def overall_revenue_delta_pct(self) -> float | None:
        if self.prior_attributed_revenue == 0:
            return None
        return round(
            (
                self.latest_attributed_revenue
                - self.prior_attributed_revenue
            ) / self.prior_attributed_revenue,
            3,
        )

    @property
    def has_alerts(self) -> bool:
        return len(self.alerts) > 0


def _index_by_name(rows: list[dict], key: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        name = r.get(key)
        if name:
            out[str(name)] = r
    return out


def compute_delta(
    prior: AttributionSnapshot,
    latest: AttributionSnapshot,
    *,
    regression_pct: float = _DEFAULT_REGRESSION_PCT,
    min_orders: int = _DEFAULT_MIN_ORDERS,
) -> AttributionDelta:
    """Diff two snapshots; surface regression alerts.

    Args:
        prior: Earlier snapshot.
        latest: Newer snapshot.
        regression_pct: Trigger threshold (0.25 = 25% drop).
        min_orders: Both sides must have at least this many
            attributed_orders for an alert to fire.

    Returns:
        Populated :class:`AttributionDelta`.
    """
    delta = AttributionDelta(
        prior_snapshot_id=prior.snapshot_id,
        latest_snapshot_id=latest.snapshot_id,
        prior_captured_at=prior.captured_at,
        latest_captured_at=latest.captured_at,
        prior_total_revenue=prior.total_revenue_in_window,
        latest_total_revenue=latest.total_revenue_in_window,
        prior_attributed_revenue=prior.attributed_revenue,
        latest_attributed_revenue=latest.attributed_revenue,
    )

    # Per-cluster diff: walk the union of names
    prior_clusters = _index_by_name(prior.per_cluster, "cluster")
    latest_clusters = _index_by_name(latest.per_cluster, "cluster")
    all_clusters = set(prior_clusters) | set(latest_clusters)
    for name in sorted(all_clusters):
        p = prior_clusters.get(name, {})
        l_ = latest_clusters.get(name, {})
        cd = ClusterDelta(
            cluster=name,
            prior_revenue=float(p.get("attributed_revenue", 0.0) or 0.0),
            latest_revenue=float(l_.get("attributed_revenue", 0.0) or 0.0),
            prior_orders=int(p.get("attributed_orders", 0) or 0),
            latest_orders=int(l_.get("attributed_orders", 0) or 0),
        )
        delta.per_cluster.append(cd)
        _maybe_alert_cluster(delta, cd, regression_pct, min_orders)

    # Per-engine diff
    prior_engines = _index_by_name(prior.per_engine, "engine")
    latest_engines = _index_by_name(latest.per_engine, "engine")
    all_engines = set(prior_engines) | set(latest_engines)
    for name in sorted(all_engines):
        p = prior_engines.get(name, {})
        l_ = latest_engines.get(name, {})
        ed = EngineDelta(
            engine=name,
            cluster=(
                p.get("cluster") or l_.get("cluster") or None
            ),
            prior_revenue=float(p.get("attributed_revenue", 0.0) or 0.0),
            latest_revenue=float(l_.get("attributed_revenue", 0.0) or 0.0),
            prior_orders=int(p.get("attributed_orders", 0) or 0),
            latest_orders=int(l_.get("attributed_orders", 0) or 0),
        )
        delta.per_engine.append(ed)
        _maybe_alert_engine(delta, ed, regression_pct, min_orders)

    # Sort by abs(delta) desc so the biggest movers surface first
    delta.per_cluster.sort(
        key=lambda c: abs(c.revenue_delta), reverse=True,
    )
    delta.per_engine.sort(
        key=lambda e: abs(e.revenue_delta), reverse=True,
    )
    return delta


def _maybe_alert_cluster(
    delta: AttributionDelta,
    cd: ClusterDelta,
    regression_pct: float,
    min_orders: int,
) -> None:
    """Fire an alert when a cluster's revenue drops materially."""
    if cd.prior_revenue == 0:
        return
    if cd.prior_orders < min_orders or cd.latest_orders < min_orders:
        return
    pct = cd.revenue_delta_pct
    if pct is None or pct > -regression_pct:
        return
    delta.alerts.append(RegressionAlert(
        scope="cluster",
        name=cd.cluster,
        prior_revenue=cd.prior_revenue,
        latest_revenue=cd.latest_revenue,
        delta_pct=pct,
        reason=(
            f"revenue dropped {abs(pct) * 100:.0f}% "
            f"(${cd.prior_revenue:.0f} -> ${cd.latest_revenue:.0f})"
        ),
    ))


def _maybe_alert_engine(
    delta: AttributionDelta,
    ed: EngineDelta,
    regression_pct: float,
    min_orders: int,
) -> None:
    if ed.prior_revenue == 0:
        return
    if ed.prior_orders < min_orders or ed.latest_orders < min_orders:
        return
    pct = ed.revenue_delta_pct
    if pct is None or pct > -regression_pct:
        return
    delta.alerts.append(RegressionAlert(
        scope="engine",
        name=ed.engine,
        prior_revenue=ed.prior_revenue,
        latest_revenue=ed.latest_revenue,
        delta_pct=pct,
        reason=(
            f"revenue dropped {abs(pct) * 100:.0f}% "
            f"(${ed.prior_revenue:.0f} -> ${ed.latest_revenue:.0f})"
        ),
    ))


def latest_delta(
    *,
    store_id: str | None = None,
    regression_pct: float = _DEFAULT_REGRESSION_PCT,
    min_orders: int = _DEFAULT_MIN_ORDERS,
) -> AttributionDelta | None:
    """Convenience: diff the two most-recent snapshots.

    Returns None when fewer than 2 snapshots exist.
    """
    snaps = recent_snapshots(limit=2, store_id=store_id)
    if len(snaps) < 2:
        return None
    # recent_snapshots returns newest first
    latest, prior = snaps[0], snaps[1]
    return compute_delta(
        prior, latest,
        regression_pct=regression_pct,
        min_orders=min_orders,
    )
