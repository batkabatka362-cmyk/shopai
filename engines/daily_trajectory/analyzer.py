"""Bin orders into calendar days + compute slope.

Reuses engines._revenue_attribution.attribute_revenue under
the hood when available, falling back to direct order
hydration if attribution is unavailable.

The output is a list of DayBuckets (YYYY-MM-DD label, order
count, revenue total, delta vs prior day) plus aggregate
verdict (rising / flat / declining / cold_start).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DayBucket:
    date: str           # YYYY-MM-DD
    order_count: int
    revenue: float
    delta_vs_prev: float = 0.0


@dataclass
class TrajectoryReport:
    days: int
    store_id: str | None
    total_orders: int = 0
    total_revenue: float = 0.0
    avg_daily_revenue: float = 0.0
    verdict: str = "cold_start"  # rising / flat / declining / cold_start
    slope_pct: float = 0.0
    buckets: list[DayBucket] = field(default_factory=list)


def _parse_iso(ts: str) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        s = ts.rstrip("Z")
        # Handle date-only strings.
        if len(s) == 10 and s.count("-") == 2:
            return datetime.fromisoformat(s).replace(
                tzinfo=timezone.utc,
            )
        # Handle space separator instead of T.
        if len(s) > 10 and s[10] == " ":
            s = s[:10] + "T" + s[11:]
        if "+" in s:
            return datetime.fromisoformat(s)
        if len(s) >= 19:
            return datetime.fromisoformat(s).replace(
                tzinfo=timezone.utc,
            )
        return None
    except (ValueError, TypeError):
        return None


def _hydrate_orders(
    days: int, store_id: str | None,
) -> list[dict[str, Any]]:
    """Pull orders via SHOPIFY_FETCH_ORDERS. Caps at 250 to
    avoid an unbounded fetch."""
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
            "trajectory: order hydrate raised: %s", exc,
        )
        return []


def _order_total(order: dict[str, Any]) -> float:
    """Extract a numeric total from a Shopify order shape.
    Tolerates several common key names."""
    for key in (
        "total_price", "total", "current_total_price",
        "subtotal_price",
    ):
        v = order.get(key)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0


def _compute_verdict_and_slope(
    buckets: list[DayBucket],
) -> tuple[str, float]:
    """Compute verdict based on first-half vs second-half
    revenue average."""
    if len(buckets) < 4:
        return "cold_start", 0.0
    nonzero = [b for b in buckets if b.revenue > 0.0]
    if len(nonzero) < 2:
        return "cold_start", 0.0
    half = len(buckets) // 2
    first_half = buckets[:half]
    second_half = buckets[half:]
    first_avg = (
        sum(b.revenue for b in first_half) / max(len(first_half), 1)
    )
    second_avg = (
        sum(b.revenue for b in second_half) / max(len(second_half), 1)
    )
    if first_avg <= 0.01:
        if second_avg > 0.01:
            return "rising", 999.0
        return "cold_start", 0.0
    slope_pct = ((second_avg - first_avg) / first_avg) * 100.0
    if slope_pct >= 15.0:
        return "rising", slope_pct
    if slope_pct <= -15.0:
        return "declining", slope_pct
    return "flat", slope_pct


def analyze_trajectory(
    *,
    days: int = 30,
    store_id: str | None = None,
    orders: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> TrajectoryReport:
    """Build the per-day trajectory."""
    days = max(2, min(days, 90))
    if now is None:
        now = datetime.now(timezone.utc)
    report = TrajectoryReport(days=days, store_id=store_id)

    # Initialize empty buckets so days with no orders show.
    today = now.replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    bucket_dates: list[str] = []
    bucket_map: dict[str, DayBucket] = {}
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        key = d.strftime("%Y-%m-%d")
        bucket_dates.append(key)
        bucket_map[key] = DayBucket(
            date=key, order_count=0, revenue=0.0,
        )

    raw_orders = (
        orders
        if orders is not None
        else _hydrate_orders(days, store_id)
    )

    cutoff = today - timedelta(days=days)

    for o in raw_orders:
        if not isinstance(o, dict):
            continue
        if o.get("cancelled_at"):
            continue
        created = o.get("created_at") or ""
        dt = _parse_iso(created)
        if dt is None:
            continue
        if dt < cutoff:
            continue
        if dt > now + timedelta(days=1):
            continue
        key = dt.strftime("%Y-%m-%d")
        bucket = bucket_map.get(key)
        if bucket is None:
            continue
        bucket.order_count += 1
        bucket.revenue += _order_total(o)

    # Compute deltas
    prev_rev = 0.0
    for key in bucket_dates:
        b = bucket_map[key]
        b.delta_vs_prev = b.revenue - prev_rev
        prev_rev = b.revenue
        report.buckets.append(b)

    report.total_orders = sum(b.order_count for b in report.buckets)
    report.total_revenue = sum(b.revenue for b in report.buckets)
    report.avg_daily_revenue = (
        report.total_revenue / max(len(report.buckets), 1)
    )
    verdict, slope = _compute_verdict_and_slope(report.buckets)
    report.verdict = verdict
    report.slope_pct = round(slope, 1)
    return report


def render_sparkline(buckets: list[DayBucket]) -> str:
    """Render a small text sparkline of revenue per day."""
    if not buckets:
        return ""
    chars = " .:-=+*#"
    max_rev = max((b.revenue for b in buckets), default=0.0)
    if max_rev <= 0.0:
        return chars[0] * len(buckets)
    out = []
    for b in buckets:
        idx = int((b.revenue / max_rev) * (len(chars) - 1))
        out.append(chars[max(0, min(idx, len(chars) - 1))])
    return "".join(out)
