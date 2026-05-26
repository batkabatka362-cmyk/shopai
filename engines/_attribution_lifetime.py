"""Lifetime AGI revenue contribution.

Snapshots (Wave 11) show CURRENT state. Delta (Wave 12) shows
single-cycle change. Neither answers "how much net revenue has
the AGI loop added since I started running it?".

This module computes lifetime contribution by summing the
POSITIVE cycle-over-cycle deltas across the snapshot history.
Negative deltas are NOT subtracted -- the question is "AGI's
contribution to revenue" not "AGI's net effect on revenue"
(those differ when the loop also shrinks revenue at times --
e.g. a misconfigured cycle).

## Two flavours

  - ``lifetime_added(limit=200)``: sum of positive cycle deltas.
    The "AGI contribution" figure.
  - ``lifetime_net(limit=200)``: sum of ALL deltas (positive +
    negative). Net effect including regressions.

## Caveats

Snapshots are bounded to last 200 entries. "Lifetime" really
means "across the snapshot retention window". When operators
need a true since-inception number, they need an external
ledger that persists past the snapshot rotation.

## Edge cases

  - Fewer than 2 snapshots -> 0 (no deltas computable).
  - Snapshots with NEW or DROPPED clusters/engines (first
    appearance in latest, absent from prior) -- counted as
    new revenue (treated as a positive delta of full amount).
  - Per-store scope: optional ``store_id`` filter scopes the
    rollup to one store's snapshot history.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LifetimeRollup:
    cycle_pairs_seen: int = 0
    total_added: float = 0.0
    total_lost: float = 0.0
    largest_gain: dict[str, Any] = field(default_factory=dict)
    largest_loss: dict[str, Any] = field(default_factory=dict)

    @property
    def net(self) -> float:
        return round(self.total_added - self.total_lost, 2)


def lifetime_rollup(
    *,
    limit: int = 200,
    store_id: str | None = None,
) -> LifetimeRollup:
    """Build the lifetime contribution rollup."""
    try:
        from engines._attribution_snapshot import recent_snapshots
        from engines._attribution_delta import compute_delta
    except Exception:  # noqa: BLE001
        return LifetimeRollup()

    snaps = recent_snapshots(limit=limit, store_id=store_id)
    if len(snaps) < 2:
        return LifetimeRollup()

    rollup = LifetimeRollup()
    # snaps is newest first; we walk pairs (newer, older) and
    # the delta is "what changed between cycle N and cycle N+1
    # (newer)". A positive overall_revenue_delta means revenue
    # grew that cycle.
    for i in range(len(snaps) - 1):
        latest = snaps[i]
        prior = snaps[i + 1]
        try:
            delta = compute_delta(prior, latest)
        except Exception:  # noqa: BLE001
            continue
        rollup.cycle_pairs_seen += 1
        change = delta.overall_revenue_delta
        if change > 0:
            rollup.total_added = round(
                rollup.total_added + change, 2,
            )
            if (
                not rollup.largest_gain
                or change > rollup.largest_gain.get("amount", 0)
            ):
                rollup.largest_gain = {
                    "amount": change,
                    "snapshot_id": latest.snapshot_id,
                    "captured_at": latest.captured_at,
                }
        elif change < 0:
            rollup.total_lost = round(
                rollup.total_lost + abs(change), 2,
            )
            if (
                not rollup.largest_loss
                or abs(change)
                > rollup.largest_loss.get("amount", 0)
            ):
                rollup.largest_loss = {
                    "amount": abs(change),
                    "snapshot_id": latest.snapshot_id,
                    "captured_at": latest.captured_at,
                }
    return rollup
