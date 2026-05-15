"""ShopifyFulfillmentEventsAdapter — shipment tracking events.

Companion to ``fulfillment.py`` (creates fulfillments) and
``fulfillment_services.py`` (registers 3PL endpoints). A
fulfillment event records a single milestone in the shipping
journey: PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, plus
the timestamp + location code.

ShopAI's fulfillment + customer-service engines use these to:

  * Surface real-time delivery status in operator dashboards and
    customer-service replies ("your package is in Memphis hub").
  * Detect delivery anomalies ("stuck IN_TRANSIT for 5 days, time
    to investigate").
  * Trigger post-purchase flows on DELIVERED (review request,
    re-order reminder).

Capabilities:

  * ``SHOPIFY_LIST_FULFILLMENT_EVENTS``    — list events for a
    given fulfillment (chronological).
  * ``SHOPIFY_CREATE_FULFILLMENT_EVENT``   — append a new tracking
    event (used by 3PL integrations writing back into Shopify).

Friendly create call shape::

    {"fulfillment_id": "gid://shopify/Fulfillment/123",
     "status":         "IN_TRANSIT",
     "address1":       "550 Mainland Hwy",
     "city":           "Memphis",
     "country":        "US",
     "happened_at":    "2026-04-26T12:00:00Z",
     "estimated_delivery_at": "2026-04-28T17:00:00Z",
     "message":        "Package arrived at Memphis sort facility"}

Pattern A: fulfillmentEventCreate takes the FulfillmentEventInput
inside a single ``fulfillmentEvent`` argument (named after the
input type — same Pattern A as marketingEngagementCreate /
validationCreate).

Pattern E note: gated by ``write_fulfillments`` scope. This
mutation is most often called BY a fulfillment service's callback
endpoint, NOT directly by ShopAI engines — adapters that need to
attribute events to a specific 3PL run as that 3PL's app.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_EVENT_FIELDS = """
id
status
happenedAt
estimatedDeliveryAt
message
address1
city
province
country
zip
latitude
longitude
""".strip()


_LIST_FULFILLMENT_EVENTS_QUERY = f"""
query fulfillmentEvents($id: ID!, $first: Int) {{
  fulfillment(id: $id) {{
    id
    name
    status
    events(first: $first) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      edges {{
        node {{
          {_EVENT_FIELDS}
        }}
      }}
    }}
  }}
}}
""".strip()


_CREATE_FULFILLMENT_EVENT_MUTATION = f"""
mutation fulfillmentEventCreate(
  $fulfillmentEvent: FulfillmentEventInput!
) {{
  fulfillmentEventCreate(fulfillmentEvent: $fulfillmentEvent) {{
    fulfillmentEvent {{
      {_EVENT_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250

_VALID_STATUSES = {
    "LABEL_PURCHASED",
    "LABEL_PRINTED",
    "READY_FOR_PICKUP",
    "PICKED_UP",
    "CONFIRMED",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "ATTEMPTED_DELIVERY",
    "DELIVERED",
    "FAILURE",
}


class ShopifyFulfillmentEventsAdapter(ShopifyBaseAdapter):
    name = "shopify_fulfillment_events"
    capabilities = {
        Capability.SHOPIFY_LIST_FULFILLMENT_EVENTS,
        Capability.SHOPIFY_CREATE_FULFILLMENT_EVENT,
    }
    required_scopes = frozenset({"write_merchant_managed_fulfillment_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_FULFILLMENT_EVENTS:
            return self._list(params)
        if capability == Capability.SHOPIFY_CREATE_FULFILLMENT_EVENT:
            return self._create(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        fulfillment_id = params.get("fulfillment_id") or params.get(
            "fulfillmentId"
        )
        if not isinstance(fulfillment_id, str) or not fulfillment_id.strip():
            raise AdapterValidationError(
                self.name,
                "'fulfillment_id' (Shopify GID) is required — there's no "
                "top-level Query.fulfillmentEvents connection",
            )

        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        data = self._gql(_LIST_FULFILLMENT_EVENTS_QUERY, {
            "id": fulfillment_id.strip(),
            "first": limit,
        })
        fulfillment = data.get("fulfillment") or {}
        envelope = fulfillment.get("events") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        events = [
            self._normalise_event(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_FULFILLMENT_EVENTS,
            data={
                "fulfillment_id": fulfillment.get("id", "") or "",
                "fulfillment_name": fulfillment.get("name", "") or "",
                "fulfillment_status": fulfillment.get("status", "") or "",
                "events": events,
                "count": len(events),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
                "fulfillment_found": bool(fulfillment),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        event_input = self._build_event_input(params)
        data = self._gql(_CREATE_FULFILLMENT_EVENT_MUTATION, {
            "fulfillmentEvent": event_input,
        })
        self._check_user_errors(data, "fulfillmentEventCreate")
        payload = data.get("fulfillmentEventCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_FULFILLMENT_EVENT,
            data={
                "event": self._normalise_event(
                    payload.get("fulfillmentEvent") or {},
                ),
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_event_input(self, params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}

        fulfillment_id = params.get("fulfillment_id") or params.get(
            "fulfillmentId"
        )
        if not isinstance(fulfillment_id, str) or not fulfillment_id.strip():
            raise AdapterValidationError(
                self.name, "'fulfillment_id' (Shopify GID) is required",
            )
        out["fulfillmentId"] = fulfillment_id.strip()

        status = params.get("status")
        if not isinstance(status, str) or status.upper() not in _VALID_STATUSES:
            raise AdapterValidationError(
                self.name,
                f"'status' is required and must be one of: "
                f"{sorted(_VALID_STATUSES)}",
            )
        out["status"] = status.upper()

        # Address fields — snake_case input, camelCase wire.
        for snake, camel in (
            ("address1", "address1"),
            ("city", "city"),
            ("province", "province"),
            ("country", "country"),
            ("zip", "zip"),
            ("message", "message"),
        ):
            value = params.get(snake)
            if value is None:
                continue
            if not isinstance(value, str):
                raise AdapterValidationError(
                    self.name, f"'{snake}' must be a string",
                )
            out[camel] = value

        # Numeric lat/long.
        for snake, camel in (("latitude", "latitude"),
                             ("longitude", "longitude")):
            value = params.get(snake)
            if value is None:
                continue
            try:
                out[camel] = float(value)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, f"'{snake}' must be numeric",
                ) from exc

        happened_at = params.get("happened_at") or params.get("happenedAt")
        if happened_at is not None:
            if not isinstance(happened_at, str):
                raise AdapterValidationError(
                    self.name, "'happened_at' must be an ISO-8601 string",
                )
            out["happenedAt"] = happened_at.strip()

        eta = params.get("estimated_delivery_at") or params.get(
            "estimatedDeliveryAt"
        )
        if eta is not None:
            if not isinstance(eta, str):
                raise AdapterValidationError(
                    self.name,
                    "'estimated_delivery_at' must be an ISO-8601 string",
                )
            out["estimatedDeliveryAt"] = eta.strip()

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_event(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        return {
            "id": node.get("id", "") or "",
            "status": node.get("status", "") or "",
            "happened_at": node.get("happenedAt", "") or "",
            "estimated_delivery_at": node.get("estimatedDeliveryAt", "") or "",
            "message": node.get("message", "") or "",
            "address1": node.get("address1", "") or "",
            "city": node.get("city", "") or "",
            "province": node.get("province", "") or "",
            "country": node.get("country", "") or "",
            "zip": node.get("zip", "") or "",
            "latitude": float(node.get("latitude") or 0) or 0.0,
            "longitude": float(node.get("longitude") or 0) or 0.0,
            "is_terminal": node.get("status", "") in {"DELIVERED", "FAILURE"},
        }
