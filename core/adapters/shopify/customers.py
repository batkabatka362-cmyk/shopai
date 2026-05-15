"""ShopifyCustomersAdapter — customer CRUD + segmentation tags.

Customers are the third pillar of commerce data. ShopAI's
segmentation engine reads them, the marketing engine adds tags
("vip", "ai-recommended", "abandoned-cart"), and the customer-
service engine updates contact info / accept-marketing flags.

The legacy ``SHOPIFY_FETCH_CUSTOMERS`` and ``SHOPIFY_UPDATE_CUSTOMER``
capabilities existed in the enum but had no adapter — this is the
first wired implementation. We add a few additional capabilities
(get, create, tag/untag, delete) to cover the full surface engines
hit.

Capabilities:

  * ``SHOPIFY_FETCH_CUSTOMERS``  — list with pagination/filter.
  * ``SHOPIFY_GET_CUSTOMER``     — single customer with addresses.
  * ``SHOPIFY_CREATE_CUSTOMER``  — create.
  * ``SHOPIFY_UPDATE_CUSTOMER``  — update profile fields.
  * ``SHOPIFY_TAG_CUSTOMER``     — add tags (segmentation).
  * ``SHOPIFY_UNTAG_CUSTOMER``   — remove tags.
  * ``SHOPIFY_DELETE_CUSTOMER``  — GDPR-style delete.

Tags add/remove use the generic ``tagsAdd``/``tagsRemove`` mutations
(same pattern as orders.py), with the Customer union variant
selected via inline fragment.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CUSTOMER_FIELDS = """
id
firstName
lastName
email
phone
note
tags
state
verifiedEmail
numberOfOrders
amountSpent { amount currencyCode }
createdAt
updatedAt
defaultAddress {
  address1
  address2
  city
  province
  country
  zip
}
""".strip()


_CUSTOMER_FIELDS_FULL = f"""
{_CUSTOMER_FIELDS}
addresses {{
  id
  address1
  address2
  city
  province
  country
  zip
  phone
  name
}}
""".strip()


_LIST_CUSTOMERS_QUERY = f"""
query customers(
  $first: Int!,
  $after: String,
  $query: String,
  $sortKey: CustomerSortKeys,
  $reverse: Boolean
) {{
  customers(
    first: $first,
    after: $after,
    query: $query,
    sortKey: $sortKey,
    reverse: $reverse
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_CUSTOMER_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_CUSTOMER_QUERY = f"""
query customer($id: ID!) {{
  customer(id: $id) {{
    {_CUSTOMER_FIELDS_FULL}
  }}
}}
""".strip()


_CREATE_CUSTOMER_MUTATION = f"""
mutation customerCreate($input: CustomerInput!) {{
  customerCreate(input: $input) {{
    customer {{
      {_CUSTOMER_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_CUSTOMER_MUTATION = f"""
mutation customerUpdate($input: CustomerInput!) {{
  customerUpdate(input: $input) {{
    customer {{
      {_CUSTOMER_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_CUSTOMER_MUTATION = """
mutation customerDelete($input: CustomerDeleteInput!) {
  customerDelete(input: $input) {
    deletedCustomerId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_TAGS_ADD_MUTATION = """
mutation tagsAdd($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) {
    node {
      id
      ... on Customer {
        tags
      }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_TAGS_REMOVE_MUTATION = """
mutation tagsRemove($id: ID!, $tags: [String!]!) {
  tagsRemove(id: $id, tags: $tags) {
    node {
      id
      ... on Customer {
        tags
      }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250

_VALID_SORT_KEYS = {
    "CREATED_AT", "UPDATED_AT", "NAME", "ID", "LOCATION",
    "ORDERS_COUNT", "TOTAL_SPENT", "RELEVANCE",
}


class ShopifyCustomersAdapter(ShopifyBaseAdapter):
    name = "shopify_customers"
    capabilities = {
        Capability.SHOPIFY_FETCH_CUSTOMERS,
        Capability.SHOPIFY_GET_CUSTOMER,
        Capability.SHOPIFY_CREATE_CUSTOMER,
        Capability.SHOPIFY_UPDATE_CUSTOMER,
        Capability.SHOPIFY_TAG_CUSTOMER,
        Capability.SHOPIFY_UNTAG_CUSTOMER,
        Capability.SHOPIFY_DELETE_CUSTOMER,
    }
    # read_customers / write_customers cover the whole CRUD +
    # tagging surface. No PII-level escalation needed here —
    # protected-customer-data is its own gate.
    required_scopes = frozenset({"read_customers", "write_customers"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_FETCH_CUSTOMERS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_CUSTOMER:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_CUSTOMER:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_CUSTOMER:
            return self._update(params)
        if capability == Capability.SHOPIFY_TAG_CUSTOMER:
            return self._tag(params, add=True)
        if capability == Capability.SHOPIFY_UNTAG_CUSTOMER:
            return self._tag(params, add=False)
        if capability == Capability.SHOPIFY_DELETE_CUSTOMER:
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

        variables: dict[str, Any] = {"first": limit, "after": cursor}

        query_filter = params.get("query")
        if query_filter is not None:
            if not isinstance(query_filter, str):
                raise AdapterValidationError(
                    self.name, "'query' must be a string",
                )
            variables["query"] = query_filter

        sort_key = params.get("sort_key")
        if sort_key is not None:
            if not isinstance(sort_key, str) or sort_key not in _VALID_SORT_KEYS:
                raise AdapterValidationError(
                    self.name,
                    f"'sort_key' must be one of: {sorted(_VALID_SORT_KEYS)}",
                )
            variables["sortKey"] = sort_key

        reverse = params.get("reverse")
        if reverse is not None:
            variables["reverse"] = bool(reverse)

        data = self._gql(_LIST_CUSTOMERS_QUERY, variables)
        envelope = data.get("customers") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        customers = [
            self._normalise_customer(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_FETCH_CUSTOMERS,
            data={
                "customers": customers,
                "count": len(customers),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        customer_id = params.get("id") or params.get("customer_id")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the customer) is required",
            )
        data = self._gql(_GET_CUSTOMER_QUERY, {"id": customer_id.strip()})
        node = data.get("customer") or {}
        return self._success(
            Capability.SHOPIFY_GET_CUSTOMER,
            data={
                "customer": self._normalise_customer_full(node),
                "found": bool(node),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        customer_input = self._build_customer_input(params, for_update=False)
        data = self._gql(
            _CREATE_CUSTOMER_MUTATION, {"input": customer_input},
        )
        self._check_user_errors(data, "customerCreate")
        payload = data.get("customerCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_CUSTOMER,
            data={
                "customer": self._normalise_customer(
                    payload.get("customer") or {}
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        customer_input = self._build_customer_input(params, for_update=True)
        data = self._gql(
            _UPDATE_CUSTOMER_MUTATION, {"input": customer_input},
        )
        self._check_user_errors(data, "customerUpdate")
        payload = data.get("customerUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_CUSTOMER,
            data={
                "customer": self._normalise_customer(
                    payload.get("customer") or {}
                ),
            },
        )

    # ── Tag / Untag ───────────────────────────────────────────────

    def _tag(self, params: dict[str, Any], add: bool) -> Any:
        customer_id = params.get("id") or params.get("customer_id")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the customer) is required",
            )
        raw_tags = params.get("tags")
        if isinstance(raw_tags, str):
            raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        if not isinstance(raw_tags, list) or not raw_tags or not all(
            isinstance(t, str) for t in raw_tags
        ):
            raise AdapterValidationError(
                self.name,
                "'tags' must be a non-empty list of strings or "
                "comma-separated string",
            )
        mutation = _TAGS_ADD_MUTATION if add else _TAGS_REMOVE_MUTATION
        mutation_name = "tagsAdd" if add else "tagsRemove"
        capability = (
            Capability.SHOPIFY_TAG_CUSTOMER if add
            else Capability.SHOPIFY_UNTAG_CUSTOMER
        )
        data = self._gql(mutation, {
            "id": customer_id.strip(),
            "tags": raw_tags,
        })
        self._check_user_errors(data, mutation_name)
        payload = data.get(mutation_name) or {}
        node = payload.get("node") or {}
        return self._success(
            capability,
            data={
                "id": node.get("id", "") or "",
                "tags": list(node.get("tags") or []),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        customer_id = params.get("id") or params.get("customer_id")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the customer) is required",
            )
        data = self._gql(_DELETE_CUSTOMER_MUTATION, {
            "input": {"id": customer_id.strip()},
        })
        self._check_user_errors(data, "customerDelete")
        payload = data.get("customerDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_CUSTOMER,
            data={
                "deleted_id": payload.get("deletedCustomerId", "") or "",
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_customer_input(
        self, params: dict[str, Any], for_update: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        if for_update:
            customer_id = params.get("id") or params.get("customer_id")
            if not isinstance(customer_id, str) or not customer_id.strip():
                raise AdapterValidationError(
                    self.name,
                    "'id' (Shopify GID for the customer) is required for update",
                )
            out["id"] = customer_id.strip()

        email = params.get("email")
        if email is not None:
            if not isinstance(email, str):
                raise AdapterValidationError(
                    self.name, "'email' must be a string",
                )
            out["email"] = email.strip()

        if not for_update and "email" not in out:
            # Create requires either email or phone for customerCreate.
            if not params.get("phone"):
                raise AdapterValidationError(
                    self.name,
                    "create requires 'email' or 'phone'",
                )

        first_name = params.get("first_name") or params.get("firstName")
        if first_name is not None:
            if not isinstance(first_name, str):
                raise AdapterValidationError(
                    self.name, "'first_name' must be a string",
                )
            out["firstName"] = first_name

        last_name = params.get("last_name") or params.get("lastName")
        if last_name is not None:
            if not isinstance(last_name, str):
                raise AdapterValidationError(
                    self.name, "'last_name' must be a string",
                )
            out["lastName"] = last_name

        phone = params.get("phone")
        if phone is not None:
            if not isinstance(phone, str):
                raise AdapterValidationError(
                    self.name, "'phone' must be a string",
                )
            out["phone"] = phone

        note = params.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    self.name, "'note' must be a string",
                )
            out["note"] = note

        tags = params.get("tags")
        if tags is not None:
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            if not isinstance(tags, list) or not all(
                isinstance(t, str) for t in tags
            ):
                raise AdapterValidationError(
                    self.name,
                    "'tags' must be a string (comma-separated) or list of strings",
                )
            out["tags"] = tags

        # Marketing consent — Shopify split this off into emailMarketingConsent
        # / smsMarketingConsent in 2024-01. ShopAI's friendly form accepts a
        # single bool that maps to email subscription state.
        accepts_email = params.get("accepts_email_marketing")
        if accepts_email is not None:
            out["emailMarketingConsent"] = {
                "marketingState": "SUBSCRIBED" if accepts_email else "UNSUBSCRIBED",
                "marketingOptInLevel": "SINGLE_OPT_IN",
            }

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_customer(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        amount_spent = node.get("amountSpent") or {}
        default_addr = node.get("defaultAddress") or {}
        return {
            "id": node.get("id", "") or "",
            "first_name": node.get("firstName", "") or "",
            "last_name": node.get("lastName", "") or "",
            "email": node.get("email", "") or "",
            "phone": node.get("phone", "") or "",
            "note": node.get("note", "") or "",
            "tags": list(node.get("tags") or []),
            "state": node.get("state", "") or "",
            "verified_email": bool(node.get("verifiedEmail", False)),
            "orders_count": int(node.get("numberOfOrders") or 0),
            "total_spent": (
                amount_spent.get("amount", "")
                if isinstance(amount_spent, dict) else ""
            ) or "",
            "currency_code": (
                amount_spent.get("currencyCode", "")
                if isinstance(amount_spent, dict) else ""
            ) or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
            "default_address": {
                "address1": (
                    default_addr.get("address1", "")
                    if isinstance(default_addr, dict) else ""
                ) or "",
                "address2": (
                    default_addr.get("address2", "")
                    if isinstance(default_addr, dict) else ""
                ) or "",
                "city": (
                    default_addr.get("city", "")
                    if isinstance(default_addr, dict) else ""
                ) or "",
                "province": (
                    default_addr.get("province", "")
                    if isinstance(default_addr, dict) else ""
                ) or "",
                "country": (
                    default_addr.get("country", "")
                    if isinstance(default_addr, dict) else ""
                ) or "",
                "zip": (
                    default_addr.get("zip", "")
                    if isinstance(default_addr, dict) else ""
                ) or "",
            } if default_addr else {},
        }

    @classmethod
    def _normalise_customer_full(
        cls, node: dict[str, Any],
    ) -> dict[str, Any]:
        base = cls._normalise_customer(node)
        if not base:
            return {}
        addresses = node.get("addresses") or []
        base["addresses"] = [
            {
                "id": a.get("id", "") or "",
                "name": a.get("name", "") or "",
                "phone": a.get("phone", "") or "",
                "address1": a.get("address1", "") or "",
                "address2": a.get("address2", "") or "",
                "city": a.get("city", "") or "",
                "province": a.get("province", "") or "",
                "country": a.get("country", "") or "",
                "zip": a.get("zip", "") or "",
            }
            for a in addresses if isinstance(a, dict)
        ]
        return base
