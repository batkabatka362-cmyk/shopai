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


def _limit(store_id: str | None = None) -> int:
    """W883: per-store override."""
    from core.automation.discoverer_env import resolve_int
    return resolve_int(
        _DOMAIN, "LIMIT",
        default=_DEFAULT_LIMIT,
        store_id=store_id,
        min_value=1,
    )


def _safety_stock(store_id: str | None = None) -> int:
    """W888: standardised naming with legacy back-compat.

    New: SHOPAI_INVENTORY_DISCOVER_SAFETY_STOCK[_<STORE>]
    Legacy: SHOPAI_INVENTORY_SAFETY_STOCK[_<STORE>]"""
    from core.automation.discoverer_env import resolve_int
    return resolve_int(
        _DOMAIN, "SAFETY_STOCK",
        default=_DEFAULT_SAFETY_STOCK,
        store_id=store_id,
        min_value=0,
        legacy_env="SHOPAI_INVENTORY_SAFETY_STOCK",
    )


def _reorder_multiplier(
    store_id: str | None = None,
) -> int:
    """W888: standardised naming with legacy back-compat.

    New: SHOPAI_INVENTORY_DISCOVER_REORDER_MULTIPLIER[_<STORE>]
    Legacy: SHOPAI_INVENTORY_REORDER_MULTIPLIER[_<STORE>]"""
    from core.automation.discoverer_env import resolve_int
    return resolve_int(
        _DOMAIN, "REORDER_MULTIPLIER",
        default=_DEFAULT_REORDER_MULTIPLIER,
        store_id=store_id,
        min_value=2,
        legacy_env="SHOPAI_INVENTORY_REORDER_MULTIPLIER",
    )


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


def _fetch_levels(
    store_id: str | None = None,
) -> list[dict[str, Any]]:
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
    # W962-4 bugfix: the 3 fallback capability names below
    # don't exist in the enum (SHOPIFY_LIST_INVENTORY_LEVELS,
    # SHOPIFY_FETCH_INVENTORY, SHOPIFY_INVENTORY). The
    # discoverer silently returned empty on EVERY call --
    # inventory autonomy was dead-on-arrival.
    #
    # Fix: collapse SHOPIFY_LIST_PRODUCTS rows into a
    # product-level pseudo-inventory. Each product gets one
    # synthetic "level" with sku=product_id, total_inventory
    # from the LIST normaliser. Real per-variant + per-
    # location breakdown still requires SHOPIFY_FETCH_PRODUCTS
    # (out of scope for the cheap LIST path).
    cap = (
        getattr(Capability, "SHOPIFY_LIST_INVENTORY_LEVELS", None)
        or getattr(Capability, "SHOPIFY_FETCH_INVENTORY", None)
        or getattr(Capability, "SHOPIFY_INVENTORY", None)
        or getattr(Capability, "SHOPIFY_LIST_PRODUCTS", None)
    )
    if cap is None:
        logger.warning(
            "inventory discoverer: no inventory capability "
            "registered -- discoverer will return empty. "
            "If new enum members exist, update this fallback "
            "chain."
        )
        return []
    try:
        res = router.execute(cap, {"limit": _limit(store_id)})
    except Exception as exc:  # noqa: BLE001
        # W962-53: surface adapter failures at WARN level so
        # operators can distinguish "adapter failed" from
        # "store legitimately has 0 inventory levels". Pre-fix
        # the DEBUG log was invisible in production.
        logger.warning(
            "inventory discoverer: execute raised: %s "
            "(store=%s) -- returning empty (NOT a real "
            "empty inventory)",
            exc, store_id,
        )
        return []
    if not getattr(res, "ok", False):
        err = getattr(getattr(res, "error", None), "reason", "?")
        logger.warning(
            "inventory discoverer: adapter returned "
            "ok=False (error=%s, store=%s) -- returning "
            "empty (NOT a real empty inventory)",
            err, store_id,
        )
        return []
    data = getattr(res, "data", None) or {}
    if not isinstance(data, dict):
        return []
    # Direct inventory levels paths
    levels = (
        data.get("inventory_levels") or data.get("levels")
        or data.get("inventory") or []
    )
    if isinstance(levels, list) and levels:
        return levels
    # W962-4 fallback: collapse SHOPIFY_LIST_PRODUCTS into
    # pseudo-levels (1 per product).
    products = data.get("products") or []
    if isinstance(products, list) and products:
        pseudo_levels = []
        for p in products:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("id", "") or "").strip()
            if not pid:
                continue
            qty = p.get("total_inventory")
            if qty is None:
                qty = p.get("totalInventory") or 0
            try:
                qty = int(qty or 0)
            except (TypeError, ValueError):
                qty = 0
            pseudo_levels.append({
                "sku": pid,
                "product_id": pid,
                "title": p.get("title", "") or "",
                "available": qty,
                "location_id": "primary",
            })
        return pseudo_levels
    return []


def discover_inventory(*, store_id: str | None = None) -> DiscoveryResult:
    now = time.time()
    try:
        levels = _fetch_levels(store_id=store_id)
    except Exception as exc:  # noqa: BLE001
        return DiscoveryResult(
            domain=_DOMAIN,
            payload=[],
            source="shopify_inventory_levels",
            discovered_at=now,
            store_id=store_id,
            error=f"fetch raised: {exc!s:.200}",
        )
    safety = _safety_stock(store_id)
    mult = _reorder_multiplier(store_id)
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
