"""ShopifyFulfillmentServicesAdapter — custom 3PL endpoint registration.

A fulfillment service is a third-party fulfillment provider Shopify
hands order line items off to: Amazon FBA, ShipBob, ShipMonk, Deliverr,
or a merchant's in-house warehouse via a custom HTTP endpoint. Once
registered, products can be assigned to the service, and Shopify
calls the service's URL when an order needs fulfilling.

Companion to ``fulfillment.py`` (which TRACKS fulfillments) and
``carrier_services.py`` (which quotes shipping rates). This adapter
manages the ENDPOINT REGISTRATION — the fulfillment lifecycle still
flows through fulfillment.py.

ShopAI's fulfillment engine + 3PL integration engine register
fulfillment services pointing at ShopAI-hosted callback endpoints
so the routing logic (which warehouse, which carrier, which split)
stays in the brain layer rather than baked into Shopify.

Capabilities:

  * ``SHOPIFY_LIST_FULFILLMENT_SERVICES``    — list registered
    services (manual + custom).
  * ``SHOPIFY_CREATE_FULFILLMENT_SERVICE``   — register a new
    custom service.
  * ``SHOPIFY_UPDATE_FULFILLMENT_SERVICE``   — update name / URL /
    inventory-tracking flag.
  * ``SHOPIFY_DELETE_FULFILLMENT_SERVICE``   — unregister.

Friendly create call shape::

    {"name":              "ShopAI Routing",
     "callback_url":      "https://fulfill.shopai.dev/callback",
     "tracks_inventory":  True,
     "permits_sku_sharing": True,
     "fulfillment_orders_opt_in": True}

Pattern E note: gated by ``write_fulfillments`` scope. Each
fulfillment service auto-creates a Location of type FULFILLMENT_APP
that products can be assigned to — engines that allocate inventory
need to discover this location via locations.py after registration.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_FULFILLMENT_SERVICE_FIELDS = """
id
serviceName
callbackUrl
inventoryManagement
permitsSkuSharing
trackingSupport
type
fulfillmentOrdersOptIn
location {
  id
  name
}
""".strip()


_LIST_FULFILLMENT_SERVICES_QUERY = """
query shop {
  shop {
    fulfillmentServices {
      id
      serviceName
      callbackUrl
      inventoryManagement
      permitsSkuSharing
      trackingSupport
      type
      fulfillmentOrdersOptIn
      location {
        id
        name
      }
    }
  }
}
""".strip()


_CREATE_FULFILLMENT_SERVICE_MUTATION = f"""
mutation fulfillmentServiceCreate(
  $name: String!,
  $callbackUrl: URL!,
  $trackingSupport: Boolean,
  $inventoryManagement: Boolean,
  $permitsSkuSharing: Boolean,
  $fulfillmentOrdersOptIn: Boolean!
) {{
  fulfillmentServiceCreate(
    name: $name,
    callbackUrl: $callbackUrl,
    trackingSupport: $trackingSupport,
    inventoryManagement: $inventoryManagement,
    permitsSkuSharing: $permitsSkuSharing,
    fulfillmentOrdersOptIn: $fulfillmentOrdersOptIn
  ) {{
    fulfillmentService {{
      {_FULFILLMENT_SERVICE_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_UPDATE_FULFILLMENT_SERVICE_MUTATION = f"""
mutation fulfillmentServiceUpdate(
  $id: ID!,
  $name: String,
  $callbackUrl: URL,
  $trackingSupport: Boolean
) {{
  fulfillmentServiceUpdate(
    id: $id,
    name: $name,
    callbackUrl: $callbackUrl,
    trackingSupport: $trackingSupport
  ) {{
    fulfillmentService {{
      {_FULFILLMENT_SERVICE_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_DELETE_FULFILLMENT_SERVICE_MUTATION = """
mutation fulfillmentServiceDelete($id: ID!) {
  fulfillmentServiceDelete(id: $id) {
    deletedId
    userErrors {
      field
      message
    }
  }
}
""".strip()


class ShopifyFulfillmentServicesAdapter(ShopifyBaseAdapter):
    name = "shopify_fulfillment_services"
    capabilities = {
        Capability.SHOPIFY_LIST_FULFILLMENT_SERVICES,
        Capability.SHOPIFY_CREATE_FULFILLMENT_SERVICE,
        Capability.SHOPIFY_UPDATE_FULFILLMENT_SERVICE,
        Capability.SHOPIFY_DELETE_FULFILLMENT_SERVICE,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_FULFILLMENT_SERVICES:
            return self._list(params)
        if capability == Capability.SHOPIFY_CREATE_FULFILLMENT_SERVICE:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_FULFILLMENT_SERVICE:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_FULFILLMENT_SERVICE:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, _params: dict[str, Any]) -> Any:
        # Pattern B-adjacent: fulfillment services don't paginate via
        # a top-level Query.fulfillmentServices connection — they hang
        # off Shop. The whole list comes back in one shot since the
        # cardinality is small (3-10 typical).
        data = self._gql(_LIST_FULFILLMENT_SERVICES_QUERY, {})
        shop = data.get("shop") or {}
        services_raw = shop.get("fulfillmentServices") or []
        services = [
            self._normalise_service(s) for s in services_raw
            if isinstance(s, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_FULFILLMENT_SERVICES,
            data={
                "fulfillment_services": services,
                "count": len(services),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        variables = self._build_create_variables(params)
        data = self._gql(_CREATE_FULFILLMENT_SERVICE_MUTATION, variables)
        self._check_user_errors(data, "fulfillmentServiceCreate")
        payload = data.get("fulfillmentServiceCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_FULFILLMENT_SERVICE,
            data={
                "fulfillment_service": self._normalise_service(
                    payload.get("fulfillmentService") or {},
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        service_id = params.get("id") or params.get("fulfillment_service_id")
        if not isinstance(service_id, str) or not service_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the fulfillment service) is required",
            )
        variables: dict[str, Any] = {"id": service_id.strip()}

        name = params.get("name")
        if name is not None:
            if not isinstance(name, str):
                raise AdapterValidationError(
                    self.name, "'name' must be a string",
                )
            variables["name"] = name.strip()

        callback_url = params.get("callback_url") or params.get("callbackUrl")
        if callback_url is not None:
            self._validate_callback_url(callback_url)
            variables["callbackUrl"] = callback_url.strip()

        tracking_support = params.get("tracking_support")
        if tracking_support is None:
            tracking_support = params.get("trackingSupport")
        if tracking_support is not None:
            variables["trackingSupport"] = bool(tracking_support)

        if len(variables) == 1:
            raise AdapterValidationError(
                self.name,
                "no updatable fields supplied (name, callback_url, "
                "tracking_support)",
            )

        data = self._gql(_UPDATE_FULFILLMENT_SERVICE_MUTATION, variables)
        self._check_user_errors(data, "fulfillmentServiceUpdate")
        payload = data.get("fulfillmentServiceUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_FULFILLMENT_SERVICE,
            data={
                "fulfillment_service": self._normalise_service(
                    payload.get("fulfillmentService") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        service_id = params.get("id") or params.get("fulfillment_service_id")
        if not isinstance(service_id, str) or not service_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the fulfillment service) is required",
            )
        data = self._gql(_DELETE_FULFILLMENT_SERVICE_MUTATION, {
            "id": service_id.strip(),
        })
        self._check_user_errors(data, "fulfillmentServiceDelete")
        payload = data.get("fulfillmentServiceDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_FULFILLMENT_SERVICE,
            data={
                "deleted_id": payload.get("deletedId", "") or "",
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_create_variables(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AdapterValidationError(
                self.name, "'name' is required",
            )

        callback_url = params.get("callback_url") or params.get("callbackUrl")
        if not isinstance(callback_url, str) or not callback_url.strip():
            raise AdapterValidationError(
                self.name, "'callback_url' is required",
            )
        self._validate_callback_url(callback_url)

        # Pattern A note: fulfillmentOrdersOptIn is REQUIRED. Shopify
        # is migrating all fulfillment to the FulfillmentOrder API;
        # services that don't opt in are deprecated. Default to True.
        opt_in = params.get("fulfillment_orders_opt_in")
        if opt_in is None:
            opt_in = params.get("fulfillmentOrdersOptIn")
        if opt_in is None:
            opt_in = True

        out: dict[str, Any] = {
            "name": name.strip(),
            "callbackUrl": callback_url.strip(),
            "fulfillmentOrdersOptIn": bool(opt_in),
        }

        tracking_support = params.get("tracking_support")
        if tracking_support is None:
            tracking_support = params.get("trackingSupport")
        if tracking_support is not None:
            out["trackingSupport"] = bool(tracking_support)

        inventory_mgmt = params.get("inventory_management")
        if inventory_mgmt is None:
            inventory_mgmt = params.get("inventoryManagement")
        if inventory_mgmt is None:
            # Convenience alias: tracks_inventory
            inventory_mgmt = params.get("tracks_inventory")
        if inventory_mgmt is not None:
            out["inventoryManagement"] = bool(inventory_mgmt)

        permits_sku_sharing = params.get("permits_sku_sharing")
        if permits_sku_sharing is None:
            permits_sku_sharing = params.get("permitsSkuSharing")
        if permits_sku_sharing is not None:
            out["permitsSkuSharing"] = bool(permits_sku_sharing)

        return out

    def _validate_callback_url(self, url: Any) -> None:
        if not isinstance(url, str) or not url.strip():
            raise AdapterValidationError(
                self.name, "'callback_url' must be a non-empty string",
            )
        if not url.startswith(("http://", "https://")):
            raise AdapterValidationError(
                self.name,
                "'callback_url' must start with http:// or https://",
            )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_service(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        location = node.get("location") or {}
        return {
            "id": node.get("id", "") or "",
            "name": node.get("serviceName", "") or "",
            "callback_url": node.get("callbackUrl", "") or "",
            "inventory_management": bool(
                node.get("inventoryManagement", False),
            ),
            "permits_sku_sharing": bool(node.get("permitsSkuSharing", False)),
            "tracking_support": bool(node.get("trackingSupport", False)),
            "type": node.get("type", "") or "",
            "fulfillment_orders_opt_in": bool(
                node.get("fulfillmentOrdersOptIn", False),
            ),
            "location_id": (
                location.get("id", "")
                if isinstance(location, dict) else ""
            ) or "",
            "location_name": (
                location.get("name", "")
                if isinstance(location, dict) else ""
            ) or "",
        }
