"""ShopifyInventoryAdapter — multi-location inventory truth.

Replaces the deleted MD5(sku) hash that
``engines/order_management/inventory_checker.py`` used to
fabricate stock levels with. Real numbers come from Shopify's
GraphQL inventory API:

  * ``inventoryItem`` query — fetch the canonical inventory
    item for a SKU and read every location's quantity in one
    round trip.
  * ``inventorySetOnHandQuantities`` mutation — write the
    on-hand count for one or more inventory items at one or
    more locations. Used by the operations agent when it
    decides to rebalance stock.

Capabilities:

  * ``SHOPIFY_FETCH_PRODUCTS`` (read variant inventory)
  * ``SHOPIFY_UPDATE_INVENTORY``

The READ path returns a normalised dict the inventory_checker
can drop straight into its ``stock_levels`` parameter:

    {
        "sku": "ABC-123",
        "tracked": True,
        "total": 87,
        "by_location": [
            {"location_id": "gid://...", "name": "Main", "available": 50},
            {"location_id": "gid://...", "name": "Warehouse 2", "available": 37},
        ],
    }

The WRITE path returns the new on-hand count plus any
``userErrors`` from Shopify (raised as ``AdapterValidationError``
inside ``_check_user_errors``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


_INVENTORY_QUERY = """
query InventoryBySku($query: String!) {
  inventoryItems(first: 1, query: $query) {
    edges {
      node {
        id
        sku
        tracked
        inventoryLevels(first: 50) {
          edges {
            node {
              location {
                id
                name
              }
              quantities(names: ["available", "on_hand"]) {
                name
                quantity
              }
            }
          }
        }
      }
    }
  }
}
""".strip()


_SET_ONHAND_MUTATION = """
mutation SetOnHand($input: InventorySetOnHandQuantitiesInput!) {
  inventorySetOnHandQuantities(input: $input) {
    inventoryAdjustmentGroup {
      createdAt
      reason
      changes {
        name
        delta
        quantityAfterChange
      }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


class ShopifyInventoryAdapter(ShopifyBaseAdapter):
    name = "shopify_inventory"
    capabilities = {
        Capability.SHOPIFY_FETCH_PRODUCTS,
        Capability.SHOPIFY_UPDATE_INVENTORY,
    }
    # FETCH_PRODUCTS is a join through inventory level, so it
    # needs both read_products AND read_inventory; the write
    # mutation needs write_inventory.
    required_scopes = frozenset({
        "read_products", "read_inventory", "write_inventory",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_FETCH_PRODUCTS:
            return self._fetch_inventory(params)
        if capability == Capability.SHOPIFY_UPDATE_INVENTORY:
            return self._set_on_hand(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── READ ──────────────────────────────────────────────────

    def _fetch_inventory(self, params: dict[str, Any]) -> Any:
        sku = params.get("sku")
        if not sku:
            raise AdapterValidationError(
                self.name, "'sku' is required",
            )

        # Shopify's inventoryItems query takes a search-style
        # filter string, not a direct SKU lookup. Quote the SKU
        # so values containing spaces / colons don't break the
        # query syntax.
        query_string = f'sku:"{sku}"'
        data = self._gql(_INVENTORY_QUERY, {"query": query_string})

        edges = (data.get("inventoryItems") or {}).get("edges") or []
        if not edges:
            return self._success(
                Capability.SHOPIFY_FETCH_PRODUCTS,
                data={
                    "sku": sku,
                    "found": False,
                    "tracked": False,
                    "total": 0,
                    "by_location": [],
                },
            )

        node = edges[0].get("node") or {}
        levels = ((node.get("inventoryLevels") or {}).get("edges") or [])

        by_location: list[dict[str, Any]] = []
        total = 0
        for lvl in levels:
            lnode = lvl.get("node") or {}
            location = lnode.get("location") or {}
            quantities = lnode.get("quantities") or []
            available = 0
            on_hand = 0
            for q in quantities:
                if not isinstance(q, dict):
                    continue
                name = q.get("name", "")
                qty = int(q.get("quantity", 0) or 0)
                if name == "available":
                    available = qty
                elif name == "on_hand":
                    on_hand = qty
            total += available
            by_location.append({
                "location_id": location.get("id", ""),
                "name": location.get("name", ""),
                "available": available,
                "on_hand": on_hand,
            })

        return self._success(
            Capability.SHOPIFY_FETCH_PRODUCTS,
            data={
                "sku": node.get("sku", sku),
                "inventory_item_id": node.get("id", ""),
                "found": True,
                "tracked": bool(node.get("tracked", False)),
                "total": total,
                "by_location": by_location,
            },
        )

    # ── WRITE ─────────────────────────────────────────────────

    def _set_on_hand(self, params: dict[str, Any]) -> Any:
        """Set the on-hand quantity for one or more
        ``(inventory_item_id, location_id)`` pairs.

        Expected ``params``:

            {
                "reason":  "correction" | "received" | "cycle_count" | ...,
                "set_quantities": [
                    {
                        "inventory_item_id": "gid://...",
                        "location_id": "gid://...",
                        "quantity": 87,
                    },
                    ...
                ],
            }
        """
        reason = str(params.get("reason") or "correction")
        set_quantities = params.get("set_quantities") or []

        if not isinstance(set_quantities, list) or not set_quantities:
            raise AdapterValidationError(
                self.name,
                "'set_quantities' must be a non-empty list",
            )

        normalised = []
        for q in set_quantities:
            if not isinstance(q, dict):
                continue
            iid = q.get("inventory_item_id")
            lid = q.get("location_id")
            qty = q.get("quantity")
            if not iid or not lid or qty is None:
                raise AdapterValidationError(
                    self.name,
                    "each set_quantities entry needs "
                    "inventory_item_id + location_id + quantity",
                )
            normalised.append({
                "inventoryItemId": iid,
                "locationId": lid,
                "quantity": int(qty),
            })

        variables = {
            "input": {
                "reason": reason,
                "setQuantities": normalised,
            },
        }

        data = self._gql(_SET_ONHAND_MUTATION, variables)
        self._check_user_errors(data, "inventorySetOnHandQuantities")

        payload = data.get("inventorySetOnHandQuantities") or {}
        adjustment = payload.get("inventoryAdjustmentGroup") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_INVENTORY,
            data={
                "reason": reason,
                "applied": len(normalised),
                "created_at": adjustment.get("createdAt", ""),
                "changes": adjustment.get("changes", []),
            },
        )
