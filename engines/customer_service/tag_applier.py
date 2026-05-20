"""Customer Service Engine -- per-customer escalation tag applier.

The engine classifies every inbound interaction (chat / email /
SMS / web form) and decides whether it needs human escalation
(return / refund / complex order issue) or can be auto-handled
by the response builder. Pre-fix the escalation signal landed
in engine output only -- the merchant had to manually translate
"this customer hit our escalation rules at 9:42 AM" into a
Shopify segment / outreach worklist.

This applier closes the loop. When escalation is needed AND a
Shopify customer_id is known, push
``shopai-cs-escalated`` on the customer via
``SHOPIFY_TAG_CUSTOMER`` (the additive tagsAdd mutation --
existing tags preserved). Merchants then save admin searches
to drive a "needs human follow-up" worklist; downstream
engines (loyalty / email_marketing) filter on the tag for
white-glove retention plays.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_cs_tags=True + data.require_approval=False
    -> SHOPIFY_TAG_CUSTOMER immediately.
  data.apply_cs_tags=True + data.require_approval=True
    (default) -> enqueue each tag-update proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on. The engine processes ONE
interaction per run; this applier's list-shaped API stays
consistent with the other writers (callers can batch
externally, or supply a single-item list).

Skipped (no API call / no queue entry) when:
  * The interaction has no customer_id (anonymous chat)
  * escalation_needed is False (auto-resolved interactions
    are noise -- we want signal)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-customer; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.customer_service.tag_applier")


_ESCALATED_TAG = "shopai-cs-escalated"


def apply_cs_tags(
    interactions: list[dict[str, Any]],
    *,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-cs-escalated`` on each escalated customer.

    Each entry in ``interactions`` is
    ``{customer_id, intent, escalation_needed, assigned_team}``.
    Returns per-customer list with
    ``{customer_id, intent, assigned_team, tag, applied, error}``.
    When ``require_approval=True`` (default), ``applied`` is
    False for queue-only entries -- the actual tag lands when
    the dispatcher executes the approved action.
    ``pending_action_id`` is populated for those entries.
    """
    proposals = _build_proposals(interactions)
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    interactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter interactions to actionable per-customer rows."""
    if not isinstance(interactions, list):
        return []
    seen: set[str] = set()
    proposals: list[dict[str, Any]] = []
    for entry in interactions:
        if not isinstance(entry, dict):
            continue
        if not bool(entry.get("escalation_needed", False)):
            continue
        customer_id = str(entry.get("customer_id") or "").strip()
        if not customer_id or customer_id in seen:
            continue
        seen.add(customer_id)
        intent = str(entry.get("intent") or "").strip()
        assigned_team = str(entry.get("assigned_team") or "").strip()
        proposals.append({
            "customer_id": customer_id,
            "intent": intent,
            "assigned_team": assigned_team,
            "tag": _ESCALATED_TAG,
        })
    return proposals


def _apply_each_direct(
    proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Direct ``SHOPIFY_TAG_CUSTOMER`` per proposal."""
    router = _get_router()
    capability = _get_tag_capability()
    if router is None or capability is None:
        return [
            {
                "customer_id": p["customer_id"],
                "intent": p["intent"],
                "assigned_team": p["assigned_team"],
                "tag": p["tag"],
                "applied": False,
                "error": "router_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        try:
            result = router.execute(capability, {
                "id": p["customer_id"],
                "tags": [p["tag"]],
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "customer_service tag_customer raised for %s: %s",
                p["customer_id"], exc,
            )
            _record_writeback_safely(
                customer_id=p["customer_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "customer_id": p["customer_id"],
                "intent": p["intent"],
                "assigned_team": p["assigned_team"],
                "tag": p["tag"],
                "applied": False,
                "error": f"adapter_raised: {exc}",
            })
            continue

        ok = bool(getattr(result, "ok", False))
        error = getattr(result, "error", None)
        if ok:
            _record_writeback_safely(
                customer_id=p["customer_id"],
                tag=p["tag"], success=True,
            )
            results.append({
                "customer_id": p["customer_id"],
                "intent": p["intent"],
                "assigned_team": p["assigned_team"],
                "tag": p["tag"],
                "applied": True,
                "error": None,
            })
        else:
            err_str = str(error or "rejected")
            _record_writeback_safely(
                customer_id=p["customer_id"],
                tag=p["tag"], success=False, error=err_str,
            )
            results.append({
                "customer_id": p["customer_id"],
                "intent": p["intent"],
                "assigned_team": p["assigned_team"],
                "tag": p["tag"],
                "applied": False,
                "error": f"adapter_failed: {err_str}",
            })
    return results


def _enqueue_each(
    proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enqueue each proposal via the approval queue."""
    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [
            {
                "customer_id": p["customer_id"],
                "intent": p["intent"],
                "assigned_team": p["assigned_team"],
                "tag": p["tag"],
                "applied": False,
                "error": "approval_queue_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        params = {
            "customer_id": p["customer_id"],
            "tag": p["tag"],
            "intent": p["intent"],
            "assigned_team": p["assigned_team"],
        }
        intent_part = f" ({p['intent']})" if p["intent"] else ""
        team_part = (
            f" -> {p['assigned_team']}" if p["assigned_team"] else ""
        )
        narrative = (
            f"customer_service: tag customer {p['customer_id']}"
            f"{intent_part} as escalated{team_part} -> "
            f"{p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="customer_service",
                action_type="tag_cs_escalated",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "customer_service enqueue raised for %s: %s",
                p["customer_id"], exc,
            )
            results.append({
                "customer_id": p["customer_id"],
                "intent": p["intent"],
                "assigned_team": p["assigned_team"],
                "tag": p["tag"],
                "applied": False,
                "error": f"enqueue_raised: {exc}",
            })
            continue

        _record_writeback_safely(
            customer_id=p["customer_id"],
            tag=p["tag"], success=True,
        )
        results.append({
            "customer_id": p["customer_id"],
            "intent": p["intent"],
            "assigned_team": p["assigned_team"],
            "tag": p["tag"],
            "applied": False,  # queued, not applied yet
            "pending_action_id": action.id,
            "error": None,
        })
    return results


def _record_writeback_safely(
    *,
    customer_id: str,
    tag: str,
    success: bool,
    error: str | None = None,
) -> None:
    """Best-effort Phase 8 recording."""
    try:
        record_writeback(
            engine="customer_service",
            action_type="tag_cs_escalated",
            capability="SHOPIFY_TAG_CUSTOMER",
            params={"customer_id": customer_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "customer_service record_writeback raised for %s: %s",
            customer_id, exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("router unavailable: %s", exc)
        return None


def _get_tag_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_TAG_CUSTOMER
    except Exception as exc:  # noqa: BLE001
        logger.debug("capability resolve failed: %s", exc)
        return None
