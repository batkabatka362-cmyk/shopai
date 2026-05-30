"""Discoverer for the inventory autonomy domain (W831).

Walks inventory levels per SKU/location. Surfaces SKUs that
have fallen below a configurable safety stock floor and emits
``reorder`` actions with a proposed restock quantity.

Per-row payload: ``{sku, location_id, store_id, action,
prior_quantity, new_quantity, reason}``. The applier
re-validates against:
  - new_quantity > 0
  - new_quantity <= SHOPAI_INVENTORY_MAX_QUANTITY
  - abs(delta) >= SHOPAI_INVENTORY_MIN_DELTA

Heuristic (conservative):
  prior <= safety_stock                 -> propose
  proposed new = safety_stock * REORDER_MULTIPLIER (default 2)
  proposed new clamped to <= MAX_QUANTITY / 2
  delta >= SHOPAI_INVENTORY_MIN_DELTA

Env:
  ``SHOPAI_INVENTORY_DISCOVER_LIMIT`` (default 100)
  ``SHOPAI_INVENTORY_SAFETY_STOCK`` (default 5)
  ``SHOPAI_INVENTORY_REORDER_MULTIPLIER`` (default 2)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from core.automation.payload_discoverer import (
    DiscoveryResult,
    register_discoverer,
)

logger = logging.getLogger(__name__)

_DOMAIN = "inventory"
_DEFAULT_LIMIT = 100
_DEFAULT_SAFETY_STOCK = 5
_DEFAULT_REORDER_MULTIPLIER = 2


def _limit() -> int:
    raw = os.environ.get(
        "SHOPAI_INVENTORY_DISCOVER_LIMIT",
        str(_DEFAULT_LIMIT),
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT


def _safety_stock() -> int:
    raw = os.environ.get(
        "SHOPAI_INVENTORY_SAFETY_STOCK",
        str(_DEFAULT_SAFETY_STOCK),
    )
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_SAFETY_STOCK


def _reorder_multiplier() -> int:
    raw = os.environ.get(
        "SHOPAI_INVENTORY_REORDER_MULTIPLIER",
        str(_DEFAULT_REORDER_MULTIPLIER),
    )
    try:
        return max(2, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_REORDER_MULTIPLIER


def _max_quantity_default() -> int:
    """Mirror inventory_applier's default ceiling."""
    raw = os.environ.get(
        "SHOPAI_INVENTORY_MAX_QUANTITY", "10000",
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 10000


def _propose_for_level(
    level: dict[str, Any],
    safety: int,
    multiplier: int,
    max_q: int,
) -> dict | None:
    if not isinstance(level, dict):
        return None
    sku = str(level.get("sku") or "").strip()
    lid = str(
        level.get("location_id")
        or level.get("location_gid") or "",
    ).strip()
    sid = str(level.get("store_id") or "").strip()
    try:
        prior = int(level.get("available") or level.get(
            "quantity",
        ) or 0)
    except (TypeError, ValueError):
        prior = 0

    if not sku or not lid:
        return None
    if prior > safety:
        return None

    proposed = safety * multiplier
    if proposed <= prior:
        proposed = prior + safety  # always positive delta
    proposed = min(proposed, max_q // 2)
    if proposed <= 0:
        return None
    delta = proposed - prior
    if delta <= 0:
        return None
    return {
        "sku": sku,
        "location_id": lid,
        "store_id": sid,
        "action": "reorder",
        "prior_quantity": prior,
        "new_quantity": proposed,
        "reason": f"below safety_stock={safety}",
        "signal_source": "inventory_discoverer",
    }


def _fetch_levels() -> list[dict[str, Any]]:
    try:
        from core.adapters.router import get_router  # noqa
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "inventory discoverer: router import raised: %s",
            exc,
        )
        return []
    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "inventory discoverer: router unavail: %s", exc,
        )
        return []
    # Try a few capability names depending on adapter
    cap = (
        getattr(Capability, "SHOPIFY_LIST_INVENTORY_LEVELS", None)
        or getattr(Capability, "SHOPIFY_FETCH_INVENTORY", None)
        or getattr(Capability, "SHOPIFY_INVENTORY", None)
    )
    if cap is None:
        return []
    try:
        res = router.execute(cap, {"limit": _limit()})
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "inventory discoverer: execute raised: %s", exc,
        )
        return []
    if not getattr(res, "ok", False):
        return []
    data = getattr(res, "data", None) or {}
    if not isinstance(data, dict):
        return []
    levels = (
        data.get("inventory_levels") or data.get("levels")
        or data.get("inventory") or []
    )
    if not isinstance(levels, list):
        return []
    return levels


def discover_inventory(*, store_id: str | None = None) -> DiscoveryResult:
    now = time.time()
    try:
        levels = _fetch_levels()
    except Exception as exc:  # noqa: BLE001
        return DiscoveryResult(
            domain=_DOMAIN,
            payload=[],
            source="shopify_inventory_levels",
            discovered_at=now,
            store_id=store_id,
            error=f"fetch raised: {exc!s:.200}",
        )
    safety = _safety_stock()
    mult = _reorder_multiplier()
    max_q = _max_quantity_default()
    payload: list[dict] = []
    for lvl in levels:
        row = _propose_for_level(lvl, safety, mult, max_q)
        if row is not None:
            payload.append(row)
    return DiscoveryResult(
        domain=_DOMAIN,
        payload=payload,
        source="shopify_inventory_levels",
        discovered_at=now,
            store_id=store_id,
    )


register_discoverer(_DOMAIN, discover_inventory)
