"""Customer Support Engine -- ticket-tag writeback (Wave 104).

The customer_support engine's ``classified_tickets`` output
carries per-ticket {category, priority, sentiment} but pre-
Wave 104 those classifications never reached Shopify. Operator
saw the engine recommend "this is a high-priority billing
complaint" with no way to filter their customer admin for the
affected accounts.

Wave 104 closes the loop. For each ticket with an addressable
customer_id, push tags via ``SHOPIFY_TAG_CUSTOMER`` (the
``tagsAdd`` mutation -- additive, no merge dance).

## Tag taxonomy

The applier emits tags using the existing
``shopai-support-{class}`` prefix:

  Priority:
    - high      -> ``shopai-support-priority-high``
    - urgent    -> ``shopai-support-priority-urgent``
    (low / medium intentionally not tagged -- noise)

  Sentiment:
    - negative  -> ``shopai-support-sentiment-negative``
    (positive / neutral not tagged)

  Category:
    - billing   -> ``shopai-support-billing``
    - product   -> ``shopai-support-product-issue``
    (general not tagged -- noise)

A single ticket may produce multiple tags. The applier
de-duplicates per customer + makes one SHOPIFY_TAG_CUSTOMER
call per customer with the merged set.

## Opt-in

Default OFF. Caller enables via ``data.apply_ticket_tags=True``.
Mirrors the Phase 6/7 pattern used by customer_segmentation /
returns_management.

## Skip taxonomy

  - ``no_customer_id``           -- engine row carries no
                                     addressable Shopify id
  - ``no_actionable_tags``       -- only low-signal classes
                                     present (e.g. low priority,
                                     positive sentiment, general
                                     category)
  - ``router_unavailable``       -- adapters layer not loadable
  - ``adapter_failed``           -- tagsAdd userErrors / raise
  - ``recorded``                 -- success
"""
from __future__ import annotations

from typing import Any

from engines._writeback_recorder import record_writeback
from utils.logger import get_logger

logger = get_logger("engines.customer_support.applier")


_ENGINE = "customer_support"
_ACTION_TYPE = "apply_ticket_tags"

_TAG_PREFIX = "shopai-support-"

# Priority -> tag (low/medium intentionally not tagged)
_PRIORITY_TAG: dict[str, str] = {
    "high":   f"{_TAG_PREFIX}priority-high",
    "urgent": f"{_TAG_PREFIX}priority-urgent",
}

# Sentiment -> tag (positive/neutral not tagged)
_SENTIMENT_TAG: dict[str, str] = {
    "negative": f"{_TAG_PREFIX}sentiment-negative",
}

# Category -> tag (general intentionally not tagged)
_CATEGORY_TAG: dict[str, str] = {
    "billing": f"{_TAG_PREFIX}billing",
    "product": f"{_TAG_PREFIX}product-issue",
}


def _get_router() -> Any | None:
    try:
        from core.adapters.router import get_router
        return get_router()
    except Exception:  # noqa: BLE001
        return None


def _capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return getattr(Capability, "SHOPIFY_TAG_CUSTOMER", None)
    except Exception:  # noqa: BLE001
        return None


def _build_customer_tag_map(
    classified_tickets: list[dict[str, Any]],
    raw_tickets: list[dict[str, Any]] | None,
) -> dict[str, list[str]]:
    """Group per-ticket classification into per-customer tag
    sets. One ticket may produce multiple tags; multiple
    tickets from the same customer merge to one call.

    Returns ``{customer_id: [unique tags...]}`` with the
    deterministic-sort property so the call shape stays stable
    across runs.
    """
    # Build ticket_id -> customer_id lookup from raw tickets
    # since classified_tickets drops the customer_id (engine
    # contract).
    ticket_to_customer: dict[str, str] = {}
    if isinstance(raw_tickets, list):
        for t in raw_tickets:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("id", "") or "")
            cid = str(t.get("customer_id", "") or "")
            if tid and cid:
                ticket_to_customer[tid] = cid

    customer_tags: dict[str, set[str]] = {}
    for row in classified_tickets:
        if not isinstance(row, dict):
            continue
        tid = str(row.get("ticket_id", "") or "")
        cid = ticket_to_customer.get(tid, "")
        if not cid:
            continue
        priority = str(row.get("priority", "") or "").lower()
        sentiment = str(row.get("sentiment", "") or "").lower()
        category = str(row.get("category", "") or "").lower()
        tags: set[str] = set()
        if priority in _PRIORITY_TAG:
            tags.add(_PRIORITY_TAG[priority])
        if sentiment in _SENTIMENT_TAG:
            tags.add(_SENTIMENT_TAG[sentiment])
        if category in _CATEGORY_TAG:
            tags.add(_CATEGORY_TAG[category])
        if not tags:
            continue
        customer_tags.setdefault(cid, set()).update(tags)
    return {
        cid: sorted(tags)
        for cid, tags in customer_tags.items()
    }


def _record(
    *,
    customer_id: str,
    tags: list[str],
    success: bool,
    error: str | None,
) -> None:
    """Pattern Z writeback recorder."""
    try:
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SHOPIFY_TAG_CUSTOMER",
            params={
                "customer_id": customer_id,
                "tags": tags,
            },
            success=success,
            error=error,
        )
    except Exception:  # noqa: BLE001
        pass


def apply_ticket_tags(
    classified_tickets: list[dict[str, Any]],
    raw_tickets: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Apply ticket-classification tags to customers.

    Args:
        classified_tickets: ``customer_support.flow`` output's
            ``classified_tickets`` list.
        raw_tickets: The original input tickets (so we can
            resolve ticket_id -> customer_id, which the
            classifier drops).

    Returns:
        Per-customer list with ``{customer_id, tags, applied,
        status, error}``.
    """
    if not isinstance(classified_tickets, list):
        return []
    customer_tags = _build_customer_tag_map(
        classified_tickets, raw_tickets,
    )
    if not customer_tags:
        return []

    router = _get_router()
    cap = _capability()

    out: list[dict[str, Any]] = []
    for cid, tags in customer_tags.items():
        applied = False
        status_label = ""
        error: str | None = None
        if router is None or cap is None:
            status_label = "router_unavailable"
        else:
            try:
                res = router.execute(
                    cap,
                    {"customer_id": cid, "tags": tags},
                )
                if getattr(res, "ok", False):
                    applied = True
                    status_label = "recorded"
                else:
                    status_label = "adapter_failed"
                    err_obj = getattr(
                        res, "error", "adapter_failed",
                    )
                    # Coerce to string -- router may return
                    # exception instances (NoAdapterAvailable,
                    # AdapterError) that aren't JSON-safe.
                    error = (
                        str(err_obj) if err_obj is not None
                        else "adapter_failed"
                    )
            except Exception as exc:  # noqa: BLE001
                status_label = "adapter_failed"
                error = str(exc)
        _record(
            customer_id=cid,
            tags=tags,
            success=applied,
            error=error,
        )
        out.append({
            "customer_id": cid,
            "tags": tags,
            "applied": applied,
            "status": status_label,
            "error": error,
        })
    return out
