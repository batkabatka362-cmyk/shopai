"""ShopifySavedSearchesAdapter — saved-search CRUD across resources.

Shopify's admin lets the merchant save a labeled query string against
a specific resource type (customers, products, orders, draft orders,
collections, files, pages, blogs, articles, URL redirects, price
rules, discount-redeem-codes, balance transactions, inventory
transfers). The saved record is reusable: bulk operations target it
by ``savedSearchId``, and the admin shows it as a one-click filter.

ShopAI's segmentation + cleanup engines write these to:

  * Persist a "high-LTV repeat customer" query for use in marketing
    automations and bulk-operation targets.
  * Save a "broken-redirect" filter so Phase 25.4's
    ``urlRedirectBulkDeleteBySavedSearch`` capability can sweep
    them later.
  * Capture a complex draft-order filter the operator built once
    and wants to re-run weekly.

Capabilities:

  * ``SHOPIFY_LIST_SAVED_SEARCHES``   — paginated list scoped to a
    given ``resource_type`` (the schema doesn't expose a unified
    top-level query — there's one per resource type, so the adapter
    dispatches).
  * ``SHOPIFY_CREATE_SAVED_SEARCH``   — savedSearchCreate.
    resourceType + name + query.
  * ``SHOPIFY_UPDATE_SAVED_SEARCH``   — savedSearchUpdate.
    Pattern A (in input): id + name + query.
  * ``SHOPIFY_DELETE_SAVED_SEARCH``   — savedSearchDelete.

Pattern A — every mutation puts its arg inside an ``input`` wrapper
(SavedSearchCreateInput / UpdateInput / DeleteInput).
Pattern F — all three mutations use the bare ``UserError`` type
(no ``code``).
Pattern B — there's no top-level ``Query.savedSearches`` connection;
each resource type has its own (``productSavedSearches``,
``customerSavedSearches``, etc.). The adapter dispatches by
resource_type.

Pattern E note: read scope per resource type (read_customers /
read_products / etc.); write_users is needed to mutate.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_SAVED_SEARCH_FIELDS = """
id
legacyResourceId
name
query
resourceType
searchTerms
""".strip()


# Resource-specific connection names. Keep in sync with
# SearchResultType enum but mapped to the actual connection field.
_RESOURCE_CONNECTIONS: dict[str, str] = {
    "CUSTOMER": "customerSavedSearches",
    "DRAFT_ORDER": "draftOrderSavedSearches",
    "INVENTORY_TRANSFER": "inventoryTransferSavedSearches",
    "PRODUCT": "productSavedSearches",
    "COLLECTION": "collectionSavedSearches",
    "FILE": "fileSavedSearches",
    "ORDER": "orderSavedSearches",
    "URL_REDIRECT": "urlRedirectSavedSearches",
    "DISCOUNT_REDEEM_CODE": "discountRedeemCodeSavedSearches",
    "AUTOMATIC_DISCOUNT": "automaticDiscountSavedSearches",
    "CODE_DISCOUNT": "codeDiscountSavedSearches",
}

_VALID_RESOURCE_TYPES = {
    "CUSTOMER", "DRAFT_ORDER", "INVENTORY_TRANSFER", "PRODUCT",
    "COLLECTION", "FILE", "PAGE", "BLOG", "ARTICLE",
    "URL_REDIRECT", "PRICE_RULE", "DISCOUNT_REDEEM_CODE",
    "ORDER", "BALANCE_TRANSACTION",
}


def _make_list_query(connection_name: str) -> str:
    return f"""
