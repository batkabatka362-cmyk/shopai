"""Revenue-aware orchestrator strategy -- substrate that closes
the attribution -> decisions loop.

The deterministic v1 strategy buckets each store into a priority
class (launching / growing / mature / at_risk / stagnant) and
maps to a fixed cluster_focus list. That's PRIORITY-aware but
not OUTCOME-aware: a store stuck on "mature" forever gets
[retention, pricing, merchandising] regardless of which of
those clusters has actually been making money.

This strategy WRAPS another strategy (defaults to
DeterministicOrchestratorStrategy) and re-ranks cluster_focus
by recent attributed revenue. Clusters that produced revenue
move toward the front of the focus list; clusters that produced
nothing stay at the back.

## Substrate-first

Like AICaptainStrategy, this is a SUBSTRATE plug-in that
operates on top of the deterministic base. Two consequences:

  1. If no attribution data exists, falls back to base verbatim.
     A fresh empire still gets coherent priorities.
  2. As attribution data grows (real Shopify orders flow in),
     reranking becomes more informed -- no code change needed.

## Algorithm

For each StorePriority from the base strategy:
  1. Pull attribution report (per-store, window_hours).
  2. Build {cluster: attributed_revenue} lookup.
  3. Re-sort cluster_focus by lookup desc.
  4. Annotate rationale with reranking summary.
  5. Return modified StorePriority.

## When this is wrong

  - Recent revenue isn't always future revenue. A spike in
    pricing-driven sales last week doesn't guarantee
    repeatability. We don't model decay.
  - Attribution is shared-credit; multi-tag orders give equal
    weight to every matched cluster. This biases focus toward
    clusters that always co-fire.

Both fix in the v2 algorithm (decay weights, last-touch).
"""
from __future__ import annotations

from typing import Any

from engines._orchestrator import (
    DeterministicOrchestratorStrategy,
    OrchestratorStrategy,
    StorePriority,
)


class RevenueAwareOrchestratorStrategy:
    """Re-rank cluster_focus by recent attributed revenue.

    Wraps a base strategy (default: deterministic) and reorders
    its cluster_focus list per store using attribution data.

    Args:
        base: Underlying strategy. Defaults to
            DeterministicOrchestratorStrategy.
        window_hours: Attribution lookback window.
        attribution_threshold: Minimum $ to consider a cluster
            "earning" -- below this, the cluster's position in
            focus is preserved (no demotion). Prevents noise
            from one $5 order pushing a cluster around.
    """

    def __init__(
        self,
        *,
        base: OrchestratorStrategy | None = None,
        window_hours: float = 168.0,
        attribution_threshold: float = 10.0,
    ) -> None:
        self.base = base or DeterministicOrchestratorStrategy()
        self.window_hours = window_hours
        self.attribution_threshold = attribution_threshold
        # Cache attribution by store-id within one fleet plan
        # so multiple priorities don't refetch.
        self._attr_cache: dict[str | None, dict[str, float]] = {}

    def decide_priority(
        self,
        store_id: str,
        world_model: dict[str, Any],
    ) -> StorePriority:
        base_priority = self.base.decide_priority(
            store_id, world_model,
        )

        # Pull per-store attribution (cached)
        cluster_revenue = self._cluster_revenue(store_id)
        if not cluster_revenue:
            # No attribution data -- return base verbatim
            return base_priority

        # Re-rank: clusters above threshold move forward in
        # focus list (desc by revenue). Clusters below threshold
        # keep relative order. Clusters not in focus stay out.
        focus = list(base_priority.cluster_focus)
        above: list[tuple[str, float]] = []
        below: list[str] = []
        for c in focus:
            rev = cluster_revenue.get(c, 0.0)
            if rev >= self.attribution_threshold:
                above.append((c, rev))
            else:
                below.append(c)
        above.sort(key=lambda kv: -kv[1])
        ranked = [c for c, _ in above] + below

        # Build annotation describing the reranking
        if above:
            top_str = ", ".join(
                f"{c}=${r:.0f}" for c, r in above[:3]
            )
            rationale_addon = (
                f" | revenue-aware rerank: {top_str}"
            )
        else:
            rationale_addon = (
                " | revenue-aware: no clusters above "
                f"${self.attribution_threshold:.0f} threshold"
            )

        return StorePriority(
            store_id=base_priority.store_id,
            priority=base_priority.priority,
            cluster_focus=ranked,
            rationale=base_priority.rationale + rationale_addon,
            signals={
                **base_priority.signals,
                "revenue_aware": True,
                "ranked_clusters": [c for c, _ in above],
            },
        )

    def _cluster_revenue(
        self, store_id: str | None,
    ) -> dict[str, float]:
        if store_id in self._attr_cache:
            return self._attr_cache[store_id]
        try:
            from engines._revenue_attribution import attribute_revenue
            report = attribute_revenue(
                window_hours=self.window_hours,
                store_id=store_id,
            )
        except Exception:  # noqa: BLE001
            self._attr_cache[store_id] = {}
            return self._attr_cache[store_id]
        out: dict[str, float] = {}
        for c in report.per_cluster:
            out[c.cluster] = c.attributed_revenue
        self._attr_cache[store_id] = out
        return out


def revenue_aware_enabled() -> bool:
    """Env-var gate. Set SHOPAI_REVENUE_AWARE_ORCHESTRATOR=1
    to enable in production. Off by default so the substrate
    is in place but operator opts in."""
    import os
    return bool(
        os.environ.get("SHOPAI_REVENUE_AWARE_ORCHESTRATOR")
    )
