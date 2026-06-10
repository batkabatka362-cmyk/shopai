"""Quota state computation.

Joins W963-118 cost events with W963-119 budget caps to
produce per-(store, adapter) snapshots that the CLI +
autopause bridge consume.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engines.per_store_costs.query import (
    _stream_events,
    costs_by_adapter,
    costs_by_store,
)

from .budget_config import resolve_cap, resolve_warn_ratio


class QuotaState(str, Enum):
    """One of three operator-actionable states."""
    UNLIMITED = "unlimited"   # No cap set
    OK = "ok"                  # spend < warn_ratio * cap
    WARN = "warn"              # spend in [warn_ratio, 1.0)
    CRITICAL = "critical"      # spend >= cap

    @property
    def severity_rank(self) -> int:
        return {
            "unlimited": 0,
            "ok": 0,
            "warn": 1,
            "critical": 2,
        }.get(self.value, 0)


@dataclass
class QuotaSnapshot:
    """Per-(store, adapter) quota state."""
    store_id: str
    adapter: str            # Empty string = "all adapters
                            # (total spend)"
    spend_usd: float
    cap_usd: float          # 0.0 = unlimited
    warn_ratio: float
    state: QuotaState
    headroom_usd: float     # cap - spend (0.0 if over)

    @property
    def pct_used(self) -> float:
        if self.cap_usd <= 0:
            return 0.0
        return min(
            999.9, self.spend_usd / self.cap_usd * 100.0,
        )


def _state_for(
    spend: float, cap: float, warn_ratio: float,
) -> QuotaState:
    if cap <= 0:
        return QuotaState.UNLIMITED
    if spend >= cap:
        return QuotaState.CRITICAL
    if spend >= cap * warn_ratio:
        return QuotaState.WARN
    return QuotaState.OK


def compute_snapshot(
    store_id: str,
    adapter: str = "",
    *,
    window_hours: float = 24.0,
) -> QuotaSnapshot:
    """Compute the QuotaSnapshot for one (store, adapter)
    pair over the lookback window.

    Empty adapter aggregates ALL adapters for that store.
    """
    cap = resolve_cap(
        store_id=store_id, adapter=adapter,
    )
    warn_ratio = resolve_warn_ratio()

    # Aggregate spend over the window
    if adapter:
        by_adapter = costs_by_adapter(
            store_id=store_id,
            window_hours=window_hours,
        )
        spend = float(
            by_adapter.get(adapter, {}).get(
                "cost_usd", 0.0,
            ) or 0.0
        )
    else:
        by_store = costs_by_store(
            window_hours=window_hours,
        )
        summary = by_store.get(store_id) or (
            by_store.get(store_id or "(fleet)")
        )
        spend = float(
            summary.total_cost_usd
        ) if summary else 0.0

    state = _state_for(spend, cap, warn_ratio)
    headroom = max(0.0, cap - spend) if cap > 0 else 0.0

    return QuotaSnapshot(
        store_id=store_id,
        adapter=adapter,
        spend_usd=round(spend, 4),
        cap_usd=round(cap, 4),
        warn_ratio=warn_ratio,
        state=state,
        headroom_usd=round(headroom, 4),
    )


def compute_all_snapshots(
    *,
    window_hours: float = 24.0,
) -> list[QuotaSnapshot]:
    """Compute snapshots for every (store, adapter) pair
    that has activity in the window PLUS any per-store
    totals.

    Always-included rows:
      - For each store with activity: total-spend snapshot
        (adapter="")
      - For each (store, adapter) pair with activity:
        per-adapter snapshot

    Includes the synthetic "(fleet)" store_id for events
    recorded without an active_store context.
    """
    snapshots: list[QuotaSnapshot] = []

    # All stores that appear in events
    by_store = costs_by_store(window_hours=window_hours)

    for sid, summary in by_store.items():
        # Total-spend per store
        snapshots.append(compute_snapshot(
            sid, adapter="",
            window_hours=window_hours,
        ))
        # Per-adapter rows
        for adapter_name in summary.by_adapter:
            snapshots.append(compute_snapshot(
                sid, adapter=adapter_name,
                window_hours=window_hours,
            ))

    # Stable sort: critical first, then warn, then ok.
    # Within same severity: highest pct_used first so the
    # operator sees the most-pressured row at top.
    snapshots.sort(
        key=lambda s: (
            -s.state.severity_rank,
            -s.pct_used,
            s.store_id,
            s.adapter,
        ),
    )
    return snapshots


def warn_stores(
    *, window_hours: float = 24.0,
) -> list[QuotaSnapshot]:
    """Return all snapshots in WARN state (sorted by
    severity)."""
    return [
        s for s in compute_all_snapshots(
            window_hours=window_hours,
        )
        if s.state == QuotaState.WARN
    ]


def critical_stores(
    *, window_hours: float = 24.0,
) -> list[QuotaSnapshot]:
    """Return all snapshots in CRITICAL state (cap
    exceeded). Caller can use this to trigger autopause."""
    return [
        s for s in compute_all_snapshots(
            window_hours=window_hours,
        )
        if s.state == QuotaState.CRITICAL
    ]
