"""ShopifyCompaniesAdapter — B2B company / buyer management.

Shopify B2B (Plus tier) lets a single buyer log in as a contact of a
"company", with the company carrying its own price list, payment terms,
and shipping locations. ShopAI's B2B engines need three handles on
that surface:

  * **Read company structure.** Before pricing the engine asks: "what
    company tier is this buyer in? what location do they ship to?
    what payment terms apply?" — all read off the Company record.
  * **Auto-create companies from CRM webhooks.** When a salesperson
    closes a new wholesale account in HubSpot/Salesforce, the
    integration engine mints the Shopify Company so the buyer can
    log in immediately rather than waiting for manual setup.
  * **Lookup by name / external_id.** Lets the engine de-dup before
    creating; existing companies get attached to.

Capabilities (read + create):

  * ``SHOPIFY_LIST_COMPANIES``   — paginate companies with optional
    query filter (name, external_id, etc.) + sort.
  * ``SHOPIFY_GET_COMPANY``      — fetch one with full main contact
    + locations.
  * ``SHOPIFY_CREATE_COMPANY``   — mint a new Company. Optionally
    seeds the first contact (the buyer's user record) and the
    primary location in the same call.

Update / delete are intentionally NOT in this pass. Companies are
high-blast-radius records (deleting one orphans every order placed
by its contacts); engines that want to mutate existing ones should
go through explicit operator approval rather than a fire-and-forget
adapter call.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_COMPANY_NODE_FIELDS = """
id
name
note
externalId
createdAt
updatedAt
ordersCount {
  count
}
totalSpent {
  amount
  currencyCode
}
mainContact {
  id
  customer {
    id
    email
    displayName
  }
}
locations(first: 25) {
  edges {
    node {
      id
      name
      shippingAddress {
        address1
        city
        province
        country
        zip
      }
    }
  }
}
""".strip()


_LIST_COMPANIES_QUERY = f"""
query companies(
  $first: Int!, $after: String, $query: String,
  $sortKey: CompanySortKeys, $reverse: Boolean
) {{
  companies(
    first: $first, after: $after, query: $query,
    sortKey: $sortKey, reverse: $reverse
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_COMPANY_NODE_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_COMPANY_QUERY = f"""
query company($id: ID!) {{
  company(id: $id) {{
    {_COMPANY_NODE_FIELDS}
  }}
}}
""".strip()


_CREATE_COMPANY_MUTATION = f"""
mutation companyCreate($input: CompanyCreateInput!) {{
  companyCreate(input: $input) {{
    company {{
      {_COMPANY_NODE_FIELDS}
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


class ShopifyCompaniesAdapter(ShopifyBaseAdapter):
    name = "shopify_companies"
    capabilities = {
        Capability.SHOPIFY_LIST_COMPANIES,
        Capability.SHOPIFY_GET_COMPANY,
        Capability.SHOPIFY_CREATE_COMPANY,
    }
    # B2B companies ride on customer scopes — Shopify treats
    # companies as a customer feature.
    required_scopes = frozenset({
        "read_customers", "write_customers",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_COMPANIES:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_COMPANY:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_COMPANY:
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
                "shopify_companies", "'cursor' must be a string or None",
            )
        query = params.get("query")
        if query is not None and not isinstance(query, str):
            raise AdapterValidationError(
                "shopify_companies", "'query' must be a string or None",
            )
        sort_key = params.get("sort_key") or params.get("sortKey")
        if sort_key is not None:
            if not isinstance(sort_key, str):
                raise AdapterValidationError(
                    "shopify_companies",
                    "'sort_key' must be a string or None",
                )
            sort_key = sort_key.upper()
        reverse = bool(params.get("reverse", False))

        data = self._gql(_LIST_COMPANIES_QUERY, {
            "first": limit,
            "after": cursor,
            "query": query,
            "sortKey": sort_key,
            "reverse": reverse,
        })
        envelope = data.get("companies") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        companies = [
            self._normalise_company(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_COMPANIES,
            data={
                "companies": companies,
                "count": len(companies),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        company_id = params.get("id") or params.get("company_id")
        if not isinstance(company_id, str) or not company_id.strip():
            raise AdapterValidationError(
                "shopify_companies",
                "'id' (Shopify GID for the company) is required",
            )
        data = self._gql(_GET_COMPANY_QUERY, {"id": company_id.strip()})
        node = data.get("company")
        if not isinstance(node, dict):
            return self._success(
                Capability.SHOPIFY_GET_COMPANY,
                data={"found": False, "company": None},
            )
        return self._success(
            Capability.SHOPIFY_GET_COMPANY,
            data={"found": True,
                  "company": self._normalise_company(node)},
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        company_input = self._build_create_input(params)
        data = self._gql(_CREATE_COMPANY_MUTATION, {"input": company_input})
        self._check_user_errors(data, "companyCreate")
        payload = data.get("companyCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_COMPANY,
            data={
                "company": self._normalise_company(
                    payload.get("company") or {}
                ),
            },
        )

    @staticmethod
    def _build_create_input(params: dict[str, Any]) -> dict[str, Any]:
        """Convert ShopAI's friendly call shape into ``CompanyCreateInput``.

        Friendly form::

            {
              "name":        "Acme Corp",                # required
              "note":        "Imported from HubSpot",    # optional
              "external_id": "hubspot-12345",            # optional
              "customer_id": "gid://shopify/Customer/X", # optional buyer
              "location": {                              # optional first
                "name": "HQ",                            # location seed
                "address": {
                  "address1": "123 Main",
                  "city":     "Springfield",
                  "country":  "United States",
                  "zip":      "62704",
                },
              },
            }

        Validates name + types up-front; address fields are
        forwarded as-is (Shopify validates them).
        """
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AdapterValidationError(
                "shopify_companies",
                "'name' is required (non-empty string)",
            )

        company_section: dict[str, Any] = {"name": name.strip()}

        note = params.get("note")
        if note:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    "shopify_companies", "'note' must be a string",
                )
            company_section["note"] = note

        external_id = params.get("external_id") or params.get("externalId")
        if external_id:
            if not isinstance(external_id, str):
                raise AdapterValidationError(
                    "shopify_companies",
                    "'external_id' must be a string",
                )
            company_section["externalId"] = external_id

        out: dict[str, Any] = {"company": company_section}

        # Optional buyer seed — attach an existing customer as the
        # company's main contact in the same call.
        customer_id = params.get("customer_id") or params.get("customerId")
        if customer_id:
            if not isinstance(customer_id, str):
                raise AdapterValidationError(
                    "shopify_companies",
                    "'customer_id' must be a Shopify GID string",
                )
            out["companyContact"] = {"customerId": customer_id.strip()}

        # Optional location seed — Shopify creates the company's
        # primary location in the same call.
        location = params.get("location")
        if location is not None:
            if not isinstance(location, dict):
                raise AdapterValidationError(
                    "shopify_companies",
                    "'location' must be a dict {name, address}",
                )
            loc_name = location.get("name")
            if not isinstance(loc_name, str) or not loc_name.strip():
                raise AdapterValidationError(
                    "shopify_companies",
                    "'location.name' is required",
                )
            address = (
                location.get("address") or location.get("shipping_address")
            )
            if address is not None and not isinstance(address, dict):
                raise AdapterValidationError(
                    "shopify_companies",
                    "'location.address' must be a dict",
                )
            location_section: dict[str, Any] = {"name": loc_name.strip()}
            if address:
                # Translate snake_case to camelCase for the AddressInput
                # fields. Pass through unmodified for the rest.
                aliases = {
                    "address1": "address1",
                    "address2": "address2",
                    "city": "city",
                    "province": "province",
                    "country": "country",
                    "zip": "zip",
                    "phone": "phone",
                    "first_name": "firstName",
                    "last_name": "lastName",
                    "company": "company",
                }
                addr_out: dict[str, Any] = {}
                for snake, camel in aliases.items():
                    if snake in address:
                        v = address[snake]
                        if v is not None and not isinstance(v, str):
                            raise AdapterValidationError(
                                "shopify_companies",
                                f"'location.address.{snake}' must "
                                f"be a string",
                            )
                        if v:
                            addr_out[camel] = v
                if addr_out:
                    location_section["shippingAddress"] = addr_out
            out["companyLocation"] = location_section

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_company(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        total_spent = node.get("totalSpent") or {}
        try:
            total_spent_amount = float(total_spent.get("amount", 0) or 0)
        except (TypeError, ValueError):
            total_spent_amount = 0.0

        # Main contact — pull the customer detail nested under it.
        main_contact = node.get("mainContact") or {}
        customer = (
            main_contact.get("customer")
            if isinstance(main_contact, dict) else None
        ) or {}

        # Locations — flatten edges → list of dicts.
        locations: list[dict[str, Any]] = []
        loc_envelope = node.get("locations") or {}
        if isinstance(loc_envelope, dict):
            for edge in loc_envelope.get("edges") or []:
                if not isinstance(edge, dict):
                    continue
                loc_node = edge.get("node") or {}
                addr = loc_node.get("shippingAddress") or {}
                locations.append({
                    "id": loc_node.get("id", "") or "",
                    "name": loc_node.get("name", "") or "",
                    "address1": (
                        addr.get("address1", "") if isinstance(addr, dict) else ""
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
                    "zip": (
                        addr.get("zip", "") if isinstance(addr, dict) else ""
                    ) or "",
                })

        # ``ordersCount`` is a Count wrapper object (caught live as
        # 'Field must have selections … returns Count'), so the value
        # lives under ``.count`` rather than being a bare int.
        orders_count_raw = node.get("ordersCount") or {}
        try:
            orders_count = int(
                orders_count_raw.get("count", 0) or 0
                if isinstance(orders_count_raw, dict)
                else (orders_count_raw or 0)
            )
        except (TypeError, ValueError):
            orders_count = 0

        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "note": node.get("note", "") or "",
            "external_id": node.get("externalId", "") or "",
            "orders_count": orders_count,
            "total_spent": total_spent_amount,
            "currency": total_spent.get("currencyCode", "") or "",
            "main_contact_id": (
                main_contact.get("id", "") if isinstance(main_contact, dict) else ""
            ) or "",
            "main_contact_email": (
                customer.get("email", "") if isinstance(customer, dict) else ""
            ) or "",
            "main_contact_name": (
                customer.get("displayName", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "locations": locations,
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
