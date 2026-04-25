"""ShopifyCompanyLocationsAdapter — B2B company-location CRUD.

Companion to ``companies.py`` (B2B company root) and
``company_contact_roles.py`` (role-binding management). Locations
are the per-warehouse / per-store records under a B2B company.
Each carries its own shipping address, billing address, tax
exemptions, and (optionally) buyer-experience configuration:
catalog, currency, market, payment terms.

ShopAI's B2B engine uses these to:

  * **Onboard a new ship-to.** Sales rep closes a deal with a
    multi-location buyer (HQ + three warehouses). The CRM
    integration mints the company once and then loops this
    adapter to add the locations.
  * **Update billing/shipping mid-flight.** When AP changes the
    "send invoices to" address, the engine pushes an UPDATE
    rather than asking the operator to click through admin.
  * **Retire shuttered locations.** When a buyer closes a
    warehouse, DELETE removes it from the catalog (orders placed
    while it was active stay intact).

Capabilities:

  * ``SHOPIFY_LIST_COMPANY_LOCATIONS``   — list locations for a
    company (Pattern B traversal: ``company(id:).locations``).
  * ``SHOPIFY_GET_COMPANY_LOCATION``     — fetch one location by GID.
  * ``SHOPIFY_CREATE_COMPANY_LOCATION``  — add a new location.
  * ``SHOPIFY_UPDATE_COMPANY_LOCATION``  — patch an existing
    location's name, note, addresses, and external_id.
  * ``SHOPIFY_DELETE_COMPANY_LOCATION``  — remove a location.

Pattern A applied: ``companyLocationCreate`` takes ``companyId``
at field level (NOT inside the input dict). ``Update`` and
``Delete`` likewise take ``companyLocationId`` at field level.

Pattern D handled: ``shippingAddress`` accepts
``CompanyAddressInput`` — a SUBSET of the broader AddressInput
(no firstName / lastName / company / phone). This adapter
forwards only the address fields Shopify actually accepts.
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
note
externalId
locale
createdAt
updatedAt
hasTimelineComment
shippingAddress {
  address1
  address2
  city
  province
  country
  countryCode
  zip
  phone
  recipient
  zoneCode
}
billingAddress {
  address1
  address2
  city
  province
  country
  countryCode
  zip
  phone
  recipient
  zoneCode
}
""".strip()


# Pattern B: list goes through the parent company. There IS a
# top-level Query.companyLocations connection, but onboarding +
# audit flows in ShopAI always know the company first; traversal
# keeps the call shape consistent with company_contact_roles.py.
_LIST_LOCATIONS_QUERY = f"""
query companyLocationsByCompany(
  $companyId: ID!,
  $first: Int!,
  $after: String,
  $reverse: Boolean
) {{
  company(id: $companyId) {{
    id
    name
    locations(
      first: $first, after: $after, reverse: $reverse
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
}}
""".strip()


_GET_LOCATION_QUERY = f"""
query companyLocation($id: ID!) {{
  companyLocation(id: $id) {{
    {_LOCATION_NODE_FIELDS}
    company {{
      id
      name
    }}
  }}
}}
""".strip()


