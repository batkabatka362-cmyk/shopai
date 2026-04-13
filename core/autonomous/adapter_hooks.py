"""Adapter-powered side effects for the autonomous cycle.

The controller's ``run_cycle`` already computes everything ShopAI
needs to learn about a store. This module is how that learning
reaches the outside world:

  * **Analytics** — every cycle (and every order) emits a
    ``cycle_complete`` / ``order_placed`` event to whichever
    analytics adapter (PostHog, Mixpanel) is configured. The
    router picks the highest-priority one.
  * **CRM sync** — new customers with an email address are
    upserted into the configured CRM (HubSpot) so the operator's
    existing sales funnel sees them.
  * **Helpdesk alerts** — if a cycle racks up enough phase errors
    (or a critical one) a ticket is opened in the configured
    helpdesk (Intercom / Zendesk / Crisp) with the error detail.
  * **Automation webhook** — end-of-cycle payload is POSTed to
    n8n (via the ``N8N_WEBHOOK_CYCLE_PATH`` path or a full URL)
    so operators can wire in custom Slack/email/CRM/etc. flows.

Every hook is **best-effort**. Missing env vars, unconfigured
adapters, router dead-ends, or vendor errors are logged at DEBUG
and ignored — they must never break the cycle. The hooks are
wrapped so even an unexpected exception is swallowed.

Each hook is gated on a router match: if the router has no
configured adapter for the capability, the hook is a no-op. That
means operators opt in by *just setting the API key*, with no
extra flag needed. A master kill-switch is still available via
``SHOPAI_ADAPTER_HOOKS=off`` for paranoid deployments.
"""
from __future__ import annotations

import os
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("autonomous.adapter_hooks")


def _hooks_enabled() -> bool:
    # Disabled only when explicitly turned off. Default on.
    val = os.environ.get("SHOPAI_ADAPTER_HOOKS", "on").strip().lower()
    return val not in ("off", "0", "false", "no")


def _safe_route_execute(
    router: Any,
    capability: Any,
    params: dict[str, Any],
    *,
    tag: str,
) -> dict[str, Any]:
    """Route + execute a capability, swallowing any failure.

    Returns a small status dict suitable for stashing inside
    ``cycle_result["phases"]["adapter_hooks"]`` so operators can
    see at a glance which hooks fired.
    """
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug("hook %s: router raised %s", tag, exc)
        return {"ok": False, "skipped": True, "reason": str(exc)[:80]}

    if not getattr(result, "ok", False):
        err = getattr(result, "error", None)
        reason = getattr(err, "reason", "") if err else ""
        logger.debug("hook %s: adapter %s failed: %s",
                     tag, getattr(result, "adapter", "?"), reason)
        return {
            "ok": False,
            "adapter": getattr(result, "adapter", ""),
            "reason": (reason or "unknown")[:80],
        }

    return {
        "ok": True,
        "adapter": getattr(result, "adapter", ""),
        "latency_ms": getattr(result, "latency_ms", 0.0),
    }


# ── Analytics ──────────────────────────────────────────────────


def emit_analytics_events(
    router: Any,
    cycle_result: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any]:
    """Track ``cycle_complete`` + one ``order_placed`` event per
    new order on whichever analytics adapter is configured.

    Returns a summary for stashing on ``cycle_result``.
    """
    from core.adapters.base import Capability

    store_id = str(cycle_result.get("store_id", "unknown"))
    cycle_id = str(cycle_result.get("cycle_id", ""))

    summary: dict[str, Any] = {"cycle_event": None, "order_events": 0}

    # 1) Fire a per-cycle summary event.
    cycle_params = {
        "event": "shopai_cycle_complete",
        "distinct_id": f"store:{store_id}",
        "properties": {
            "store_id": store_id,
            "cycle_id": cycle_id,
            "duration_s": cycle_result.get("duration_s", 0.0),
            "phase_error_count": cycle_result.get("phase_error_count", 0),
            "insights": (cycle_result.get("phases", {})
                         .get("analysis", {}).get("insights", 0)),
            "actions_proposed": (cycle_result.get("phases", {})
                                 .get("decisions", {}).get("proposed", 0)),
            "products": (cycle_result.get("phases", {})
                         .get("data", {}).get("products", 0)),
            "orders": (cycle_result.get("phases", {})
                       .get("data", {}).get("orders", 0)),
        },
    }
    summary["cycle_event"] = _safe_route_execute(
        router, Capability.ANALYTICS_TRACK_EVENT, cycle_params,
        tag="analytics.cycle",
    )

    # 2) Fire one event per order. Bound by a modest per-cycle
    # cap so a bulk import doesn't spam the analytics backend.
    max_orders = int(os.environ.get("SHOPAI_ANALYTICS_ORDER_CAP", "25"))
    orders = data.get("order_data", []) or []
    fired = 0
    for order in orders[:max_orders]:
        if not isinstance(order, dict):
            continue
        order_id = str(order.get("id") or order.get("order_id") or "")
        customer = order.get("customer") or {}
        customer_id = (
            str(customer.get("id") or "")
            or str(order.get("customer_id") or "")
            or f"order:{order_id}"
        )
        params = {
            "event": "order_placed",
            "distinct_id": customer_id,
            "properties": {
                "store_id": store_id,
                "order_id": order_id,
                "total_price": order.get("total_price")
                               or order.get("total"),
                "currency": order.get("currency", ""),
                "line_items_count": len(order.get("line_items", []) or []),
                "financial_status": order.get("financial_status", ""),
            },
        }
        status = _safe_route_execute(
            router, Capability.ANALYTICS_TRACK_EVENT, params,
            tag="analytics.order",
        )
        if status.get("ok"):
            fired += 1
    summary["order_events"] = fired

    return summary


