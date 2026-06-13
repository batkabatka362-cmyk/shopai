"""Revenue attribution: connect Shopify orders to cluster firings.

After a cycle runs, captains have tagged products / customers /
orders. Orders that subsequently happen may carry those tags
(or be on those tagged products). This module joins:

  - Recent cycle history (which clusters fired when)
  - Recent Shopify orders (revenue + line items + customer)
  - Tag catalog (which tags map to which clusters)

To produce a per-cluster revenue attribution:

  attribution = {
    "cluster": "retention",
    "window_hours": 168,
    "attributed_revenue": $1247.50,
    "attributed_orders": 12,
    "tag_matches": [...],
    "confidence": "high" | "medium" | "low",
  }

## Attribution method (v1 deterministic)

For each recent order within the attribution window:
  1. Pull the order's tags + line item product tags
  2. For each tag, look up which cluster wrote it
     (via engines._tag_catalog)
  3. Split the order's revenue equally among matched clusters
     (multi-tag overlap = revenue split)
  4. Aggregate per cluster

This is "shared credit" attribution. Not perfect but
operationally meaningful. Future plug-ins (v2):
  - First-touch attribution
  - Last-touch attribution
  - Time-decay weighting
  - Causal correlation (control group)

## Pluggable

Same protocol-based pattern as other substrate layers.
AttributionStrategy interface for plugging in better
algorithms when data justifies them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ClusterAttribution:
    """Revenue + order count attributed to one cluster."""
    cluster: str
    window_hours: float
    attributed_revenue: float = 0.0
    attributed_orders: int = 0
    tag_matches: list[str] = field(default_factory=list)
    sample_orders: list[dict[str, Any]] = field(default_factory=list)

    @property
    def confidence(self) -> str:
        """Low when few orders / no overlap, high when many."""
        if self.attributed_orders == 0:
            return "none"
        if self.attributed_orders >= 10:
            return "high"
        if self.attributed_orders >= 3:
            return "medium"
        return "low"


@dataclass
class EngineAttribution:
    """Revenue + order count attributed to one engine.

    Same shared-credit math as cluster level but joined via the
    tag catalog's engine field (which engine wrote which tag).
    Lets the operator answer "which engine in retention cluster
    pulled the revenue?".
    """
    engine: str
    cluster: str | None
    window_hours: float
    attributed_revenue: float = 0.0
    attributed_orders: int = 0
    tag_matches: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> str:
        if self.attributed_orders == 0:
            return "none"
        if self.attributed_orders >= 10:
            return "high"
        if self.attributed_orders >= 3:
            return "medium"
        return "low"


@dataclass
class AttributionReport:
    """Per-cluster attribution rollup over a time window."""
    window_hours: float
    total_orders_in_window: int = 0
    total_revenue_in_window: float = 0.0
    per_cluster: list[ClusterAttribution] = field(default_factory=list)
    per_engine: list[EngineAttribution] = field(default_factory=list)

    @property
    def attributed_revenue(self) -> float:
        return sum(c.attributed_revenue for c in self.per_cluster)

    @property
    def attribution_rate(self) -> float:
        """% of total revenue that was attributable to ANY cluster."""
        if self.total_revenue_in_window == 0:
            return 0.0
        return round(
            self.attributed_revenue / self.total_revenue_in_window,
            3,
        )


class AttributionStrategy(Protocol):
    """Pluggable revenue-attribution algorithm."""

    def attribute(
        self,
        orders: list[dict[str, Any]],
        tag_to_cluster: dict[str, str],
    ) -> dict[str, ClusterAttribution]:
        ...


class SharedCreditStrategy:
    """v1: equally split revenue across all matched clusters.

    Most operationally meaningful default. Each cluster that
    "touched" the order (via any tag) gets 1/N share where N
    is the number of clusters that touched the order.
    """

    def attribute(
        self,
        orders: list[dict[str, Any]],
        tag_to_cluster: dict[str, str],
    ) -> dict[str, ClusterAttribution]:
        out: dict[str, ClusterAttribution] = {}

        for order in orders:
            order_id = str(order.get("id", "") or order.get("order_id", ""))
            try:
                total = float(order.get("total_price", 0.0) or 0.0)
            except (TypeError, ValueError):
                total = 0.0

            tags = self._gather_tags(order)
            matched_clusters: set[str] = set()
            tag_hits: list[str] = []
            for tag in tags:
                cluster = tag_to_cluster.get(tag)
                if cluster is None:
                    # Try namespace lookup -- prefix match
                    # for dynamic tags (e.g. "cohort:2026-05"
                    # matches "cohort:*")
                    cluster = self._match_dynamic(
                        tag, tag_to_cluster,
                    )
                if cluster is not None:
                    matched_clusters.add(cluster)
                    tag_hits.append(tag)

            if not matched_clusters:
                continue

            share = total / len(matched_clusters)
            for cluster in matched_clusters:
                attr = out.setdefault(
                    cluster,
                    ClusterAttribution(
                        cluster=cluster, window_hours=0.0,
                    ),
                )
                attr.attributed_revenue += share
                attr.attributed_orders += 1
                for tag in tag_hits:
                    if tag not in attr.tag_matches:
                        attr.tag_matches.append(tag)
                if len(attr.sample_orders) < 5:
                    attr.sample_orders.append({
                        "order_id": order_id,
                        "total_price": total,
                        "share": share,
                        "tags": tag_hits,
                    })

        return out

    def _gather_tags(
        self, order: dict[str, Any],
    ) -> set[str]:
        tags: set[str] = set()
        # Order-level tags
        raw = order.get("tags")
        if isinstance(raw, str):
            tags.update(t.strip() for t in raw.split(",") if t.strip())
        elif isinstance(raw, list):
            tags.update(str(t).strip() for t in raw if t)
        # Customer tags
        customer = order.get("customer", {})
        if isinstance(customer, dict):
            ctags = customer.get("tags")
            if isinstance(ctags, str):
                tags.update(
                    t.strip() for t in ctags.split(",") if t.strip()
                )
            elif isinstance(ctags, list):
                tags.update(
                    str(t).strip() for t in ctags if t
                )
        # Line item product tags (when included by adapter)
        for item in order.get("line_items", []) or []:
            if not isinstance(item, dict):
                continue
            itags = item.get("tags") or []
            if isinstance(itags, str):
                tags.update(
                    t.strip() for t in itags.split(",") if t.strip()
                )
            elif isinstance(itags, list):
                tags.update(str(t).strip() for t in itags if t)
        return {t for t in tags if t}

    def _match_dynamic(
        self,
        tag: str,
        tag_to_cluster: dict[str, str],
    ) -> str | None:
        """For tags like 'cohort:2026-05' that aren't in the
        static map, look for the namespace prefix
        ('cohort:*')."""
        if ":" in tag:
            ns = tag.split(":", 1)[0]
            return tag_to_cluster.get(f"{ns}:*")
        if "-" in tag:
            # Try progressively shorter dash prefixes
            parts = tag.split("-")
            for n in range(len(parts) - 1, 0, -1):
                prefix = "-".join(parts[:n]) + "-*"
                if prefix in tag_to_cluster:
                    return tag_to_cluster[prefix]
        return None


def _build_tag_to_cluster_map() -> dict[str, str]:
    """Inverted index from tag -> cluster name.

    Uses the existing tag_catalog (which clusters write which
    tags) + cluster definitions (which engines belong to which
    cluster).
    """
    out: dict[str, str] = {}
    try:
        from engines._tag_catalog import catalog_tags
        from engines._clusters import cluster_for_engine
    except Exception:  # noqa: BLE001
        return out

    try:
        catalog = catalog_tags("engines")
    except Exception:  # noqa: BLE001
        return out

    for entry in catalog.entries:
        cluster = cluster_for_engine(entry.engine)
        if cluster is None:
            continue
        out[entry.tag] = cluster.name
    return out


def _build_tag_to_engine_map() -> dict[str, str]:
    """Inverted index from tag -> engine name.

    Mirrors ``_build_tag_to_cluster_map`` but keeps the engine
    granularity. The tag catalog already carries the engine
    field per entry; this just flattens it.
    """
    out: dict[str, str] = {}
    try:
        from engines._tag_catalog import catalog_tags
    except Exception:  # noqa: BLE001
        return out
    try:
        catalog = catalog_tags("engines")
    except Exception:  # noqa: BLE001
        return out
    for entry in catalog.entries:
        out[entry.tag] = entry.engine
    return out


def _attribute_per_engine(
    orders: list[dict[str, Any]],
    tag_to_engine: dict[str, str],
    strategy: "SharedCreditStrategy",
) -> dict[str, EngineAttribution]:
    """Per-engine version of the cluster attribution loop.

    Re-uses the strategy's tag-gathering + dynamic-match logic
    via _gather_tags + _match_dynamic on the engine map.
    """
    from engines._clusters import cluster_for_engine
    out: dict[str, EngineAttribution] = {}
    for order in orders:
        try:
            total = float(order.get("total_price", 0.0) or 0.0)
        except (TypeError, ValueError):
            total = 0.0
        tags = strategy._gather_tags(order)
        matched_engines: set[str] = set()
        tag_hits: list[str] = []
        for tag in tags:
            engine = tag_to_engine.get(tag)
            if engine is None:
                engine = strategy._match_dynamic(
                    tag, tag_to_engine,
                )
            if engine is not None:
                matched_engines.add(engine)
                tag_hits.append(tag)
        if not matched_engines:
            continue
        share = total / len(matched_engines)
        for engine in matched_engines:
            attr = out.setdefault(
                engine,
                EngineAttribution(
                    engine=engine,
                    cluster=(
                        cluster_for_engine(engine).name
                        if cluster_for_engine(engine) else None
                    ),
                    window_hours=0.0,
                ),
            )
            attr.attributed_revenue += share
            attr.attributed_orders += 1
            for tag in tag_hits:
                if tag not in attr.tag_matches:
                    attr.tag_matches.append(tag)
    return out


def _fetch_recent_orders(
    *,
    window_hours: float,
    store_id: str | None,
) -> list[dict[str, Any]]:
    """Pull orders within the window via SHOPIFY_LIST_ORDERS."""
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
        router = get_router()
    except Exception:  # noqa: BLE001
        return []
    if router is None:
        return []

    cutoff_iso = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(time.time() - window_hours * 3600.0),
    )
    params: dict[str, Any] = {
        "query": f"created_at:>={cutoff_iso}",
        "limit": 250,
    }
    if store_id:
        params["store_id"] = store_id

    try:
        result = router.execute(
            Capability.SHOPIFY_LIST_ORDERS, params,
        )
    except Exception:  # noqa: BLE001
        return []
    if not getattr(result, "ok", False):
        return []
    data = getattr(result, "data", None) or {}
    orders = data.get("orders") or []
    return [o for o in orders if isinstance(o, dict)]


def attribute_revenue(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
    orders: list[dict[str, Any]] | None = None,
    strategy: AttributionStrategy | None = None,
) -> AttributionReport:
    """Attribute revenue from recent orders to clusters.

    Args:
        window_hours: How far back to look at orders.
        store_id: Optional per-store filter.
        orders: Pre-fetched orders (for tests). If None,
            fetches via SHOPIFY_LIST_ORDERS.
        strategy: Pluggable algorithm. Default = SharedCredit.

    Returns:
        Populated :class:`AttributionReport`.
    """
    strategy = strategy or SharedCreditStrategy()
    if orders is None:
        orders = _fetch_recent_orders(
            window_hours=window_hours, store_id=store_id,
        )

    tag_to_cluster = _build_tag_to_cluster_map()
    per_cluster_dict = strategy.attribute(orders, tag_to_cluster)

    # Per-engine attribution (separate from per-cluster). Only
    # SharedCreditStrategy supports it -- custom strategies just
    # opt out of the per-engine breakdown.
    per_engine_dict: dict[str, EngineAttribution] = {}
    if isinstance(strategy, SharedCreditStrategy):
        tag_to_engine = _build_tag_to_engine_map()
        per_engine_dict = _attribute_per_engine(
            orders, tag_to_engine, strategy,
        )

    report = AttributionReport(
        window_hours=window_hours,
        total_orders_in_window=len(orders),
    )
    for o in orders:
        try:
            report.total_revenue_in_window += float(
                o.get("total_price", 0.0) or 0.0
            )
        except (TypeError, ValueError):
            pass

    for cluster, attr in per_cluster_dict.items():
        attr.window_hours = window_hours
        report.per_cluster.append(attr)

    for engine, eattr in per_engine_dict.items():
        eattr.window_hours = window_hours
        report.per_engine.append(eattr)

    # Sort by attributed_revenue desc
    report.per_cluster.sort(
        key=lambda a: a.attributed_revenue, reverse=True,
    )
    report.per_engine.sort(
        key=lambda a: a.attributed_revenue, reverse=True,
    )
    return report
