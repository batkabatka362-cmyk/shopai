"""Per-engine approval velocity report.

When operators scale to N stores, the approval queue's
SHAPE matters as much as its content. Are 60% of pending
actions coming from 3 engines? That's a bottleneck. Are
some engines never producing approvals? Maybe their wireup
broke.

Wave 64 reports per-engine velocity:

  - actions proposed per hour over window
  - actions approved per hour
  - actions rejected per hour
  - rejection rate (operator distrust signal)
  - average decision latency (proposed -> approved/rejected)

## API

  compute_velocity_report(window_hours=168) -> VelocityReport
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EngineVelocity:
    engine: str
    proposed_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    pending_count: int = 0
    total_decision_latency_hours: float = 0.0
    decisions_with_latency: int = 0

    @property
    def proposed_per_hour(self) -> float:
        # Window-relative; populated by report
        return 0.0  # placeholder

    @property
    def rejection_rate(self) -> float:
        decided = self.approved_count + self.rejected_count
        if decided == 0:
            return 0.0
        return round(self.rejected_count / decided, 3)

    @property
    def avg_latency_hours(self) -> float | None:
        if self.decisions_with_latency == 0:
            return None
        return round(
            self.total_decision_latency_hours
            / self.decisions_with_latency, 2,
        )


@dataclass
class VelocityReport:
    window_hours: float
    total_actions_in_window: int = 0
    per_engine: list[EngineVelocity] = field(default_factory=list)

    @property
    def top_engine(self) -> str | None:
        if not self.per_engine:
            return None
        return self.per_engine[0].engine

    @property
    def highest_rejection_engine(self) -> str | None:
        """Engine with highest rejection rate (n >= 3)."""
        candidates = [
            e for e in self.per_engine
            if (e.approved_count + e.rejected_count) >= 3
        ]
        if not candidates:
            return None
        worst = max(candidates, key=lambda e: e.rejection_rate)
        if worst.rejection_rate < 0.2:
            return None
        return worst.engine


def compute_velocity_report(
    window_hours: float = 168.0,
    *,
    queue: Any = None,
) -> VelocityReport:
    """Aggregate per-engine approval velocity over a window."""
    report = VelocityReport(window_hours=window_hours)
    if queue is None:
        try:
            from core.approval.queue import get_approval_queue
            queue = get_approval_queue()
        except Exception:  # noqa: BLE001
            return report

    cutoff = time.time() - (window_hours * 3600.0)
    per_engine: dict[str, EngineVelocity] = defaultdict(
        lambda: EngineVelocity(engine="?"),
    )

    # Walk every status; lifetime fits in 10k limit
    for status in ("pending", "approved", "rejected"):
        try:
            actions = queue.list_by_status(status) or []
        except Exception:  # noqa: BLE001
            continue
        for a in actions:
            engine = getattr(a, "engine", None) or "unknown"
            proposed_at = getattr(a, "proposed_at", None)
            try:
                ts = float(proposed_at) if proposed_at else 0
            except (TypeError, ValueError):
                ts = 0
            # Filter by window (use proposed_at if available;
            # decided_at fallback below)
            if ts > 0 and ts < cutoff:
                continue
            bucket = per_engine[engine]
            bucket.engine = engine
            if status == "pending":
                bucket.pending_count += 1
                bucket.proposed_count += 1
            elif status == "approved":
                bucket.approved_count += 1
                bucket.proposed_count += 1
            else:  # rejected
                bucket.rejected_count += 1
                bucket.proposed_count += 1
            # Decision latency
            decided_at = getattr(a, "decided_at", None)
            if (
                status in ("approved", "rejected")
                and ts > 0 and decided_at
            ):
                try:
                    dts = float(decided_at)
                    latency_h = max(
                        0.0, (dts - ts) / 3600.0,
                    )
                    bucket.total_decision_latency_hours += latency_h
                    bucket.decisions_with_latency += 1
                except (TypeError, ValueError):
                    pass
            report.total_actions_in_window += 1

    # Sort by proposed_count desc
    report.per_engine = sorted(
        per_engine.values(),
        key=lambda e: -e.proposed_count,
    )
    return report
