"""ShopifyReverseDeliveryAdapter — return shipment lifecycle.

Companion to ``returns.py`` (the upstream return record from
the customer's perspective). Once a return is approved, the
operations side spins up:

  1. A **reverse delivery** — the shipment from the customer
     back to the merchant. This adapter creates it with
     tracking info + a return-shipping label, optionally
     notifying the customer with the label PDF.
  2. The **disposal** of returned line items — restock to a
     specific location, mark for reprocessing, mark not
     restocked (damaged), or mark missing.

ShopAI's returns engine uses the trio:

  * **Auto-issue return label.** Customer requests a return,
    return is approved, engine calls
    ``reverseDeliveryCreateWithShipping`` with the carrier's
    tracking + label URL. Customer gets the shipping label
    email automatically.
  * **Tracking swap.** Carrier mis-routed; ops moves the
    return to a different carrier and updates the tracking
    via ``reverseDeliveryShippingUpdate``.
  * **Disposition decision.** Returned items hit the receiving
    dock; engine calls ``reverseFulfillmentOrderDispose`` per
    line item with disposition RESTOCKED / PROCESSING_REQUIRED
    / NOT_RESTOCKED / MISSING.

Capabilities:

  * ``SHOPIFY_CREATE_REVERSE_DELIVERY`` —
    reverseDeliveryCreateWithShipping. Pattern A:
    reverseFulfillmentOrderId + reverseDeliveryLineItems +
    optional tracking/label/notify all at field level.
  * ``SHOPIFY_UPDATE_REVERSE_DELIVERY_SHIPPING`` —
    reverseDeliveryShippingUpdate. Pattern A:
    reverseDeliveryId + tracking/label updates.
  * ``SHOPIFY_DISPOSE_REVERSE_FULFILLMENT_ORDER`` —
    reverseFulfillmentOrderDispose. Takes a list of
    {line_item_id, quantity, disposition_type, location_id?}
    dicts.

UserError variant for all three is ``ReturnUserError`` (has
``code``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_REVERSE_DELIVERY_FIELDS = """
id
deliverable {
  ... on ReverseDeliveryShippingDeliverable {
    label {
      publicFileUrl
      createdAt
    }
    tracking {
      number
      url
    }
  }
}
""".strip()


_CREATE_REVERSE_DELIVERY_MUTATION = f"""
mutation reverseDeliveryCreateWithShipping(
  $reverseFulfillmentOrderId: ID!,
  $reverseDeliveryLineItems: [ReverseDeliveryLineItemInput!]!,
  $trackingInput: ReverseDeliveryTrackingInput,
  $labelInput: ReverseDeliveryLabelInput,
  $notifyCustomer: Boolean
) {{
  reverseDeliveryCreateWithShipping(
    reverseFulfillmentOrderId: $reverseFulfillmentOrderId,
    reverseDeliveryLineItems: $reverseDeliveryLineItems,
    trackingInput: $trackingInput,
    labelInput: $labelInput,
    notifyCustomer: $notifyCustomer
  ) {{
    reverseDelivery {{
      {_REVERSE_DELIVERY_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_REVERSE_DELIVERY_SHIPPING_MUTATION = f"""
mutation reverseDeliveryShippingUpdate(
  $reverseDeliveryId: ID!,
  $trackingInput: ReverseDeliveryTrackingInput,
  $labelInput: ReverseDeliveryLabelInput,
  $notifyCustomer: Boolean
) {{
  reverseDeliveryShippingUpdate(
    reverseDeliveryId: $reverseDeliveryId,
    trackingInput: $trackingInput,
    labelInput: $labelInput,
    notifyCustomer: $notifyCustomer
  ) {{
    reverseDelivery {{
      {_REVERSE_DELIVERY_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DISPOSE_REVERSE_FO_MUTATION = """
mutation reverseFulfillmentOrderDispose(
  $dispositionInputs: [ReverseFulfillmentOrderDisposeInput!]!
) {
  reverseFulfillmentOrderDispose(
    dispositionInputs: $dispositionInputs
  ) {
    reverseFulfillmentOrderLineItems {
      id
      dispositions {
        id
        type
        quantity
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


_VALID_DISPOSITION_TYPES = {
    "RESTOCKED", "PROCESSING_REQUIRED", "NOT_RESTOCKED", "MISSING",
}


class ShopifyReverseDeliveryAdapter(ShopifyBaseAdapter):
    name = "shopify_reverse_delivery"
    capabilities = {
        Capability.SHOPIFY_CREATE_REVERSE_DELIVERY,
        Capability.SHOPIFY_UPDATE_REVERSE_DELIVERY_SHIPPING,
        Capability.SHOPIFY_DISPOSE_REVERSE_FULFILLMENT_ORDER,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_REVERSE_DELIVERY:
            return self._create(params)
        if capability == \
                Capability.SHOPIFY_UPDATE_REVERSE_DELIVERY_SHIPPING:
            return self._update_shipping(params)
        if capability == \
                Capability.SHOPIFY_DISPOSE_REVERSE_FULFILLMENT_ORDER:
            return self._dispose(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        rfo_id = (
            params.get("reverse_fulfillment_order_id")
            or params.get("reverseFulfillmentOrderId")
            or params.get("id")
        )
        if not isinstance(rfo_id, str) or not rfo_id.strip():
            raise AdapterValidationError(
                self.name,
                "'reverse_fulfillment_order_id' (Shopify GID for the "
                "ReverseFulfillmentOrder) is required",
            )
        line_items = self._build_line_items(params.get("line_items"))

        variables: dict[str, Any] = {
            "reverseFulfillmentOrderId": rfo_id.strip(),
            "reverseDeliveryLineItems": line_items,
            "trackingInput": self._build_tracking(params.get("tracking")),
            "labelInput": self._build_label(params.get("label")),
            "notifyCustomer": None,
        }
        notify = params.get("notify_customer")
        if notify is None:
            notify = params.get("notifyCustomer")
        if notify is not None:
            variables["notifyCustomer"] = bool(notify)

        data = self._gql(_CREATE_REVERSE_DELIVERY_MUTATION, variables)
        self._check_user_errors(data, "reverseDeliveryCreateWithShipping")
        payload = data.get("reverseDeliveryCreateWithShipping") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_REVERSE_DELIVERY,
            data={
                "reverse_delivery": self._normalise_reverse_delivery(
                    payload.get("reverseDelivery") or {}
                ),
                "line_items_count": len(line_items),
            },
        )

    # ── Update shipping ────────────────────────────────────────────

    def _update_shipping(self, params: dict[str, Any]) -> Any:
        rd_id = (
            params.get("reverse_delivery_id")
            or params.get("reverseDeliveryId")
            or params.get("id")
        )
        if not isinstance(rd_id, str) or not rd_id.strip():
            raise AdapterValidationError(
                self.name,
                "'reverse_delivery_id' (Shopify GID for the "
                "ReverseDelivery) is required",
            )

        tracking = self._build_tracking(params.get("tracking"))
        label = self._build_label(params.get("label"))
        if tracking is None and label is None:
            raise AdapterValidationError(
                self.name,
                "supply at least one of 'tracking' or 'label' to update",
            )

        variables: dict[str, Any] = {
            "reverseDeliveryId": rd_id.strip(),
            "trackingInput": tracking,
            "labelInput": label,
            "notifyCustomer": None,
        }
        notify = params.get("notify_customer")
        if notify is None:
            notify = params.get("notifyCustomer")
        if notify is not None:
            variables["notifyCustomer"] = bool(notify)

        data = self._gql(
            _UPDATE_REVERSE_DELIVERY_SHIPPING_MUTATION, variables,
        )
        self._check_user_errors(data, "reverseDeliveryShippingUpdate")
        payload = data.get("reverseDeliveryShippingUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_REVERSE_DELIVERY_SHIPPING,
            data={
                "reverse_delivery": self._normalise_reverse_delivery(
                    payload.get("reverseDelivery") or {}
                ),
            },
        )

    # ── Dispose ────────────────────────────────────────────────────

    def _dispose(self, params: dict[str, Any]) -> Any:
        dispositions = self._build_dispositions(
            params.get("dispositions"),
        )
        data = self._gql(_DISPOSE_REVERSE_FO_MUTATION, {
            "dispositionInputs": dispositions,
        })
        self._check_user_errors(data, "reverseFulfillmentOrderDispose")
        payload = data.get("reverseFulfillmentOrderDispose") or {}
        items = payload.get("reverseFulfillmentOrderLineItems") or []
        return self._success(
            Capability.SHOPIFY_DISPOSE_REVERSE_FULFILLMENT_ORDER,
            data={
                "line_items": [
                    self._normalise_disposed_item(li)
                    for li in items if isinstance(li, dict)
                ],
                "dispositions_count": len(dispositions),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _build_line_items(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'line_items' must be a non-empty list of "
                "{reverse_fulfillment_order_line_item_id, quantity} "
                "dicts",
            )
        out: list[dict[str, Any]] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise AdapterValidationError(
                    self.name, f"line_items[{i}] must be a dict",
                )
            li_id = (
                item.get("reverse_fulfillment_order_line_item_id")
                or item.get("reverseFulfillmentOrderLineItemId")
                or item.get("id")
            )
            qty = item.get("quantity")
            if not isinstance(li_id, str) or not li_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"line_items[{i}] missing "
                    "'reverse_fulfillment_order_line_item_id'",
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
                "reverseFulfillmentOrderLineItemId": li_id.strip(),
                "quantity": qty_int,
            })
        return out

    def _build_tracking(self, raw: Any) -> dict[str, Any] | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'tracking' must be a dict {number?, url?}",
            )
        out: dict[str, Any] = {}
        number = raw.get("number") or raw.get("tracking_number")
        if number is not None:
            if not isinstance(number, str):
                raise AdapterValidationError(
                    self.name, "'tracking.number' must be a string",
                )
            out["number"] = number.strip()
        url = raw.get("url") or raw.get("tracking_url")
        if url is not None:
            if not isinstance(url, str):
                raise AdapterValidationError(
                    self.name, "'tracking.url' must be a string",
                )
            out["url"] = url.strip()
        if not out:
            raise AdapterValidationError(
                self.name,
                "'tracking' had no fields — pass at least 'number' "
                "or 'url'",
            )
        return out

    def _build_label(self, raw: Any) -> dict[str, Any] | None:
        if raw is None:
            return None
        if isinstance(raw, str):
            # Friendly: bare URL string maps to {file_url}.
            return {"fileUrl": raw.strip()}
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'label' must be a string URL or {file_url} dict",
            )
        file_url = raw.get("file_url") or raw.get("fileUrl") or raw.get("url")
        if not isinstance(file_url, str) or not file_url.strip():
            raise AdapterValidationError(
                self.name,
                "'label.file_url' is required (PDF / PNG return-label URL)",
            )
        return {"fileUrl": file_url.strip()}

    def _build_dispositions(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'dispositions' must be a non-empty list of "
                "{reverse_fulfillment_order_line_item_id, quantity, "
                "disposition_type, location_id?} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, d in enumerate(raw):
            if not isinstance(d, dict):
                raise AdapterValidationError(
                    self.name, f"dispositions[{i}] must be a dict",
                )
            li_id = (
                d.get("reverse_fulfillment_order_line_item_id")
                or d.get("reverseFulfillmentOrderLineItemId")
                or d.get("id")
            )
            qty = d.get("quantity")
            disp_type_raw = (
                d.get("disposition_type") or d.get("dispositionType")
            )
            location_id = d.get("location_id") or d.get("locationId")

            if not isinstance(li_id, str) or not li_id.strip():
                raise AdapterValidationError(
                    self.name,
                    f"dispositions[{i}] missing "
                    "'reverse_fulfillment_order_line_item_id'",
                )
            if qty is None:
                raise AdapterValidationError(
                    self.name,
                    f"dispositions[{i}] missing 'quantity'",
                )
            try:
                qty_int = int(qty)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"dispositions[{i}].quantity must be an int",
                ) from exc
            if qty_int <= 0:
                raise AdapterValidationError(
                    self.name,
                    f"dispositions[{i}].quantity must be > 0",
                )
            if not isinstance(disp_type_raw, str) or \
                    not disp_type_raw.strip():
                raise AdapterValidationError(
                    self.name,
                    f"dispositions[{i}] missing 'disposition_type' "
                    f"(one of {sorted(_VALID_DISPOSITION_TYPES)})",
                )
            disp_type = disp_type_raw.strip().upper()
            if disp_type not in _VALID_DISPOSITION_TYPES:
                raise AdapterValidationError(
                    self.name,
                    f"dispositions[{i}].disposition_type must be one of "
                    f"{sorted(_VALID_DISPOSITION_TYPES)}",
                )

            entry: dict[str, Any] = {
                "reverseFulfillmentOrderLineItemId": li_id.strip(),
                "quantity": qty_int,
                "dispositionType": disp_type,
            }
            if location_id is not None:
                if not isinstance(location_id, str):
                    raise AdapterValidationError(
                        self.name,
                        f"dispositions[{i}].location_id must be a "
                        "GID string",
                    )
                entry["locationId"] = location_id.strip()
            out.append(entry)
        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_reverse_delivery(
        node: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        deliverable = node.get("deliverable") or {}
        label = (
            deliverable.get("label")
            if isinstance(deliverable, dict) else None
        ) or {}
        tracking = (
            deliverable.get("tracking")
            if isinstance(deliverable, dict) else None
        ) or {}
        return {
            "id": node.get("id", "") or "",
            "label_url": (
                label.get("publicFileUrl", "")
                if isinstance(label, dict) else ""
            ) or "",
            "label_created_at": (
                label.get("createdAt", "")
                if isinstance(label, dict) else ""
            ) or "",
            "tracking_number": (
                tracking.get("number", "")
                if isinstance(tracking, dict) else ""
            ) or "",
            "tracking_url": (
                tracking.get("url", "")
                if isinstance(tracking, dict) else ""
            ) or "",
        }

    @staticmethod
    def _normalise_disposed_item(
        node: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        dispositions: list[dict[str, Any]] = []
        for d in (node.get("dispositions") or []):
            if not isinstance(d, dict):
                continue
            location = d.get("location") or {}
            try:
                qty = int(d.get("quantity") or 0)
            except (TypeError, ValueError):
                qty = 0
            dispositions.append({
                "id": d.get("id", "") or "",
                "type": d.get("type", "") or "",
                "quantity": qty,
                "location_id": (
                    location.get("id", "")
                    if isinstance(location, dict) else ""
                ) or "",
                "location_name": (
                    location.get("name", "")
                    if isinstance(location, dict) else ""
                ) or "",
            })
        return {
            "id": node.get("id", "") or "",
            "dispositions": dispositions,
        }
