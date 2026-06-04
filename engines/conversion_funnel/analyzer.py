"""Compute conversion-funnel drop-off per stage.

Funnel stages (in order):
  1. sessions          (from analytics, optional)
  2. cart_adds         (from analytics, optional)
  3. checkouts_started (= abandoned_checkouts + completed orders)
  4. checkouts_completed (= completed orders)

When analytics data is unavailable, the stages collapse but the
funnel still surfaces the checkout-vs-paid ratio which is the
most operator-actionable signal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FunnelStage:
    name: str
    count: int
    conversion_from_prev: float | None = None  # 0..1 or None
    drop_rate: float | None = None             # 0..1 or None


@dataclass
class FunnelReport:
    days: int
    store_id: str | None
    stages: list[FunnelStage] = field(default_factory=list)
    weakest_link: str = ""
    weakest_drop: float = 0.0
    verdict: str = "unknown"   # healthy / leaky / no_traffic / unknown
    next_action: str = ""


def _parse_iso(s: str) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        x = s.strip().replace(" ", "T", 1)
        if x.endswith("Z"):
            x = x[:-1] + "+00:00"
        if len(x) == 10:
            x += "T00:00:00+00:00"
        dt = datetime.fromisoformat(x)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _hydrate_orders(days: int) -> list[dict[str, Any]]:
    try:
        from engines._shopify_hydrator import hydrate
        return hydrate(
            supplied=[],
            capability_name="SHOPIFY_FETCH_ORDERS",
            list_field="orders",
            limit=min(250, max(50, days * 8)),
        ) or []
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "funnel: order hydrate raised: %s", exc,
        )
        return []


def _hydrate_abandoned() -> list[dict[str, Any]]:
    try:
        from engines._shopify_hydrator import hydrate
        return hydrate(
            supplied=[],
            capability_name="SHOPIFY_LIST_ABANDONED_CHECKOUTS",
            list_field="checkouts",
            limit=250,
        ) or []
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "funnel: abandoned hydrate raised: %s", exc,
        )
        return []


def _count_in_window(
    items: list[dict[str, Any]],
    *,
    field: str,
    cutoff: datetime,
    now: datetime,
) -> int:
    n = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("cancelled_at"):
            continue
        dt = _parse_iso(it.get(field) or "")
        if dt is None:
            continue
        if dt < cutoff:
            continue
        if dt > now + timedelta(days=1):
            continue
        n += 1
    return n


def _compute_stages(
    *,
    sessions: int | None,
    cart_adds: int | None,
    checkouts_started: int,
    checkouts_completed: int,
) -> list[FunnelStage]:
    """Build the per-stage list including conversion ratios.
    Stages where the upstream count is unknown (None) report
    conversion_from_prev as None."""
    stages: list[FunnelStage] = []

    if sessions is not None and sessions > 0:
        stages.append(
            FunnelStage(name="sessions", count=sessions)
        )

    if cart_adds is not None:
        prev = stages[-1].count if stages else None
        conv = (cart_adds / prev) if prev else None
        stages.append(
            FunnelStage(
                name="cart_adds",
                count=cart_adds,
                conversion_from_prev=conv,
                drop_rate=(1.0 - conv) if conv is not None else None,
            )
        )

    prev = stages[-1].count if stages else None
    conv = (
        (checkouts_started / prev)
        if prev else None
    )
    stages.append(
        FunnelStage(
            name="checkouts_started",
            count=checkouts_started,
            conversion_from_prev=conv,
            drop_rate=(1.0 - conv) if conv is not None else None,
        )
    )

    prev_started = checkouts_started
    conv = (
        (checkouts_completed / prev_started)
        if prev_started else None
    )
    stages.append(
        FunnelStage(
            name="checkouts_completed",
            count=checkouts_completed,
            conversion_from_prev=conv,
            drop_rate=(1.0 - conv) if conv is not None else None,
        )
    )
    return stages


def _identify_weakest(
    stages: list[FunnelStage],
) -> tuple[str, float]:
    """Find the stage with the biggest drop. Returns
    (stage_name, drop_rate)."""
    worst_name = ""
    worst_drop = 0.0
    for s in stages:
        if s.drop_rate is None:
            continue
        if s.drop_rate > worst_drop:
            worst_drop = s.drop_rate
            worst_name = s.name
    return worst_name, worst_drop


def _verdict_for(
    completed: int,
    started: int,
    weakest_drop: float,
) -> str:
    if completed == 0 and started == 0:
        return "no_traffic"
    if completed == 0 and started > 0:
        return "leaky"
    if weakest_drop >= 0.7:
        return "leaky"
    return "healthy"


def _next_action_for(
    weakest_link: str,
    weakest_drop: float,
    verdict: str,
) -> str:
    if verdict == "no_traffic":
        return (
            "0 sessions + 0 checkouts. Run: shopai "
            "earn-bootstrap + shopai ads launch."
        )
    if weakest_link == "checkouts_completed":
        return (
            f"Biggest drop is checkout->paid "
            f"({weakest_drop*100:.0f}% abandon). Fire: "
            "shopai approvals approve-all "
            "--engine cart_recovery --execute"
        )
    if weakest_link == "checkouts_started":
        return (
            f"Biggest drop is product->checkout "
            f"({weakest_drop*100:.0f}%). Try: shopai cro "
            "variants on top product."
        )
    if weakest_link == "cart_adds":
        return (
            f"Biggest drop is session->cart-add "
            f"({weakest_drop*100:.0f}%). Improve product "
            "page: shopai cro variants."
        )
    if verdict == "healthy":
        return (
            "Funnel healthy. Reinvest: shopai ads launch "
            "with higher budget."
        )
    return ""


def analyze_funnel(
    *,
    days: int = 7,
    store_id: str | None = None,
    orders: list[dict[str, Any]] | None = None,
    abandoned: list[dict[str, Any]] | None = None,
    sessions: int | None = None,
    cart_adds: int | None = None,
    now: datetime | None = None,
) -> FunnelReport:
    days = max(1, min(days, 90))
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    raw_orders = (
        orders
        if orders is not None
        else _hydrate_orders(days)
    )
    raw_abandoned = (
        abandoned
        if abandoned is not None
        else _hydrate_abandoned()
    )

    completed = _count_in_window(
        raw_orders, field="created_at",
        cutoff=cutoff, now=now,
    )
    abandoned_in_window = _count_in_window(
        raw_abandoned, field="created_at",
        cutoff=cutoff, now=now,
    )
    started = completed + abandoned_in_window

    stages = _compute_stages(
        sessions=sessions,
        cart_adds=cart_adds,
        checkouts_started=started,
        checkouts_completed=completed,
    )
    weakest_link, weakest_drop = _identify_weakest(stages)
    verdict = _verdict_for(
        completed, started, weakest_drop,
    )
    next_action = _next_action_for(
        weakest_link, weakest_drop, verdict,
    )

    return FunnelReport(
        days=days,
        store_id=store_id,
        stages=stages,
        weakest_link=weakest_link,
        weakest_drop=weakest_drop,
        verdict=verdict,
        next_action=next_action,
    )
