"""Discoverer for the shipping_alert autonomy domain (W821).

Walks recent orders from Shopify, inspects fulfillment status
+ tracking signals, maps each order to one of the curated
shipping-alert tags. Returns a payload ready for the
shipping_alert applier.

Mapping (heuristic, conservative):

  fulfillment_status         -> tag
  ------------------------   -------------------------------
  fulfilled + delivered      shopai-shipping-delivered
  fulfilled + (in_transit /
    pending tracking update) shopai-shipping-in-transit
  fulfilled + days_since >
    14 + not delivered       shopai-shipping-delayed
  fulfilled + days_since >
    30 + not delivered       shopai-shipping-lost
  cancelled / refused        shopai-shipping-refused

If the Shopify router is unavailable or returns no orders,
the discoverer returns an empty payload with no error -- the
cycle treats this as "nothing to fire".

Default lookback window: 60 days. Override via
``SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS`` env var.
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

_DOMAIN = "shipping_alert"
_DEFAULT_LOOKBACK_DAYS = 60


def _lookback_days() -> int:
    raw = os.environ.get(
        "SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS",
        str(_DEFAULT_LOOKBACK_DAYS),
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_LOOKBACK_DAYS


def _classify_order(order: dict[str, Any]) -> str | None:
    """Map a Shopify order dict to one shipping-alert tag.

    Returns None if no signal applies (skip this order)."""
    fulfilment = (
        (order.get("fulfillment_status") or "")
        if isinstance(order, dict) else ""
    )
    fulfilment = str(fulfilment).lower()
    cancelled = bool(order.get("cancelled_at"))
    if cancelled:
        return "shopai-shipping-refused"
    if fulfilment != "fulfilled":
        return None

    delivered = False
    for fulfillment in (order.get("fulfillments") or []):
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
        return "shopai-shipping-delivered"

    # Not delivered yet; classify by age
    created = order.get("created_at") or order.get(
        "processed_at",
    )
    if not created:
        return "shopai-shipping-in-transit"
    try:
        ts = datetime.fromisoformat(
            str(created).replace("Z", "+00:00"),
        )
    except (TypeError, ValueError):
        return "shopai-shipping-in-transit"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = (
        datetime.now(timezone.utc) - ts
    ).total_seconds() / 86400.0
    if age_days >= 30:
        return "shopai-shipping-lost"
    if age_days >= 14:
        return "shopai-shipping-delayed"
    return "shopai-shipping-in-transit"


def _fetch_recent_orders() -> list[dict[str, Any]]:
    """Pull recent orders via the SmartRouter. Returns [] if
    the router / adapter is unavailable."""
    try:
        from core.adapters.router import get_router  # noqa
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "shipping_alert discoverer: router import "
            "raised: %s", exc,
        )
        return []
    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "shipping_alert discoverer: router unavail: %s",
            exc,
        )
        return []
    days = _lookback_days()
    since = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat()
    try:
        cap = getattr(Capability, "SHOPIFY_FETCH_ORDERS", None)
        if cap is None:
            return []
        res = router.execute(cap, {"since": since})
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "shipping_alert discoverer: execute raised: %s",
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


def discover_shipping_alert() -> DiscoveryResult:
    """Generate payload of shipping-tag actions for recent
    orders."""
    now = time.time()
    try:
        orders = _fetch_recent_orders()
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
            "action": "tag_shipping",
            "tag": tag,
            "signal_source": "shipping_alert_discoverer",
        })
    return DiscoveryResult(
        domain=_DOMAIN,
        payload=payload,
        source="shopify_orders",
        discovered_at=now,
    )


# Self-register at import time
register_discoverer(_DOMAIN, discover_shipping_alert)
