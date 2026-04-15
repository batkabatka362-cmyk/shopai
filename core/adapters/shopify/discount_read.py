"""ShopifyDiscountReadAdapter — list existing discount codes.

Complements the write-only ``ShopifyDiscountAdapter`` by
providing read access to the merchant's discount catalog. The
merchandising agent uses this to audit active promotions before
creating a new one (avoid stacking 15% on top of 20%), and the
finance agent uses it to report on promotional spend.

READ-ONLY. Creation + deletion live in ``ShopifyDiscountAdapter``
and a future ``ShopifyDiscountDeleteAdapter``.

Params shape::

    {
        "query":   "status:active",       # Shopify search DSL, optional
        "first":   50,                    # page size (1..250)
        "after":   "cursor...",           # pagination cursor
    }

Returns::

    {
        "discounts":  [
            {
                "id":             "gid://shopify/DiscountCodeNode/123",
                "code":           "SAVE15",
                "title":          "Spring Sale",
                "status":         "active",
                "starts_at":      "2026-04-01T00:00:00Z",
                "ends_at":        "2026-04-30T23:59:59Z",
                "usage_limit":    100,
                "applies_once_per_customer": True,
                "async_usage_count": 37,
                "summary":        "15% off",
            },
            ...
        ],
        "page_info":  {"has_next_page": bool, "end_cursor": str},
        "count":      int,
    }
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# Only DiscountCodeBasic is listed — other node types
# (DiscountCodeBxgy, DiscountCodeFreeShipping, DiscountCodeApp)
# carry much richer / idiosyncratic payloads. A dedicated
# adapter for the other shapes can ship later without
# breaking consumers of this one.
_LIST_DISCOUNTS_QUERY = """
query ListDiscounts($first: Int!, $after: String, $query: String) {
  codeDiscountNodes(first: $first, after: $after, query: $query, sortKey: UPDATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    edges {
      cursor
      node {
        id
        codeDiscount {
          __typename
          ... on DiscountCodeBasic {
            title
            status
            startsAt
            endsAt
            usageLimit
            appliesOncePerCustomer
            asyncUsageCount
            summary
            codes(first: 1) {
              edges { node { code } }
            }
          }
          ... on DiscountCodeBxgy {
            title
            status
            startsAt
            endsAt
            usageLimit
            asyncUsageCount
            summary
            codes(first: 1) { edges { node { code } } }
          }
          ... on DiscountCodeFreeShipping {
            title
            status
            startsAt
            endsAt
            usageLimit
            appliesOncePerCustomer
            asyncUsageCount
            summary
            codes(first: 1) { edges { node { code } } }
          }
        }
      }
    }
  }
}
""".strip()


class ShopifyDiscountReadAdapter(ShopifyBaseAdapter):
    """Paginated read of Shopify discount codes."""

    name = "shopify_discount_read"
    capabilities = {Capability.SHOPIFY_LIST_DISCOUNTS}

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_LIST_DISCOUNTS:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

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

        query = str(params.get("query") or "").strip() or None
        after = params.get("after")

        variables = {
            "first": first,
            "after": after or None,
            "query": query,
        }

        data = self._gql(_LIST_DISCOUNTS_QUERY, variables)
        block = data.get("codeDiscountNodes") or {}
        edges = block.get("edges") or []
        page_info = block.get("pageInfo") or {}

        out: list[dict[str, Any]] = []
        for edge in edges:
            node = edge.get("node") or {}
            cd = node.get("codeDiscount") or {}
            # Extract the (first) code attached to the node. Every
            # code node has at least one code in practice, but
            # guard defensively so a malformed payload can't
            # crash the whole list.
            code_edges = (cd.get("codes") or {}).get("edges") or []
            code_str = ""
            if code_edges:
                code_str = (
                    (code_edges[0].get("node") or {}).get("code") or ""
                )

            out.append({
                "id": node.get("id", "") or "",
                "code": code_str,
                "title": cd.get("title", "") or "",
                "type": (cd.get("__typename", "") or "").lower(),
                "status": (cd.get("status", "") or "").lower(),
                "starts_at": cd.get("startsAt", "") or "",
                "ends_at": cd.get("endsAt", "") or "",
                "usage_limit": cd.get("usageLimit"),
                "applies_once_per_customer": bool(
                    cd.get("appliesOncePerCustomer", False),
                ),
                "async_usage_count": int(cd.get("asyncUsageCount", 0) or 0),
                "summary": cd.get("summary", "") or "",
                "cursor": edge.get("cursor", "") or "",
            })

        return self._success(
            Capability.SHOPIFY_LIST_DISCOUNTS,
            data={
                "discounts": out,
                "count": len(out),
                "page_info": {
                    "has_next_page": bool(page_info.get("hasNextPage")),
                    "end_cursor": page_info.get("endCursor", "") or "",
                },
            },
        )
