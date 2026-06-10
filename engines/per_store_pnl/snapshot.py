"""Per-store P&L snapshot computation.

Robust against the cold-start empire (zero revenue + zero
spend), single-side ledgers (cost without revenue or vice
versa), and missing data sources (revenue attribution
backend down).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class PnLState(str, Enum):
    """Operator-readable financial state."""
    COLD = "cold"               # No revenue + no spend
    LOSING = "losing"           # spend > revenue
    BREAKEVEN = "breakeven"     # revenue >= spend but margin < 20%
    HEALTHY = "healthy"         # margin 20-66%
    THRIVING = "thriving"       # margin > 66% (revenue >= 3x spend)

    @property
    def severity_rank(self) -> int:
        """Higher = WORSE state. Operator dashboards
        sort by this so problems surface first."""
        return {
            "thriving": 0,
            "healthy": 1,
            "cold": 2,
            "breakeven": 3,
            "losing": 4,
        }.get(self.value, 0)


@dataclass
class StorePnLSnapshot:
    """One store's P&L over the lookback window."""
    store_id: str
    window_hours: float
    spend_usd: float
    revenue_usd: float
    attributed_revenue_usd: float
    profit_usd: float
    margin_pct: float
    roas_ratio: float
    state: PnLState
    # Diagnostic hints when something is partial
    has_cost_data: bool = True
    has_revenue_data: bool = True
    notes: list[str] = field(default_factory=list)


def _classify(
    revenue: float, spend: float,
) -> PnLState:
    """State ladder based on margin + ratios."""
    if revenue <= 0.0 and spend <= 0.0:
        return PnLState.COLD
    if spend > 0 and revenue < spend:
        return PnLState.LOSING
    if spend <= 0 and revenue > 0:
        # Revenue with no measured spend -- treat as
        # thriving (organic / pre-AGI), but flag as
        # informational only.
        return PnLState.THRIVING
    # Both positive. Compute margin.
    margin = (revenue - spend) / revenue if revenue > 0 else 0.0
    if margin >= 0.66:
        return PnLState.THRIVING
    if margin >= 0.20:
        return PnLState.HEALTHY
    return PnLState.BREAKEVEN


def _safe_attribute_revenue(
    *, store_id: str, window_hours: float,
) -> tuple[float, float, bool]:
    """Call attribute_revenue with active_store(sid) so the
    Shopify orders hydrate hits the right store. Returns
    (total_revenue, attributed_revenue, ok)."""
    try:
        from engines._revenue_attribution import (
            attribute_revenue,
        )
        from core.context import active_store
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "per_store_pnl: attribution import "
            "raised: %s", exc,
        )
        return 0.0, 0.0, False

    try:
        with active_store(store_id):
            report = attribute_revenue(
                window_hours=window_hours,
                store_id=store_id,
            )
        total = float(
            report.total_revenue_in_window or 0.0,
        )
        attributed = float(report.attributed_revenue or 0.0)
        return total, attributed, True
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "per_store_pnl: attribute_revenue raised "
            "for %s: %s", store_id, exc,
        )
        return 0.0, 0.0, False


def _safe_spend_for_store(
    *, store_id: str, window_hours: float,
) -> tuple[float, bool]:
    """Read total adapter spend for one store. Returns
    (spend_usd, ok)."""
    try:
        from engines.per_store_costs.query import (
            costs_by_store,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "per_store_pnl: costs import raised: %s", exc,
        )
        return 0.0, False
    try:
        by_store = costs_by_store(
            window_hours=window_hours,
        )
        summary = by_store.get(store_id)
        if summary is None:
            return 0.0, True
        return float(summary.total_cost_usd or 0.0), True
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "per_store_pnl: spend query raised: %s", exc,
        )
        return 0.0, False


def compute_snapshot(
    store_id: str,
    *,
    window_hours: float = 168.0,
) -> StorePnLSnapshot:
    """Build the P&L snapshot for one store.

    Fail-soft: if revenue attribution is unreachable, the
    snapshot still ships with revenue=0.0 + has_revenue_
    data=False + a note. Same for spend.
    """
    spend, spend_ok = _safe_spend_for_store(
        store_id=store_id, window_hours=window_hours,
    )
    revenue, attributed, revenue_ok = _safe_attribute_revenue(
        store_id=store_id, window_hours=window_hours,
    )

    profit = revenue - spend
    margin = (
        (profit / revenue) if revenue > 0 else 0.0
    )
    roas = (
        (revenue / spend) if spend > 0
        else (float("inf") if revenue > 0 else 0.0)
    )
    # Sanitise infinity for JSON; cap at 9999 for display.
    if roas == float("inf"):
        roas_display = 9999.0
    else:
        roas_display = round(roas, 2)
    state = _classify(revenue, spend)

    notes: list[str] = []
    if not spend_ok:
        notes.append(
            "spend data unavailable; spend reported as 0"
        )
    if not revenue_ok:
        notes.append(
            "revenue attribution unavailable; revenue "
            "reported as 0"
        )
    if state == PnLState.THRIVING and spend <= 0:
        notes.append(
            "thriving with zero measured spend -- "
            "likely organic / pre-AGI baseline"
        )

    return StorePnLSnapshot(
        store_id=store_id,
        window_hours=window_hours,
        spend_usd=round(spend, 4),
        revenue_usd=round(revenue, 2),
        attributed_revenue_usd=round(attributed, 2),
        profit_usd=round(profit, 2),
        margin_pct=round(margin * 100.0, 1),
        roas_ratio=roas_display,
        state=state,
        has_cost_data=spend_ok,
        has_revenue_data=revenue_ok,
        notes=notes,
    )


def compute_fleet_snapshot(
    *,
    window_hours: float = 168.0,
) -> list[StorePnLSnapshot]:
    """Per-store P&L for every store the StoreManager knows
    about. Sorted by state severity (LOSING first), then
    by profit descending so the highest-margin store
    surfaces above same-state peers.
    """
    try:
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        stores = StoreManager().list_stores() or []
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "per_store_pnl: list_stores raised: %s", exc,
        )
        return []

    out: list[StorePnLSnapshot] = []
    for store in stores:
        sid = (
            store.get("store_id") if isinstance(store, dict)
            else getattr(store, "store_id", "")
        )
        if not sid:
            continue
        out.append(compute_snapshot(
            sid, window_hours=window_hours,
        ))

    out.sort(
        key=lambda s: (
            -s.state.severity_rank,
            -s.profit_usd,
            s.store_id,
        ),
    )
    return out