_CREATE_LOCATION_MUTATION = f"""
mutation companyLocationCreate(
  $companyId: ID!,
  $input: CompanyLocationInput!
) {{
  companyLocationCreate(
    companyId: $companyId, input: $input
  ) {{
    companyLocation {{
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
mutation companyLocationUpdate(
  $companyLocationId: ID!,
  $input: CompanyLocationUpdateInput!
) {{
  companyLocationUpdate(
    companyLocationId: $companyLocationId, input: $input
  ) {{
    companyLocation {{
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


_DELETE_LOCATION_MUTATION = """
mutation companyLocationDelete($companyLocationId: ID!) {
  companyLocationDelete(companyLocationId: $companyLocationId) {
    deletedCompanyLocationId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


# CompanyAddressInput accepts only this address-field subset.
_ADDRESS_ALIASES = {
    "address1": "address1",
    "address2": "address2",
    "city": "city",
    "country_code": "countryCode",
    "countryCode": "countryCode",
    "phone": "phone",
    "recipient": "recipient",
    "zip": "zip",
    "zone_code": "zoneCode",
    "zoneCode": "zoneCode",
}


class ShopifyCompanyLocationsAdapter(ShopifyBaseAdapter):
    name = "shopify_company_locations"
    capabilities = {
        Capability.SHOPIFY_LIST_COMPANY_LOCATIONS,
        Capability.SHOPIFY_GET_COMPANY_LOCATION,
        Capability.SHOPIFY_CREATE_COMPANY_LOCATION,
        Capability.SHOPIFY_UPDATE_COMPANY_LOCATION,
        Capability.SHOPIFY_DELETE_COMPANY_LOCATION,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_COMPANY_LOCATIONS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_COMPANY_LOCATION:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_COMPANY_LOCATION:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_COMPANY_LOCATION:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_COMPANY_LOCATION:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        company_id = params.get("company_id") or params.get("companyId")
        if not isinstance(company_id, str) or not company_id.strip():
            raise AdapterValidationError(
                self.name,
                "'company_id' (Shopify GID) is required — list traverses "
                "via company(id:).locations",
            )

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
        reverse = bool(params.get("reverse", False))

        data = self._gql(_LIST_LOCATIONS_QUERY, {
            "companyId": company_id.strip(),
            "first": limit,
            "after": cursor,
            "reverse": reverse,
        })
        company = data.get("company") or {}
        envelope = company.get("locations") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        locations = [
            self._normalise_location(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_COMPANY_LOCATIONS,
            data={
                "company_id": company.get("id", "") or "",
                "company_name": company.get("name", "") or "",
                "company_found": bool(company),
                "locations": locations,
                "count": len(locations),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        loc_id = (
            params.get("id")
            or params.get("company_location_id")
            or params.get("companyLocationId")
        )
        if not isinstance(loc_id, str) or not loc_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the company location) is required",
            )
        data = self._gql(_GET_LOCATION_QUERY, {"id": loc_id.strip()})
        node = data.get("companyLocation")
        if not isinstance(node, dict):
            return self._success(
                Capability.SHOPIFY_GET_COMPANY_LOCATION,
                data={"found": False, "location": None},
            )
        company_node = node.get("company") or {}
        normalised = self._normalise_location(node)
        normalised["company_id"] = (
            company_node.get("id", "") if isinstance(company_node, dict)
            else ""
        ) or ""
        normalised["company_name"] = (
            company_node.get("name", "") if isinstance(company_node, dict)
            else ""
        ) or ""
        return self._success(
            Capability.SHOPIFY_GET_COMPANY_LOCATION,
            data={"found": True, "location": normalised},
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        company_id = params.get("company_id") or params.get("companyId")
        if not isinstance(company_id, str) or not company_id.strip():
            raise AdapterValidationError(
                self.name,
                "'company_id' (Shopify GID) is required — Pattern A: "
                "companyId at field level, NOT inside input",
            )
        location_input = self._build_create_input(params)
        data = self._gql(_CREATE_LOCATION_MUTATION, {
            "companyId": company_id.strip(),
            "input": location_input,
        })
        self._check_user_errors(data, "companyLocationCreate")
        payload = data.get("companyLocationCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_COMPANY_LOCATION,
            data={
                "location": self._normalise_location(
                    payload.get("companyLocation") or {}
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        loc_id = (
            params.get("id")
            or params.get("company_location_id")
            or params.get("companyLocationId")
        )
        if not isinstance(loc_id, str) or not loc_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the company location) is required",
            )
        location_input = self._build_update_input(params)
        if not location_input:
            raise AdapterValidationError(
                self.name,
                "no patchable fields supplied — pass at least one of "
                "name/note/external_id/shipping_address/billing_address",
            )
        data = self._gql(_UPDATE_LOCATION_MUTATION, {
            "companyLocationId": loc_id.strip(),
            "input": location_input,
        })
        self._check_user_errors(data, "companyLocationUpdate")
        payload = data.get("companyLocationUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_COMPANY_LOCATION,
            data={
                "location": self._normalise_location(
                    payload.get("companyLocation") or {}
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        loc_id = (
            params.get("id")
            or params.get("company_location_id")
            or params.get("companyLocationId")
        )
        if not isinstance(loc_id, str) or not loc_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the company location) is required",
            )
        data = self._gql(_DELETE_LOCATION_MUTATION, {
            "companyLocationId": loc_id.strip(),
        })
        self._check_user_errors(data, "companyLocationDelete")
        payload = data.get("companyLocationDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_COMPANY_LOCATION,
            data={
                "deleted_id": (
                    payload.get("deletedCompanyLocationId", "") or ""
                ),
            },
        )

    # ── Input builders ─────────────────────────────────────────────

    def _build_create_input(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AdapterValidationError(
                self.name, "'name' is required (non-empty string)",
            )
        out: dict[str, Any] = {"name": name.strip()}

        note = params.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    self.name, "'note' must be a string",
                )
            out["note"] = note

        external_id = params.get("external_id") or params.get("externalId")
        if external_id is not None:
            if not isinstance(external_id, str):
                raise AdapterValidationError(
                    self.name, "'external_id' must be a string",
                )
            out["externalId"] = external_id

        locale = params.get("locale")
        if locale is not None:
            if not isinstance(locale, str):
                raise AdapterValidationError(
                    self.name, "'locale' must be a string",
                )
            out["locale"] = locale

        phone = params.get("phone")
        if phone is not None:
            if not isinstance(phone, str):
                raise AdapterValidationError(
                    self.name, "'phone' must be a string",
                )
            out["phone"] = phone

        shipping = (
            params.get("shipping_address")
            or params.get("shippingAddress")
        )
        if shipping is not None:
            out["shippingAddress"] = self._build_address(
                shipping, label="shipping_address",
            )

        billing = (
            params.get("billing_address") or params.get("billingAddress")
        )
        if billing is not None:
            out["billingAddress"] = self._build_address(
                billing, label="billing_address",
            )

        # Convenience: tax_settings forwarded as-is when caller
        # supplies the camelCase Shopify shape.
        tax = params.get("tax_settings") or params.get("taxSettings")
        if tax is not None:
            if not isinstance(tax, dict):
                raise AdapterValidationError(
                    self.name, "'tax_settings' must be a dict",
                )
            out["taxSettings"] = tax

        return out

    def _build_update_input(self, params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}

        name = params.get("name")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise AdapterValidationError(
                    self.name, "'name' must be a non-empty string",
                )
            out["name"] = name.strip()

        note = params.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    self.name, "'note' must be a string",
                )
            out["note"] = note

        external_id = params.get("external_id") or params.get("externalId")
        if external_id is not None:
            if not isinstance(external_id, str):
                raise AdapterValidationError(
                    self.name, "'external_id' must be a string",
                )
            out["externalId"] = external_id

        locale = params.get("locale")
        if locale is not None:
            if not isinstance(locale, str):
                raise AdapterValidationError(
                    self.name, "'locale' must be a string",
                )
            out["locale"] = locale

        phone = params.get("phone")
        if phone is not None:
            if not isinstance(phone, str):
                raise AdapterValidationError(
                    self.name, "'phone' must be a string",
                )
            out["phone"] = phone

        shipping = (
            params.get("shipping_address")
            or params.get("shippingAddress")
        )
        if shipping is not None:
            out["shippingAddress"] = self._build_address(
                shipping, label="shipping_address",
            )

        billing = (
            params.get("billing_address") or params.get("billingAddress")
        )
        if billing is not None:
            out["billingAddress"] = self._build_address(
                billing, label="billing_address",
            )

        return out

    def _build_address(self, raw: Any, *, label: str) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name, f"'{label}' must be a dict",
            )
        addr_out: dict[str, Any] = {}
        for snake, camel in _ADDRESS_ALIASES.items():
            if snake in raw:
                v = raw[snake]
                if v is None:
                    continue
                if not isinstance(v, str):
                    raise AdapterValidationError(
                        self.name,
                        f"'{label}.{snake}' must be a string",
                    )
                if v:
                    addr_out[camel] = v
        if not addr_out:
            raise AdapterValidationError(
                self.name,
                f"'{label}' had no recognised fields — accepted: "
                f"{sorted(set(_ADDRESS_ALIASES.values()))}",
            )
        return addr_out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_location(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}

        def flatten_address(addr: Any) -> dict[str, str]:
            if not isinstance(addr, dict):
                return {}
            return {
                "address1": addr.get("address1", "") or "",
                "address2": addr.get("address2", "") or "",
                "city": addr.get("city", "") or "",
                "province": addr.get("province", "") or "",
                "country": addr.get("country", "") or "",
                "country_code": addr.get("countryCode", "") or "",
                "zip": addr.get("zip", "") or "",
                "phone": addr.get("phone", "") or "",
                "recipient": addr.get("recipient", "") or "",
                "zone_code": addr.get("zoneCode", "") or "",
            }

        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "note": node.get("note", "") or "",
            "external_id": node.get("externalId", "") or "",
            "locale": node.get("locale", "") or "",
            "has_timeline_comment": bool(
                node.get("hasTimelineComment", False),
            ),
            "shipping_address": flatten_address(
                node.get("shippingAddress")
            ),
            "billing_address": flatten_address(
                node.get("billingAddress")
            ),
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
