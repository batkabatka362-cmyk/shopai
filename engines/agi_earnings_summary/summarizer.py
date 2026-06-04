"""Compose reconciliation + pnl + trend into one verdict."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EarningsSummary:
    days: int
    attribution_window_hours: float
    fleet_attributed_revenue: float = 0.0
    fleet_organic_revenue: float = 0.0
    fleet_attribution_pct: float = 0.0
    fleet_orphan_action_count: int = 0
    fleet_gross_profit: float = 0.0
    fleet_margin_pct: float = 0.0
    store_count: int = 0
    profitable_store_count: int = 0
    loss_store_count: int = 0
    verdict: str = "no_data"
    monthly_run_rate: float = 0.0
    per_store: list[dict[str, Any]] = field(
        default_factory=list,
    )
    trend_verdict: str = "no_data"


def _compute_reconciliation(
    days: int, attribution_window_hours: float,
) -> Any:
    try:
        from engines.revenue_reconciliation.reconciler import (
            reconcile_fleet,
        )
        return reconcile_fleet(
            days=days,
            attribution_window_hours=attribution_window_hours,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "earnings_summary: recon raised: %s", exc,
        )
        return None


def _compute_pnl(days: int) -> Any:
    try:
        from engines.store_pnl_tracker.tracker import (
            compute_fleet_pnl,
        )
        return compute_fleet_pnl(days=days)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "earnings_summary: pnl raised: %s", exc,
        )
        return None


def _fleet_trend(days: int = 30) -> str:
    """Aggregate per-store trends into a fleet-wide verdict."""
    try:
        from engines.daily_pnl_history.store import (
            stores_with_history, compute_trend,
        )
    except Exception:  # noqa: BLE001
        return "no_data"
    try:
        stores = stores_with_history() or []
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "earnings_summary: history list raised: %s",
            exc,
        )
        return "no_data"
    if not stores:
        return "no_data"
    rising = falling = flat = no_data = 0
    for sid in stores:
        try:
            t = compute_trend(store_id=sid, days=days)
        except Exception:  # noqa: BLE001
            no_data += 1
            continue
        v = t.get("verdict", "no_data")
        if v == "rising":
            rising += 1
        elif v == "falling":
            falling += 1
        elif v == "flat":
            flat += 1
        else:
            no_data += 1
    if rising == falling == flat == 0:
        return "no_data"
    # Majority wins; ties favour flat
    if rising > falling and rising >= flat:
        return "rising"
    if falling > rising and falling >= flat:
        return "falling"
    return "flat"


def _classify_verdict(
    fleet_attr: float,
    fleet_org: float,
    fleet_profit: float,
) -> str:
    total_rev = fleet_attr + fleet_org
    if total_rev == 0:
        return "no_data"
    if fleet_attr <= 0:
        return "organic_only"
    if fleet_profit < 0:
        return "attributed_loss"
    return "earning"


def compute_summary(
    *,
    days: int = 7,
    attribution_window_hours: float = 48.0,
    trend_days: int = 30,
) -> EarningsSummary:
    s = EarningsSummary(
        days=max(1, days),
        attribution_window_hours=max(
            0.0, float(attribution_window_hours),
        ),
    )
    recon = _compute_reconciliation(
        s.days, s.attribution_window_hours,
    )
    pnl = _compute_pnl(s.days)
    if recon is not None:
        s.fleet_attributed_revenue = (
            recon.fleet_attributed_revenue
        )
        s.fleet_organic_revenue = recon.fleet_organic_revenue
        s.fleet_attribution_pct = recon.fleet_attribution_pct
        s.fleet_orphan_action_count = (
            recon.fleet_orphan_action_count
        )
    if pnl is not None:
        s.fleet_gross_profit = pnl.fleet_gross_profit
        s.fleet_margin_pct = pnl.fleet_margin_pct
        s.store_count = len(pnl.by_store)
        for p in pnl.by_store:
            if p.verdict == "profitable":
                s.profitable_store_count += 1
            elif p.verdict == "loss":
                s.loss_store_count += 1
            s.per_store.append({
                "store_id": p.store_id,
                "gross_revenue": p.gross_revenue,
                "gross_profit": p.gross_profit,
                "verdict": p.verdict,
            })

    s.verdict = _classify_verdict(
        s.fleet_attributed_revenue,
        s.fleet_organic_revenue,
        s.fleet_gross_profit,
    )
    # Monthly run-rate: gross_profit / days * 30
    if s.days > 0:
        s.monthly_run_rate = round(
            s.fleet_gross_profit / s.days * 30.0, 2,
        )
    s.trend_verdict = _fleet_trend(days=trend_days)
    s.fleet_attributed_revenue = round(
        s.fleet_attributed_revenue, 2,
    )
    s.fleet_organic_revenue = round(
        s.fleet_organic_revenue, 2,
    )
    s.fleet_gross_profit = round(s.fleet_gross_profit, 2)
    return s
