"""Autonomy single-domain drill view (W332).

When an operator notices ONE autonomy domain is warning, the
current surfaces are too broad: autonomy-status shows all 7
domains, autonomy-doctor shows wiring across all 7, autonomy-
history shows the unified timeline. The operator has to mentally
filter for just the one domain they care about.

`autonomy-domain <name>` is the focused drill: a per-domain
mini-dashboard that aggregates verdict + paused state + recent
events + env knobs + applied count + wiring health for ONE
specific domain.

Accepted domain identifiers (any of these resolves to the same
domain):
  - canonical key: customer_support_refund, marketing_budget,
    fulfillment, inventory, discount_cleanup, order_followup,
    product_seo
  - short alias: refund, marketing, budget, fulfillment,
    inventory, cleanup, followup, seo
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Aliases → canonical domain key
_DOMAIN_ALIASES: dict[str, str] = {
    # canonical → canonical
    "customer_support_refund": "customer_support_refund",
    "marketing_budget": "marketing_budget",
    "fulfillment": "fulfillment",
    "inventory": "inventory",
    "discount_cleanup": "discount_cleanup",
    "order_followup": "order_followup",
    "product_seo": "product_seo",
    "customer_outreach": "customer_outreach",
    "catalog_quality": "catalog_quality",
    # short aliases
    "refund": "customer_support_refund",
    "support": "customer_support_refund",
    "customer_support": "customer_support_refund",
    "marketing": "marketing_budget",
    "budget": "marketing_budget",
    "cleanup": "discount_cleanup",
    "followup": "order_followup",
    "seo": "product_seo",
    "outreach": "customer_outreach",
    "quality": "catalog_quality",
    "shipping_alert": "shipping_alert",
    "shipping": "shipping_alert",
}


# Canonical → (autonomy_status name used in DomainSummary,
# log module identifier for the timeline)
_DOMAIN_META: dict[
    str, tuple[str, str],
] = {
    "customer_support_refund": ("customer_support", "refund"),
    "marketing_budget": ("marketing", "marketing"),
    "fulfillment": ("fulfillment", "fulfillment"),
    "inventory": ("inventory", "inventory"),
    "discount_cleanup": ("discount_cleanup", "cleanup"),
    "order_followup": ("order_followup", "followup"),
    "product_seo": ("product_seo", "seo"),
    "customer_outreach": ("customer_outreach", "outreach"),
    "catalog_quality": ("catalog_quality", "quality"),
    "shipping_alert": ("shipping_alert", "shipping"),
}


@dataclass
class DomainView:
    domain: str
    found: bool = False
    verdict: str = ""
    paused: bool = False
    applied_count: int = 0
    next_action: str = ""
    health_failure_ratio: float | None = None
    recent_events_count: int = 0
    sample_events: list[dict[str, Any]] = field(
        default_factory=list,
    )
    env_knobs_set: int = 0
    env_knobs_total: int = 0
    env_knobs: list[dict[str, Any]] = field(
        default_factory=list,
    )
    wiring_cls: str = ""  # ok / warn / fail


def resolve_domain(name: str) -> str | None:
    """Map an alias or canonical name to the canonical key,
    or None if unknown."""
    norm = (name or "").lower().strip().replace("-", "_")
    return _DOMAIN_ALIASES.get(norm)


def _status_block(canonical: str) -> dict[str, Any]:
    try:
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
        r = get_autonomy_status()
        status_name = _DOMAIN_META[canonical][0]
        for d in r.domains:
            if d.name == status_name:
                return {
                    "verdict": d.verdict,
                    "paused": d.paused,
                    "applied_count": d.applied_count,
                    "next_action": d.next_action,
                    "health_failure_ratio": (
                        d.health_failure_ratio
                    ),
                }
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "domain summary probe raised: %s", exc,
        )
    return {}


def _events_block(
    canonical: str, window_hours: float, store_id: str | None,
) -> tuple[int, list[dict[str, Any]]]:
    """Fetch recent events for one domain via autonomy_history's
    per-domain extractor."""
    try:
        from core.automation.autonomy_history import (
            _DOMAIN_LOGS, _domain_events,
        )
        log_key = _DOMAIN_META[canonical][1]
        match = None
        for tup in _DOMAIN_LOGS:
            if tup[0] == log_key:
                match = tup
                break
        if match is None:
            return (0, [])
        domain, pkg, log_modname, fn_name = match
        entries = _domain_events(
            domain, pkg, log_modname, fn_name,
            window_hours, store_id,
        )
        sample = [
            {
                "timestamp": e.timestamp,
                "action": e.action,
                "status": e.status,
                "detail": e.detail,
            }
            for e in entries[:5]
        ]
        return (len(entries), sample)
    except Exception:  # noqa: BLE001
        return (0, [])


def _env_block(
    canonical: str,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Fetch env knob coverage for one domain via Pattern T."""
    try:
        from engines._pattern_t_audit import (
            build_autonomy_env_registry,
        )
        r = build_autonomy_env_registry()
        domain_knobs = [
            k for k in r.knobs if k.domain == canonical
        ]
        set_count = sum(
            1 for k in domain_knobs
            if k.current_value is not None
        )
        knobs_dump = [
            {
                "name": k.name,
                "value": k.current_value,
            }
            for k in domain_knobs
        ]
        return (set_count, len(domain_knobs), knobs_dump)
    except Exception:  # noqa: BLE001
        return (0, 0, [])


def _wiring_cls(canonical: str) -> str:
    try:
        from core.automation.autonomy_doctor import (
            run_autonomy_doctor,
        )
        r = run_autonomy_doctor()
        status_name = _DOMAIN_META[canonical][0]
        for d in r.domains:
            if d.name == status_name:
                return d.cls
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "doctor probe raised for %s: %s",
            canonical, exc,
        )
    return ""


def run_autonomy_domain_view(
    name: str,
    *,
    window_hours: float = 24.0,
    store_id: str | None = None,
) -> DomainView:
    """Build the per-domain drill view."""
    canonical = resolve_domain(name)
    if canonical is None:
        return DomainView(domain=name, found=False)
    view = DomainView(domain=canonical, found=True)
    status = _status_block(canonical)
    view.verdict = status.get("verdict", "unknown")
    view.paused = bool(status.get("paused", False))
    view.applied_count = int(
        status.get("applied_count", 0),
    )
    view.next_action = status.get("next_action", "")
    view.health_failure_ratio = status.get(
        "health_failure_ratio",
    )
    view.recent_events_count, view.sample_events = (
        _events_block(canonical, window_hours, store_id)
    )
    view.env_knobs_set, view.env_knobs_total, view.env_knobs = (
        _env_block(canonical)
    )
    view.wiring_cls = _wiring_cls(canonical)
    return view


def list_domains() -> list[str]:
    """Canonical domain keys, for ``--help`` enumeration."""
    return list(_DOMAIN_META.keys())
