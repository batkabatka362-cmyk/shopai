"""Discoverer for the fulfillment autonomy domain (W832).

Walks recent OPEN orders that haven't been fulfilled yet and
suggests a default routing location. Emits ``route``
actions per order with the operator-configured default
location id.

Payload shape matches applier expectations:
  {order_id, location_id, store_id, action="route",
   signal_source}

Default routing strategy is "single-location fallback":
  - Reads ``SHOPAI_FULFILLMENT_DEFAULT_LOCATION_ID`` env
  - If set: every open order gets that location
  - If unset: walks the order's line_items for the first
    `fulfillment_service` location_id; if none found, skip.

This is intentionally conservative -- the more sophisticated
"closest-warehouse + capacity" logic is for a future engine.
Today's discoverer just unblocks the "every open order has
SOMEWHERE to route" flow.

Env:
  ``SHOPAI_FULFILLMENT_DISCOVER_LIMIT`` (default 100)
  ``SHOPAI_FULFILLMENT_DEFAULT_LOCATION_ID`` (no default)
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

_DOMAIN = "fulfillment"
_DEFAULT_LIMIT = 100
_LOOKBACK_DAYS = 14


def _limit() -> int:
    raw = os.environ.get(
        "SHOPAI_FULFILLMENT_DISCOVER_LIMIT",
        str(_DEFAULT_LIMIT),
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT


def _default_location_id() -> str:
    return (
        os.environ.get(
            "SHOPAI_FULFILLMENT_DEFAULT_LOCATION_ID", "",
        ) or ""
    ).strip()


def _pick_location(
    order: dict[str, Any], default_lid: str,
) -> str:
    """Decide which location_id to route this order to.

    Preference: explicit env default > first line_item's
    fulfillment_service location > nothing (skip).
    """
    if default_lid:
        return default_lid
    line_items = order.get("line_items") or []
    if isinstance(line_items, list):
        for li in line_items:
            if not isinstance(li, dict):
                continue
            for key in (
                "location_id", "fulfillment_location_id",
                "origin_location_id",
            ):
                val = str(li.get(key) or "").strip()
                if val:
                    return val
    return ""


def _classify_order(
    order: dict[str, Any], default_lid: str,
) -> dict | None:
    """Return a payload row for an open order or None to skip."""
    if not isinstance(order, dict):
        return None
    # Already fulfilled / cancelled -> skip
    if order.get("cancelled_at"):
        return None
    fulfilment = str(
        order.get("fulfillment_status") or "",
    ).lower()
    if fulfilment in ("fulfilled", "shipped", "delivered"):
        return None

    oid = str(order.get("id") or order.get("gid") or "").strip()
    if not oid:
        return None
    lid = _pick_location(order, default_lid)
    if not lid:
        return None
    sid = str(order.get("store_id") or "").strip()
    return {
        "order_id": oid,
        "location_id": lid,
        "store_id": sid,
        "action": "route",
        "signal_source": "fulfillment_discoverer",
    }


def _fetch_orders() -> list[dict[str, Any]]:
    try:
        from core.adapters.router import get_router  # noqa
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fulfillment discoverer: router import "
            "raised: %s", exc,
        )
        return []
    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fulfillment discoverer: router unavail: %s",
            exc,
        )
        return []
    cap = getattr(Capability, "SHOPIFY_FETCH_ORDERS", None)
    if cap is None:
        return []
    since = (
        datetime.now(timezone.utc)
        - timedelta(days=_LOOKBACK_DAYS)
    ).isoformat()
    try:
        res = router.execute(
            cap,
            {"since": since, "status": "open"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fulfillment discoverer: execute raised: %s",
            exc,
        )
        return []
    if not getattr(res, "ok", False):
        return []
    data = getattr(res, "data", None) or {}
    orders = (
        data.get("orders") if isinstance(data, dict) else None
    )
    if not isinstance(orders, list):
        return []
    return orders


def discover_fulfillment(*, store_id: str | None = None) -> DiscoveryResult:
    now = time.time()
    try:
        orders = _fetch_orders()
    except Exception as exc:  # noqa: BLE001
        return DiscoveryResult(
            domain=_DOMAIN,
            payload=[],
            source="shopify_orders",
            discovered_at=now,
            store_id=store_id,
            error=f"fetch raised: {exc!s:.200}",
        )
    default_lid = _default_location_id()
    payload: list[dict] = []
    for o in orders:
        row = _classify_order(o, default_lid)
        if row is not None:
            payload.append(row)
    return DiscoveryResult(
        domain=_DOMAIN,
        payload=payload,
        source="shopify_orders",
        discovered_at=now,
            store_id=store_id,
    )


register_discoverer(_DOMAIN, discover_fulfillment)
