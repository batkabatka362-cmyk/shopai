"""Revenue-aware captain strategy -- per-engine attribution
shapes member selection within a cluster.

Wave 8 wrapped the orchestrator to re-rank CLUSTERS by
attributed revenue. Wave 10 (this module) wraps the captain
to re-rank MEMBERS within a cluster.

## Substrate-first

Like RevenueAwareOrchestratorStrategy, this is a wrapper. Takes
any base CaptainStrategy + uses per-engine attribution to:

  1. Re-order the returned members list (high-revenue engines
     first -- matters when downstream fires top-N under budget)
  2. Optionally drop members that have ZERO attribution when
     ALL other members in the cluster have positive attribution
     (signal that this member has been chronic underperformer)

The substrate stays the same. Plug in different decision logic
later by composing different strategies.

## When this is wrong

  - "Zero attribution" can mean "never fired" not "fired and
    failed". A brand-new engine has zero history; that's not
    a reason to skip it.
  - Per-engine attribution is shared-credit-split, so a
    co-firing engine that always rides with a winner gets
    credit it didn't earn.

Both fixed in v2 (fire-count gating, last-touch attribution).
For now this is OPT-IN via SHOPAI_REVENUE_AWARE_CAPTAIN=1.
"""
from __future__ import annotations

from typing import Any

from engines._clusters import Cluster
from engines._cluster_captain import (
    CaptainStrategy,
    DeterministicCaptainStrategy,
)


class RevenueAwareCaptainStrategy:
    """Wrap a base captain strategy; re-rank + (optionally)
    prune members by per-engine attribution.

    Args:
        base: Underlying captain. Defaults to Deterministic.
        window_hours: Attribution lookback window.
        attribution_threshold: Minimum $ to be considered
            "earning". Below this, the engine's per-engine
            revenue is treated as 0 (noise filter).
        drop_zeros_when_others_earning: If True, members with
            zero attribution are DROPPED when at least one
            other member in the cluster has earnings above the
            threshold. False = keep all, just reorder.
    """

    def __init__(
        self,
        *,
        base: CaptainStrategy | None = None,
        window_hours: float = 168.0,
        attribution_threshold: float = 10.0,
        drop_zeros_when_others_earning: bool = False,
    ) -> None:
        self.base = base or DeterministicCaptainStrategy()
        self.window_hours = window_hours
        self.attribution_threshold = attribution_threshold
        self.drop_zeros_when_others_earning = (
            drop_zeros_when_others_earning
        )
        # Cache attribution map at strategy instance level so
        # repeated captain invocations in one cycle share it.
        self._engine_revenue: dict[str, float] | None = None

    def select_members(
        self,
        cluster: Cluster,
        wired_members: list[str],
        signals: dict[str, Any],
    ) -> list[str]:
        base_picks = self.base.select_members(
            cluster, wired_members, signals,
        )
        if not base_picks:
            return base_picks

        revenue = self._load_engine_revenue()
        if not revenue:
            # No attribution data -> base verbatim
            return base_picks

        # Build per-engine scores within the BASE picks (don't
        # introduce engines that base didn't choose)
        scored: list[tuple[str, float]] = []
        for engine in base_picks:
            rev = revenue.get(engine, 0.0)
            # Apply threshold: revenue below threshold counts as 0
            rev = rev if rev >= self.attribution_threshold else 0.0
            scored.append((engine, rev))

        # Optional pruning: if some members are earning, drop
        # those with zero. Only kicks in when AT LEAST ONE
        # member has positive revenue -- avoids cold-start
        # paralysis where everyone is zero.
        if self.drop_zeros_when_others_earning:
            any_earning = any(rev > 0 for _, rev in scored)
            if any_earning:
                scored = [
                    (e, r) for e, r in scored if r > 0
                ]
                if not scored:
                    # Safety: never strand the cluster empty
                    return base_picks

        # Sort by revenue desc, but preserve base order for ties
        # (Python's sort is stable -- equal-revenue engines keep
        # their base-order positions)
        scored.sort(key=lambda kv: -kv[1])
        return [e for e, _ in scored]

    def _load_engine_revenue(self) -> dict[str, float]:
        if self._engine_revenue is not None:
            return self._engine_revenue
        try:
            from engines._revenue_attribution import attribute_revenue
            report = attribute_revenue(
                window_hours=self.window_hours,
            )
        except Exception:  # noqa: BLE001
            self._engine_revenue = {}
            return self._engine_revenue
        out: dict[str, float] = {}
        for e in report.per_engine:
            out[e.engine] = e.attributed_revenue
        self._engine_revenue = out
        return out


def revenue_aware_captain_enabled() -> bool:
    """Env-var gate. Set SHOPAI_REVENUE_AWARE_CAPTAIN=1 to
    enable in production. Off by default so the substrate is
    in place but operator opts in."""
    import os
    return bool(os.environ.get("SHOPAI_REVENUE_AWARE_CAPTAIN"))
