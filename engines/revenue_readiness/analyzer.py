"""Revenue-readiness 6-gate analyzer.

Each gate inspects an existing substrate signal and returns a
``Gate`` dataclass:

  status   : "ready" / "partial" / "missing"
  metric   : a single numeric measure backing the status
  detail   : one-line human-readable summary
  next_action : CLI command to advance this gate (empty if ready)

Read-only. Never raises; defensive guards turn every probe
failure into a "missing" gate with the exception text in detail.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Threshold knobs. Conservative defaults that distinguish
# "anything > 0" from "actually trafficked".
_RECENT_ORDER_WINDOW_HOURS = 24.0 * 30.0  # 30 days
_AD_SPEND_WINDOW_HOURS = 24.0 * 7.0       # 7 days
_REPEAT_PURCHASE_MIN_PER_CUSTOMER = 1.5   # avg orders/customer
_PARTIAL_PRODUCT_COUNT = 3                # < 3 = partial
_PARTIAL_CUSTOMER_COUNT = 5


@dataclass
class Gate:
    name: str
    status: str  # "ready" | "partial" | "missing"
    metric: float = 0.0
    detail: str = ""
    next_action: str = ""


@dataclass
class ReadinessReport:
    store_id: str | None
    gates: list[Gate] = field(default_factory=list)
    verdict: str = "unknown"
    next_action: str = ""

    def passed_count(self) -> int:
        return sum(1 for g in self.gates if g.status == "ready")

    def total_count(self) -> int:
        return len(self.gates)


# ── Gate probes ──────────────────────────────────────────────


def _gate_products(stats: dict[str, Any]) -> Gate:
    count = int(stats.get("products", 0) or 0)
    if count >= _PARTIAL_PRODUCT_COUNT:
        status = "ready"
        action = ""
    elif count > 0:
        status = "partial"
        action = "shopai product-candidates --niche <niche> [--count 20]"
    else:
        status = "missing"
        action = (
            "Seed catalog: shopai onboard ... + shopai product-candidates"
        )
    return Gate(
        name="has_products",
        status=status,
        metric=float(count),
        detail=f"{count} product(s) in catalog",
        next_action=action,
    )


def _gate_orders_recent(stats: dict[str, Any]) -> Gate:
    # Use total_orders as a coarse proxy. A real-time
    # recent-orders probe would require SHOPIFY_FETCH_ORDERS;
    # WorldModel already aggregates total order count which is
    # enough to tell "any sales yet" vs "cold".
    orders = int(stats.get("orders", 0) or 0)
    if orders >= 10:
        status = "ready"
        action = ""
    elif orders > 0:
        status = "partial"
        action = "Build traffic: shopai marketing-status + ads connect"
    else:
        status = "missing"
        action = (
            "Wire ads + email: shopai ads connect <platform> "
            "+ shopai engine try-wireup email_marketing"
        )
    return Gate(
        name="has_orders_recent",
        status=status,
        metric=float(orders),
        detail=f"{orders} total order(s) recorded",
        next_action=action,
    )


def _gate_customers(stats: dict[str, Any]) -> Gate:
    count = int(stats.get("customers", 0) or 0)
    if count >= _PARTIAL_CUSTOMER_COUNT:
        status = "ready"
        action = ""
    elif count > 0:
        status = "partial"
        action = "Grow list: shopai engine try-wireup email_marketing"
    else:
        status = "missing"
        action = "Capture leads: install email signup + run first campaign"
    return Gate(
        name="has_active_customers",
        status=status,
        metric=float(count),
        detail=f"{count} customer(s) in store",
        next_action=action,
    )


def _gate_attributed_revenue(store_id: str | None) -> Gate:
    try:
        from engines._attribution_snapshot import last_snapshot
        snap = last_snapshot(store_id=store_id)
    except Exception as exc:  # noqa: BLE001
        return Gate(
            name="has_attributed_revenue",
            status="missing",
            metric=0.0,
            detail=f"attribution probe raised: {exc}",
            next_action="shopai cycle attribution --window-hours 168",
        )
    if snap is None:
        return Gate(
            name="has_attributed_revenue",
            status="missing",
            metric=0.0,
            detail="no attribution snapshots yet",
            next_action=(
                "Trigger first cycle: shopai cycle run --yes "
                "(env-gated)"
            ),
        )
    revenue = float(snap.attributed_revenue or 0.0)
    if revenue >= 1.0:
        return Gate(
            name="has_attributed_revenue",
            status="ready",
            metric=revenue,
            detail=(
                f"last snapshot: ${revenue:.2f} attributed "
                f"({snap.total_orders_in_window} orders)"
            ),
            next_action="",
        )
    return Gate(
        name="has_attributed_revenue",
        status="partial",
        metric=revenue,
        detail=(
            "attribution wired but $0 attributed in last snapshot"
        ),
        next_action="shopai engine ranking + engine alerts",
    )


def _gate_ad_spend_path(store_id: str | None) -> Gate:
    # First check: ads adapter registered at all.
    adapter_present = False
    try:
        from core.adapters.router import get_registry
        from core.adapters.base import Capability
        reg = get_registry()
        try:
            adapter_present = bool(
                reg.adapters_for_capability(
                    Capability.ADS_UPDATE_BUDGET,
                )
            )
        except (AttributeError, KeyError):
            adapter_present = False
    except Exception as exc:  # noqa: BLE001
        logger.debug("ads adapter probe raised: %s", exc)

    # Second check: any recent spend events.
    spend_events = 0
    try:
        from engines.roas_guardrails.ad_spend_log import (
            recent_events,
        )
        events = recent_events(
            window_hours=_AD_SPEND_WINDOW_HOURS,
        )
        spend_events = len(events or [])
    except Exception as exc:  # noqa: BLE001
        logger.debug("ad_spend_log probe raised: %s", exc)

    if adapter_present and spend_events > 0:
        return Gate(
            name="has_ad_spend_path",
            status="ready",
            metric=float(spend_events),
            detail=(
                f"ads adapter registered + "
                f"{spend_events} spend event(s) in 7d"
            ),
            next_action="",
        )
    if adapter_present:
        return Gate(
            name="has_ad_spend_path",
            status="partial",
            metric=0.0,
            detail="ads adapter registered but no recent spend",
            next_action=(
                "Launch first campaign + "
                "set SHOPAI_SPEND_CAP_DAILY_USD"
            ),
        )
    return Gate(
        name="has_ad_spend_path",
        status="missing",
        metric=0.0,
        detail="no ads adapter registered",
        next_action=(
            "Connect ads: bootstrap meta_ads / google_ads "
            "adapter + credentials"
        ),
    )


def _gate_repeat_purchase(stats: dict[str, Any]) -> Gate:
    customers = int(stats.get("customers", 0) or 0)
    orders = int(stats.get("orders", 0) or 0)
    if customers <= 0:
        return Gate(
            name="has_repeat_purchase",
            status="missing",
            metric=0.0,
            detail="no customers yet — repeat-rate undefined",
            next_action="(blocked on has_active_customers)",
        )
    ratio = orders / customers if customers > 0 else 0.0
    if ratio >= _REPEAT_PURCHASE_MIN_PER_CUSTOMER:
        return Gate(
            name="has_repeat_purchase",
            status="ready",
            metric=ratio,
            detail=(
                f"{orders} orders / {customers} customers = "
                f"{ratio:.2f} avg"
            ),
            next_action="",
        )
    if orders > customers:
        return Gate(
            name="has_repeat_purchase",
            status="partial",
            metric=ratio,
            detail=(
                f"some repeat orders ({ratio:.2f} avg per customer)"
            ),
            next_action=(
                "Strengthen retention: shopai engine try-wireup "
                "loyalty + churn_prediction"
            ),
        )
    return Gate(
        name="has_repeat_purchase",
        status="missing",
        metric=ratio,
        detail=(
            f"{ratio:.2f} orders/customer "
            f"— no repeat purchase signal yet"
        ),
        next_action=(
            "Wire retention: shopai engine try-wireup loyalty"
        ),
    )


# ── Top-level analyzer ──────────────────────────────────────


def _verdict(passed: int, total: int) -> str:
    if total <= 0:
        return "unknown"
    if passed == total:
        return "earning_active"
    pct = passed / total
    if pct >= 0.66:
        return "growing"
    if pct >= 0.33:
        return "building_traction"
    return "cold_start"


def _pick_next_action(gates: list[Gate]) -> str:
    """Highest-impact-first traversal. Order matters: products
    block everything else, then orders block traffic learning,
    etc."""
    priority = [
        "has_products",
        "has_active_customers",
        "has_orders_recent",
        "has_ad_spend_path",
        "has_attributed_revenue",
        "has_repeat_purchase",
    ]
    by_name = {g.name: g for g in gates}
    for name in priority:
        g = by_name.get(name)
        if g is None:
            continue
        if g.status == "missing":
            return g.next_action
    for name in priority:
        g = by_name.get(name)
        if g is None:
            continue
        if g.status == "partial":
            return g.next_action
    return ""


def analyze(
    *,
    stats: dict[str, Any],
    store_id: str | None = None,
) -> ReadinessReport:
    """Run all 6 gates against the supplied store stats + global
    substrate signals."""
    gates = [
        _gate_products(stats),
        _gate_orders_recent(stats),
        _gate_customers(stats),
        _gate_attributed_revenue(store_id),
        _gate_ad_spend_path(store_id),
        _gate_repeat_purchase(stats),
    ]
    passed = sum(1 for g in gates if g.status == "ready")
    return ReadinessReport(
        store_id=store_id,
        gates=gates,
        verdict=_verdict(passed, len(gates)),
        next_action=_pick_next_action(gates),
    )
