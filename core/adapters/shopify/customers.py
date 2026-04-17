"""ShopifyCustomersAdapter — paginated customer read.

Fills the ``SHOPIFY_FETCH_CUSTOMERS`` gap in the adapter catalog
(Option D). Needed by the churn-risk agent, the VIP targeting
flow, and any dunning sweep that needs to identify recent
repeat buyers.

READ-ONLY. Customer mutations (update tags, add metafield)
belong to ``ShopifyMetafieldAdapter`` or a future
``ShopifyCustomerMutateAdapter``.

Params shape::

    {
        "query":   "tag:vip email:*@acme.com",  # Shopify search DSL
        "first":   50,
        "after":   "cursor...",
        "include_addresses": False,
    }

Returns::

    {
        "customers":  [...],
        "page_info":  {"has_next_page": bool, "end_cursor": str},
        "count":      int,
    }
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


_CUSTOMERS_QUERY = """
query FetchCustomers(
    $first: Int!,
    $after: String,
    $query: String,
    $includeAddresses: Boolean!
) {
  customers(first: $first, after: $after, query: $query, sortKey: UPDATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    edges {
      cursor
      node {
        id
        displayName
        firstName
        lastName
        email
        phone
        createdAt
        updatedAt
        numberOfOrders
        amountSpent { amount currencyCode }
        state
        tags
        verifiedEmail
        note
        defaultAddress @include(if: $includeAddresses) {
          id
          address1
          address2
          city
          province
          provinceCode
          country
          countryCodeV2
          zip
          phone
        }
      }
    }
  }
}
""".strip()


class ShopifyCustomersAdapter(ShopifyBaseAdapter):
    """Read paginated customers from Shopify Admin."""

    name = "shopify_customers"
    capabilities = {Capability.SHOPIFY_FETCH_CUSTOMERS}

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_FETCH_CUSTOMERS:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        query = str(params.get("query") or "").strip() or None

        try:
            first = int(params.get("first", 50))
        except (TypeError, ValueError):
            raise AdapterValidationError(
                self.name, "'first' must be an integer",
            )
        if first <= 0 or first > 250:
            raise AdapterValidationError(
                self.name, "'first' must be in 1..250 (Shopify cap)",
            )

        after = params.get("after")
        include_addresses = bool(params.get("include_addresses", False))

        variables = {
            "first": first,
            "after": after or None,
            "query": query,
            "includeAddresses": include_addresses,
        }

        data = self._gql(_CUSTOMERS_QUERY, variables)
        block = data.get("customers") or {}
        edges = block.get("edges") or []
        page_info = block.get("pageInfo") or {}

        out: list[dict[str, Any]] = []
        for edge in edges:
            node = edge.get("node") or {}
            amount = node.get("amountSpent") or {}
            row: dict[str, Any] = {
                "id": node.get("id", ""),
                "display_name": node.get("displayName", "") or "",
                "first_name": node.get("firstName", "") or "",
                "last_name": node.get("lastName", "") or "",
                "email": node.get("email", "") or "",
                "phone": node.get("phone", "") or "",
                "created_at": node.get("createdAt", "") or "",
                "updated_at": node.get("updatedAt", "") or "",
                "orders_count": int(node.get("numberOfOrders", 0) or 0),
                "total_spent": amount.get("amount", "0"),
                "currency": amount.get("currencyCode", ""),
                "state": (node.get("state", "") or "").lower(),
                "tags": list(node.get("tags") or []),
                "verified_email": bool(node.get("verifiedEmail", False)),
                "note": node.get("note", "") or "",
                "cursor": edge.get("cursor", ""),
            }
            if include_addresses:
                addr = node.get("defaultAddress") or {}
                row["default_address"] = {
                    "id": addr.get("id", ""),
                    "address1": addr.get("address1", "") or "",
                    "address2": addr.get("address2", "") or "",
                    "city": addr.get("city", "") or "",
                    "province": addr.get("province", "") or "",
                    "province_code": addr.get("provinceCode", "") or "",
                    "country": addr.get("country", "") or "",
                    "country_code": addr.get("countryCodeV2", "") or "",
                    "zip": addr.get("zip", "") or "",
                    "phone": addr.get("phone", "") or "",
                } if addr else {}
            out.append(row)

        return self._success(
            Capability.SHOPIFY_FETCH_CUSTOMERS,
            data={
                "customers": out,
                "count": len(out),
                "page_info": {
                    "has_next_page": bool(page_info.get("hasNextPage")),
                    "end_cursor": page_info.get("endCursor", "") or "",
                },
            },
        )
