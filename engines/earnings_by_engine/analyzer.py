"""Aggregate per-engine attribution against the W963 roster.

The W963 roster is the 18-engine cold-start chain. Engines
outside the roster are excluded so the operator gets a focused
view of which cold-start moves actually paid off — not a full
fleet drilldown (use shopai engine ranking for that).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 18-engine cold-start roster, mapped to the day on which the
# warmup-plan first introduces them. Lets the report sort by
# "appeared on day N", which is how the operator remembers them.
_W963_ROSTER: dict[str, int] = {
    "revenue_readiness":        1,   # W963-1
    "product_sourcer":          1,   # W963-2
    "earnings_report":          7,   # W963-4
    "earn_bootstrap":           1,   # W963-5
    "content_publisher":        2,   # W963-6
    "ads_launcher":             3,   # W963-7
    "email_connect":            3,   # W963-8
    "affiliate_links":          6,   # W963-9
    "pinterest_publisher":      3,   # W963-10
    "cro_variants":            13,   # W963-11
    "tiktok_publisher":         5,   # W963-12
    "customer_chat":           15,   # W963-13
    "cold_start_orchestrator":  1,   # W963-14
    "instagram_publisher":      5,   # W963-15
    "review_request":          11,   # W963-16
    "warmup_plan":              0,   # W963-17 (meta)
    "today_brief":              0,   # W963-18 (meta)
    "earnings_by_engine":       0,   # W963-19 (meta)
}


@dataclass
class EngineEarnings:
    engine: str
    intro_day: int
    attributed_orders: int = 0
    attributed_revenue: float = 0.0
    confidence: str = "none"
    verdict: str = "no_data"  # earning / flat / no_data


@dataclass
class EarningsByEngineReport:
    window_hours: float
    store_id: str | None
    total_attributed_revenue: float = 0.0
    total_attributed_orders: int = 0
    engines: list[EngineEarnings] = field(default_factory=list)
    earning_count: int = 0
    no_data_count: int = 0


def _verdict_for(rev: float, orders: int) -> str:
    if orders == 0:
        return "no_data"
    if rev >= 10.0:
        return "earning"
    return "flat"


def analyze_earnings_by_engine(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
    orders: list[dict[str, Any]] | None = None,
) -> EarningsByEngineReport:
    """Build the per-W963-engine earnings report. Best-effort;
    if attribution substrate raises, returns an empty report
    populated with the roster + no_data verdict so callers can
    still render the table."""
    report = EarningsByEngineReport(
        window_hours=window_hours, store_id=store_id,
    )

    try:
        from engines._revenue_attribution import (
            attribute_revenue,
        )
        attr = attribute_revenue(
            window_hours=window_hours,
            store_id=store_id,
            orders=orders,
        )
    except Exception:  # noqa: BLE001
        attr = None

    per_engine: dict[str, Any] = {}
    if attr is not None:
        # AttributionReport.per_engine is a list[EngineAttribution]
        for ea in getattr(attr, "per_engine", []) or []:
            name = getattr(ea, "engine", "") or ""
            if not name:
                continue
            per_engine[name] = ea

    for name, intro_day in sorted(
        _W963_ROSTER.items(), key=lambda x: (x[1], x[0]),
    ):
        ea = per_engine.get(name)
        orders_n = int(getattr(ea, "attributed_orders", 0)) if ea else 0
        rev = float(getattr(ea, "attributed_revenue", 0.0)) if ea else 0.0
        conf = str(getattr(ea, "confidence", "none")) if ea else "none"
        verdict = _verdict_for(rev, orders_n)
        report.engines.append(
            EngineEarnings(
                engine=name,
                intro_day=intro_day,
                attributed_orders=orders_n,
                attributed_revenue=rev,
                confidence=conf,
                verdict=verdict,
            )
        )
        report.total_attributed_orders += orders_n
        report.total_attributed_revenue += rev
        if verdict == "earning":
            report.earning_count += 1
        if verdict == "no_data":
            report.no_data_count += 1

    return report


def w963_roster() -> dict[str, int]:
    """Public roster (engine -> intro day)."""
    return dict(_W963_ROSTER)
