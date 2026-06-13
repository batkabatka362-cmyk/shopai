"""Compute per-store P&L from Shopify + queue substrate."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


_DEFAULT_ESP_COST_PER_SEND = 0.001     # $0.001 per email
_AD_ACTION_TYPES = (
    "apply_budget_change",
    "launch_campaign",
    "ads_create_campaign",
)


@dataclass
class StorePnl:
    store_id: str
    days: int
    gross_revenue: float = 0.0
    refunds: float = 0.0
    net_revenue: float = 0.0
    ad_spend: float = 0.0
    esp_spend: float = 0.0
    shipping_cost: float = 0.0
    total_cost: float = 0.0
    gross_profit: float = 0.0
    margin_pct: float = 0.0
    order_count: int = 0
    cost_action_count: int = 0
    verdict: str = "no_data"  # profitable / break_even / loss / no_data


@dataclass
class FleetPnlReport:
    days: int
    store_filter: str = ""
    by_store: list[StorePnl] = field(default_factory=list)
    fleet_revenue: float = 0.0
    fleet_refunds: float = 0.0
    fleet_ad_spend: float = 0.0
    fleet_esp_spend: float = 0.0
    fleet_shipping_cost: float = 0.0
    fleet_gross_profit: float = 0.0
    fleet_margin_pct: float = 0.0


def _parse_iso(s: Any) -> datetime | None:
    if s is None:
        return None
    if isinstance(s, datetime):
        if s.tzinfo is None:
            return s.replace(tzinfo=timezone.utc)
        return s
    if isinstance(s, (int, float)):
        try:
            return datetime.fromtimestamp(
                float(s), tz=timezone.utc,
            )
        except (ValueError, OverflowError, OSError):
            return None
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


def _list_fleet_stores() -> list[str]:
    try:
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        sm = StoreManager()
        out: list[str] = []
        for s in (sm.list_stores() or []):
            if not isinstance(s, dict):
                continue
            sid = s.get("store_id")
            if sid and sid not in out:
                out.append(sid)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "pnl: store listing raised: %s", exc,
        )
        return []


def _hydrate_orders(
    store_id: str, limit: int = 250,
) -> list[dict[str, Any]]:
    """W963-99: see engines.revenue_reconciliation.reconciler.
    _hydrate_orders for the rationale. Same fix applies here
    (compute_fleet_pnl iterates per-store and previously
    multi-counted orders across stores)."""
    try:
        from engines._shopify_hydrator import hydrate
        from core.context import active_store
        sid = (store_id or "").strip() or None
        import contextlib
        ctx = (
            active_store(sid)
            if sid
            else contextlib.nullcontext()
        )
        with ctx:
            return hydrate(
                supplied=[],
                capability_name="SHOPIFY_FETCH_ORDERS",
                list_field="orders",
                limit=int(limit),
            ) or []
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "pnl: order hydrate raised: %s", exc,
        )
        return []


def _order_total(order: dict[str, Any]) -> float:
    for key in (
        "total_price", "total",
        "current_total_price", "subtotal_price",
    ):
        v = order.get(key)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0


def _order_refund_total(order: dict[str, Any]) -> float:
    """Sum refunds on an order. Tolerates several shapes."""
    refunds = order.get("refunds") or []
    if not isinstance(refunds, list):
        return 0.0
    total = 0.0
    for r in refunds:
        if not isinstance(r, dict):
            continue
        # transactions array
        for t in r.get("transactions") or []:
            if not isinstance(t, dict):
                continue
            try:
                total += float(t.get("amount") or 0.0)
            except (TypeError, ValueError):
                continue
    return total


def _order_shipping_cost(order: dict[str, Any]) -> float:
    """Pull shipping cost from shipping_lines."""
    lines = order.get("shipping_lines") or []
    if not isinstance(lines, list):
        return 0.0
    total = 0.0
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        try:
            total += float(ln.get("price") or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def _action_cost(action: Any) -> float:
    """Try to extract a $ cost from an approval queue action's
    params / result / metrics."""
    for src_name in ("result", "params"):
        src = getattr(action, src_name, None) or {}
        if not isinstance(src, dict):
            continue
        for key in (
            "cost", "cost_usd", "amount",
            "daily_budget_usd", "budget",
        ):
            v = src.get(key)
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _list_executed(
    queue: Any, store_id: str | None,
) -> list[Any]:
    try:
        from core.approval.queue import ApprovalStatus
        kwargs = {"limit": 500}
        if store_id:
            kwargs["store_id"] = store_id
        return list(queue.list_by_status(
            ApprovalStatus.EXECUTED, **kwargs,
        ) or [])
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "pnl: executed lookup raised: %s", exc,
        )
        return []


def _verdict_for(pnl: StorePnl) -> str:
    if pnl.gross_revenue == 0.0 and pnl.total_cost == 0.0:
        return "no_data"
    # break_even band: within $1 either direction.
    if abs(pnl.gross_profit) < 1.0:
        return "break_even"
    if pnl.gross_profit > 0.0:
        return "profitable"
    return "loss"


def compute_store_pnl(
    *,
    store_id: str,
    days: int = 7,
    now: datetime | None = None,
    orders_override: list[dict[str, Any]] | None = None,
    executed_override: list[Any] | None = None,
    esp_cost_per_send: float = _DEFAULT_ESP_COST_PER_SEND,
) -> StorePnl:
    """Compute one store's P&L."""
    pnl = StorePnl(store_id=store_id, days=max(1, days))
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=pnl.days)

    # Orders
    orders = (
        orders_override
        if orders_override is not None
        else _hydrate_orders(store_id)
    )
    for o in orders:
        if not isinstance(o, dict):
            continue
        if o.get("cancelled_at"):
            continue
        dt = _parse_iso(o.get("created_at") or "")
        if dt is None or dt < cutoff:
            continue
        pnl.gross_revenue += _order_total(o)
        pnl.refunds += _order_refund_total(o)
        pnl.shipping_cost += _order_shipping_cost(o)
        pnl.order_count += 1

    # Approval queue costs
    if executed_override is not None:
        executed = executed_override
    else:
        try:
            from core.approval.queue import (
                get_approval_queue,
            )
            queue = get_approval_queue()
            executed = _list_executed(queue, store_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "pnl: queue load raised: %s", exc,
            )
            executed = []

    for action in executed:
        atype = str(
            getattr(action, "action_type", "") or "",
        ).lower()
        # Time-window filter on decided_at
        dt = _parse_iso(getattr(action, "decided_at", None))
        if dt is None or dt < cutoff:
            continue
        # Ad spend
        if any(t in atype for t in _AD_ACTION_TYPES):
            cost = _action_cost(action)
            if cost > 0:
                pnl.ad_spend += cost
                pnl.cost_action_count += 1
        # ESP cost
        engine = str(
            getattr(action, "engine", "") or "",
        ).lower()
        if (
            "email" in atype
            or engine in (
                "welcome_series",
                "review_request",
                "email_marketing",
            )
        ):
            pnl.esp_spend += esp_cost_per_send
            pnl.cost_action_count += 1

    pnl.net_revenue = pnl.gross_revenue - pnl.refunds
    pnl.total_cost = (
        pnl.ad_spend + pnl.esp_spend + pnl.shipping_cost
    )
    pnl.gross_profit = pnl.net_revenue - pnl.total_cost
    if pnl.net_revenue > 0:
        pnl.margin_pct = round(
            pnl.gross_profit / pnl.net_revenue * 100.0, 1,
        )
    pnl.verdict = _verdict_for(pnl)
    pnl.gross_revenue = round(pnl.gross_revenue, 2)
    pnl.refunds = round(pnl.refunds, 2)
    pnl.net_revenue = round(pnl.net_revenue, 2)
    pnl.ad_spend = round(pnl.ad_spend, 2)
    pnl.esp_spend = round(pnl.esp_spend, 4)
    pnl.shipping_cost = round(pnl.shipping_cost, 2)
    pnl.total_cost = round(pnl.total_cost, 2)
    pnl.gross_profit = round(pnl.gross_profit, 2)
    return pnl


