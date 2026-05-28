"""Unified empire-wide autonomy status (Wave 149).

Aggregates the 4 production autonomy domains into one
verdict + roll-up:

  - Customer support (refund + ticket-tag)
  - Marketing (budget)
  - Fulfillment (route)
  - Inventory (reorder)

The verdict aggregator picks the WORST domain verdict (paused
> degraded > quiet > healthy). next_action surfaces the
operator's highest-priority drill.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_VERDICT_SEVERITY = {
    "paused": 3,
    "degraded": 2,
    "quiet": 1,
    "healthy": 0,
}


@dataclass
class DomainSummary:
    name: str
    verdict: str = "healthy"
    paused: bool = False
    applied_count: int = 0
    health_failure_ratio: float = 0.0
    next_action: str = ""
    reasons: list[str] = field(default_factory=list)


@dataclass
class AutonomyStatusReport:
    window_hours: float
    store_id: str | None = None
    domains: list[DomainSummary] = field(default_factory=list)
    overall_verdict: str = "healthy"
    overall_next_action: str = ""
    total_applied: int = 0
    paused_domains: list[str] = field(default_factory=list)


def _customer_support_summary(
    window_hours: float, store_id: str | None = None,
) -> DomainSummary:
    try:
        from engines.customer_support.support_status import (
            get_support_status,
        )
        r = get_support_status(
            window_hours=window_hours, store_id=store_id,
        )
        return DomainSummary(
            name="customer_support",
            verdict=r.verdict,
            paused=r.refund_paused,
            applied_count=r.refund_applied_count,
            health_failure_ratio=r.refund_failure_ratio,
            next_action=r.next_action,
            reasons=list(r.verdict_reasons),
        )
    except Exception as exc:  # noqa: BLE001
        return DomainSummary(
            name="customer_support",
            verdict="quiet",
            reasons=[f"probe raised: {exc}"],
        )


def _marketing_summary(
    window_hours: float, store_id: str | None = None,
) -> DomainSummary:
    try:
        from engines.roas_guardrails.marketing_status import (
            get_marketing_status,
        )
        r = get_marketing_status(
            window_hours=window_hours, store_id=store_id,
        )
        return DomainSummary(
            name="marketing",
            verdict=r.verdict,
            paused=r.paused,
            applied_count=r.applied_count,
            health_failure_ratio=r.health_failure_ratio,
            next_action=r.next_action,
            reasons=list(r.verdict_reasons),
        )
    except Exception as exc:  # noqa: BLE001
        return DomainSummary(
            name="marketing",
            verdict="quiet",
            reasons=[f"probe raised: {exc}"],
        )


def _fulfillment_summary(
    window_hours: float, store_id: str | None = None,
) -> DomainSummary:
    try:
        from engines.fulfillment_autonomy.fulfillment_status import (
            get_fulfillment_status,
        )
        r = get_fulfillment_status(
            window_hours=window_hours, store_id=store_id,
        )
        return DomainSummary(
            name="fulfillment",
            verdict=r.verdict,
            paused=r.paused,
            applied_count=r.applied_count,
            health_failure_ratio=r.health_failure_ratio,
            next_action=r.next_action,
            reasons=list(r.verdict_reasons),
        )
    except Exception as exc:  # noqa: BLE001
        return DomainSummary(
            name="fulfillment",
            verdict="quiet",
            reasons=[f"probe raised: {exc}"],
        )


def _discount_cleanup_summary(
    window_hours: float, store_id: str | None = None,
) -> DomainSummary:
    try:
        from engines.discount_cleanup_autonomy.cleanup_status import (
            get_cleanup_status,
        )
        r = get_cleanup_status(
            window_hours=window_hours, store_id=store_id,
        )
        return DomainSummary(
            name="discount_cleanup",
            verdict=r.verdict,
            paused=r.paused,
            applied_count=r.applied_count,
            health_failure_ratio=r.health_failure_ratio,
            next_action=r.next_action,
            reasons=list(r.verdict_reasons),
        )
    except Exception as exc:  # noqa: BLE001
        return DomainSummary(
            name="discount_cleanup",
            verdict="quiet",
            reasons=[f"probe raised: {exc}"],
        )


def _product_seo_summary(
    window_hours: float, store_id: str | None = None,
) -> DomainSummary:
    try:
        from engines.product_seo_autonomy.seo_status import (
            get_seo_status,
        )
        r = get_seo_status(
            window_hours=window_hours, store_id=store_id,
        )
        return DomainSummary(
            name="product_seo",
            verdict=r.verdict,
            paused=r.paused,
            applied_count=r.applied_count,
            health_failure_ratio=r.health_failure_ratio,
            next_action=r.next_action,
            reasons=list(r.verdict_reasons),
        )
    except Exception as exc:  # noqa: BLE001
        return DomainSummary(
            name="product_seo",
            verdict="quiet",
            reasons=[f"probe raised: {exc}"],
        )


def _order_followup_summary(
    window_hours: float, store_id: str | None = None,
) -> DomainSummary:
    try:
        from engines.order_followup_autonomy.followup_status import (
            get_followup_status,
        )
        r = get_followup_status(
            window_hours=window_hours, store_id=store_id,
        )
        return DomainSummary(
            name="order_followup",
            verdict=r.verdict,
            paused=r.paused,
            applied_count=r.applied_count,
            health_failure_ratio=r.health_failure_ratio,
            next_action=r.next_action,
            reasons=list(r.verdict_reasons),
        )
    except Exception as exc:  # noqa: BLE001
        return DomainSummary(
            name="order_followup",
            verdict="quiet",
            reasons=[f"probe raised: {exc}"],
        )


def _catalog_quality_summary(
    window_hours: float, store_id: str | None = None,
) -> DomainSummary:
    try:
        from engines.catalog_quality_autonomy.quality_status import (  # noqa: E501
            get_catalog_quality_status,
        )
        r = get_catalog_quality_status(
            window_hours=window_hours, store_id=store_id,
        )
        return DomainSummary(
            name="catalog_quality",
            verdict=r.verdict,
            paused=r.paused,
            applied_count=r.applied_count,
            health_failure_ratio=r.health_failure_ratio,
            next_action=r.next_action,
            reasons=list(r.verdict_reasons),
        )
    except Exception as exc:  # noqa: BLE001
        return DomainSummary(
            name="catalog_quality",
            verdict="quiet",
            reasons=[f"probe raised: {exc}"],
        )


def _customer_outreach_summary(
    window_hours: float, store_id: str | None = None,
) -> DomainSummary:
    try:
        from engines.customer_outreach_autonomy.outreach_status import (  # noqa: E501
            get_customer_outreach_status,
        )
        r = get_customer_outreach_status(
            window_hours=window_hours, store_id=store_id,
        )
        return DomainSummary(
            name="customer_outreach",
            verdict=r.verdict,
            paused=r.paused,
            applied_count=r.applied_count,
            health_failure_ratio=r.health_failure_ratio,
            next_action=r.next_action,
            reasons=list(r.verdict_reasons),
        )
    except Exception as exc:  # noqa: BLE001
        return DomainSummary(
            name="customer_outreach",
            verdict="quiet",
            reasons=[f"probe raised: {exc}"],
        )


def _inventory_summary(
    window_hours: float, store_id: str | None = None,
) -> DomainSummary:
    try:
        from engines.inventory_autonomy.inventory_status import (
            get_inventory_status,
        )
        r = get_inventory_status(
            window_hours=window_hours, store_id=store_id,
        )
        return DomainSummary(
            name="inventory",
            verdict=r.verdict,
            paused=r.paused,
            applied_count=r.applied_count,
            health_failure_ratio=r.health_failure_ratio,
            next_action=r.next_action,
            reasons=list(r.verdict_reasons),
        )
    except Exception as exc:  # noqa: BLE001
        return DomainSummary(
            name="inventory",
            verdict="quiet",
            reasons=[f"probe raised: {exc}"],
        )


def get_autonomy_status(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> AutonomyStatusReport:
    """Roll up all 4 autonomy domains into one report.

    Wave 151: when ``store_id`` is supplied, each domain
    aggregator scopes to that store. None means fleet-wide
    (default behaviour preserved).
    """
    report = AutonomyStatusReport(window_hours=window_hours)
    report.store_id = store_id
    report.domains = [
        _customer_support_summary(
            window_hours, store_id=store_id,
        ),
        _marketing_summary(
            window_hours, store_id=store_id,
        ),
        _fulfillment_summary(
            window_hours, store_id=store_id,
        ),
        _inventory_summary(
            window_hours, store_id=store_id,
        ),
        _discount_cleanup_summary(
            window_hours, store_id=store_id,
        ),
        _order_followup_summary(
            window_hours, store_id=store_id,
        ),
        _product_seo_summary(
            window_hours, store_id=store_id,
        ),
        _customer_outreach_summary(
            window_hours, store_id=store_id,
        ),
        _catalog_quality_summary(
            window_hours, store_id=store_id,
        ),
    ]

    # Aggregate
    for d in report.domains:
        report.total_applied += d.applied_count
        if d.paused:
            report.paused_domains.append(d.name)

    # Overall verdict = worst domain verdict
    worst_severity = 0
    worst_domain: DomainSummary | None = None
    for d in report.domains:
        sev = _VERDICT_SEVERITY.get(d.verdict, 0)
        if sev > worst_severity:
            worst_severity = sev
            worst_domain = d

    if worst_domain is None:
        report.overall_verdict = "healthy"
        report.overall_next_action = (
            "All domains nominal. Monitor via daily-brief."
        )
    else:
        report.overall_verdict = worst_domain.verdict
        report.overall_next_action = (
            f"[{worst_domain.name}] "
            f"{worst_domain.next_action}"
        )
    return report
