"""ShopifyInventoryShipmentsAdapter — track + create inter-location shipments.

Inventory shipments are Shopify's record of physical stock moving
from one Location to another (warehouse → store, supplier → DC, etc.).
ShopAI's two engines that touch this surface:

  * **Replenishment engine.** When the stock level at Location A
    drops below threshold and Location B has surplus, the engine
    auto-creates a shipment to move N units. The merchant approves
    in admin or the engine auto-marks-in-transit for trusted lanes.
  * **In-transit visibility.** The order-routing engine wants to
    know "is the SKU already in transit to a closer location?"
    before sourcing from a distant one. Reading shipments answers
    that.

Capabilities (read + create — lifecycle mutations deferred):

  * ``SHOPIFY_LIST_INVENTORY_SHIPMENTS``   — paginate shipments,
    filter by status (open / in-transit / received).
  * ``SHOPIFY_GET_INVENTORY_SHIPMENT``     — fetch one with full
    line items + tracking.
  * ``SHOPIFY_CREATE_INVENTORY_SHIPMENT``  — mint a new shipment
    from origin → destination with line items.

Lifecycle mutations (mark-in-transit / receive / delete) are
intentionally deferred — those are merchant-confirmable actions
where mistakes (marking received before scan-in) corrupt inventory
counts. v1 keeps engines on the read path + create only;
operator advances state.

----

**API version gate — important caveat.**

``Query.inventoryShipments`` and the ``InventoryShipmentSortKeys``
enum were introduced in Shopify Admin API ``2025-04``. ShopAI's
GraphQL client is pinned to ``2024-01`` (see
``data_pipeline.ingestion.api.shopify_api._API_VERSION``), so a
live call against this adapter currently rejects with::

    Field 'inventoryShipments' doesn't exist on type 'QueryRoot'

This is Pattern B in CLAUDE.md (Query.X does not exist on some API
versions) crossed with a version-pin issue, not a scope gate. The
adapter wire format follows the modern schema; when the GraphQL
client is bumped to ``2025-04`` or later, this adapter starts
working without any code changes here.

Engines that need shipment visibility *today* should use the
legacy ``inventoryTransfer`` REST surface (out of scope for this
adapter) or wait for the version bump.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_SHIPMENT_NODE_FIELDS = """
id
name
status
trackingNumber
trackingUrl
note
createdAt
updatedAt
arrivalDate
origin {
  id
  name
}
destination {
  id
  name
}
lineItems(first: 50) {
  edges {
    node {
      id
      quantity
      receivedQuantity
      inventoryItem {
        id
        sku
      }
    }
  }
}
""".strip()


_LIST_SHIPMENTS_QUERY = f"""
query inventoryShipments(
  $first: Int!, $after: String, $query: String,
  $sortKey: InventoryShipmentSortKeys, $reverse: Boolean
) {{
  inventoryShipments(
    first: $first, after: $after, query: $query,
    sortKey: $sortKey, reverse: $reverse
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_SHIPMENT_NODE_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_SHIPMENT_QUERY = f"""
query inventoryShipment($id: ID!) {{
  inventoryShipment(id: $id) {{
    {_SHIPMENT_NODE_FIELDS}
  }}
}}
""".strip()


_CREATE_SHIPMENT_MUTATION = f"""
mutation inventoryShipmentCreate($input: InventoryShipmentCreateInput!) {{
  inventoryShipmentCreate(input: $input) {{
    inventoryShipment {{
      {_SHIPMENT_NODE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250
# Shopify caps inventory shipment line items at 250 per shipment.
# Engines pushing larger transfers should chunk into multiple
# shipments rather than expecting one giant call.
_MAX_LINE_ITEMS_PER_SHIPMENT = 250


class ShopifyInventoryShipmentsAdapter(ShopifyBaseAdapter):
    name = "shopify_inventory_shipments"
    capabilities = {
        Capability.SHOPIFY_LIST_INVENTORY_SHIPMENTS,
        Capability.SHOPIFY_GET_INVENTORY_SHIPMENT,
        Capability.SHOPIFY_CREATE_INVENTORY_SHIPMENT,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_INVENTORY_SHIPMENTS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_INVENTORY_SHIPMENT:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_INVENTORY_SHIPMENT:
            return self._create(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                "shopify_inventory_shipments",
                "'cursor' must be a string or None",
            )
        query = params.get("query")
        if query is not None and not isinstance(query, str):
            raise AdapterValidationError(
                "shopify_inventory_shipments",
                "'query' must be a string or None",
            )
        sort_key = params.get("sort_key") or params.get("sortKey")
        if sort_key is not None:
            if not isinstance(sort_key, str):
                raise AdapterValidationError(
                    "shopify_inventory_shipments",
                    "'sort_key' must be a string or None",
                )
            sort_key = sort_key.upper()
        reverse = bool(params.get("reverse", False))

        data = self._gql(_LIST_SHIPMENTS_QUERY, {
            "first": limit,
            "after": cursor,
            "query": query,
            "sortKey": sort_key,
            "reverse": reverse,
        })
        envelope = data.get("inventoryShipments") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        shipments = [
            self._normalise_shipment(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_INVENTORY_SHIPMENTS,
            data={
                "shipments": shipments,
                "count": len(shipments),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        shipment_id = params.get("id") or params.get("shipment_id")
        if not isinstance(shipment_id, str) or not shipment_id.strip():
            raise AdapterValidationError(
                "shopify_inventory_shipments",
                "'id' (Shopify GID for the inventory shipment) is required",
            )
        data = self._gql(_GET_SHIPMENT_QUERY, {"id": shipment_id.strip()})
        node = data.get("inventoryShipment")
        if not isinstance(node, dict):
            return self._success(
                Capability.SHOPIFY_GET_INVENTORY_SHIPMENT,
                data={"found": False, "shipment": None},
            )
        return self._success(
            Capability.SHOPIFY_GET_INVENTORY_SHIPMENT,
            data={"found": True,
                  "shipment": self._normalise_shipment(node)},
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        shipment_input = self._build_create_input(params)
        data = self._gql(
            _CREATE_SHIPMENT_MUTATION,
            {"input": shipment_input},
        )
        self._check_user_errors(data, "inventoryShipmentCreate")
        payload = data.get("inventoryShipmentCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_INVENTORY_SHIPMENT,
            data={
                "shipment": self._normalise_shipment(
                    payload.get("inventoryShipment") or {}
                ),
            },
        )

    @staticmethod
    def _build_create_input(params: dict[str, Any]) -> dict[str, Any]:
        """Convert ShopAI's friendly call shape into ``InventoryShipmentCreateInput``.

        Friendly form::

            {
              "origin_id":      "gid://shopify/Location/A",
              "destination_id": "gid://shopify/Location/B",
              "tracking_number": "1Z999...",                  # optional
              "tracking_url":    "https://carrier/...",       # optional
              "note":            "Replenish from DC",          # optional
              "arrival_date":    "2026-05-15",                 # optional ISO
              "line_items": [
                  {"inventory_item_id": "gid://shopify/InventoryItem/X",
                   "quantity": 50},
                  ...
              ],
            }
        """
        origin_id = params.get("origin_id") or params.get("originId")
        if not isinstance(origin_id, str) or not origin_id.strip():
            raise AdapterValidationError(
                "shopify_inventory_shipments",
                "'origin_id' (origin Location GID) is required",
            )
        destination_id = (
            params.get("destination_id") or params.get("destinationId")
        )
        if not isinstance(destination_id, str) or not destination_id.strip():
            raise AdapterValidationError(
                "shopify_inventory_shipments",
                "'destination_id' (destination Location GID) is required",
            )
        if origin_id.strip() == destination_id.strip():
            raise AdapterValidationError(
                "shopify_inventory_shipments",
                "'origin_id' and 'destination_id' must differ — "
                "Shopify rejects self-shipments",
            )

        line_items_raw = params.get("line_items") or params.get("lineItems")
        if not isinstance(line_items_raw, list) or not line_items_raw:
            raise AdapterValidationError(
                "shopify_inventory_shipments",
                "'line_items' must be a non-empty list of "
                "{inventory_item_id, quantity} dicts",
            )
        if len(line_items_raw) > _MAX_LINE_ITEMS_PER_SHIPMENT:
            raise AdapterValidationError(
                "shopify_inventory_shipments",
                f"max {_MAX_LINE_ITEMS_PER_SHIPMENT} line items per "
                f"shipment, got {len(line_items_raw)}",
            )

        out_items: list[dict[str, Any]] = []
        for i, li in enumerate(line_items_raw):
            if not isinstance(li, dict):
                raise AdapterValidationError(
                    "shopify_inventory_shipments",
                    f"line_items[{i}] must be a dict",
                )
            inv_item_id = (
                li.get("inventory_item_id") or li.get("inventoryItemId")
            )
            if not isinstance(inv_item_id, str) or not inv_item_id.strip():
                raise AdapterValidationError(
                    "shopify_inventory_shipments",
                    f"line_items[{i}] needs 'inventory_item_id' (GID)",
                )
            quantity = li.get("quantity")
            try:
                qty = int(quantity)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    "shopify_inventory_shipments",
                    f"line_items[{i}] 'quantity' must be int, "
                    f"got {type(quantity).__name__}",
                ) from exc
            if qty < 1:
                raise AdapterValidationError(
                    "shopify_inventory_shipments",
                    f"line_items[{i}] 'quantity' must be >= 1, got {qty}",
                )
            out_items.append({
                "inventoryItemId": inv_item_id.strip(),
                "quantity": qty,
            })

        out: dict[str, Any] = {
            "originLocationId": origin_id.strip(),
            "destinationLocationId": destination_id.strip(),
            "lineItems": out_items,
        }

        # Optional pass-through fields.
        for friendly, camel in (
            ("tracking_number", "trackingNumber"),
            ("tracking_url", "trackingUrl"),
            ("note", "note"),
            ("arrival_date", "arrivalDate"),
        ):
            if friendly in params:
                v = params[friendly]
                if v is not None and not isinstance(v, str):
                    raise AdapterValidationError(
                        "shopify_inventory_shipments",
                        f"'{friendly}' must be a string when set",
                    )
                if v:
                    out[camel] = v

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_shipment(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        origin = node.get("origin") or {}
        destination = node.get("destination") or {}
        line_items_raw = (node.get("lineItems") or {}).get("edges") or []
        line_items: list[dict[str, Any]] = []
        for edge in line_items_raw:
            if not isinstance(edge, dict):
                continue
            li = edge.get("node") or {}
            inv_item = li.get("inventoryItem") or {}
            line_items.append({
                "id": li.get("id", "") or "",
                "quantity": int(li.get("quantity", 0) or 0),
                "received_quantity": int(li.get("receivedQuantity", 0) or 0),
                "inventory_item_id": (
                    inv_item.get("id", "")
                    if isinstance(inv_item, dict) else ""
                ) or "",
                "sku": (
                    inv_item.get("sku", "")
                    if isinstance(inv_item, dict) else ""
                ) or "",
            })
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "status": node.get("status", "") or "",
            "tracking_number": node.get("trackingNumber", "") or "",
            "tracking_url": node.get("trackingUrl", "") or "",
            "note": node.get("note", "") or "",
            "arrival_date": node.get("arrivalDate", "") or "",
            "origin_id": (
                origin.get("id", "") if isinstance(origin, dict) else ""
            ) or "",
            "origin_name": (
                origin.get("name", "") if isinstance(origin, dict) else ""
            ) or "",
            "destination_id": (
                destination.get("id", "")
                if isinstance(destination, dict) else ""
            ) or "",
            "destination_name": (
                destination.get("name", "")
                if isinstance(destination, dict) else ""
            ) or "",
            "line_items": line_items,
            "line_items_count": len(line_items),
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
