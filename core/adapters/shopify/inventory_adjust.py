"""ShopifyInventoryAdjustAdapter — absolute inventory set.

Companions:
  * ``inventory.py`` reads + ``inventorySetOnHandQuantities``
    (on-hand only).
  * ``inventory_activation.py`` covers ACTIVATE / DEACTIVATE +
    delta-based ``inventoryAdjustQuantities``.

This adapter fills the remaining write-side gap: the absolute
``inventorySetQuantities`` mutation, used when reconciliation
flows need to overwrite (not delta) a quantity:

  * **Bulk reset from POS.** New POS load lands; engine flips
    each SKU's available qty to the authoritative count rather
    than computing a delta-from-current.
  * **Audit fix-ups.** Operator runs a cycle count and supplies
    the correct absolute number. Cleaner than a delta because
    no risk of a concurrent change drifting it.

Capability:

  * ``SHOPIFY_SET_INVENTORY_QUANTITIES`` — inventorySetQuantities
    (absolute, e.g. ``quantity=100``).

Input shape: required ``reason`` + ``name`` (the inventory
state being modified — typically ``available`` or ``on_hand``)
+ a list of ``quantities``.

UserError variant is ``InventorySetQuantitiesUserError`` with
``code`` field.

Pattern C: Shopify requires ``referenceDocumentUri`` on
``inventorySetQuantities`` (cycle-count provenance). The adapter
defaults to a synthetic URI when the caller doesn't supply one,
so engines that don't track audit URIs locally still get
through.

Pattern C: Shopify validates ``reason`` against an allowed set
('correction', 'cycle_count_available', 'damaged', 'received',
'restock', 'safety_stock', 'shrinkage', etc.). The adapter
doesn't whitelist locally — Shopify's userError will spell the
bad value out.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_ADJUSTMENT_GROUP_FIELDS = """
id
reason
referenceDocumentUri
createdAt
""".strip()


_SET_QUANTITIES_MUTATION = f"""
mutation inventorySetQuantities(
  $input: InventorySetQuantitiesInput!
) {{
  inventorySetQuantities(input: $input) {{
    inventoryAdjustmentGroup {{
      {_ADJUSTMENT_GROUP_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


class ShopifyInventoryAdjustAdapter(ShopifyBaseAdapter):
    name = "shopify_inventory_adjust"
    capabilities = {Capability.SHOPIFY_SET_INVENTORY_QUANTITIES}
    required_scopes = frozenset({"write_inventory"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_SET_INVENTORY_QUANTITIES:
            return self._set(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Set (absolute) ─────────────────────────────────────────────

    def _set(self, params: dict[str, Any]) -> Any:
        input_dict = self._build_common_input(params)
        quantities = self._build_quantities(params.get("quantities"))
        input_dict["quantities"] = quantities
        # Pattern C: Shopify requires referenceDocumentUri on
        # inventorySetQuantities (cycle-count provenance). Default
        # to a synthetic uri if the caller didn't pass one.
        input_dict.setdefault(
            "referenceDocumentUri",
            "shopai://inventory-set/synthetic",
        )
        # Pattern C: Shopify requires either per-quantity
        # compareQuantity (optimistic concurrency check) OR a
        # top-level ignoreCompareQuantity=true to skip the check.
        # Default to skipping unless the caller explicitly opted in.
        ignore_compare = (
            params.get("ignore_compare_quantity")
            if "ignore_compare_quantity" in params
            else params.get("ignoreCompareQuantity")
        )
        if ignore_compare is None:
            ignore_compare = True
        input_dict["ignoreCompareQuantity"] = bool(ignore_compare)

        data = self._gql(_SET_QUANTITIES_MUTATION, {"input": input_dict})
        self._check_user_errors(data, "inventorySetQuantities")
        payload = data.get("inventorySetQuantities") or {}
        return self._success(
            Capability.SHOPIFY_SET_INVENTORY_QUANTITIES,
            data={
                "adjustment_group": self._normalise_group(
                    payload.get("inventoryAdjustmentGroup") or {}
                ),
                "quantities_count": len(quantities),
            },
        )

    # ── Input builders ─────────────────────────────────────────────

    def _build_common_input(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        reason = params.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise AdapterValidationError(
                self.name,
                "'reason' is required (e.g. 'correction', "
                "'cycle_count_available', 'damaged', 'received', "
                "'restock', 'shrinkage')",
            )
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AdapterValidationError(
                self.name,
                "'name' is required (the inventory state — "
                "typically 'available' or 'on_hand')",
            )
        out: dict[str, Any] = {
            "reason": reason.strip(),
            "name": name.strip(),
        }
        ref = (
            params.get("reference_document_uri")
            or params.get("referenceDocumentUri")
        )
        if ref is not None:
            if not isinstance(ref, str):
                raise AdapterValidationError(
                    self.name,
                    "'reference_document_uri' must be a string",
                )
            out["referenceDocumentUri"] = ref.strip()
        return out

    def _build_quantities(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'quantities' must be a non-empty list of "
                "{inventory_item_id, location_id, quantity} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, q in enumerate(raw):
            if not isinstance(q, dict):
                raise AdapterValidationError(
                    self.name, f"quantities[{i}] must be a dict",
                )
            item_id = (
                q.get("inventory_item_id") or q.get("inventoryItemId")
            )
            loc_id = q.get("location_id") or q.get("locationId")
            quantity = q.get("quantity")
            if not isinstance(item_id, str) or not item_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"quantities[{i}] missing 'inventory_item_id'",
                )
            if not isinstance(loc_id, str) or not loc_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"quantities[{i}] missing 'location_id'",
                )
            if quantity is None:
                raise AdapterValidationError(
                    self.name,
                    f"quantities[{i}] missing 'quantity' (int)",
                )
            try:
                qty_int = int(quantity)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"quantities[{i}].quantity must be an int",
                ) from exc
            if qty_int < 0:
                raise AdapterValidationError(
                    self.name,
                    f"quantities[{i}].quantity must be >= 0",
                )
            out.append({
                "inventoryItemId": item_id.strip(),
                "locationId": loc_id.strip(),
                "quantity": qty_int,
            })
        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_group(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        return {
            "id": node.get("id", "") or "",
            "reason": node.get("reason", "") or "",
            "reference_document_uri": (
                node.get("referenceDocumentUri", "") or ""
            ),
            "created_at": node.get("createdAt", "") or "",
        }
