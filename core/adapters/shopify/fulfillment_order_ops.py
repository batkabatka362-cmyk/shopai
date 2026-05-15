"""ShopifyFulfillmentOrderOpsAdapter — move / reschedule / split.

Companion to ``fulfillment.py`` (create + read fulfillments),
``fulfillment_hold.py`` (hold + release), and
``fulfillment_tracking.py`` (tracking update + cancel). The
three remaining FulfillmentOrder primitives — move to a new
location, reschedule the fulfillAt window, split a single FO
across multiple downstream FOs — sit outside those.

ShopAI's fulfillment + warehousing engines use these:

  * **Move on stockout.** Picker reports the SKU is missing at
    the assigned location. Engine moves the FO to a peer DC
    that has stock — Shopify routes the customer's package
    from there instead.
  * **Reschedule on backorder.** Inbound shipment ETA slipped;
    engine pushes the FO's fulfillAt out to the new ETA so
    customer-facing "ships by" displays stay accurate.
  * **Split for partial-ship.** Buyer ordered 3 SKUs, only 2
    are in stock at the primary location. Split the FO so the
    in-stock pair ships now while the third stays open at a
    location that has it.

Capabilities:

  * ``SHOPIFY_MOVE_FULFILLMENT_ORDER``       — fulfillmentOrderMove.
    Pattern A: id + newLocationId at field level; optional
    fulfillmentOrderLineItems list scopes the move (move only a
    subset of lines).
  * ``SHOPIFY_RESCHEDULE_FULFILLMENT_ORDER`` — fulfillmentOrderReschedule.
    Pattern A: id + fulfillAt at field level (DateTime).
  * ``SHOPIFY_SPLIT_FULFILLMENT_ORDER``      — fulfillmentOrderSplit.
    Takes a list of FulfillmentOrderSplitInput dicts. Splits
    can target multiple source FOs in one call.

Pattern F: ``fulfillmentOrderMove`` uses typed ``UserError`` (no
``code``). ``fulfillmentOrderReschedule`` uses
``FulfillmentOrderRescheduleUserError`` (has code).
``fulfillmentOrderSplit`` uses ``FulfillmentOrderSplitUserError``
(has code). Adapter handles each per-mutation.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_FO_FIELDS = """
id
status
requestStatus
fulfillAt
assignedLocation {
  location {
    id
    name
  }
}
""".strip()


_MOVE_FO_MUTATION = f"""
mutation fulfillmentOrderMove(
  $id: ID!,
  $newLocationId: ID!,
  $fulfillmentOrderLineItems: [FulfillmentOrderLineItemInput!]
) {{
  fulfillmentOrderMove(
    id: $id,
    newLocationId: $newLocationId,
    fulfillmentOrderLineItems: $fulfillmentOrderLineItems
  ) {{
    movedFulfillmentOrder {{
      {_FO_FIELDS}
    }}
    originalFulfillmentOrder {{
      {_FO_FIELDS}
    }}
    remainingFulfillmentOrder {{
      {_FO_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_RESCHEDULE_FO_MUTATION = f"""
mutation fulfillmentOrderReschedule($id: ID!, $fulfillAt: DateTime!) {{
  fulfillmentOrderReschedule(id: $id, fulfillAt: $fulfillAt) {{
    fulfillmentOrder {{
      {_FO_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_SPLIT_FO_MUTATION = f"""
mutation fulfillmentOrderSplit(
  $fulfillmentOrderSplits: [FulfillmentOrderSplitInput!]!
) {{
  fulfillmentOrderSplit(
    fulfillmentOrderSplits: $fulfillmentOrderSplits
  ) {{
    fulfillmentOrderSplits {{
      fulfillmentOrder {{
        {_FO_FIELDS}
      }}
      remainingFulfillmentOrder {{
        {_FO_FIELDS}
      }}
      replacementFulfillmentOrder {{
        {_FO_FIELDS}
      }}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


class ShopifyFulfillmentOrderOpsAdapter(ShopifyBaseAdapter):
    name = "shopify_fulfillment_order_ops"
    capabilities = {
        Capability.SHOPIFY_MOVE_FULFILLMENT_ORDER,
        Capability.SHOPIFY_RESCHEDULE_FULFILLMENT_ORDER,
        Capability.SHOPIFY_SPLIT_FULFILLMENT_ORDER,
    }
    required_scopes = frozenset({
        "read_merchant_managed_fulfillment_orders",
        "write_merchant_managed_fulfillment_orders",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_MOVE_FULFILLMENT_ORDER:
            return self._move(params)
        if capability == Capability.SHOPIFY_RESCHEDULE_FULFILLMENT_ORDER:
            return self._reschedule(params)
        if capability == Capability.SHOPIFY_SPLIT_FULFILLMENT_ORDER:
            return self._split(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Move ───────────────────────────────────────────────────────

    def _move(self, params: dict[str, Any]) -> Any:
        fo_id = self._extract_fo_id(params)
        new_location_id = (
            params.get("new_location_id")
            or params.get("newLocationId")
        )
        if not isinstance(new_location_id, str) or \
                not new_location_id.strip():
            raise AdapterValidationError(
                self.name,
                "'new_location_id' (Shopify GID for the target "
                "location) is required",
            )

        variables: dict[str, Any] = {
            "id": fo_id,
            "newLocationId": new_location_id.strip(),
            "fulfillmentOrderLineItems": None,
        }
        line_items = (
            params.get("line_items")
            or params.get("fulfillment_order_line_items")
            or params.get("fulfillmentOrderLineItems")
        )
        if line_items is not None:
            variables["fulfillmentOrderLineItems"] = (
                self._build_line_items(line_items)
            )

        data = self._gql(_MOVE_FO_MUTATION, variables)
        self._check_user_errors(data, "fulfillmentOrderMove")
        payload = data.get("fulfillmentOrderMove") or {}
        return self._success(
            Capability.SHOPIFY_MOVE_FULFILLMENT_ORDER,
            data={
                "moved_fulfillment_order": self._normalise_fo(
                    payload.get("movedFulfillmentOrder") or {}
                ),
                "original_fulfillment_order": self._normalise_fo(
                    payload.get("originalFulfillmentOrder") or {}
                ),
                "remaining_fulfillment_order": self._normalise_fo(
                    payload.get("remainingFulfillmentOrder") or {}
                ),
            },
        )

    # ── Reschedule ─────────────────────────────────────────────────

    def _reschedule(self, params: dict[str, Any]) -> Any:
        fo_id = self._extract_fo_id(params)
        fulfill_at = params.get("fulfill_at") or params.get("fulfillAt")
        if not isinstance(fulfill_at, str) or not fulfill_at.strip():
            raise AdapterValidationError(
                self.name,
                "'fulfill_at' is required (ISO-8601 datetime, e.g. "
                "'2026-05-15T00:00:00Z')",
            )
        data = self._gql(_RESCHEDULE_FO_MUTATION, {
            "id": fo_id, "fulfillAt": fulfill_at.strip(),
        })
        self._check_user_errors(data, "fulfillmentOrderReschedule")
        payload = data.get("fulfillmentOrderReschedule") or {}
        return self._success(
            Capability.SHOPIFY_RESCHEDULE_FULFILLMENT_ORDER,
            data={
                "fulfillment_order": self._normalise_fo(
                    payload.get("fulfillmentOrder") or {}
                ),
            },
        )

    # ── Split ──────────────────────────────────────────────────────

    def _split(self, params: dict[str, Any]) -> Any:
        splits = self._build_splits(params.get("splits"))
        data = self._gql(_SPLIT_FO_MUTATION, {
            "fulfillmentOrderSplits": splits,
        })
        self._check_user_errors(data, "fulfillmentOrderSplit")
        payload = data.get("fulfillmentOrderSplit") or {}
        results: list[dict[str, Any]] = []
        for split in (payload.get("fulfillmentOrderSplits") or []):
            if not isinstance(split, dict):
                continue
            results.append({
                "fulfillment_order": self._normalise_fo(
                    split.get("fulfillmentOrder") or {}
                ),
                "remaining_fulfillment_order": self._normalise_fo(
                    split.get("remainingFulfillmentOrder") or {}
                ),
                "replacement_fulfillment_order": self._normalise_fo(
                    split.get("replacementFulfillmentOrder") or {}
                ),
            })
        return self._success(
            Capability.SHOPIFY_SPLIT_FULFILLMENT_ORDER,
            data={
                "splits": results,
                "splits_count": len(splits),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_fo_id(self, params: dict[str, Any]) -> str:
        fo_id = (
            params.get("id")
            or params.get("fulfillment_order_id")
            or params.get("fulfillmentOrderId")
        )
        if not isinstance(fo_id, str) or not fo_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the FulfillmentOrder) is required",
            )
        return fo_id.strip()

    def _build_line_items(
        self, raw: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'line_items' must be a non-empty list of "
                "{id, quantity} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise AdapterValidationError(
                    self.name, f"line_items[{i}] must be a dict",
                )
            li_id = (
                item.get("id")
                or item.get("fulfillment_order_line_item_id")
            )
            qty = item.get("quantity")
            if not isinstance(li_id, str) or not li_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"line_items[{i}] missing 'id' "
                    "(FulfillmentOrderLineItem GID)",
                )
            if qty is None:
                raise AdapterValidationError(
                    self.name, f"line_items[{i}] missing 'quantity'",
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
                "id": li_id.strip(),
                "quantity": qty_int,
            })
        return out

    def _build_splits(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'splits' must be a non-empty list of "
                "{fulfillment_order_id, line_items: [...]} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, split in enumerate(raw):
            if not isinstance(split, dict):
                raise AdapterValidationError(
                    self.name, f"splits[{i}] must be a dict",
                )
            fo_id = (
                split.get("fulfillment_order_id")
                or split.get("fulfillmentOrderId")
            )
            if not isinstance(fo_id, str) or not fo_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"splits[{i}] missing 'fulfillment_order_id'",
                )
            line_items = (
                split.get("line_items")
                or split.get("fulfillment_order_line_items")
                or split.get("fulfillmentOrderLineItems")
            )
            line_items_built = self._build_line_items(line_items)
            out.append({
                "fulfillmentOrderId": fo_id.strip(),
                "fulfillmentOrderLineItems": line_items_built,
            })
        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_fo(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        assigned = node.get("assignedLocation") or {}
        location = (
            assigned.get("location")
            if isinstance(assigned, dict) else None
        ) or {}
        return {
            "id": node.get("id", "") or "",
            "status": node.get("status", "") or "",
            "request_status": node.get("requestStatus", "") or "",
            "fulfill_at": node.get("fulfillAt", "") or "",
            "location_id": (
                location.get("id", "")
                if isinstance(location, dict) else ""
            ) or "",
            "location_name": (
                location.get("name", "")
                if isinstance(location, dict) else ""
            ) or "",
        }
