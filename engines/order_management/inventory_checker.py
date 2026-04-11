"""Order Management Engine — inventory checker.

Checks inventory availability for each line item against either
a caller-supplied ``stock_levels`` map OR the Shopify Inventory
adapter (``Capability.SHOPIFY_FETCH_PRODUCTS``) when no map is
provided.

History:

  * **Pre-cleanup**: derived stock from ``md5(sku) % 496 + 5``,
    a deterministic-looking but completely fabricated number.
    Downstream engines treated the fakes as truth.
  * **Cleanup pass**: ripped out the MD5 simulator and added
    the ``stock_levels`` parameter. When the caller didn't
    supply a map every item was classified ``unknown`` so the
    fakes couldn't sneak back in.
  * **Migration to adapter (this commit)**: when ``stock_levels``
    is ``None`` (NOT just empty), the module now resolves each
    SKU via the adapter ``SmartRouter`` using
    ``Capability.SHOPIFY_FETCH_PRODUCTS``. The adapter returns
    real multi-location quantities from Shopify's
    ``inventoryItems`` GraphQL query. If the router has no
    configured Shopify inventory adapter, the per-SKU lookup
    silently returns nothing and the items still end up in
    ``unknown`` — the cleanup invariant ("no fake data") holds
    even when adapters are unwired.

Callers can still inject an explicit ``stock_levels`` map:

  * For tests (no real network)
  * For batched lookups where the caller already has the data
  * For non-Shopify inventory backends (NetSuite, WMS, …)
"""
from __future__ import annotations

import copy
from typing import Any

from utils.logger import get_logger

logger = get_logger("order_management.inventory")

_DEFAULT_WAREHOUSE = "wh_east_01"


def check_inventory(
    line_items: list[dict[str, Any]],
    warehouse_id: str | None = None,
    stock_levels: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Check inventory availability for all line items.

    Args:
        line_items: List of LineItem dicts from the order.
        warehouse_id: Optional specific warehouse to check.
        stock_levels: Mapping of ``sku → available units``.

            * ``None`` (default) — fetch real stock from the
              Shopify Inventory adapter via the SmartRouter.
              SKUs the adapter cannot resolve end up in
              ``unknown``.
            * ``{}`` (explicit empty dict) — skip adapter
              lookup; classify every SKU as ``unknown``. Used
              by tests and offline cycles.
            * ``{sku: qty, ...}`` — use the supplied numbers
              directly. Adapter is not called.

    Returns:
        Structured dict with inventory check results. The
        ``unknown`` list captures items whose stock could not
        be resolved (no caller map AND no adapter result).
    """
    try:
        items = copy.deepcopy(line_items)
        warehouse = warehouse_id or _DEFAULT_WAREHOUSE

        if stock_levels is None:
            # Auto-resolve via the SmartRouter using
            # ``Capability.SHOPIFY_FETCH_PRODUCTS``. Returns an
            # empty dict when no adapter is registered or
            # configured — that path classifies the items as
            # ``unknown`` (the cleanup invariant).
            unique_skus = {
                str(item.get("sku", item.get("product_id", "")))
                for item in items
                if item.get("sku") or item.get("product_id")
            }
            stock_map = _fetch_stock_via_adapter(unique_skus)
        else:
            stock_map = dict(stock_levels)

        reservations: list[dict[str, Any]] = []
        shortages: list[dict[str, Any]] = []
        unknown: list[dict[str, Any]] = []
        all_in_stock = True

        for item in items:
            sku = str(item.get("sku", item.get("product_id", "unknown")))
            requested_qty = int(item.get("quantity", 0))

            if sku not in stock_map:
                # No fake data — an adapter must resolve this.
                all_in_stock = False
                unknown.append({
                    "sku": sku,
                    "requested": requested_qty,
                    "reason": "stock_not_supplied",
                })
                reservations.append({
                    "sku": sku,
                    "quantity": requested_qty,
                    "reserved": False,
                    "warehouse": warehouse,
                    "reason": "stock_not_supplied",
                })
                continue

            available = int(stock_map[sku])
            if requested_qty <= available:
                reservations.append({
                    "sku": sku,
                    "quantity": requested_qty,
                    "reserved": True,
                    "warehouse": warehouse,
                })
            else:
                all_in_stock = False
                reservations.append({
                    "sku": sku,
                    "quantity": requested_qty,
                    "reserved": False,
                    "warehouse": warehouse,
                })
                shortages.append({
                    "sku": sku,
                    "requested": requested_qty,
                    "available": available,
                })

        return {
            "status": "success",
            "all_in_stock": all_in_stock,
            "reservations": reservations,
            "shortages": shortages,
            "unknown": unknown,
        }
    except Exception as exc:
        return _fail(f"Inventory check failed: {exc}")


def _fetch_stock_via_adapter(skus: set[str]) -> dict[str, int]:
    """Resolve real per-SKU stock levels via the adapter layer.

    Asks the SmartRouter for ``Capability.SHOPIFY_FETCH_PRODUCTS``
    once per SKU. Returns a ``{sku: total_available}`` map
    populated only with the SKUs the adapter could resolve;
    SKUs that fail (router has no Shopify adapter, adapter not
    configured, vendor returned not-found, network error, …)
    are simply absent from the result. The caller will then
    drop them into the ``unknown`` bucket — same as the
    cleanup behaviour when no map was supplied.

    The function never raises. A bug here would silently
    classify everything as unknown (safe failure mode), which
    is exactly what we want — the alternative is exploding the
    order pipeline because Shopify hiccupped.
    """
    if not skus:
        return {}

    try:
        from core.adapters import Capability, get_router
    except Exception as exc:  # noqa: BLE001
        logger.debug("adapter import failed: %s", exc)
        return {}

    router = get_router()
    resolved: dict[str, int] = {}

    for sku in skus:
        if not sku or sku == "unknown":
            continue
        try:
            result = router.execute(
                Capability.SHOPIFY_FETCH_PRODUCTS,
                {"sku": sku},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("inventory adapter raised for %s: %s", sku, exc)
            continue
        if not result.ok:
            # NoAdapterAvailable on the first call → no point
            # asking for the rest. Bail out and let the
            # remaining SKUs become unknown.
            from core.adapters.errors import AdapterError
            err_name = (
                type(result.error).__name__ if result.error else ""
            )
            if err_name == "NoAdapterAvailable":
                break
            continue
        data = result.data or {}
        if data.get("found"):
            resolved[sku] = int(data.get("total", 0) or 0)

    return resolved


def _fail(reason: str) -> dict[str, Any]:
    """Return standardized error output."""
    return {
        "status": "error",
        "all_in_stock": False,
        "reservations": [],
        "shortages": [],
        "unknown": [],
        "error": reason,
    }
