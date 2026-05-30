"""Discoverer for the order_followup autonomy domain (W825).

Walks recent fulfilled orders + classifies into the order-
followup tag taxonomy. The applier already records dedup by
tag, so the discoverer is allowed to be loose -- it emits one
event per qualifying order + the applier handles cap-per-run
+ idempotency.

Mapping (conservative first-match wins):

  Delivered (fulfilled + delivered_at)  -> shopai-followup-delivery-confirmed
  Fulfilled + 3-7 days old              -> shopai-followup-thank-you-sent
  Fulfilled + 8-21 days old             -> shopai-followup-survey-sent
  Has pending refund / dispute          -> shopai-followup-needs-attention
  Pending / open / partial fulfillment  -> shopai-followup-pending-review

Default lookback window: 30 days. Env knob:
``SHOPAI_ORDER_FOLLOWUP_DISCOVER_DAYS``.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from core.automation.payload_discoverer import (
    DiscoveryResult,
    register_discoverer,
)

logger = logging.getLogger(__name__)

_DOMAIN = "order_followup"
_DEFAULT_LOOKBACK_DAYS = 30


def _lookback_days() -> int:
    raw = os.environ.get(
        "SHOPAI_ORDER_FOLLOWUP_DISCOVER_DAYS",
        str(_DEFAULT_LOOKBACK_DAYS),
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_LOOKBACK_DAYS


def _classify_order(order: dict[str, Any]) -> str | None:
    if not isinstance(order, dict):
        return None
    # Refund / dispute signal first -- always needs attention
    has_refund = bool(order.get("refunds")) or bool(
        order.get("dispute_id"),
    )
    if has_refund:
        return "shopai-followup-needs-attention"

    fulfilment = str(
        order.get("fulfillment_status") or "",
    ).lower()
    fulfillments = order.get("fulfillments") or []
    delivered = False
    if isinstance(fulfillments, list):
        for fulfillment in fulfillments:
            if not isinstance(fulfillment, dict):
                continue
            if (
                str(fulfillment.get("status") or "").lower()
                == "delivered"
                or fulfillment.get("delivered_at")
            ):
                delivered = True
                break
    if delivered:
        return "shopai-followup-delivery-confirmed"

    if fulfilment != "fulfilled":
        return "shopai-followup-pending-review"

    created = order.get("created_at") or order.get(
        "processed_at",
    )
    if not created:
        return "shopai-followup-pending-review"
    try:
        ts = datetime.fromisoformat(
            str(created).replace("Z", "+00:00"),
        )
    except (TypeError, ValueError):
        return "shopai-followup-pending-review"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = (
        datetime.now(timezone.utc) - ts
    ).total_seconds() / 86400.0
    if age_days >= 3 and age_days < 8:
        return "shopai-followup-thank-you-sent"
    if age_days >= 8 and age_days < 22:
        return "shopai-followup-survey-sent"
    return "shopai-followup-pending-review"


def _fetch_orders() -> list[dict[str, Any]]:
    try:
        from core.adapters.router import get_router  # noqa
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "order_followup discoverer: router import "
            "raised: %s", exc,
        )
        return []
    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "order_followup discoverer: router unavail: %s",
            exc,
        )
        return []
    days = _lookback_days()
    since = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat()
    cap = getattr(Capability, "SHOPIFY_FETCH_ORDERS", None)
    if cap is None:
        return []
    try:
        res = router.execute(cap, {"since": since})
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "order_followup discoverer: execute raised: %s",
            exc,
        )
        return []
    if not getattr(res, "ok", False):
        return []
    data = getattr(res, "data", None) or {}
    orders = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(orders, list):
        return []
    return orders


def discover_order_followup() -> DiscoveryResult:
    now = time.time()
    try:
        orders = _fetch_orders()
    except Exception as exc:  # noqa: BLE001
        return DiscoveryResult(
            domain=_DOMAIN,
            payload=[],
            source="shopify_orders",
            discovered_at=now,
            error=f"fetch raised: {exc!s:.200}",
        )
    payload: list[dict] = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        tag = _classify_order(o)
        if tag is None:
            continue
        oid = str(o.get("id") or o.get("gid") or "").strip()
        if not oid:
            continue
        sid = str(o.get("store_id") or "").strip()
        payload.append({
            "order_id": oid,
            "store_id": sid,
            "action": "tag_followup",
            "tag": tag,
            "signal_source": "order_followup_discoverer",
        })
    return DiscoveryResult(
        domain=_DOMAIN,
        payload=payload,
        source="shopify_orders",
        discovered_at=now,
    )


register_discoverer(_DOMAIN, discover_order_followup)
