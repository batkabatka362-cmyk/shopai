"""Classify orders vs actions into attributed/organic/orphan."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


# Engines that plausibly cause revenue.
# Action types matching these engines (case-insensitive
# substring) attribute their following orders.
_REVENUE_DRIVING_ENGINES = (
    "loyalty",
    "discount_strategy",
    "cart_recovery",
    "browse_recovery",
    "email_marketing",
    "welcome_series",
    "review_request",
    "affiliate",
    "ads_launcher",
    "pinterest_publisher",
    "instagram_publisher",
    "tiktok_publisher",
    "content_publisher",
    "cro_variants",
    "product_sourcer",
)


_DEFAULT_ATTRIBUTION_WINDOW_HOURS = 48.0


@dataclass
class OrderClassification:
    order_id: str
    store_id: str
    revenue: float
    created_at: str
    bucket: str    # attributed / organic / unknown
    matched_action_ids: list[str] = field(default_factory=list)
    matched_engines: list[str] = field(default_factory=list)


@dataclass
class OrphanAction:
    action_id: str
    engine: str
    action_type: str
    store_id: str
    decided_at: str
    age_hours: float


@dataclass
class StoreRecon:
    store_id: str
    days: int
    attribution_window_hours: float
    order_count: int = 0
    attributed_order_count: int = 0
    organic_order_count: int = 0
    attributed_revenue: float = 0.0
    organic_revenue: float = 0.0
    attribution_pct: float = 0.0
    orphan_action_count: int = 0
    orders: list[OrderClassification] = field(default_factory=list)
    orphans: list[OrphanAction] = field(default_factory=list)


@dataclass
class FleetRecon:
    days: int
    attribution_window_hours: float
    store_filter: str = ""
    by_store: list[StoreRecon] = field(default_factory=list)
    fleet_attributed_revenue: float = 0.0
    fleet_organic_revenue: float = 0.0
    fleet_attribution_pct: float = 0.0
    fleet_orphan_action_count: int = 0


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
            "reconciliation: store listing raised: %s",
            exc,
        )
        return []


def _hydrate_orders(
    store_id: str, limit: int = 250,
) -> list[dict[str, Any]]:
    """W963-99: wrap the hydrate call in active_store(sid)
    so the adapter router can scope the Shopify call to
    that store's credentials.

    Pre-fix, the store_id parameter was ACCEPTED but never
    threaded through to hydrate(). For multi-store empires,
    each per-store iteration in reconcile_fleet then fetched
    the SAME orders from the singleton Shopify connection;
    fleet_revenue = N_stores * actual_revenue. Single-store
    empires worked by accident (one connection, one set of
    orders).

    Today this is a no-op for credential routing (the
    Shopify adapter doesn't yet consult active_store to
    swap creds), but it establishes the contract: 'when
    you call _hydrate_orders(sid), the result is scoped
    to sid'. The router refactor lands separately.
    """
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
            "reconciliation: order hydrate raised: %s", exc,
        )
        return []


def _list_executed(
    store_id: str | None,
) -> list[Any]:
    try:
        from core.approval.queue import (
            get_approval_queue, ApprovalStatus,
        )
        q = get_approval_queue()
        kwargs = {"limit": 500}
        if store_id:
            kwargs["store_id"] = store_id
        return list(q.list_by_status(
            ApprovalStatus.EXECUTED, **kwargs,
        ) or [])
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "reconciliation: executed lookup raised: %s",
            exc,
        )
        return []


def _is_revenue_driving(action: Any) -> bool:
    """Heuristic: action's engine is one we consider
    revenue-driving."""
    engine = str(getattr(action, "engine", "") or "").lower()
    atype = str(
        getattr(action, "action_type", "") or "",
    ).lower()
    for kw in _REVENUE_DRIVING_ENGINES:
        if kw in engine or kw in atype:
            return True
    return False


def _matches_order(
    action_decided: datetime,
    order_created: datetime,
    *,
    window_hours: float,
) -> bool:
    """Match if action was decided BEFORE the order AND within
    the attribution window."""
    if action_decided >= order_created:
        return False
    delta_hours = (
        (order_created - action_decided).total_seconds() / 3600.0
    )
    return delta_hours <= window_hours


def reconcile_store(
    *,
    store_id: str,
    days: int = 7,
    attribution_window_hours: float = (
        _DEFAULT_ATTRIBUTION_WINDOW_HOURS
    ),
    now: datetime | None = None,
    orders_override: list[dict[str, Any]] | None = None,
    executed_override: list[Any] | None = None,
) -> StoreRecon:
    """Reconcile one store."""
    recon = StoreRecon(
        store_id=store_id,
        days=max(1, days),
        attribution_window_hours=max(
            0.0, float(attribution_window_hours),
        ),
    )
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=recon.days)

    raw_orders = (
        orders_override
        if orders_override is not None
        else _hydrate_orders(store_id)
    )
    actions = (
        executed_override
        if executed_override is not None
        else _list_executed(store_id)
    )

    # Pre-filter revenue-driving actions in window
    driving_actions: list[
        tuple[Any, datetime, str, str]
    ] = []
    for a in actions:
        if not _is_revenue_driving(a):
            continue
        dt = _parse_iso(getattr(a, "decided_at", None))
        if dt is None:
            continue
        # Action must be within (now - days - window)
        if dt < cutoff - timedelta(
            hours=recon.attribution_window_hours,
        ):
            continue
        if dt > now + timedelta(days=1):
            continue
        driving_actions.append((
            a,
            dt,
            str(getattr(a, "id", "") or ""),
            str(getattr(a, "engine", "") or ""),
        ))

    # Track which actions matched at least one order
    matched_action_ids: set[str] = set()

    for o in raw_orders:
        if not isinstance(o, dict):
            continue
        if o.get("cancelled_at"):
            continue
        odt = _parse_iso(o.get("created_at") or "")
        if odt is None or odt < cutoff:
            continue
        rev = _order_total(o)
        oid = str(o.get("id") or "")

        cls = OrderClassification(
            order_id=oid,
            store_id=store_id,
            revenue=round(rev, 2),
            created_at=str(o.get("created_at") or ""),
            bucket="organic",
        )

        for action, adt, aid, engine in driving_actions:
            if _matches_order(
                adt, odt,
                window_hours=recon.attribution_window_hours,
            ):
                cls.bucket = "attributed"
                cls.matched_action_ids.append(aid)
                if engine not in cls.matched_engines:
                    cls.matched_engines.append(engine)
                matched_action_ids.add(aid)

        recon.orders.append(cls)
        recon.order_count += 1
        if cls.bucket == "attributed":
            recon.attributed_order_count += 1
            recon.attributed_revenue += rev
        else:
            recon.organic_order_count += 1
            recon.organic_revenue += rev

    # Find orphan actions: revenue-driving but matched nothing
    for action, adt, aid, engine in driving_actions:
        if aid in matched_action_ids:
            continue
        if adt < cutoff:
            # Action older than the order window doesn't
            # count as an orphan.
            continue
        age_hours = (
            (now - adt).total_seconds() / 3600.0
        )
        recon.orphans.append(OrphanAction(
            action_id=aid,
            engine=engine,
            action_type=str(
                getattr(action, "action_type", "") or "",
            ),
            store_id=store_id,
            decided_at=str(getattr(action, "decided_at", "") or ""),
            age_hours=round(age_hours, 1),
        ))

    recon.orphan_action_count = len(recon.orphans)
    total = recon.attributed_revenue + recon.organic_revenue
    if total > 0:
        recon.attribution_pct = round(
            recon.attributed_revenue / total * 100.0, 1,
        )
    recon.attributed_revenue = round(
        recon.attributed_revenue, 2,
    )
    recon.organic_revenue = round(recon.organic_revenue, 2)
    return recon


def reconcile_fleet(
    *,
    days: int = 7,
    attribution_window_hours: float = (
        _DEFAULT_ATTRIBUTION_WINDOW_HOURS
    ),
    store_filter: str = "",
    now: datetime | None = None,
) -> FleetRecon:
    """Reconcile across the fleet."""
    report = FleetRecon(
        days=max(1, days),
        attribution_window_hours=attribution_window_hours,
        store_filter=store_filter,
    )
    if store_filter:
        store_ids = [store_filter]
    else:
        store_ids = _list_fleet_stores()

    for sid in store_ids:
        try:
            rc = reconcile_store(
                store_id=sid,
                days=days,
                attribution_window_hours=(
                    attribution_window_hours
                ),
                now=now,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "reconciliation: store %s raised: %s",
                sid, exc,
            )
            continue
        report.by_store.append(rc)
        report.fleet_attributed_revenue += (
            rc.attributed_revenue
        )
        report.fleet_organic_revenue += rc.organic_revenue
        report.fleet_orphan_action_count += (
            rc.orphan_action_count
        )

    total_rev = (
        report.fleet_attributed_revenue
        + report.fleet_organic_revenue
    )
    if total_rev > 0:
        report.fleet_attribution_pct = round(
            report.fleet_attributed_revenue
            / total_rev * 100.0,
            1,
        )
    report.fleet_attributed_revenue = round(
        report.fleet_attributed_revenue, 2,
    )
    report.fleet_organic_revenue = round(
        report.fleet_organic_revenue, 2,
    )
    # Sort by attributed revenue desc
    report.by_store.sort(
        key=lambda r: r.attributed_revenue, reverse=True,
    )
    return report
