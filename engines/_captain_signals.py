"""Captain signal collector -- auto-derive cluster signals.

Reads world-model + Pattern Z aggregates + ApprovalQueue
state to produce the per-cluster signals dict that
SignalDrivenCaptainStrategy needs.

Without this layer, operators must pass ``--signals JSON``
every time. With it, the captain reads its environment
automatically -- truly autonomous behavior.

## Signal sources

  world-model:
    stats.products / orders / total_revenue / customers
    sync.last_sync_at
    approvals.pending_count

  Pattern Z (via ApprovalQueue.stats_by_engine):
    per-engine fire counts (recent firings = high-attention
    engines)
    per-engine failure rates

  ApprovalQueue:
    pending modifications waiting for operator
    recent rejections (operator pushback signal)

## Signal extractors (per cluster)

Each cluster has a small per-cluster extractor function
that maps world-model + queue stats into the specific
signals its captain rules expect:

  retention: at_risk_count, abandoned_cart_count
  pricing:   thin_margin_count, discount_opportunity_count
  quality:   defect_count, warranty_claim_count,
             fraud_count, negative_review_count
  fulfillment: stockout_imminent_count, pending_returns_count
  merchandising: declining_product_count
  acquisition:   new_signups_count

For v1, these are HEURISTICS derived from store stats. As
Phase 8 outcome data accumulates, real aggregates replace
heuristics (e.g. at_risk_count from churn_prediction's
historical outputs).

## Pluggable

SignalCollectorStrategy protocol: anyone can plug in a
smarter collector (LLM, ML model, external API).
"""
from __future__ import annotations

from typing import Any, Protocol


class SignalCollectorStrategy(Protocol):
    """Pluggable: per-cluster signal extraction."""

    def collect(
        self,
        store_id: str,
        world_model: dict[str, Any],
        queue_stats: dict[str, dict[str, int]],
    ) -> dict[str, dict[str, Any]]:
        """Return ``signals_by_cluster`` dict.

        Keys: cluster names. Values: signals dict for each
        cluster's captain.
        """
        ...


class HeuristicSignalCollector:
    """v1 deterministic signal collector.

    Reads world-model stats + queue stats. Derives domain
    signals via heuristics. Returns ALL clusters with at
    least a default signals dict (empty is fine -- captain
    falls back to default rules).
    """

    def collect(
        self,
        store_id: str,
        world_model: dict[str, Any],
        queue_stats: dict[str, dict[str, int]],
    ) -> dict[str, dict[str, Any]]:
        wm = world_model or {}
        stats = wm.get("stats", {}) or {}
        approvals = wm.get("approvals", {}) or {}

        products = int(stats.get("products", 0) or 0)
        orders = int(stats.get("orders", 0) or 0)
        customers = int(stats.get("customers", 0) or 0)
        revenue = float(stats.get("total_revenue", 0.0) or 0.0)

        # Pending approval count -- signal that operator
        # has items to review (helps captain not pile MORE
        # modifications on)
        pending = int(approvals.get("pending_count", 0) or 0)

        # Recent firings: how many EXECUTED actions in
        # queue per engine. High count = high-attention
        # engine.
        recent_fires: dict[str, int] = {}
        for engine, statuses in queue_stats.items():
            recent_fires[engine] = int(statuses.get("executed", 0) or 0)

        out: dict[str, dict[str, Any]] = {}

        # retention: customers exist + recently active
        if customers > 0:
            # Heuristic: assume some customers are at-risk
            # if total customers > 10. Real signal comes
            # from churn_prediction's historical outputs.
            at_risk = max(0, customers // 10) if customers > 10 else 0
            out["retention"] = {
                "at_risk_count": at_risk,
                # abandoned_cart_count -- need real data;
                # placeholder is 0
                "abandoned_cart_count": 0,
            }

        # pricing: products exist + revenue trend
        if products > 0:
            # Heuristic: thin margin if avg order is very low
            avg_order = revenue / orders if orders > 0 else 0.0
            thin_margin_estimate = (
                max(1, products // 20) if avg_order < 20.0
                else 0
            )
            out["pricing"] = {
                "thin_margin_count": thin_margin_estimate,
                "discount_opportunity_count": (
                    1 if products > 10 else 0
                ),
            }

        # quality: based on store maturity
        if orders > 0:
            # Real defect_count would come from order_quality
            # engine history. Placeholder: assume 1% defect
            # rate above 100 orders.
            defects = max(0, (orders - 100) // 100)
            out["quality"] = {
                "defect_count": defects,
                "warranty_claim_count": 0,
                "fraud_count": 0,
                "negative_review_count": 0,
            }

        # fulfillment: low product count w/ orders = stockout
        # imminent
        if products > 0 and orders > 0:
            stockout_imm = 1 if products < 20 else 0
            out["fulfillment"] = {
                "stockout_imminent_count": stockout_imm,
                "pending_returns_count": 0,
            }

        # merchandising: every cycle gets at least defaults
        out["merchandising"] = {
            "declining_product_count": (
                1 if products > 50 and orders < 10 else 0
            ),
        }

        # acquisition: low customer count = need acquisition
        if customers < 10:
            out["acquisition"] = {"new_signups_count": 1}
        else:
            out["acquisition"] = {}

        # discovery: investigate when store is stagnant
        if orders == 0 and products > 5:
            out["discovery"] = {"investigate": 1}
        else:
            out["discovery"] = {}

        # governance: always-on (no signal-gated rules)
        out["governance"] = {}

        # setup: only signal if store is new
        if products < 5 or orders == 0:
            out["setup"] = {"first_launch": True}

        # content: only signal if operator opts in (returned
        # but empty -- supervisor handles opt-in gating)
        out["content"] = {}

        return out


def collect_signals_for_store(
    store_id: str,
    *,
    world_model: dict[str, Any] | None = None,
    queue_stats: dict[str, dict[str, int]] | None = None,
    strategy: SignalCollectorStrategy | None = None,
) -> dict[str, dict[str, Any]]:
    """Pull signals_by_cluster for one store.

    Args:
        store_id: The store to collect for.
        world_model: Optional pre-fetched world-model. If
            None, the collector tries to fetch it via
            ``core.world_model.WorldModel.snapshot``.
        queue_stats: Optional pre-fetched
            ``ApprovalQueue.stats_by_engine()`` rollup. If
            None, the collector tries to fetch it.
        strategy: Pluggable collector. Defaults to
            :class:`HeuristicSignalCollector`.

    Returns:
        ``signals_by_cluster`` dict suitable for
        ``make_supervisor_plan(signals_by_cluster=...)`` or
        ``make_fleet_plan`` via Tier 1.
    """
    strategy = strategy or HeuristicSignalCollector()

    if world_model is None:
        try:
            from core.world_model import WorldModel
            world_model = WorldModel().snapshot(
                store_id, skip_live=True,
            )
        except Exception:  # noqa: BLE001
            world_model = {}

    if queue_stats is None:
        try:
            from core.approval.queue import get_approval_queue
            queue_stats = (
                get_approval_queue().stats_by_engine() or {}
            )
        except Exception:  # noqa: BLE001
            queue_stats = {}

    return strategy.collect(store_id, world_model, queue_stats)
