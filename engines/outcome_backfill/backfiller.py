"""Match EXECUTED actions to Shopify orders + update outcomes."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BackfillDecision:
    action_id: str
    engine: str
    action_type: str
    store_id: str = ""
    decided_at: str = ""
    age_hours: float = 0.0
    matched_orders: int = 0
    attributed_revenue: float = 0.0
    outcome: str = "skip"   # positive / negative / skip
    skip_reason: str = ""
    recorded: bool = False


@dataclass
class BackfillReport:
    confirmed: bool
    min_age_hours: float
    grace_hours: float
    store_filter: str
    total_executed_scanned: int = 0
    already_recorded: int = 0
    too_recent: int = 0
    positive_count: int = 0
    negative_count: int = 0
    decisions: list[BackfillDecision] = field(default_factory=list)
    skip_reasons: dict[str, int] = field(default_factory=dict)


def _bump_skip(r: BackfillReport, reason: str) -> None:
    r.skip_reasons[reason] = (
        r.skip_reasons.get(reason, 0) + 1
    )


def _parse_iso(s: Any) -> datetime | None:
    """Parse a Shopify ISO string, a Python datetime, OR a
    unix-timestamp number (the approval queue records
    decided_at as float seconds)."""
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


def _hydrate_orders(
    store_id: str | None,
    limit: int = 250,
) -> list[dict[str, Any]]:
    try:
        from engines._shopify_hydrator import hydrate
        return hydrate(
            supplied=[],
            capability_name="SHOPIFY_FETCH_ORDERS",
            list_field="orders",
            limit=int(limit),
        ) or []
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "outcome_backfill: order hydrate raised: %s", exc,
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
            "outcome_backfill: executed lookup raised: %s",
            exc,
        )
        return []


def _matches_action_to_orders(
    decided_at: datetime,
    orders: list[dict[str, Any]],
    *,
    action_store_id: str,
) -> tuple[int, float]:
    """Count orders created AFTER decided_at and (when
    available) matching action_store_id. Returns (count,
    total_revenue)."""
    n = 0
    total = 0.0
    for o in orders:
        if not isinstance(o, dict):
            continue
        if o.get("cancelled_at"):
            continue
        ord_dt = _parse_iso(o.get("created_at") or "")
        if ord_dt is None:
            continue
        if ord_dt < decided_at:
            continue
        # Optional per-store filter: when both the action and
        # the order carry store ids, match on that. Most
        # Shopify order dicts don't carry a store_id field
        # since they're already fetched per-store.
        order_store = str(o.get("store_id") or "")
        if (
            action_store_id and order_store
            and order_store != action_store_id
        ):
            continue
        n += 1
        total += _order_total(o)
    return (n, total)


def _already_recorded(action: Any) -> bool:
    """Check if the action has an outcome record on it
    already. Returns True if outcome is recorded -- don't
    re-record."""
    try:
        from core.approval.queue import get_approval_queue
        q = get_approval_queue()
        outcomes = q.get_outcomes(
            getattr(action, "id", ""),
        ) or []
        return len(outcomes) > 0
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "outcome_backfill: outcomes lookup raised: %s",
            exc,
        )
        return False


def _record_outcome(
    action_id: str,
    polarity: str,
    metrics: dict[str, Any],
) -> bool:
    try:
        from core.approval.queue import get_approval_queue
        q = get_approval_queue()
        return bool(q.record_outcome(
            action_id=action_id,
            topic="revenue_backfill",
            polarity=polarity,
            metrics=metrics,
            source_event="outcome_backfill_engine",
        ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "outcome_backfill: record_outcome raised: %s",
            exc,
        )
        return False


def run_backfill(
    *,
    confirmed: bool,
    min_age_hours: float = 24.0,
    grace_hours: float = 168.0,
    store_filter: str = "",
    now: datetime | None = None,
    orders_override: list[dict[str, Any]] | None = None,
    executed_override: list[Any] | None = None,
) -> BackfillReport:
    """Backfill outcomes onto EXECUTED actions."""
    report = BackfillReport(
        confirmed=confirmed,
        min_age_hours=max(0.0, float(min_age_hours)),
        grace_hours=max(min_age_hours, float(grace_hours)),
        store_filter=store_filter,
    )
    now = now or datetime.now(timezone.utc)

    try:
        from core.approval.queue import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "outcome_backfill: queue import raised: %s", exc,
        )
        return report

    executed = (
        executed_override
        if executed_override is not None
        else _list_executed(
            queue,
            store_filter if store_filter else None,
        )
    )
    report.total_executed_scanned = len(executed)
    if not executed:
        return report

    orders = (
        orders_override
        if orders_override is not None
        else _hydrate_orders(
            store_filter if store_filter else None,
        )
    )

    for action in executed:
        aid = str(getattr(action, "id", "") or "")
        engine = str(getattr(action, "engine", "") or "")
        atype = str(getattr(action, "action_type", "") or "")
        sid = str(getattr(action, "store_id", "") or "")
        decided_at_raw = getattr(action, "decided_at", None)
        decided_dt = _parse_iso(decided_at_raw)
        decision = BackfillDecision(
            action_id=aid,
            engine=engine,
            action_type=atype,
            store_id=sid,
            decided_at=str(decided_at_raw or ""),
        )

        if not aid:
            decision.skip_reason = "no_action_id"
            report.decisions.append(decision)
            _bump_skip(report, "no_action_id")
            continue

        # Already recorded?
        if _already_recorded(action):
            decision.skip_reason = "already_recorded"
            report.already_recorded += 1
            report.decisions.append(decision)
            _bump_skip(report, "already_recorded")
            continue

        if decided_dt is None:
            decision.skip_reason = "bad_decided_at"
            report.decisions.append(decision)
            _bump_skip(report, "bad_decided_at")
            continue

        age_hours = (
            (now - decided_dt).total_seconds() / 3600.0
        )
        decision.age_hours = round(age_hours, 1)

        if age_hours < report.min_age_hours:
            decision.skip_reason = "too_recent"
            report.too_recent += 1
            report.decisions.append(decision)
            _bump_skip(report, "too_recent")
            continue

        # Match
        matched, revenue = _matches_action_to_orders(
            decided_dt, orders, action_store_id=sid,
        )
        decision.matched_orders = matched
        decision.attributed_revenue = round(revenue, 2)

        if matched > 0:
            decision.outcome = "positive"
            report.positive_count += 1
        elif age_hours >= report.grace_hours:
            decision.outcome = "negative"
            report.negative_count += 1
        else:
            decision.skip_reason = "awaiting_grace"
            _bump_skip(report, "awaiting_grace")
            report.decisions.append(decision)
            continue

        if not confirmed:
            decision.skip_reason = "dry_run"
            _bump_skip(report, "dry_run")
            report.decisions.append(decision)
            continue

        wrote = _record_outcome(
            aid,
            polarity=decision.outcome,
            metrics={
                "matched_orders": matched,
                "attributed_revenue": revenue,
                "age_hours": age_hours,
            },
        )
        decision.recorded = wrote
        if not wrote:
            decision.skip_reason = "record_failed"
            _bump_skip(report, "record_failed")
        report.decisions.append(decision)

    return report
