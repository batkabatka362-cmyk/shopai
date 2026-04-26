"""ShopifyInventoryTransferAdapter — warehouse transfer lifecycle.

Companion to ``inventory_shipments.py`` (the per-shipment line-
item bookkeeping that hangs off a transfer). The transfer
record itself — origin location, destination location, the
intent to move stock — needed its own write surface.

ShopAI's fulfillment + replenishment engines lean on this:

  * **Auto-replenishment from main DC.** Replenishment engine
    sees a regional warehouse running below safety stock and
    creates an inventory transfer from the main DC. Operator
    approves, ops marks ready-to-ship.
  * **Cross-warehouse balancing.** Excess stock in one location,
    shortage in another. Engine creates a transfer, edits it
    if priorities shift, cancels it if a customer order eats
    the source.
  * **Manual overrides.** Operator inspects an in-flight
    transfer and edits notes / reference name. Mark-ready
    flips its state from DRAFT to OPEN.

Capabilities:

  * ``SHOPIFY_CREATE_INVENTORY_TRANSFER``       — inventoryTransferCreate.
  * ``SHOPIFY_EDIT_INVENTORY_TRANSFER``         — inventoryTransferEdit.
    Pattern A: id at field level, NOT inside the input dict.
  * ``SHOPIFY_CANCEL_INVENTORY_TRANSFER``       — inventoryTransferCancel.
    Pattern A.
  * ``SHOPIFY_DELETE_INVENTORY_TRANSFER``       — inventoryTransferDelete.
    Pattern A.
  * ``SHOPIFY_MARK_INVENTORY_TRANSFER_READY``   —
    inventoryTransferMarkAsReadyToShip. Pattern A.

UserError variants are all per-mutation (Inventory*UserError),
all with ``code``.

Pattern D note: ``InventoryTransferEditInput`` uses ``originId``
and ``destinationId`` (NOT ``originLocationId`` /
``destinationLocationId`` like Create does). Adapter accepts
the friendly snake_case ``origin_location_id`` /
``destination_location_id`` on both forms and routes to the
right camelCase field per mutation.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_TRANSFER_FIELDS = """
id
status
referenceName
note
dateCreated
origin {
  name
  location {
    id
    name
  }
}
destination {
  name
  location {
    id
    name
  }
}
""".strip()


_CREATE_TRANSFER_MUTATION = f"""
mutation inventoryTransferCreate($input: InventoryTransferCreateInput!) {{
  inventoryTransferCreate(input: $input) {{
    inventoryTransfer {{
      {_TRANSFER_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_EDIT_TRANSFER_MUTATION = f"""
mutation inventoryTransferEdit(
  $id: ID!,
  $input: InventoryTransferEditInput!
) {{
  inventoryTransferEdit(id: $id, input: $input) {{
    inventoryTransfer {{
      {_TRANSFER_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_CANCEL_TRANSFER_MUTATION = f"""
mutation inventoryTransferCancel($id: ID!) {{
  inventoryTransferCancel(id: $id) {{
    inventoryTransfer {{
      {_TRANSFER_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_TRANSFER_MUTATION = """
mutation inventoryTransferDelete($id: ID!) {
  inventoryTransferDelete(id: $id) {
    deletedId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_MARK_READY_MUTATION = f"""
mutation inventoryTransferMarkAsReadyToShip($id: ID!) {{
  inventoryTransferMarkAsReadyToShip(id: $id) {{
    inventoryTransfer {{
      {_TRANSFER_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


class ShopifyInventoryTransferAdapter(ShopifyBaseAdapter):
    name = "shopify_inventory_transfer"
    capabilities = {
        Capability.SHOPIFY_CREATE_INVENTORY_TRANSFER,
        Capability.SHOPIFY_EDIT_INVENTORY_TRANSFER,
        Capability.SHOPIFY_CANCEL_INVENTORY_TRANSFER,
        Capability.SHOPIFY_DELETE_INVENTORY_TRANSFER,
        Capability.SHOPIFY_MARK_INVENTORY_TRANSFER_READY,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_INVENTORY_TRANSFER:
            return self._create(params)
        if capability == Capability.SHOPIFY_EDIT_INVENTORY_TRANSFER:
            return self._edit(params)
        if capability == Capability.SHOPIFY_CANCEL_INVENTORY_TRANSFER:
            return self._cancel(params)
        if capability == Capability.SHOPIFY_DELETE_INVENTORY_TRANSFER:
            return self._delete(params)
        if capability == \
                Capability.SHOPIFY_MARK_INVENTORY_TRANSFER_READY:
            return self._mark_ready(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        input_dict = self._build_create_input(params)
        data = self._gql(_CREATE_TRANSFER_MUTATION, {"input": input_dict})
        self._check_user_errors(data, "inventoryTransferCreate")
        payload = data.get("inventoryTransferCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_INVENTORY_TRANSFER,
            data={
                "transfer": self._normalise_transfer(
                    payload.get("inventoryTransfer") or {}
                ),
            },
        )

    # ── Edit ───────────────────────────────────────────────────────

    def _edit(self, params: dict[str, Any]) -> Any:
        transfer_id = self._extract_id(params)
        input_dict = self._build_edit_input(params)
        if not input_dict:
            raise AdapterValidationError(
                self.name,
                "no patchable fields supplied — pass at least one of "
                "origin_location_id / destination_location_id / "
                "date_created / note / tags / reference_name",
            )
        data = self._gql(_EDIT_TRANSFER_MUTATION, {
            "id": transfer_id, "input": input_dict,
        })
        self._check_user_errors(data, "inventoryTransferEdit")
        payload = data.get("inventoryTransferEdit") or {}
        return self._success(
            Capability.SHOPIFY_EDIT_INVENTORY_TRANSFER,
            data={
                "transfer": self._normalise_transfer(
                    payload.get("inventoryTransfer") or {}
                ),
            },
        )

    # ── Cancel ─────────────────────────────────────────────────────

    def _cancel(self, params: dict[str, Any]) -> Any:
        transfer_id = self._extract_id(params)
        data = self._gql(_CANCEL_TRANSFER_MUTATION, {"id": transfer_id})
        self._check_user_errors(data, "inventoryTransferCancel")
        payload = data.get("inventoryTransferCancel") or {}
        return self._success(
            Capability.SHOPIFY_CANCEL_INVENTORY_TRANSFER,
            data={
                "transfer": self._normalise_transfer(
                    payload.get("inventoryTransfer") or {}
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        transfer_id = self._extract_id(params)
        data = self._gql(_DELETE_TRANSFER_MUTATION, {"id": transfer_id})
        self._check_user_errors(data, "inventoryTransferDelete")
        payload = data.get("inventoryTransferDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_INVENTORY_TRANSFER,
            data={
                "deleted_id": (
                    payload.get("deletedId", "") or ""
                ),
            },
        )

    # ── Mark ready to ship ─────────────────────────────────────────

    def _mark_ready(self, params: dict[str, Any]) -> Any:
        transfer_id = self._extract_id(params)
        data = self._gql(_MARK_READY_MUTATION, {"id": transfer_id})
        self._check_user_errors(data, "inventoryTransferMarkAsReadyToShip")
        payload = data.get("inventoryTransferMarkAsReadyToShip") or {}
        return self._success(
            Capability.SHOPIFY_MARK_INVENTORY_TRANSFER_READY,
            data={
                "transfer": self._normalise_transfer(
                    payload.get("inventoryTransfer") or {}
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(self, params: dict[str, Any]) -> str:
        transfer_id = (
            params.get("id")
            or params.get("transfer_id")
            or params.get("transferId")
        )
        if not isinstance(transfer_id, str) or not transfer_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the inventory transfer) is required",
            )
        return transfer_id.strip()

    def _build_create_input(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        origin = (
            params.get("origin_location_id")
            or params.get("originLocationId")
        )
        destination = (
            params.get("destination_location_id")
            or params.get("destinationLocationId")
        )
        if not isinstance(origin, str) or not origin.strip():
            raise AdapterValidationError(
                self.name,
                "'origin_location_id' (source location GID) is required",
            )
        if not isinstance(destination, str) or not destination.strip():
            raise AdapterValidationError(
                self.name,
                "'destination_location_id' (target location GID) "
                "is required",
            )
        line_items = self._build_line_items(params.get("line_items"))

        out: dict[str, Any] = {
            "originLocationId": origin.strip(),
            "destinationLocationId": destination.strip(),
            "lineItems": line_items,
        }

        date_created = (
            params.get("date_created") or params.get("dateCreated")
        )
        if date_created is not None:
            if not isinstance(date_created, str):
                raise AdapterValidationError(
                    self.name,
                    "'date_created' must be ISO-8601 datetime string",
                )
            out["dateCreated"] = date_created.strip()

        note = params.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    self.name, "'note' must be a string",
                )
            out["note"] = note

        tags = params.get("tags")
        if tags is not None:
            out["tags"] = self._build_tags(tags)

        reference = (
            params.get("reference_name") or params.get("referenceName")
        )
        if reference is not None:
            if not isinstance(reference, str):
                raise AdapterValidationError(
                    self.name, "'reference_name' must be a string",
                )
            out["referenceName"] = reference

        return out

    def _build_edit_input(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        # Pattern D: Edit uses originId / destinationId, NOT
        # originLocationId / destinationLocationId.
        out: dict[str, Any] = {}

        origin = (
            params.get("origin_location_id")
            or params.get("originId")
            or params.get("originLocationId")
        )
        if origin is not None:
            if not isinstance(origin, str) or not origin.strip():
                raise AdapterValidationError(
                    self.name,
                    "'origin_location_id' must be a non-empty GID string",
                )
            out["originId"] = origin.strip()

        destination = (
            params.get("destination_location_id")
            or params.get("destinationId")
            or params.get("destinationLocationId")
        )
        if destination is not None:
            if not isinstance(destination, str) or \
                    not destination.strip():
                raise AdapterValidationError(
                    self.name,
                    "'destination_location_id' must be a non-empty "
                    "GID string",
                )
            out["destinationId"] = destination.strip()

        date_created = (
            params.get("date_created") or params.get("dateCreated")
        )
        if date_created is not None:
            if not isinstance(date_created, str):
                raise AdapterValidationError(
                    self.name,
                    "'date_created' must be ISO-8601 date string",
                )
            out["dateCreated"] = date_created.strip()

        note = params.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    self.name, "'note' must be a string",
                )
            out["note"] = note

        tags = params.get("tags")
        if tags is not None:
            out["tags"] = self._build_tags(tags)

        reference = (
            params.get("reference_name") or params.get("referenceName")
        )
        if reference is not None:
            if not isinstance(reference, str):
                raise AdapterValidationError(
                    self.name, "'reference_name' must be a string",
                )
            out["referenceName"] = reference

        return out

    def _build_line_items(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'line_items' must be a non-empty list of "
                "{inventory_item_id, quantity} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise AdapterValidationError(
                    self.name, f"line_items[{i}] must be a dict",
                )
            inv_id = (
                item.get("inventory_item_id")
                or item.get("inventoryItemId")
            )
            qty = item.get("quantity")
            if not isinstance(inv_id, str) or not inv_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"line_items[{i}] missing 'inventory_item_id'",
                )
            if qty is None:
                raise AdapterValidationError(
                    self.name,
                    f"line_items[{i}] missing 'quantity'",
                )
            try:
                qty_int = int(qty)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"line_items[{i}].quantity must be an int",
                ) from exc
            if qty_int <= 0:
                raise AdapterValidationError(
                    self.name,
                    f"line_items[{i}].quantity must be > 0",
                )
            out.append({
                "inventoryItemId": inv_id.strip(),
                "quantity": qty_int,
            })
        return out

    def _build_tags(self, raw: Any) -> list[str]:
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list) or not all(
            isinstance(t, str) for t in raw
        ):
            raise AdapterValidationError(
                self.name, "'tags' must be a list of strings",
            )
        return [t.strip() for t in raw if t.strip()]

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_transfer(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        # Pattern D: origin/destination are LocationSnapshot (snapshotted
        # at transfer-creation time); the underlying live Location lives
        # under .location.
        origin = node.get("origin") or {}
        destination = node.get("destination") or {}
        origin_loc = (
            origin.get("location")
            if isinstance(origin, dict) else None
        ) or {}
        dest_loc = (
            destination.get("location")
            if isinstance(destination, dict) else None
        ) or {}
        return {
            "id": node.get("id", "") or "",
            "status": node.get("status", "") or "",
            "reference_name": node.get("referenceName", "") or "",
            "note": node.get("note", "") or "",
            "date_created": node.get("dateCreated", "") or "",
            "origin_id": (
                origin_loc.get("id", "")
                if isinstance(origin_loc, dict) else ""
            ) or "",
            "origin_name": (
                origin.get("name", "")
                if isinstance(origin, dict) else ""
            ) or "",
            "destination_id": (
                dest_loc.get("id", "")
                if isinstance(dest_loc, dict) else ""
            ) or "",
            "destination_name": (
                destination.get("name", "")
                if isinstance(destination, dict) else ""
            ) or "",
        }
