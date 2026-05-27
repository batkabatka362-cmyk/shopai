"""Refund status surface (Wave 102).

Aggregates ``data/refund_log.json`` entries into an operator-
facing report. Powers ``shopai refund-status``.

Surfaces:
  - total refunds in window (count + total $)
  - applied vs skipped breakdown
  - status distribution (recorded / adapter_failed /
    fraud_risk_too_high / exceeds_max_amount / ...)
  - per-store rollup when multiple stores present
  - sample skip reasons for debugging
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engines.returns_management.refund_log import recent_refunds


@dataclass
class RefundStatusReport:
    window_hours: float
    store_id: str | None = None
    total_entries: int = 0
    applied_count: int = 0
    skipped_count: int = 0
    total_refunded: float = 0.0
    by_status: dict[str, int] = field(default_factory=dict)
    by_store: dict[str, dict[str, Any]] = field(default_factory=dict)
    avg_refund_amount: float = 0.0
    sample_skips: list[dict[str, Any]] = field(
        default_factory=list,
    )


def get_refund_status(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> RefundStatusReport:
    """Build the refund status report for the window."""
    rows = recent_refunds(
        window_hours=window_hours, store_id=store_id,
    )
    report = RefundStatusReport(
        window_hours=window_hours,
        store_id=store_id,
    )
    report.total_entries = len(rows)

    if not rows:
        return report

    applied_amounts: list[float] = []
    for r in rows:
        status = r.get("status", "")
        report.by_status[status] = (
            report.by_status.get(status, 0) + 1
        )
        if r.get("applied") is True:
            report.applied_count += 1
            try:
                amount = float(r.get("refund_amount", 0) or 0)
            except (TypeError, ValueError):
                amount = 0.0
            applied_amounts.append(amount)
            report.total_refunded = round(
                report.total_refunded + amount, 2,
            )
        else:
            report.skipped_count += 1
        # Per-store rollup -- only when caller didn't filter
        # to one store
        sid = str(r.get("store_id", "") or "")
        if not store_id and sid:
            bucket = report.by_store.setdefault(sid, {
                "applied": 0,
                "skipped": 0,
                "total_refunded": 0.0,
            })
            if r.get("applied"):
                bucket["applied"] += 1
                bucket["total_refunded"] = round(
                    bucket["total_refunded"] + float(
                        r.get("refund_amount", 0) or 0,
                    ),
                    2,
                )
            else:
                bucket["skipped"] += 1

    if applied_amounts:
        report.avg_refund_amount = round(
            sum(applied_amounts) / len(applied_amounts), 2,
        )

    # Sample up to 5 most recent SKIPPED rows for debugging
    skipped = [
        r for r in rows
        if r.get("applied") is False
    ]
    report.sample_skips = skipped[:5]

    return report
