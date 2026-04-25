"""Shopify inventory — levels, set, adjust, connect.

Shopify's inventory model:

  * Every variant has an ``inventory_item_id`` (distinct from
    the variant's own ``id``).
  * Stock is stored per (inventory_item × location) pair —
    ``inventory_level`` row.
  * ``set`` writes an absolute count (idempotent — §4b.D);
    ``adjust`` increments / decrements (NOT idempotent; retry
    would double-adjust).

We expose ``set`` as the primary mutation since idempotent
mutations are safer under retry. ``adjust`` is available for
callers that explicitly want deltas.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger("shopai.shopify_admin.inventory")


class Inventory:
    """Inventory CRUD. Stateless."""

    # ── Locations ──────────────────────────────────────

    @staticmethod
    def list_locations(
        client: ShopifyAdminClient,
    ) -> list[dict[str, Any]]:
        """Every store has ≥1 location. Most dropshipping
        stores have exactly one; multi-warehouse needs more
        sophisticated routing (future work)."""
        result = client.get("locations.json")
        locations = result.get("locations") or []
        return [l for l in locations if isinstance(l, dict)]

    @staticmethod
    def primary_location_id(
        client: ShopifyAdminClient,
    ) -> int | None:
        """Return the first active location's id, or None if
        no locations exist (impossible on a live store but we
        defend against it)."""
        for loc in Inventory.list_locations(client):
            if loc.get("active") is False:
                continue
            try:
                return int(loc.get("id") or 0)
            except (TypeError, ValueError):
                continue
        # Fall back to first location regardless of active
        for loc in Inventory.list_locations(client):
            try:
                return int(loc.get("id") or 0)
            except (TypeError, ValueError):
                continue
        return None

    # ── Inventory levels ───────────────────────────────

    @staticmethod
    def list_levels(
        client: ShopifyAdminClient,
        *,
        inventory_item_ids: list[int | str] | None = None,
        location_ids: list[int | str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """At least one of ``inventory_item_ids`` or
        ``location_ids`` must be supplied (Shopify's API
        requirement)."""
        if not inventory_item_ids and not location_ids:
            raise ValueError(
                "at least one of inventory_item_ids or "
                "location_ids required",
            )
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if inventory_item_ids:
            params["inventory_item_ids"] = ",".join(
                str(i) for i in inventory_item_ids
            )
        if location_ids:
            params["location_ids"] = ",".join(
                str(i) for i in location_ids
            )
        result = client.get(
            "inventory_levels.json", params=params,
        )
        levels = result.get("inventory_levels") or []
        return [l for l in levels if isinstance(l, dict)]

    @staticmethod
    def set_level(
        client: ShopifyAdminClient,
        *,
        inventory_item_id: int | str,
        location_id: int | str,
        available: int,
    ) -> dict[str, Any]:
        """Write an ABSOLUTE stock count. Idempotent — retry
        lands on the same end state. Preferred over ``adjust``.

        Shopify requires the (inventory_item × location) pair
        to be "connected" first — most variants are auto-
        connected to the primary location at product-create.
        If the pair isn't connected, Shopify returns 422; the
        caller should ``connect`` first.
        """
        if not isinstance(available, int):
            try:
                available = int(available)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"available: int required ({exc})",
                ) from exc
        result = client.post(
            "inventory_levels/set.json",
            {
                "inventory_item_id": int(inventory_item_id),
                "location_id": int(location_id),
                "available": int(available),
            },
        )
        level = result.get("inventory_level")
        if not isinstance(level, dict):
            raise ShopifyAdminError(
                "inventory_level not returned by set",
                path="inventory_levels/set.json",
                body=str(result),
            )
        return level

    @staticmethod
    def adjust_level(
        client: ShopifyAdminClient,
        *,
        inventory_item_id: int | str,
        location_id: int | str,
        available_adjustment: int,
    ) -> dict[str, Any]:
        """Apply a DELTA (positive or negative) to the current
        count. NOT idempotent — retry would double-apply. Use
        only for one-shot supplier-ack flows where the webhook
        layer guarantees single delivery.

        Prefer ``set_level`` when you know the target count."""
        if not isinstance(available_adjustment, int):
            try:
                available_adjustment = int(
                    available_adjustment,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"available_adjustment: int required "
                    f"({exc})",
                ) from exc
        result = client.post(
            "inventory_levels/adjust.json",
            {
                "inventory_item_id": int(inventory_item_id),
                "location_id": int(location_id),
                "available_adjustment": int(
                    available_adjustment,
                ),
            },
        )
        level = result.get("inventory_level")
        if not isinstance(level, dict):
            raise ShopifyAdminError(
                "inventory_level not returned by adjust",
                path="inventory_levels/adjust.json",
                body=str(result),
            )
        return level

    @staticmethod
    def connect_level(
        client: ShopifyAdminClient,
        *,
        inventory_item_id: int | str,
        location_id: int | str,
    ) -> dict[str, Any]:
        """Create the (inventory_item × location) pair without
        setting stock. Needed before ``set_level`` if the
        product was created via GraphQL without auto-connect."""
        result = client.post(
            "inventory_levels/connect.json",
            {
                "inventory_item_id": int(inventory_item_id),
                "location_id": int(location_id),
            },
        )
        level = result.get("inventory_level")
        if not isinstance(level, dict):
            raise ShopifyAdminError(
                "inventory_level not returned by connect",
                path="inventory_levels/connect.json",
                body=str(result),
            )
        return level

    # ── Inventory items (metadata) ─────────────────────

    @staticmethod
    def get_item(
        client: ShopifyAdminClient,
        inventory_item_id: int | str,
    ) -> dict[str, Any]:
        """Cost + sku + tracking flag. Used by LTV + margin
        calculations."""
        result = client.get(
            f"inventory_items/{inventory_item_id}.json",
        )
        item = result.get("inventory_item")
        if not isinstance(item, dict):
            raise ShopifyAdminError(
                f"inventory_item {inventory_item_id} "
                "not returned",
                path=(
                    f"inventory_items/"
                    f"{inventory_item_id}.json"
                ),
            )
        return item

    @staticmethod
    def set_item_cost(
        client: ShopifyAdminClient,
        inventory_item_id: int | str,
        *,
        cost_usd: float,
    ) -> dict[str, Any]:
        """Owner-side cost for margin math. Shopify accepts
        string-formatted decimal — we format defensively."""
        result = client.put(
            f"inventory_items/{inventory_item_id}.json",
            {"inventory_item": {
                "id": int(inventory_item_id),
                "cost": f"{float(cost_usd):.2f}",
            }},
        )
        item = result.get("inventory_item")
        if not isinstance(item, dict):
            raise ShopifyAdminError(
                "inventory_item not returned by update",
                path=(
                    f"inventory_items/"
                    f"{inventory_item_id}.json"
                ),
            )
        return item
