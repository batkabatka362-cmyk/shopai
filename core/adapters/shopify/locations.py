"""ShopifyLocationsAdapter — read + write physical fulfillment locations.

Locations are Shopify's "where physical inventory and fulfillment
happens" record. Every inventory level, every fulfillment, every
in-store-pickup option ties back to a Location. ShopAI's engines
have three reasons to touch this surface:

  * **Inventory engine** needs to know what locations exist before
    it can call ``inventory_levels/set`` (location_id is a required
    arg there). The existing ``shopify_inventory`` adapter assumes
    the engine already knows location ids; this adapter is how it
    finds them.
  * **3PL onboarding flow** auto-creates a new Shopify Location when
    a merchant adds a fulfillment partner — without this adapter
    the merchant had to do it by hand in admin.
  * **Multi-warehouse pricing** reads the location list to decide
    where to source from per order, considering distance / cost.

Capabilities (read + create + update — no delete):

  * ``SHOPIFY_LIST_LOCATIONS``     — paginate locations, optional
    query filter (active/inactive, country, etc.).
  * ``SHOPIFY_GET_LOCATION``       — fetch one with its address +
    fulfillment-service binding.
  * ``SHOPIFY_CREATE_LOCATION``    — mint a new location with name
    + address.
  * ``SHOPIFY_UPDATE_LOCATION``    — change name / address /
    activation state.

Delete is intentionally NOT in this pass. Deleting a location is
high-blast-radius (orphans inventory levels, breaks reservations,
disrupts in-flight fulfillments); engines that want a location
gone should deactivate it via update first, then operator finishes
manually.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_LOCATION_NODE_FIELDS = """
id
name
isActive
shipsInventory
fulfillsOnlineOrders
hasActiveInventory
address {
  address1
  address2
  city
  province
  country
  countryCode
  zip
  phone
  formatted
}
""".strip()


_LIST_LOCATIONS_QUERY = f"""
query locations(
  $first: Int!, $after: String, $query: String,
  $sortKey: LocationSortKeys, $reverse: Boolean,
  $includeInactive: Boolean
) {{
  locations(
    first: $first, after: $after, query: $query,
    sortKey: $sortKey, reverse: $reverse,
    includeInactive: $includeInactive
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_LOCATION_NODE_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_LOCATION_QUERY = f"""
query location($id: ID!) {{
  location(id: $id) {{
    {_LOCATION_NODE_FIELDS}
  }}
}}
""".strip()


_CREATE_LOCATION_MUTATION = f"""
mutation locationAdd($input: LocationAddInput!) {{
  locationAdd(input: $input) {{
    location {{
      {_LOCATION_NODE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_LOCATION_MUTATION = f"""
mutation locationEdit($id: ID!, $input: LocationEditInput!) {{
  locationEdit(id: $id, input: $input) {{
    location {{
      {_LOCATION_NODE_FIELDS}
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


# AddressInput field aliases (snake_case → camelCase). Same map used
# by create + update, so callers learn one shape.
_ADDRESS_ALIASES = {
    "address1": "address1",
    "address2": "address2",
    "city": "city",
    "province": "province",
    "province_code": "provinceCode",
    "country": "country",
    "country_code": "countryCode",
    "zip": "zip",
    "phone": "phone",
}


class ShopifyLocationsAdapter(ShopifyBaseAdapter):
    name = "shopify_locations"
    capabilities = {
        Capability.SHOPIFY_LIST_LOCATIONS,
        Capability.SHOPIFY_GET_LOCATION,
        Capability.SHOPIFY_CREATE_LOCATION,
        Capability.SHOPIFY_UPDATE_LOCATION,
    }
    required_scopes = frozenset({"read_locations"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_LOCATIONS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_LOCATION:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_LOCATION:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_LOCATION:
            return self._update(params)
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
                "shopify_locations", "'cursor' must be a string or None",
            )
        query = params.get("query")
        if query is not None and not isinstance(query, str):
            raise AdapterValidationError(
                "shopify_locations", "'query' must be a string or None",
            )
        sort_key = params.get("sort_key") or params.get("sortKey")
        if sort_key is not None:
            if not isinstance(sort_key, str):
                raise AdapterValidationError(
                    "shopify_locations",
                    "'sort_key' must be a string or None",
                )
            sort_key = sort_key.upper()
        reverse = bool(params.get("reverse", False))
        # Default: active locations only. Engines that want the full
        # set (audit, cleanup) pass include_inactive=True explicitly.
        include_inactive = bool(params.get("include_inactive", False))

        data = self._gql(_LIST_LOCATIONS_QUERY, {
            "first": limit,
            "after": cursor,
            "query": query,
            "sortKey": sort_key,
            "reverse": reverse,
            "includeInactive": include_inactive,
        })
        envelope = data.get("locations") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        locations = [
            self._normalise_location(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_LOCATIONS,
            data={
                "locations": locations,
                "count": len(locations),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        location_id = params.get("id") or params.get("location_id")
        if not isinstance(location_id, str) or not location_id.strip():
            raise AdapterValidationError(
                "shopify_locations",
                "'id' (Shopify GID for the location) is required",
            )
        data = self._gql(_GET_LOCATION_QUERY, {"id": location_id.strip()})
        node = data.get("location")
        if not isinstance(node, dict):
            return self._success(
                Capability.SHOPIFY_GET_LOCATION,
                data={"found": False, "location": None},
            )
        return self._success(
            Capability.SHOPIFY_GET_LOCATION,
            data={"found": True,
                  "location": self._normalise_location(node)},
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        location_input = self._build_create_input(params)
        data = self._gql(
            _CREATE_LOCATION_MUTATION,
            {"input": location_input},
        )
        self._check_user_errors(data, "locationAdd")
        payload = data.get("locationAdd") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_LOCATION,
            data={
                "location": self._normalise_location(
                    payload.get("location") or {}
                ),
            },
        )

    @staticmethod
    def _build_create_input(params: dict[str, Any]) -> dict[str, Any]:
        """Convert ShopAI's friendly call shape into ``LocationAddInput``.

        Friendly form::

            {
              "name":    "Brooklyn DC",
              "address": {
                "address1":  "123 Main",
                "city":      "Brooklyn",
                "province":  "NY",
                "country":   "US",
                "country_code": "US",
                "zip":       "11201",
                "phone":     "+1-555-0100",
              },
              "fulfills_online_orders": True,    # optional, default True
            }
        """
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AdapterValidationError(
                "shopify_locations",
                "'name' is required (non-empty string)",
            )
        address = params.get("address")
        if not isinstance(address, dict):
            raise AdapterValidationError(
                "shopify_locations",
                "'address' is required (dict with at least country)",
            )

        out: dict[str, Any] = {
            "name": name.strip(),
            "address": _build_address_input(address, where="address"),
        }
        # Optional flag — engines toggling click-and-collect at a
        # warehouse will set this False.
        if "fulfills_online_orders" in params or "fulfillsOnlineOrders" in params:
            out["fulfillsOnlineOrders"] = bool(
                params.get("fulfills_online_orders",
                           params.get("fulfillsOnlineOrders", True))
            )
        return out

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        location_id = params.get("id") or params.get("location_id")
        if not isinstance(location_id, str) or not location_id.strip():
            raise AdapterValidationError(
                "shopify_locations",
                "'id' (Shopify GID for the location) is required",
            )

        update_input = self._build_update_input(params)
        if not update_input:
            raise AdapterValidationError(
                "shopify_locations",
                "update needs at least one field besides 'id' "
                "(name / address / fulfills_online_orders)",
            )
        data = self._gql(_UPDATE_LOCATION_MUTATION, {
            "id": location_id.strip(),
            "input": update_input,
        })
        self._check_user_errors(data, "locationEdit")
        payload = data.get("locationEdit") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_LOCATION,
            data={
                "location": self._normalise_location(
                    payload.get("location") or {}
                ),
            },
        )

    @staticmethod
    def _build_update_input(params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "name" in params:
            name = params["name"]
            if not isinstance(name, str) or not name.strip():
                raise AdapterValidationError(
                    "shopify_locations",
                    "'name' must be a non-empty string when set",
                )
            out["name"] = name.strip()
        if "address" in params:
            address = params["address"]
            if not isinstance(address, dict):
                raise AdapterValidationError(
                    "shopify_locations",
                    "'address' must be a dict when set",
                )
            out["address"] = _build_address_input(
                address, where="address",
            )
        if "fulfills_online_orders" in params or "fulfillsOnlineOrders" in params:
            out["fulfillsOnlineOrders"] = bool(
                params.get("fulfills_online_orders",
                           params.get("fulfillsOnlineOrders"))
            )
        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_location(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        addr = node.get("address") or {}
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "is_active": bool(node.get("isActive", False)),
            "ships_inventory": bool(node.get("shipsInventory", False)),
            "fulfills_online_orders": bool(
                node.get("fulfillsOnlineOrders", False)
            ),
            "has_active_inventory": bool(
                node.get("hasActiveInventory", False)
            ),
            "address1": (
                addr.get("address1", "") if isinstance(addr, dict) else ""
            ) or "",
            "address2": (
                addr.get("address2", "") if isinstance(addr, dict) else ""
            ) or "",
            "city": (
                addr.get("city", "") if isinstance(addr, dict) else ""
            ) or "",
            "province": (
                addr.get("province", "") if isinstance(addr, dict) else ""
            ) or "",
            "country": (
                addr.get("country", "") if isinstance(addr, dict) else ""
            ) or "",
            "country_code": (
                addr.get("countryCode", "") if isinstance(addr, dict) else ""
            ) or "",
            "zip": (
                addr.get("zip", "") if isinstance(addr, dict) else ""
            ) or "",
            "phone": (
                addr.get("phone", "") if isinstance(addr, dict) else ""
            ) or "",
            "formatted_address": (
                addr.get("formatted", "") if isinstance(addr, dict) else ""
            ),
        }


def _build_address_input(
    address: dict[str, Any], *, where: str,
) -> dict[str, Any]:
    """Translate a friendly snake_case address dict into the
    LocationAddress*Input the schema wants.

    Country is functionally required by Shopify (a location with no
    country can't be tax-resolved); the adapter rejects address
    dicts that omit it instead of paying for a userErrors round trip.
    """
    if not address.get("country") and not address.get("country_code") \
            and not address.get("countryCode"):
        raise AdapterValidationError(
            "shopify_locations",
            f"{where!r} needs at least 'country' or 'country_code' "
            f"(Shopify rejects locations with no country binding)",
        )
    out: dict[str, Any] = {}
    for snake, camel in _ADDRESS_ALIASES.items():
        if snake in address:
            v = address[snake]
            if v is not None and not isinstance(v, str):
                raise AdapterValidationError(
                    "shopify_locations",
                    f"{where!r} field {snake!r} must be a string",
                )
            if v:
                out[camel] = v
    return out