# ── CRM sync ───────────────────────────────────────────────────


def sync_crm_contacts(
    router: Any,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Upsert customers from this cycle's data into the configured
    CRM. Deduplicated by email. Throttled per cycle.

    Returns ``{"synced": n, "skipped": m}``.
    """
    from core.adapters.base import Capability

    customers = data.get("customer_data", []) or []
    if not customers:
        return {"synced": 0, "skipped": 0}

    max_syncs = int(os.environ.get("SHOPAI_CRM_SYNC_CAP", "20"))
    seen: set[str] = set()
    synced = 0
    skipped = 0

    for customer in customers:
        if synced >= max_syncs:
            break
        if not isinstance(customer, dict):
            skipped += 1
            continue
        email = (customer.get("email") or "").strip().lower()
        if not email or email in seen:
            skipped += 1
            continue
        seen.add(email)

        params = {
            "email": email,
            "first_name": customer.get("first_name", ""),
            "last_name": customer.get("last_name", ""),
            "phone": customer.get("phone", ""),
        }
        if customer.get("default_address", {}).get("company"):
            params["company"] = customer["default_address"]["company"]

        status = _safe_route_execute(
            router, Capability.CRM_UPSERT_CONTACT, params,
            tag="crm.upsert",
        )
        if status.get("ok"):
            synced += 1
        else:
            skipped += 1
            # If the router has no CRM adapter at all, abort early
            # rather than churning through every customer.
            if status.get("skipped") or "no adapter" in status.get(
                "reason", "",
            ).lower():
                break

    return {"synced": synced, "skipped": skipped}


# ── Helpdesk alerts ────────────────────────────────────────────


def create_helpdesk_ticket_for_errors(
    router: Any,
    cycle_result: dict[str, Any],
    phase_errors: dict[str, str],
) -> dict[str, Any]:
    """If the cycle crossed the error threshold, open a helpdesk
    ticket summarising the failures.

    Only fires when the error count is >= the threshold (default
    3) so routine warnings don't spam the inbox.
    """
    from core.adapters.base import Capability

    if not phase_errors:
        return {"created": False, "reason": "no_errors"}

    threshold = int(os.environ.get("SHOPAI_HELPDESK_ERROR_THRESHOLD", "3"))
    if len(phase_errors) < threshold:
        return {
            "created": False,
            "reason": f"below_threshold ({len(phase_errors)}/{threshold})",
        }

    cycle_id = cycle_result.get("cycle_id", "")
    store_id = cycle_result.get("store_id", "")

    subject = (
        f"[ShopAI] Cycle {cycle_id} degraded: "
        f"{len(phase_errors)} phase errors"
    )
    body_lines = [
        f"Store: {store_id}",
        f"Cycle: {cycle_id}",
        f"Duration: {cycle_result.get('duration_s', 0.0)}s",
        f"Error count: {len(phase_errors)}",
        "",
        "Failed phases:",
    ]
    for phase, err in sorted(phase_errors.items())[:15]:
        body_lines.append(f"  - {phase}: {err[:200]}")

    # Default requester: the operator's configured support inbox,
    # or a synthesised one derived from the store id so the ticket
    # is always assignable even on fresh installs.
    requester_email = (
        os.environ.get("SHOPAI_SUPPORT_EMAIL")
        or f"shopai-alerts@{store_id or 'unknown'}"
    )

    params = {
        "subject": subject,
        "body": "\n".join(body_lines),
        "priority": "high",
        "tags": ["shopai", "autonomous", "degraded-cycle"],
        "requester_email": requester_email,
        "requester_name": "ShopAI Autonomous Controller",
    }

    status = _safe_route_execute(
        router, Capability.HELPDESK_CREATE_TICKET, params,
        tag="helpdesk.ticket",
    )
    return {
        "created": bool(status.get("ok")),
        "adapter": status.get("adapter", ""),
        "reason": status.get("reason", ""),
    }


# ── Automation webhook ─────────────────────────────────────────


def trigger_automation_webhook(
    router: Any,
    cycle_result: dict[str, Any],
) -> dict[str, Any]:
    """POST a compact cycle summary to an automation platform
    (n8n / Zapier) so operators can fan out to Slack, Google
    Sheets, their own CRM, etc.

    The adapter is selected by ``AUTOMATION_TRIGGER`` capability.
    For n8n the payload is sent either to an explicit webhook path
    (``SHOPAI_CYCLE_WEBHOOK_PATH`` env var) or a direct URL
    (``SHOPAI_CYCLE_WEBHOOK_URL``).
    """
    from core.adapters.base import Capability

    webhook_url = os.environ.get("SHOPAI_CYCLE_WEBHOOK_URL", "").strip()
    webhook_path = os.environ.get("SHOPAI_CYCLE_WEBHOOK_PATH", "").strip()
    workflow_id = os.environ.get("SHOPAI_CYCLE_WORKFLOW_ID", "").strip()

    if not (webhook_url or webhook_path or workflow_id):
        return {"triggered": False, "reason": "no_webhook_configured"}

    payload = {
        "store_id": cycle_result.get("store_id", ""),
        "cycle_id": cycle_result.get("cycle_id", ""),
        "timestamp": time.time(),
        "duration_s": cycle_result.get("duration_s", 0.0),
        "phase_error_count": cycle_result.get("phase_error_count", 0),
        "insights": (cycle_result.get("phases", {})
                     .get("analysis", {}).get("insights", 0)),
        "actions_proposed": (cycle_result.get("phases", {})
                             .get("decisions", {}).get("proposed", 0)),
        "status": cycle_result.get("status", ""),
    }

    params: dict[str, Any] = {"data": payload}
    if webhook_url:
        params["webhook_url"] = webhook_url
    elif webhook_path:
        params["webhook_path"] = webhook_path
    else:
        params["workflow_id"] = workflow_id

    status = _safe_route_execute(
        router, Capability.AUTOMATION_TRIGGER, params,
        tag="automation.webhook",
    )
    return {
        "triggered": bool(status.get("ok")),
        "adapter": status.get("adapter", ""),
        "reason": status.get("reason", ""),
    }


# ── Top-level orchestrator ─────────────────────────────────────


def run_post_cycle_hooks(
    router: Any,
    cycle_result: dict[str, Any],
    data: dict[str, Any],
    phase_errors: dict[str, str],
) -> dict[str, Any]:
    """Run every adapter hook in sequence, stash a summary.

    Wrapped in a try/except so a single hook raising can't take
    down the others. The returned summary is suitable for
    attaching to ``cycle_result["phases"]["adapter_hooks"]``.
    """
    if not _hooks_enabled():
        return {"enabled": False}
    if router is None:
        return {"enabled": False, "reason": "no_router"}

    summary: dict[str, Any] = {"enabled": True}

    try:
        summary["analytics"] = emit_analytics_events(
            router, cycle_result, data,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("analytics hook crashed: %s", exc)
        summary["analytics"] = {"ok": False, "error": str(exc)[:80]}

    try:
        summary["crm"] = sync_crm_contacts(router, data)
    except Exception as exc:  # noqa: BLE001
        logger.debug("crm hook crashed: %s", exc)
        summary["crm"] = {"synced": 0, "error": str(exc)[:80]}

    try:
        summary["helpdesk"] = create_helpdesk_ticket_for_errors(
            router, cycle_result, phase_errors,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("helpdesk hook crashed: %s", exc)
        summary["helpdesk"] = {"created": False, "error": str(exc)[:80]}

    try:
        summary["automation"] = trigger_automation_webhook(
            router, cycle_result,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("automation hook crashed: %s", exc)
        summary["automation"] = {"triggered": False, "error": str(exc)[:80]}

    return summary
