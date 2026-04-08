"""Order Fulfillment Automation — manages order processing pipeline.

Automates: order validation, inventory check, carrier rate
quote, fulfillment routing, and status tracking.

History:

  * **Pre-cleanup**: computed a hardcoded shipping ETA table
    (US/CA=3 days, EU=7 days, other=10 days). Numbers were
    invented, unrelated to real carriers, and downstream
    engines trusted the fake ``shipping_days`` field for
    decisions.
  * **Cleanup pass**: ripped the table out and added a
    ``shipping_rate_source = "adapter_required"`` marker so
    callers could detect the gap.
  * **This migration**: when a merchant origin address is
    supplied via the ``from_address`` parameter (and the
    order has a shipping address with enough detail), the
    pipeline now queries the adapter ``SmartRouter`` via
    ``Capability.SHIPPING_RATE_QUOTE`` for real rates from
    EasyPost / Shippo. Results are attached to the per-order
    dict as ``shipping_rates`` (list) + ``cheapest_rate``
    (dict). If the caller didn't supply ``from_address`` or
    the router has no configured carrier adapter, the method
    still returns the cleanup-era placeholder so legacy
    callers don't break.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("fulfillment.auto")


class FulfillmentAutomation:
    """Automated order fulfillment pipeline."""

    def __init__(self) -> None:
        self._processed: list[dict] = []

    def process_orders(
        self,
        orders: list[dict],
        products: list[dict],
        *,
        from_address: dict[str, Any] | None = None,
        default_parcel: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Process pending orders through the fulfillment pipeline.

        Args:
            orders: List of order dicts.
            products: List of product dicts (used for inventory check).
            from_address: Optional merchant origin address. When
                provided, the pipeline attempts a real shipping
                rate quote per order via the adapter SmartRouter.
                When omitted, orders carry the cleanup-era
                ``shipping_rate_source = "adapter_required"``
                placeholder field.
            default_parcel: Optional default parcel dimensions
                used when an order doesn't carry explicit
                length/width/height/weight fields. Shape:
                ``{length, width, height, weight}`` in inches
                and ounces.
        """
        if not orders:
            return {"status": "no_orders", "processed": 0}

        inventory = {str(p.get("id", "")): int(p.get("inventory_quantity", 0))
                     for p in products}
        results = []

        for order in orders:
            result = self._process_order(
                order, inventory,
                from_address=from_address,
                default_parcel=default_parcel,
            )
            results.append(result)
            self._processed.append(result)

        fulfillable = sum(1 for r in results if r["status"] == "fulfillable")
        return {
            "total_orders": len(orders),
            "fulfillable": fulfillable,
            "blocked": len(results) - fulfillable,
            "results": results[:10],
        }

    def _process_order(
        self,
        order: dict,
        inventory: dict,
        *,
        from_address: dict[str, Any] | None = None,
        default_parcel: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        oid = str(order.get("id", order.get("order_number", "")))
        total = float(order.get("total_price", order.get("total", 0)))
        status = order.get("financial_status", order.get("status", "pending"))

        # Step 1: Validate
        if status not in ("paid", "authorized", "complete"):
            return {"order_id": oid, "status": "awaiting_payment", "reason": status}

        # Step 2: Check inventory
        items = order.get("line_items", order.get("items", []))
        if not isinstance(items, list):
            items = []
        out_of_stock = []
        for item in items:
            if isinstance(item, dict):
                pid = str(item.get("product_id", ""))
                qty = int(item.get("quantity", 1))
                avail = inventory.get(pid, 0)
                if avail < qty:
                    out_of_stock.append(pid)

        if out_of_stock:
            return {"order_id": oid, "status": "blocked",
                    "reason": "out_of_stock", "products": out_of_stock}

        # Step 3: Route + shipping rate quote.
        shipping_country = ""
        addr = order.get("shipping_address") or {}
        if isinstance(addr, dict):
            shipping_country = str(
                addr.get("country_code") or addr.get("country") or "",
            )

        base_result: dict[str, Any] = {
            "order_id": oid,
            "status": "fulfillable",
            "total": total,
            "shipping_country": shipping_country,
            "action": "ship",
        }

        # Attempt a real shipping rate quote via the router.
        # Returns the cleanup-era placeholder when the adapter
        # layer isn't configured (or the caller didn't supply
        # a from_address) so legacy consumers keep working.
        rates_payload = _quote_shipping_rates(
            order=order,
            from_address=from_address,
            default_parcel=default_parcel,
        )
        base_result.update(rates_payload)
        return base_result

    def get_stats(self) -> dict[str, Any]:
        fulfillable = sum(1 for r in self._processed if r.get("status") == "fulfillable")
        return {"processed": len(self._processed), "fulfillable": fulfillable}


# ── Shipping rate helper ────────────────────────────────────


def _quote_shipping_rates(
    *,
    order: dict[str, Any],
    from_address: dict[str, Any] | None,
    default_parcel: dict[str, Any] | None,
) -> dict[str, Any]:
    """Ask the adapter SmartRouter for shipping rates on a
    single order.

    Returns a dict that will be merged into the order result.
    Three possible shapes:

      * ``{"shipping_rates": [...], "cheapest_rate": {...},
           "shipping_rate_source": "<adapter_name>"}``
        on success
      * ``{"shipping_rate_source": "adapter_required"}``
        when the caller didn't supply a from_address, the
        router has no configured carrier adapter, or the
        order is missing required shipping fields
      * ``{"shipping_rate_source": "adapter_error",
           "shipping_rate_error": "<reason>"}``
        on vendor failure — the status stays ``fulfillable``
        because the order CAN still be shipped, we just don't
        have a rate quote right now

    The function never raises — shipping failures should
    never break the order pipeline.
    """
    if not isinstance(from_address, dict):
        return {"shipping_rate_source": "adapter_required"}

    to_address = _build_to_address(order.get("shipping_address"))
    if to_address is None:
        return {"shipping_rate_source": "adapter_required"}

    parcel = _build_parcel(order, default_parcel)
    if parcel is None:
        return {"shipping_rate_source": "adapter_required"}

    try:
        from core.adapters import Capability, get_router
    except Exception as exc:  # noqa: BLE001
        logger.debug("adapter import failed: %s", exc)
        return {"shipping_rate_source": "adapter_required"}

    try:
        result = get_router().execute(
            Capability.SHIPPING_RATE_QUOTE,
            {
                "from_address": from_address,
                "to_address": to_address,
                "parcel": parcel,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("shipping router raised: %s", exc)
        return {"shipping_rate_source": "adapter_required"}

    if not result.ok:
        err_name = (
            type(result.error).__name__ if result.error else "unknown"
        )
        if err_name == "NoAdapterAvailable":
            return {"shipping_rate_source": "adapter_required"}
        return {
            "shipping_rate_source": "adapter_error",
            "shipping_rate_error": err_name,
        }

    data = result.data or {}
    rates = data.get("rates") or []
    cheapest = data.get("cheapest")
    return {
        "shipping_rate_source": result.adapter,
        "shipping_rates": rates,
        "cheapest_rate": cheapest,
    }


def _build_to_address(raw: Any) -> dict[str, Any] | None:
    """Translate the order's shipping_address into the
    adapter's normalised ``to_address`` shape.

    Returns ``None`` when the order doesn't carry enough
    detail for a rate quote (no zip, no country, etc.) — the
    caller falls back to the placeholder.
    """
    if not isinstance(raw, dict):
        return None

    street1 = (
        raw.get("address1") or raw.get("street1")
        or raw.get("street_line1") or raw.get("street") or ""
    )
    city = raw.get("city") or ""
    zip_code = (
        raw.get("zip") or raw.get("postal_code") or raw.get("postcode") or ""
    )
    country = (
        raw.get("country_code") or raw.get("country") or ""
    )

    if not street1 or not city or not zip_code or not country:
        return None

    return {
        "name": raw.get("name", "") or "",
        "street1": str(street1),
        "street2": raw.get("address2", "") or raw.get("street2", "") or "",
        "city": str(city),
        "state": raw.get("province_code", "") or raw.get("state", "") or "",
        "zip": str(zip_code),
        "country": str(country)[:2].upper() if len(str(country)) >= 2 else str(country),
        "phone": raw.get("phone", "") or "",
    }


def _build_parcel(
    order: dict[str, Any],
    default_parcel: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve parcel dimensions for an order.

    Priority:
      1. order.parcel (explicit per-order override)
      2. default_parcel (caller-supplied default)
      3. None → placeholder, caller falls back
    """
    parcel = order.get("parcel")
    if isinstance(parcel, dict) and all(
        parcel.get(f) for f in ("length", "width", "height", "weight")
    ):
        return parcel
    if isinstance(default_parcel, dict) and all(
        default_parcel.get(f) for f in ("length", "width", "height", "weight")
    ):
        return default_parcel
    return None


_instance = None
def get_fulfillment():
    global _instance
    if _instance is None:
        _instance = FulfillmentAutomation()
    return _instance