query {connection_name}(
  $first: Int!,
  $after: String,
  $reverse: Boolean
) {{
  {connection_name}(
    first: $first, after: $after, reverse: $reverse
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_SAVED_SEARCH_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_CREATE_MUTATION = f"""
mutation savedSearchCreate(
  $input: SavedSearchCreateInput!
) {{
  savedSearchCreate(input: $input) {{
    savedSearch {{
      {_SAVED_SEARCH_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_UPDATE_MUTATION = f"""
mutation savedSearchUpdate(
  $input: SavedSearchUpdateInput!
) {{
  savedSearchUpdate(input: $input) {{
    savedSearch {{
      {_SAVED_SEARCH_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_DELETE_MUTATION = """
mutation savedSearchDelete($input: SavedSearchDeleteInput!) {
  savedSearchDelete(input: $input) {
    deletedSavedSearchId
    shop {
      id
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


class ShopifySavedSearchesAdapter(ShopifyBaseAdapter):
    name = "shopify_saved_searches"
    capabilities = {
        Capability.SHOPIFY_LIST_SAVED_SEARCHES,
        Capability.SHOPIFY_CREATE_SAVED_SEARCH,
        Capability.SHOPIFY_UPDATE_SAVED_SEARCH,
        Capability.SHOPIFY_DELETE_SAVED_SEARCH,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_SAVED_SEARCHES:
            return self._list(params)
        if capability == Capability.SHOPIFY_CREATE_SAVED_SEARCH:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_SAVED_SEARCH:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_SAVED_SEARCH:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        resource_type = self._normalise_resource_type(
            params.get("resource_type") or params.get("resourceType"),
            require=True,
        )
        connection = _RESOURCE_CONNECTIONS.get(resource_type)
        if connection is None:
            raise AdapterValidationError(
                self.name,
                f"resource_type {resource_type!r} doesn't expose a "
                f"savedSearches connection in the current Shopify "
                f"schema. Supported: "
                f"{sorted(_RESOURCE_CONNECTIONS.keys())}",
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
        reverse = params.get("reverse")

        query = _make_list_query(connection)
        data = self._gql(query, {
            "first": limit,
            "after": cursor,
            "reverse": bool(reverse) if reverse is not None else None,
        })
        envelope = data.get(connection) or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        searches = [
            self._normalise(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_SAVED_SEARCHES,
            data={
                "resource_type": resource_type,
                "saved_searches": searches,
                "count": len(searches),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        resource_type = self._normalise_resource_type(
            params.get("resource_type") or params.get("resourceType"),
            require=True,
        )
        name = params.get("name")
        query = params.get("query")
        if not isinstance(name, str) or not name.strip():
            raise AdapterValidationError(
                self.name,
                "'name' is required (the human-readable label for "
                "the saved search)",
            )
        if not isinstance(query, str) or not query.strip():
            raise AdapterValidationError(
                self.name,
                "'query' is required (the search query string the "
                "saved search persists)",
            )
        body = {
            "resourceType": resource_type,
            "name": name.strip(),
            "query": query.strip(),
        }
        data = self._gql(_CREATE_MUTATION, {"input": body})
        self._check_user_errors(data, "savedSearchCreate")
        payload = data.get("savedSearchCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_SAVED_SEARCH,
            data={
                "saved_search": self._normalise(
                    payload.get("savedSearch") or {},
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        saved_id = self._extract_id(params)
        body: dict[str, Any] = {"id": saved_id}
        name = params.get("name")
        if isinstance(name, str) and name.strip():
            body["name"] = name.strip()
        query = params.get("query")
        if isinstance(query, str) and query.strip():
            body["query"] = query.strip()
        if "name" not in body and "query" not in body:
            raise AdapterValidationError(
                self.name,
                "supply at least one of 'name' / 'query'",
            )
        data = self._gql(_UPDATE_MUTATION, {"input": body})
        self._check_user_errors(data, "savedSearchUpdate")
        payload = data.get("savedSearchUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_SAVED_SEARCH,
            data={
                "saved_search": self._normalise(
                    payload.get("savedSearch") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        saved_id = self._extract_id(params)
        data = self._gql(_DELETE_MUTATION, {
            "input": {"id": saved_id},
        })
        self._check_user_errors(data, "savedSearchDelete")
        payload = data.get("savedSearchDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_SAVED_SEARCH,
            data={
                "deleted_id": (
                    payload.get("deletedSavedSearchId", "") or ""
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _normalise_resource_type(
        self, raw: Any, *, require: bool,
    ) -> str:
        if raw is None:
            if require:
                raise AdapterValidationError(
                    self.name,
                    f"'resource_type' is required (one of "
                    f"{sorted(_VALID_RESOURCE_TYPES)})",
                )
            return ""
        if not isinstance(raw, str):
            raise AdapterValidationError(
                self.name, "'resource_type' must be a string",
            )
        up = raw.strip().upper().replace("-", "_")
        if up not in _VALID_RESOURCE_TYPES:
            raise AdapterValidationError(
                self.name,
                f"'resource_type' must be one of "
                f"{sorted(_VALID_RESOURCE_TYPES)}",
            )
        return up

    def _extract_id(self, params: dict[str, Any]) -> str:
        saved_id = (
            params.get("id")
            or params.get("saved_search_id")
            or params.get("savedSearchId")
        )
        if not isinstance(saved_id, str) or not saved_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the saved search) is required",
            )
        return saved_id.strip()

    @staticmethod
    def _normalise(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        return {
            "id": node.get("id", "") or "",
            "legacy_resource_id": (
                node.get("legacyResourceId", "") or ""
            ),
            "name": node.get("name", "") or "",
            "query": node.get("query", "") or "",
            "resource_type": node.get("resourceType", "") or "",
            "search_terms": node.get("searchTerms", "") or "",
        }
