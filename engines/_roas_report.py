"""ROAS (return on ad spend) report.

Wave 50: per-engine ROAS rollup. Correlates two existing
substrate signals:

  - Ad-spend metrics from approval-queue outcomes (action
    records carry ``metrics.ad_spend`` / ``metrics.cost`` /
    ``metrics.discount_value`` from Wave 47's spend-cap path)
  - Attributed revenue per engine from Wave 9's per-engine
    attribution (revenue from Shopify orders joined via tags)

The cross-join answers "for every \\$1 my AGI spends through
engine X, how many \\$ in attributed revenue comes back?".

Engines with ROAS < 1.0 are losing money. Engines with
ROAS > 3.0 are highly efficient. Operator can use this to
decide which engines deserve more / less budget.

## Why this is high-value

Spend cap (Wave 47) tells you "we spent \\$X this week".
Revenue attribution (Wave 7-9) tells you "we earned \\$Y this
week". ROAS = Y/X per engine. Without the join, operators
guess at efficiency; with it, they have ground truth.

## Caveats

- Same attribution window for both numerator + denominator
  (default 168h / 7 days)
- ROAS=None when engine has spend but no attributed orders
  yet (lag between spend + sale)
- Engines without spend metrics simply don't appear -- this
  is a SPEND-focused report
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EngineROAS:
    engine: str
    cluster: str | None
    total_spend: float = 0.0
    attributed_revenue: float = 0.0
    attributed_orders: int = 0
    actions_counted: int = 0

    @property
    def roas(self) -> float | None:
        """attributed_revenue / total_spend.

        Returns None when:
          - total_spend == 0 (can't divide)
          - attributed_revenue == 0 AND attributed_orders == 0
            (attribution may lag spend; treat as no-data
            rather than negative-verdict)
        """
        if self.total_spend <= 0:
            return None
        if (
            self.attributed_revenue == 0
            and self.attributed_orders == 0
        ):
            return None
        return round(self.attributed_revenue / self.total_spend, 2)

    @property
    def verdict(self) -> str:
        """strong / break_even / negative / no_data."""
        roas = self.roas
        if roas is None:
            return "no_data"
        if roas >= 2.0:
            return "strong"
        if roas >= 1.0:
            return "break_even"
        return "negative"


@dataclass
class ROASReport:
    window_hours: float
    total_spend: float = 0.0
    total_attributed_revenue: float = 0.0
    per_engine: list[EngineROAS] = field(default_factory=list)

    @property
    def fleet_roas(self) -> float | None:
        if self.total_spend <= 0:
            return None
        return round(
            self.total_attributed_revenue / self.total_spend, 2,
        )


def compute_roas_report(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> ROASReport:
    """Build a ROAS report from spend metrics + attribution."""
    report = ROASReport(window_hours=window_hours)

    # 1. Pull per-engine spend from approval queue
    spend_by_engine: dict[str, dict[str, Any]] = {}
    try:
        from core.approval.queue import get_approval_queue
        queue = get_approval_queue()
    except Exception:  # noqa: BLE001
        return report

    cutoff = time.time() - (window_hours * 3600.0)
    try:
        actions = queue.list_by_status("executed") or []
    except Exception:  # noqa: BLE001
        return report

    for action in actions:
        action_store = getattr(action, "store_id", None)
        if store_id is not None and action_store != store_id:
            continue
        action_id = getattr(action, "id", None)
        engine = getattr(action, "engine", None) or "unknown"
        if action_id is None:
            continue
        try:
            outcomes = queue.get_outcomes(action_id) or []
        except Exception:  # noqa: BLE001
            continue
        for o in outcomes:
            if not isinstance(o, dict):
                continue
            try:
                if float(o.get("captured_at", 0)) < cutoff:
                    continue
            except (TypeError, ValueError):
                continue
            metrics = o.get("metrics") or {}
            spend = 0.0
            for key in ("cost", "ad_spend", "discount_value"):
                try:
                    spend += float(metrics.get(key, 0) or 0)
                except (TypeError, ValueError):
                    continue
            if spend <= 0:
                continue
            bucket = spend_by_engine.setdefault(
                engine, {"spend": 0.0, "actions": 0},
            )
            bucket["spend"] = round(bucket["spend"] + spend, 2)
            bucket["actions"] += 1

    # 2. Pull per-engine attributed revenue
    revenue_by_engine: dict[str, dict[str, Any]] = {}
    try:
        from engines._revenue_attribution import attribute_revenue
        attr_report = attribute_revenue(
            window_hours=window_hours, store_id=store_id,
        )
        for e in attr_report.per_engine:
            revenue_by_engine[e.engine] = {
                "revenue": e.attributed_revenue,
                "orders": e.attributed_orders,
                "cluster": e.cluster,
            }
    except Exception:  # noqa: BLE001
        pass

    # 3. Cross-join: only engines with spend appear
    for engine, spend_data in spend_by_engine.items():
        rev_data = revenue_by_engine.get(engine, {})
        per_engine = EngineROAS(
            engine=engine,
            cluster=rev_data.get("cluster"),
            total_spend=spend_data["spend"],
            attributed_revenue=rev_data.get("revenue", 0.0),
            attributed_orders=rev_data.get("orders", 0),
            actions_counted=spend_data["actions"],
        )
        report.per_engine.append(per_engine)
        report.total_spend = round(
            report.total_spend + spend_data["spend"], 2,
        )
        report.total_attributed_revenue = round(
            report.total_attributed_revenue
            + rev_data.get("revenue", 0.0),
            2,
        )

    # Sort by ROAS desc, with no-data engines last
    def _sort_key(e: EngineROAS) -> tuple:
        if e.roas is None:
            return (1, 0.0)
        return (0, -e.roas)
    report.per_engine.sort(key=_sort_key)
    return report
