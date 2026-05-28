"""Autonomous order followup tagging (Wave 177).

Tags orders with follow-up state via SHOPIFY_TAG_ORDER. Tag
taxonomy:

  - shopai-followup-pending-review    (delivered but no review)
  - shopai-followup-thank-you-sent    (operator acknowledgement)
  - shopai-followup-needs-attention   (delivery issue / dispute)

Operator filters Shopify admin by these tags + downstream
automations (review-request flows, customer-outreach engines)
consume them.

## Safety gates

  1. action='tag_followup' (engine-approved)
  2. order_id present + tag string non-empty
  3. is_paused() False
  4. tag matches the curated taxonomy (don't allow arbitrary
     tag strings -- prevent typos polluting Shopify admin)
  5. router + capability resolution

## Opt-in

``data.apply_order_followup=True``. Default OFF.
"""
from __future__ import annotations

from typing import Any

from engines._writeback_recorder import record_writeback
from engines.order_followup_autonomy.followup_log import (
    OrderFollowupEvent,
    record_followup_event,
)
from engines.order_followup_autonomy.followup_state import (
    is_paused,
)
from utils.logger import get_logger

logger = get_logger(
    "engines.order_followup_autonomy.applier",
)

_ENGINE = "order_followup"
_ACTION_TYPE = "apply_order_followup_tag"

# Curated taxonomy
_VALID_TAGS: frozenset[str] = frozenset({
    "shopai-followup-pending-review",
    "shopai-followup-thank-you-sent",
    "shopai-followup-needs-attention",
    "shopai-followup-delivery-confirmed",
    "shopai-followup-survey-sent",
})


def _get_router() -> Any | None:
    try:
        from core.adapters.router import get_router
        return get_router()
    except Exception:  # noqa: BLE001
        return None


def _capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return getattr(
            Capability, "SHOPIFY_TAG_ORDER", None,
        )
    except Exception:  # noqa: BLE001
        return None


def _record(
    *,
    order_id: str,
    store_id: str,
    customer_id: str,
    action: str,
    tag: str,
    applied: bool,
    status: str,
    error: str | None,
) -> None:
    """Dual recording."""
    try:
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SHOPIFY_TAG_ORDER",
            params={
                "order_id": order_id,
                "store_id": store_id,
                "customer_id": customer_id,
                "tag": tag,
            },
            success=applied,
            error=error,
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        record_followup_event(OrderFollowupEvent(
            order_id=order_id,
            store_id=store_id,
            customer_id=customer_id,
            action=action,
            tag=tag,
            applied=applied,
            status=status,
            error=error or "",
        ))
    except Exception:  # noqa: BLE001
        pass


def apply_order_followups(
    followups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag orders with follow-up state.

    Args:
        followups: list of {order_id, store_id, customer_id,
                   action, tag} dicts.

    Returns:
        Per-followup list with {order_id, tag, applied,
        status, error}.
    """
    if not isinstance(followups, list) or not followups:
        return []

    paused = is_paused()
    router = _get_router() if not paused else None
    cap = _capability() if not paused else None

    out: list[dict[str, Any]] = []
    for row in followups:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("order_id", "") or "")
        sid = str(row.get("store_id", "") or "")
        cid = str(row.get("customer_id", "") or "")
        action = str(row.get("action", "") or "").lower()
        tag = str(row.get("tag", "") or "")
        applied = False
        status_label = ""
        error: str | None = None

        if paused:
            status_label = "paused"
            error = "order followup auto-pause flag set"
        elif action != "tag_followup":
            status_label = "not_actionable"
        elif not oid or not tag:
            status_label = "missing_ids"
        elif tag not in _VALID_TAGS:
            status_label = "invalid_tag"
            error = (
                f"tag={tag!r} not in curated taxonomy"
            )
        elif router is None or cap is None:
            status_label = "router_unavailable"
        else:
            try:
                res = router.execute(
                    cap,
                    {"order_id": oid, "tags": [tag]},
                )
                if getattr(res, "ok", False):
                    applied = True
                    status_label = "recorded"
                else:
                    status_label = "adapter_failed"
                    err_obj = getattr(
                        res, "error", "adapter_failed",
                    )
                    error = (
                        str(err_obj) if err_obj is not None
                        else "adapter_failed"
                    )
            except Exception as exc:  # noqa: BLE001
                status_label = "adapter_failed"
                error = str(exc)

        _record(
            order_id=oid,
            store_id=sid,
            customer_id=cid,
            action=action,
            tag=tag,
            applied=applied,
            status=status_label,
            error=error,
        )
        out.append({
            "order_id": oid,
            "tag": tag,
            "applied": applied,
            "status": status_label,
            "error": error,
        })
    return out
