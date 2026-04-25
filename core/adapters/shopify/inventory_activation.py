"""ShopifyInventoryActivationAdapter — per-location item activation.

Companion to ``inventory.py`` (which reads inventory levels and
sets on-hand quantities) and ``locations.py`` (which manages the
warehouses themselves). This adapter handles the BINDING between
an inventory item and a location:

  * **Activate** an item at a location — register that the item
    is stocked there. Subsequent inventoryAdjustQuantities /
    inventorySetOnHandQuantities calls succeed.
  * **Deactivate** — remove the binding. Useful when a SKU stops
    selling from a particular warehouse (regional discontinuation,
    seasonal close).
  * **Adjust quantities** — incremental delta-based adjustments
    (companion to inventory.py's set_on_hand which is absolute).
    Engines that emit ledger-style "+5 received from supplier" or
    "-3 damaged" events use this rather than recomputing the
    absolute total.

ShopAI's inventory + multi-warehouse engines use these to:

  * Roll out a new SKU across N warehouses on launch day.
  * Auto-deactivate dead inventory at low-velocity locations to
    free up shelf space.
  * Process per-event ledger adjustments from receiving/damage
    callbacks in the warehouse-management integration.

Capabilities:

  * ``SHOPIFY_ACTIVATE_INVENTORY_AT_LOCATION``   — bind item to
    location with optional initial available quantity.
  * ``SHOPIFY_DEACTIVATE_INVENTORY_AT_LOCATION`` — unbind.
  * ``SHOPIFY_ADJUST_INVENTORY_QUANTITIES``      — delta adjust
    (positive or negative) for one or more items at one or more
    locations in a single transaction.

Pattern A: ``inventoryActivate`` takes inventoryItemId + locationId
at field level, NOT in an Input dict. ``inventoryDeactivate`` takes
the InventoryLevel GID directly. ``inventoryAdjustQuantities`` takes
a single ``input`` containing the changes list.

Pattern E note: gated by ``write_inventory`` scope.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_INVENTORY_LEVEL_FIELDS = """
id
location {
  id
  name
}
item {
  id
  sku
  tracked
}
quantities(names: ["available", "on_hand", "committed", "incoming"]) {
  name
  quantity
}
""".strip()


_ACTIVATE_INVENTORY_MUTATION = f"""
mutation inventoryActivate(
  $inventoryItemId: ID!,
  $locationId: ID!,
  $available: Int,
  $onHand: Int
) {{
  inventoryActivate(
    inventoryItemId: $inventoryItemId,
    locationId: $locationId,
    available: $available,
    onHand: $onHand
  ) {{
    inventoryLevel {{
      {_INVENTORY_LEVEL_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DEACTIVATE_INVENTORY_MUTATION = """
mutation inventoryDeactivate($inventoryLevelId: ID!) {
  inventoryDeactivate(inventoryLevelId: $inventoryLevelId) {
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_ADJUST_QUANTITIES_MUTATION = """
mutation inventoryAdjustQuantities(
  $input: InventoryAdjustQuantitiesInput!
) {
  inventoryAdjustQuantities(input: $input) {
    inventoryAdjustmentGroup {
      id
      reason
      changes {
        delta
        name
        quantityAfterChange
        item {
          id
          sku
        }
        location {
          id
          name
        }
      }
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_VALID_QUANTITY_NAMES = {
    "available", "on_hand", "committed", "incoming",
    "damaged", "quality_control", "reserved", "safety_stock",
}

_VALID_REASONS = {
    "correction", "cycle_count_available", "damaged", "movement_created",
    "movement_updated", "movement_received", "movement_canceled",
    "other", "promotion", "quality_control", "received",
    "reservation_created", "reservation_deleted", "reservation_updated",
    "restock", "safety_stock", "shrinkage",
}


class ShopifyInventoryActivationAdapter(ShopifyBaseAdapter):
    name = "shopify_inventory_activation"
    capabilities = {
        Capability.SHOPIFY_ACTIVATE_INVENTORY_AT_LOCATION,
        Capability.SHOPIFY_DEACTIVATE_INVENTORY_AT_LOCATION,
        Capability.SHOPIFY_ADJUST_INVENTORY_QUANTITIES,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_ACTIVATE_INVENTORY_AT_LOCATION:
            return self._activate(params)
        if capability == Capability.SHOPIFY_DEACTIVATE_INVENTORY_AT_LOCATION:
            return self._deactivate(params)
        if capability == Capability.SHOPIFY_ADJUST_INVENTORY_QUANTITIES:
            return self._adjust(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Activate ───────────────────────────────────────────────────

    def _activate(self, params: dict[str, Any]) -> Any:
        item_id = params.get("inventory_item_id") or params.get(
            "inventoryItemId"
        )
        if not isinstance(item_id, str) or not item_id.strip():
            raise AdapterValidationError(
                self.name,
                "'inventory_item_id' (Shopify GID) is required",
            )

        location_id = params.get("location_id") or params.get("locationId")
        if not isinstance(location_id, str) or not location_id.strip():
            raise AdapterValidationError(
                self.name,
                "'location_id' (Shopify GID) is required",
            )

        variables: dict[str, Any] = {
            "inventoryItemId": item_id.strip(),
            "locationId": location_id.strip(),
        }

        available = params.get("available")
        if available is not None:
            try:
                variables["available"] = int(available)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, "'available' must be an integer",
                ) from exc

        on_hand = params.get("on_hand") or params.get("onHand")
        if on_hand is not None:
            try:
                variables["onHand"] = int(on_hand)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, "'on_hand' must be an integer",
                ) from exc

        data = self._gql(_ACTIVATE_INVENTORY_MUTATION, variables)
        self._check_user_errors(data, "inventoryActivate")
        payload = data.get("inventoryActivate") or {}
        level = payload.get("inventoryLevel") or {}
        return self._success(
            Capability.SHOPIFY_ACTIVATE_INVENTORY_AT_LOCATION,
            data={"inventory_level": self._normalise_level(level)},
        )

    # ── Deactivate ─────────────────────────────────────────────────

    def _deactivate(self, params: dict[str, Any]) -> Any:
        level_id = params.get("inventory_level_id") or params.get(
            "inventoryLevelId"
        ) or params.get("id")
        if not isinstance(level_id, str) or not level_id.strip():
            raise AdapterValidationError(
                self.name,
                "'inventory_level_id' (Shopify GID for the InventoryLevel) "
                "is required",
            )
        data = self._gql(_DEACTIVATE_INVENTORY_MUTATION, {
            "inventoryLevelId": level_id.strip(),
        })
        self._check_user_errors(data, "inventoryDeactivate")
        return self._success(
            Capability.SHOPIFY_DEACTIVATE_INVENTORY_AT_LOCATION,
            data={"deactivated": True},
        )

    # ── Adjust ────────────────────────────────────────────────────

    def _adjust(self, params: dict[str, Any]) -> Any:
        adjust_input = self._build_adjust_input(params)
        data = self._gql(_ADJUST_QUANTITIES_MUTATION, {"input": adjust_input})
        self._check_user_errors(data, "inventoryAdjustQuantities")
        payload = data.get("inventoryAdjustQuantities") or {}
        group = payload.get("inventoryAdjustmentGroup") or {}
        changes_raw = group.get("changes") or []
        changes = [
            self._normalise_change(c) for c in changes_raw
            if isinstance(c, dict)
        ]
        return self._success(
            Capability.SHOPIFY_ADJUST_INVENTORY_QUANTITIES,
            data={
                "adjustment_group_id": group.get("id", "") or "",
                "reason": group.get("reason", "") or "",
                "changes": changes,
                "count": len(changes),
            },
        )

    # ── Input builder for adjust ──────────────────────────────────

    def _build_adjust_input(self, params: dict[str, Any]) -> dict[str, Any]:
        reason = params.get("reason")
        if not isinstance(reason, str) or reason.lower() not in _VALID_REASONS:
            raise AdapterValidationError(
                self.name,
                f"'reason' is required and must be one of: "
                f"{sorted(_VALID_REASONS)}",
            )

        name = params.get("name") or "available"
        if not isinstance(name, str) or name.lower() not in _VALID_QUANTITY_NAMES:
            raise AdapterValidationError(
                self.name,
                f"'name' must be one of: {sorted(_VALID_QUANTITY_NAMES)}",
            )

        changes_raw = params.get("changes")
        if not isinstance(changes_raw, list) or not changes_raw:
            raise AdapterValidationError(
                self.name,
                "'changes' must be a non-empty list of "
                "{inventory_item_id, location_id, delta} dicts",
            )

        out_changes: list[dict[str, Any]] = []
        for i, c in enumerate(changes_raw):
            if not isinstance(c, dict):
                raise AdapterValidationError(
                    self.name, f"changes[{i}] must be a dict",
                )
            item_id = c.get("inventory_item_id") or c.get("inventoryItemId")
            if not isinstance(item_id, str) or not item_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"changes[{i}] missing 'inventory_item_id' (GID)",
                )
            location_id = c.get("location_id") or c.get("locationId")
            if not isinstance(location_id, str) or not location_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"changes[{i}] missing 'location_id' (GID)",
                )
            delta = c.get("delta")
            if delta is None:
                raise AdapterValidationError(
                    self.name,
                    f"changes[{i}] missing 'delta' (positive or negative int)",
                )
            try:
                delta_int = int(delta)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"changes[{i}].delta must be an integer",
                ) from exc
            if delta_int == 0:
                raise AdapterValidationError(
                    self.name,
                    f"changes[{i}].delta must be non-zero",
                )

            entry: dict[str, Any] = {
                "inventoryItemId": item_id.strip(),
                "locationId": location_id.strip(),
                "delta": delta_int,
            }
            ledger_uri = c.get("ledger_document_uri") or c.get(
                "ledgerDocumentUri"
            )
            if ledger_uri is not None:
                if not isinstance(ledger_uri, str):
                    raise AdapterValidationError(
                        self.name,
                        f"changes[{i}].ledger_document_uri must be a string",
                    )
                entry["ledgerDocumentUri"] = ledger_uri.strip()
            out_changes.append(entry)

        return {
            "reason": reason.lower(),
            "name": name.lower(),
            "changes": out_changes,
        }

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_level(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        location = node.get("location") or {}
        item = node.get("item") or {}
        quantities_raw = node.get("quantities") or []
        quantities = {}
        for q in quantities_raw:
            if isinstance(q, dict):
                qname = q.get("name", "") or ""
                if qname:
                    quantities[qname] = int(q.get("quantity") or 0)
        return {
            "id": node.get("id", "") or "",
            "location_id": (
                location.get("id", "")
                if isinstance(location, dict) else ""
            ) or "",
            "location_name": (
                location.get("name", "")
                if isinstance(location, dict) else ""
            ) or "",
            "inventory_item_id": (
                item.get("id", "") if isinstance(item, dict) else ""
            ) or "",
            "sku": (
                item.get("sku", "") if isinstance(item, dict) else ""
            ) or "",
            "tracked": bool(
                item.get("tracked", False)
                if isinstance(item, dict) else False
            ),
            "quantities": quantities,
            "available": quantities.get("available", 0),
            "on_hand": quantities.get("on_hand", 0),
        }

    @staticmethod
    def _normalise_change(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        location = node.get("location") or {}
        item = node.get("item") or {}
        return {
            "delta": int(node.get("delta") or 0),
            "name": node.get("name", "") or "",
            "quantity_after_change": int(node.get("quantityAfterChange") or 0),
            "inventory_item_id": (
                item.get("id", "") if isinstance(item, dict) else ""
            ) or "",
            "sku": (
                item.get("sku", "") if isinstance(item, dict) else ""
            ) or "",
            "location_id": (
                location.get("id", "")
                if isinstance(location, dict) else ""
            ) or "",
            "location_name": (
                location.get("name", "")
                if isinstance(location, dict) else ""
            ) or "",
        }
