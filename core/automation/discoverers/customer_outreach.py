"""Discoverer for the customer_outreach autonomy domain (W829).

Walks recent customers, classifies each into the 5-tag outreach
taxonomy based on lifecycle signals:

  total_spent >= VIP_THRESHOLD          -> shopai-outreach-vip-engagement
  orders_count >= 1 + last order > 90d  -> shopai-outreach-winback
  orders_count >= 1 + last order > 30d  -> shopai-outreach-at-risk
  orders_count == 0 + > 7 days since
    account created                     -> shopai-outreach-followup-needed
  Otherwise active recent buyer         -> shopai-outreach-reviewed

The applier tags customers via SHOPIFY_TAG_CUSTOMER with per-
run cap (200 default). Discoverer emits one event per
qualifying customer; the applier handles dedup + cap.

Env:
  ``SHOPAI_CUSTOMER_OUTREACH_DISCOVER_LIMIT`` (default 200)
  ``SHOPAI_CUSTOMER_OUTREACH_VIP_USD`` (default 500.0)
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from core.automation.payload_discoverer import (
    DiscoveryResult,
    register_discoverer,
)

logger = logging.getLogger(__name__)

_DOMAIN = "customer_outreach"
_DEFAULT_LIMIT = 200
_DEFAULT_VIP_USD = 500.0


def _limit() -> int:
    raw = os.environ.get(
        "SHOPAI_CUSTOMER_OUTREACH_DISCOVER_LIMIT",
        str(_DEFAULT_LIMIT),
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT


def _vip_threshold() -> float:
    raw = os.environ.get(
        "SHOPAI_CUSTOMER_OUTREACH_VIP_USD",
        str(_DEFAULT_VIP_USD),
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_VIP_USD


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(
            str(ts).replace("Z", "+00:00"),
        )
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _classify_customer(
    cust: dict[str, Any], vip_usd: float,
) -> str | None:
    if not isinstance(cust, dict):
        return None
    try:
        spent = float(cust.get("total_spent") or 0.0)
    except (TypeError, ValueError):
        spent = 0.0
    if spent >= vip_usd:
        return "shopai-outreach-vip-engagement"

    try:
        orders = int(cust.get("orders_count") or 0)
    except (TypeError, ValueError):
        orders = 0

    last_order = _parse_iso(
        cust.get("last_order_at")
        or cust.get("updated_at") or "",
    )
    now = datetime.now(timezone.utc)
    if orders >= 1 and last_order is not None:
        days_since = (now - last_order).total_seconds() / 86400.0
        if days_since >= 90:
            return "shopai-outreach-winback"
        if days_since >= 30:
            return "shopai-outreach-at-risk"
        return "shopai-outreach-reviewed"

    created = _parse_iso(cust.get("created_at") or "")
    if orders == 0 and created is not None:
        days_since_signup = (
            now - created
        ).total_seconds() / 86400.0
        if days_since_signup >= 7:
            return "shopai-outreach-followup-needed"

    return None


def _fetch_customers() -> list[dict[str, Any]]:
    try:
        from core.adapters.router import get_router  # noqa
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "customer_outreach discoverer: router import "
            "raised: %s", exc,
        )
        return []
    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "customer_outreach discoverer: router unavail: %s",
            exc,
        )
        return []
    cap = getattr(Capability, "SHOPIFY_FETCH_CUSTOMERS", None)
    if cap is None:
        return []
    try:
        res = router.execute(cap, {"limit": _limit()})
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "customer_outreach discoverer: execute raised: %s",
            exc,
        )
        return []
    if not getattr(res, "ok", False):
        return []
    data = getattr(res, "data", None) or {}
    customers = (
        data.get("customers") if isinstance(data, dict) else None
    )
    if not isinstance(customers, list):
        return []
    return customers


def discover_customer_outreach(*, store_id: str | None = None) -> DiscoveryResult:
    now = time.time()
    try:
        customers = _fetch_customers()
    except Exception as exc:  # noqa: BLE001
        return DiscoveryResult(
            domain=_DOMAIN,
            payload=[],
            source="shopify_customers",
            discovered_at=now,
            store_id=store_id,
            error=f"fetch raised: {exc!s:.200}",
        )
    vip_usd = _vip_threshold()
    payload: list[dict] = []
    for c in customers:
        if not isinstance(c, dict):
            continue
        tag = _classify_customer(c, vip_usd)
        if tag is None:
            continue
        cid = str(c.get("id") or c.get("gid") or "").strip()
        if not cid:
            continue
        sid = str(c.get("store_id") or "").strip()
        payload.append({
            "customer_id": cid,
            "store_id": sid,
            "action": "tag_outreach",
            "tag": tag,
            "signal_source": "customer_outreach_discoverer",
        })
    return DiscoveryResult(
        domain=_DOMAIN,
        payload=payload,
        source="shopify_customers",
        discovered_at=now,
            store_id=store_id,
    )


register_discoverer(_DOMAIN, discover_customer_outreach)
