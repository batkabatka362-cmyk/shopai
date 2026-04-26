"""ShopifyCarrierServicesAdapter — custom shipping rate calculators.

A carrier service is an HTTP callback Shopify hits at checkout to
ask "what's the shipping rate for this cart + destination?". The
default carriers (UPS, USPS, DHL, ...) are built in; custom carrier
services let merchants plug in their own rate logic — third-party
3PL endpoints, dynamic rate APIs, weight-based rules engines.

ShopAI's shipping engine + 3PL integration engine register carrier
services pointing at ShopAI-hosted callback endpoints so the
shipping rate logic stays in the brain layer rather than baked
into Shopify config.

Capabilities:

  * ``SHOPIFY_LIST_CARRIER_SERVICES``    — list registered services.
  * ``SHOPIFY_CREATE_CARRIER_SERVICE``   — register a new endpoint.
  * ``SHOPIFY_UPDATE_CARRIER_SERVICE``   — update name / URL / scope.
  * ``SHOPIFY_DELETE_CARRIER_SERVICE``   — unregister.

Friendly create call shape::

    {"name":          "ShopAI Smart Rates",
     "callback_url":  "https://rates.shopai.dev/quote",
     "supports_service_discovery": True,  # Shopify probes the URL
                                          # at registration time
     "active":        True}

Pattern E note: gated by ``write_shipping`` scope. Non-Plus stores
are limited to 3 active carrier services; Plus stores get unlimited.
Live verification on a non-Plus store will surface the limit at
create time as a userError.

Pattern A: variable name is "input" (matches CarrierServiceCreateInput).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CARRIER_SERVICE_FIELDS = """
id
name
callbackUrl
active
supportsServiceDiscovery
""".strip()


_LIST_CARRIER_SERVICES_QUERY = f"""
query carrierServices($first: Int!, $after: String) {{
  carrierServices(first: $first, after: $after) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_CARRIER_SERVICE_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_CREATE_CARRIER_SERVICE_MUTATION = f"""
mutation carrierServiceCreate($input: DeliveryCarrierServiceCreateInput!) {{
  carrierServiceCreate(input: $input) {{
    carrierService {{
      {_CARRIER_SERVICE_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_UPDATE_CARRIER_SERVICE_MUTATION = f"""
mutation carrierServiceUpdate($input: DeliveryCarrierServiceUpdateInput!) {{
  carrierServiceUpdate(input: $input) {{
    carrierService {{
      {_CARRIER_SERVICE_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_DELETE_CARRIER_SERVICE_MUTATION = """
mutation carrierServiceDelete($id: ID!) {
  carrierServiceDelete(id: $id) {
    deletedId
    userErrors {
      field
      message
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyCarrierServicesAdapter(ShopifyBaseAdapter):
    name = "shopify_carrier_services"
    capabilities = {
        Capability.SHOPIFY_LIST_CARRIER_SERVICES,
        Capability.SHOPIFY_CREATE_CARRIER_SERVICE,
        Capability.SHOPIFY_UPDATE_CARRIER_SERVICE,
        Capability.SHOPIFY_DELETE_CARRIER_SERVICE,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_CARRIER_SERVICES:
            return self._list(params)
        if capability == Capability.SHOPIFY_CREATE_CARRIER_SERVICE:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_CARRIER_SERVICE:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_CARRIER_SERVICE:
            return self._delete(params)
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
                self.name, "'cursor' must be a string or None",
            )

        data = self._gql(_LIST_CARRIER_SERVICES_QUERY, {
            "first": limit, "after": cursor,
        })
        envelope = data.get("carrierServices") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        services = [
            self._normalise_service(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_CARRIER_SERVICES,
            data={
                "carrier_services": services,
                "count": len(services),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        service_input = self._build_input(params, for_update=False)
        data = self._gql(_CREATE_CARRIER_SERVICE_MUTATION, {
            "input": service_input,
        })
        self._check_user_errors(data, "carrierServiceCreate")
        payload = data.get("carrierServiceCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_CARRIER_SERVICE,
            data={
                "carrier_service": self._normalise_service(
                    payload.get("carrierService") or {},
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        service_input = self._build_input(params, for_update=True)
        data = self._gql(_UPDATE_CARRIER_SERVICE_MUTATION, {
            "input": service_input,
        })
        self._check_user_errors(data, "carrierServiceUpdate")
        payload = data.get("carrierServiceUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_CARRIER_SERVICE,
            data={
                "carrier_service": self._normalise_service(
                    payload.get("carrierService") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        service_id = params.get("id") or params.get("carrier_service_id")
        if not isinstance(service_id, str) or not service_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the carrier service) is required",
            )
        data = self._gql(_DELETE_CARRIER_SERVICE_MUTATION, {
            "id": service_id.strip(),
        })
        self._check_user_errors(data, "carrierServiceDelete")
        payload = data.get("carrierServiceDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_CARRIER_SERVICE,
            data={
                "deleted_id": payload.get("deletedId", "") or "",
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_input(
        self, params: dict[str, Any], for_update: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        if for_update:
            service_id = params.get("id") or params.get("carrier_service_id")
            if not isinstance(service_id, str) or not service_id.strip():
                raise AdapterValidationError(
                    self.name,
                    "'id' (Shopify GID) is required for update",
                )
            out["id"] = service_id.strip()

        name = params.get("name")
        if name is not None:
            if not isinstance(name, str):
                raise AdapterValidationError(
                    self.name, "'name' must be a string",
                )
            if name.strip():
                out["name"] = name.strip()

        if not for_update and "name" not in out:
            raise AdapterValidationError(
                self.name, "'name' is required to create a carrier service",
            )

        callback_url = params.get("callback_url") or params.get("callbackUrl")
        if callback_url is not None:
            if not isinstance(callback_url, str) or not callback_url.strip():
                raise AdapterValidationError(
                    self.name,
                    "'callback_url' must be a non-empty string",
                )
            if not callback_url.startswith(("http://", "https://")):
                raise AdapterValidationError(
                    self.name,
                    "'callback_url' must start with http:// or https://",
                )
            out["callbackUrl"] = callback_url.strip()
        elif not for_update:
            raise AdapterValidationError(
                self.name,
                "'callback_url' is required to create a carrier service",
            )

        supports_discovery = params.get("supports_service_discovery")
        if supports_discovery is None:
            supports_discovery = params.get("supportsServiceDiscovery")
        if supports_discovery is not None:
            out["supportsServiceDiscovery"] = bool(supports_discovery)

        active = params.get("active")
        if active is not None:
            out["active"] = bool(active)

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_service(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "callback_url": node.get("callbackUrl", "") or "",
            "active": bool(node.get("active", False)),
            "supports_service_discovery": bool(
                node.get("supportsServiceDiscovery", False),
            ),
        }