def compute_fleet_pnl(
    *,
    days: int = 7,
    store_filter: str = "",
    now: datetime | None = None,
) -> FleetPnlReport:
    """Compute P&L across the whole fleet (or one store)."""
    report = FleetPnlReport(
        days=max(1, days), store_filter=store_filter,
    )
    if store_filter:
        store_ids = [store_filter]
    else:
        store_ids = _list_fleet_stores()
    for sid in store_ids:
        try:
            pnl = compute_store_pnl(
                store_id=sid, days=days, now=now,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "pnl: store %s raised: %s", sid, exc,
            )
            continue
        report.by_store.append(pnl)
        report.fleet_revenue += pnl.gross_revenue
        report.fleet_refunds += pnl.refunds
        report.fleet_ad_spend += pnl.ad_spend
        report.fleet_esp_spend += pnl.esp_spend
        report.fleet_shipping_cost += pnl.shipping_cost
        report.fleet_gross_profit += pnl.gross_profit
    # Sort by gross_profit desc
    report.by_store.sort(
        key=lambda p: p.gross_profit, reverse=True,
    )
    net = report.fleet_revenue - report.fleet_refunds
    if net > 0:
        report.fleet_margin_pct = round(
            report.fleet_gross_profit / net * 100.0, 1,
        )
    report.fleet_revenue = round(report.fleet_revenue, 2)
    report.fleet_refunds = round(report.fleet_refunds, 2)
    report.fleet_ad_spend = round(report.fleet_ad_spend, 2)
    report.fleet_esp_spend = round(report.fleet_esp_spend, 4)
    report.fleet_shipping_cost = round(
        report.fleet_shipping_cost, 2,
    )
    report.fleet_gross_profit = round(
        report.fleet_gross_profit, 2,
    )
    return report
