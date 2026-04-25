"""ShopifyCollectionsAdapter — product collections CRUD.

Collections are merchant-defined groupings of products: "Summer
Sale", "New Arrivals", "Bundle Deals", "By Brand: Acme". They drive
storefront navigation, ad-campaign landing pages, and the catalog
engine's auto-merchandising rules.

Two flavours:

  * **Manual collections** — explicit product list (the merchant or
    the catalog engine adds/removes products one at a time).
  * **Smart (rule-based) collections** — Shopify auto-populates the
    product list based on rules ("price > $50", "tag = sale").

This adapter handles both via the unified ``Collection`` GraphQL
type. ShopAI's catalog engine writes seasonal collections; the SEO
engine reads collections to generate landing-page content.

Capabilities:

  * ``SHOPIFY_LIST_COLLECTIONS``    — paginated list with filter/sort.
  * ``SHOPIFY_GET_COLLECTION``      — single collection with first
    100 products.
  * ``SHOPIFY_CREATE_COLLECTION``   — create manual or smart.
  * ``SHOPIFY_UPDATE_COLLECTION``   — update title / description /
    rules / sort order.
  * ``SHOPIFY_DELETE_COLLECTION``   — delete.

Friendly call shapes::

    create manual::
      {"title":      "Summer Sale 2026",
       "description_html": "<p>Up to 50% off.</p>",
       "is_published": True,
       "products": [
         "gid://shopify/Product/1",
         "gid://shopify/Product/2",
       ]}

    create smart::
      {"title":      "Sale Items",
       "rule_set": {
         "applied_disjunctively": False,
         "rules": [
           {"column": "TAG", "relation": "EQUALS", "condition": "sale"},
           {"column": "VARIANT_PRICE", "relation": "GREATER_THAN",
            "condition": "10"},
         ]}}

Pattern A note: products are managed via separate
``collectionAddProductsV2`` / ``collectionRemoveProducts`` mutations
on existing collections; the create mutation also accepts a
``products`` array which the adapter converts behind the scenes.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_COLLECTION_FIELDS = """
id
title
handle
description
descriptionHtml
templateSuffix
sortOrder
updatedAt
productsCount {
  count
}
ruleSet {
  appliedDisjunctively
  rules {
    column
    relation
    condition
  }
}
""".strip()


_COLLECTION_FIELDS_WITH_PRODUCTS = f"""
{_COLLECTION_FIELDS}
products(first: 100) {{
  pageInfo {{
    hasNextPage
    endCursor
  }}
  edges {{
    node {{
      id
      title
      handle
      status
    }}
  }}
}}
""".strip()


_LIST_COLLECTIONS_QUERY = f"""
query collections(
  $first: Int!,
  $after: String,
  $query: String,
  $sortKey: CollectionSortKeys,
  $reverse: Boolean
) {{
  collections(
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
        {_COLLECTION_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_COLLECTION_QUERY = f"""
query collection($id: ID!) {{
  collection(id: $id) {{
    {_COLLECTION_FIELDS_WITH_PRODUCTS}
  }}
}}
""".strip()


_CREATE_COLLECTION_MUTATION = f"""
mutation collectionCreate($input: CollectionInput!) {{
  collectionCreate(input: $input) {{
    collection {{
      {_COLLECTION_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_COLLECTION_MUTATION = f"""
mutation collectionUpdate($input: CollectionInput!) {{
  collectionUpdate(input: $input) {{
    collection {{
      {_COLLECTION_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_COLLECTION_MUTATION = """
mutation collectionDelete($input: CollectionDeleteInput!) {
  collectionDelete(input: $input) {
    deletedCollectionId
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

_VALID_SORT_KEYS = {
    "TITLE", "UPDATED_AT", "ID", "RELEVANCE",
}

_VALID_COLLECTION_SORT_ORDERS = {
    "MANUAL", "BEST_SELLING", "ALPHA_ASC", "ALPHA_DESC",
    "PRICE_DESC", "PRICE_ASC", "CREATED", "CREATED_DESC",
}

_VALID_RULE_COLUMNS = {
    "TAG", "TITLE", "TYPE", "VENDOR",
    "VARIANT_PRICE", "VARIANT_COMPARE_AT_PRICE", "VARIANT_WEIGHT",
    "VARIANT_INVENTORY", "VARIANT_TITLE", "PRODUCT_METAFIELD_DEFINITION",
    "VARIANT_METAFIELD_DEFINITION", "IS_PRICE_REDUCED",
}

_VALID_RULE_RELATIONS = {
    "EQUALS", "NOT_EQUALS", "GREATER_THAN", "LESS_THAN",
    "STARTS_WITH", "ENDS_WITH", "CONTAINS", "NOT_CONTAINS",
    "IS_SET", "IS_NOT_SET",
}


class ShopifyCollectionsAdapter(ShopifyBaseAdapter):
    name = "shopify_collections"
    capabilities = {
        Capability.SHOPIFY_LIST_COLLECTIONS,
        Capability.SHOPIFY_GET_COLLECTION,
        Capability.SHOPIFY_CREATE_COLLECTION,
        Capability.SHOPIFY_UPDATE_COLLECTION,
        Capability.SHOPIFY_DELETE_COLLECTION,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_COLLECTIONS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_COLLECTION:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_COLLECTION:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_COLLECTION:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_COLLECTION:
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

        data = self._gql(_LIST_COLLECTIONS_QUERY, variables)
        envelope = data.get("collections") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        collections = [
            self._normalise_collection(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_COLLECTIONS,
            data={
                "collections": collections,
                "count": len(collections),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        collection_id = params.get("id") or params.get("collection_id")
        if not isinstance(collection_id, str) or not collection_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the collection) is required",
            )
        data = self._gql(_GET_COLLECTION_QUERY, {"id": collection_id.strip()})
        node = data.get("collection") or {}
        return self._success(
            Capability.SHOPIFY_GET_COLLECTION,
            data={
                "collection": self._normalise_collection_with_products(node),
                "found": bool(node),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        collection_input = self._build_collection_input(
            params, for_update=False,
        )
        data = self._gql(_CREATE_COLLECTION_MUTATION, {
            "input": collection_input,
        })
        self._check_user_errors(data, "collectionCreate")
        payload = data.get("collectionCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_COLLECTION,
            data={
                "collection": self._normalise_collection(
                    payload.get("collection") or {},
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        collection_input = self._build_collection_input(
            params, for_update=True,
        )
        data = self._gql(_UPDATE_COLLECTION_MUTATION, {
            "input": collection_input,
        })
        self._check_user_errors(data, "collectionUpdate")
        payload = data.get("collectionUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_COLLECTION,
            data={
                "collection": self._normalise_collection(
                    payload.get("collection") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        collection_id = params.get("id") or params.get("collection_id")
        if not isinstance(collection_id, str) or not collection_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the collection) is required",
            )
        data = self._gql(_DELETE_COLLECTION_MUTATION, {
            "input": {"id": collection_id.strip()},
        })
        self._check_user_errors(data, "collectionDelete")
        payload = data.get("collectionDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_COLLECTION,
            data={
                "deleted_id": payload.get("deletedCollectionId", "") or "",
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_collection_input(
        self, params: dict[str, Any], for_update: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        if for_update:
            collection_id = params.get("id") or params.get("collection_id")
            if not isinstance(collection_id, str) or not collection_id.strip():
                raise AdapterValidationError(
                    self.name,
                    "'id' (Shopify GID) is required for update",
                )
            out["id"] = collection_id.strip()

        title = params.get("title")
        if title is not None:
            if not isinstance(title, str):
                raise AdapterValidationError(
                    self.name, "'title' must be a string",
                )
            if title.strip():
                out["title"] = title.strip()

        if not for_update and "title" not in out:
            raise AdapterValidationError(
                self.name, "'title' is required to create a collection",
            )

        description = params.get("description_html") or params.get("description")
        if description is not None:
            if not isinstance(description, str):
                raise AdapterValidationError(
                    self.name, "'description_html' must be a string",
                )
            out["descriptionHtml"] = description

        handle = params.get("handle")
        if handle is not None:
            if not isinstance(handle, str):
                raise AdapterValidationError(
                    self.name, "'handle' must be a string",
                )
            out["handle"] = handle.strip()

        template_suffix = params.get("template_suffix") or params.get(
            "templateSuffix"
        )
        if template_suffix is not None:
            if not isinstance(template_suffix, str):
                raise AdapterValidationError(
                    self.name, "'template_suffix' must be a string",
                )
            out["templateSuffix"] = template_suffix

        sort_order = params.get("sort_order") or params.get("sortOrder")
        if sort_order is not None:
            if not isinstance(sort_order, str) or sort_order.upper() not in (
                _VALID_COLLECTION_SORT_ORDERS
            ):
                raise AdapterValidationError(
                    self.name,
                    f"'sort_order' must be one of: "
                    f"{sorted(_VALID_COLLECTION_SORT_ORDERS)}",
                )
            out["sortOrder"] = sort_order.upper()

        rule_set = params.get("rule_set") or params.get("ruleSet")
        if rule_set is not None:
            out["ruleSet"] = self._build_rule_set(rule_set)

        # Manual collection: products list
        products = params.get("products")
        if products is not None:
            if not isinstance(products, list) or not all(
                isinstance(p, str) for p in products
            ):
                raise AdapterValidationError(
                    self.name,
                    "'products' must be a list of Shopify product GIDs",
                )
            out["products"] = [p.strip() for p in products if p.strip()]

        return out

    def _build_rule_set(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'rule_set' must be a dict with 'applied_disjunctively' "
                "and 'rules'",
            )
        rules_raw = raw.get("rules")
        if not isinstance(rules_raw, list) or not rules_raw:
            raise AdapterValidationError(
                self.name,
                "'rule_set.rules' must be a non-empty list",
            )
        out_rules: list[dict[str, Any]] = []
        for i, rule in enumerate(rules_raw):
            if not isinstance(rule, dict):
                raise AdapterValidationError(
                    self.name, f"rule_set.rules[{i}] must be a dict",
                )
            column = rule.get("column")
            if not isinstance(column, str) or column not in _VALID_RULE_COLUMNS:
                raise AdapterValidationError(
                    self.name,
                    f"rule_set.rules[{i}].column must be one of: "
                    f"{sorted(_VALID_RULE_COLUMNS)}",
                )
            relation = rule.get("relation")
            if not isinstance(relation, str) or relation not in _VALID_RULE_RELATIONS:
                raise AdapterValidationError(
                    self.name,
                    f"rule_set.rules[{i}].relation must be one of: "
                    f"{sorted(_VALID_RULE_RELATIONS)}",
                )
            condition = rule.get("condition")
            if condition is None:
                raise AdapterValidationError(
                    self.name,
                    f"rule_set.rules[{i}].condition is required",
                )
            condition_str = str(condition)
            out_rules.append({
                "column": column,
                "relation": relation,
                "condition": condition_str,
            })
        applied_disjunctively = raw.get(
            "applied_disjunctively",
            raw.get("appliedDisjunctively", False),
        )
        return {
            "appliedDisjunctively": bool(applied_disjunctively),
            "rules": out_rules,
        }

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _extract_count(value: Any) -> int:
        """Pattern D: ``Collection.productsCount`` returns a Count
        wrapper ``{count: N}`` in 2024-01+ but may legacy-return a
        scalar in some versions. Tolerate both forms."""
        if isinstance(value, dict):
            value = value.get("count", 0)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _normalise_rule_set(node: Any) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        rules_raw = node.get("rules") or []
        return {
            "applied_disjunctively": bool(
                node.get("appliedDisjunctively", False),
            ),
            "rules": [
                {
                    "column": r.get("column", "") or "",
                    "relation": r.get("relation", "") or "",
                    "condition": r.get("condition", "") or "",
                }
                for r in rules_raw if isinstance(r, dict)
            ],
        }

    @classmethod
    def _normalise_collection(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        rule_set = cls._normalise_rule_set(node.get("ruleSet"))
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "handle": node.get("handle", "") or "",
            "description": node.get("description", "") or "",
            "description_html": node.get("descriptionHtml", "") or "",
            "template_suffix": node.get("templateSuffix", "") or "",
            "sort_order": node.get("sortOrder", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
            "products_count": cls._extract_count(node.get("productsCount")),
            "is_smart": bool(rule_set),
            "rule_set": rule_set,
        }

    @classmethod
    def _normalise_collection_with_products(
        cls, node: dict[str, Any],
    ) -> dict[str, Any]:
        base = cls._normalise_collection(node)
        if not base:
            return {}
        product_edges = (node.get("products") or {}).get("edges") or []
        base["products"] = [
            {
                "id": (e.get("node") or {}).get("id", "") or "",
                "title": (e.get("node") or {}).get("title", "") or "",
                "handle": (e.get("node") or {}).get("handle", "") or "",
                "status": (e.get("node") or {}).get("status", "") or "",
            }
            for e in product_edges if isinstance(e, dict)
        ]
        page_info = (node.get("products") or {}).get("pageInfo") or {}
        base["products_has_next_page"] = bool(
            page_info.get("hasNextPage", False),
        )
        base["products_end_cursor"] = page_info.get("endCursor", "") or ""
        return base
