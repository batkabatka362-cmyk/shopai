"""Earnings analyzer: orders -> (revenue, count, AOV) per window."""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WindowSummary:
    """Per-window aggregate of order activity."""

    revenue: float = 0.0
    order_count: int = 0
    avg_order_value: float = 0.0
    currency: str = ""


@dataclass
class EarningsReport:
    """Full report shape — current + previous + verdict."""

    store_id: str | None
    window_hours: float
    current: WindowSummary = field(default_factory=WindowSummary)
    previous: WindowSummary = field(default_factory=WindowSummary)
    delta: float = 0.0           # revenue change in USD
    delta_pct: float = 0.0       # % change vs previous
    verdict: str = "unknown"     # earning / flat / declining / cold


def _parse_iso(ts: Any) -> float | None:
    """Parse a Shopify ISO-8601 createdAt to unix epoch seconds.

    Returns None for unparseable / missing inputs so the caller
    can skip the order rather than crash on a malformed feed."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        # Shopify sends "2026-06-03T08:15:00Z" — datetime.fromisoformat
        # accepts the format after stripping the trailing Z.
        s = ts.rstrip("Z")
        # fromisoformat doesn't accept fractional seconds with Z in
        # older Python; defensive parse:
        if "+" not in s and len(s) >= 19:
            dt = datetime.fromisoformat(s).replace(
                tzinfo=timezone.utc,
            )
        else:
            dt = datetime.fromisoformat(s)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _safe_amount(raw: Any) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            return 0.0
    return 0.0


def _summarize(
    orders: list[dict[str, Any]],
    *,
    window_start: float,
    window_end: float,
) -> WindowSummary:
    """Aggregate orders whose created_at falls within
    [window_start, window_end). Cancelled / refunded orders are
    EXCLUDED from revenue (we want net earned, not gross written)."""
    summary = WindowSummary()
    for o in orders:
        if not isinstance(o, dict):
            continue
        ts = _parse_iso(o.get("created_at"))
        if ts is None:
            continue
        if ts < window_start or ts >= window_end:
            continue
        # Exclude cancelled orders entirely.
        if o.get("cancelled_at"):
            continue
        total = _safe_amount(o.get("total_price"))
        refunded = _safe_amount(o.get("refunded_price"))
        net = max(0.0, total - refunded)
        summary.revenue += net
        summary.order_count += 1
        if not summary.currency and o.get("currency_code"):
            summary.currency = str(o.get("currency_code"))
    if summary.order_count > 0:
        summary.avg_order_value = round(
            summary.revenue / summary.order_count, 2,
        )
    summary.revenue = round(summary.revenue, 2)
    return summary


def _verdict(current_rev: float, prev_rev: float) -> str:
    """Verdict bands. Match the empire dashboard's vocabulary."""
    if current_rev <= 0 and prev_rev <= 0:
        return "cold"
    if prev_rev <= 0:
        # New activity from a previously-zero baseline = earning.
        return "earning" if current_rev > 0 else "cold"
    delta_pct = (current_rev - prev_rev) / prev_rev * 100
    if delta_pct >= 10:
        return "earning"
    if delta_pct <= -25:
        return "declining"
    return "flat"


def analyze(
    *,
    orders: list[dict[str, Any]],
    window_hours: float,
    store_id: str | None = None,
    now: float | None = None,
) -> EarningsReport:
    """Compute the (current, previous) window pair from the
    supplied orders list.

    ``window_hours`` defines BOTH the current and previous window
    width. ``now`` defaults to time.time() but is overridable for
    tests."""
    window_hours = max(0.0, float(window_hours))
    now = now if now is not None else time.time()
    window_seconds = window_hours * 3600.0

    current_start = now - window_seconds
    previous_start = current_start - window_seconds

    current = _summarize(
        orders,
        window_start=current_start,
        window_end=now,
    )
    previous = _summarize(
        orders,
        window_start=previous_start,
        window_end=current_start,
    )

    delta = round(current.revenue - previous.revenue, 2)
    if previous.revenue > 0:
        delta_pct = round(
            (current.revenue - previous.revenue) / previous.revenue
            * 100, 1,
        )
    elif current.revenue > 0:
        delta_pct = 100.0
    else:
        delta_pct = 0.0

    return EarningsReport(
        store_id=store_id,
        window_hours=window_hours,
        current=current,
        previous=previous,
        delta=delta,
        delta_pct=delta_pct,
        verdict=_verdict(current.revenue, previous.revenue),
    )


def to_dict(report: EarningsReport) -> dict[str, Any]:
    """Serialize the dataclass tree to a plain dict."""
    return {
        "store_id": report.store_id,
        "window_hours": report.window_hours,
        "current": asdict(report.current),
        "previous": asdict(report.previous),
        "delta": report.delta,
        "delta_pct": report.delta_pct,
        "verdict": report.verdict,
    }
