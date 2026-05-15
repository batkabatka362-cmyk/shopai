"""ShopifyCatalogsAdapter — B2B catalog tier discovery.

Companion to ``price_lists.py`` (which manages B2B price lists)
and ``companies.py`` (which manages B2B company customers).
A Catalog binds a price list + a publication to a "context" — a
specific company location, market, or app — so different
B2B tiers see different prices and product availability.

ShopAI's B2B engine reads catalogs to:

  * Map a company-location GID to its catalog (and from there,
    the price list to use in cart preview).
  * Surface "this market has no published catalog" diagnostics
    when an internationalization rollout is incomplete.
  * Audit the catalog → price-list binding when the pricing engine
    rebuilds tier rules.

Capabilities (read-only — catalogs are merchant-administered via
the admin UI; engines just need to discover them):

  * ``SHOPIFY_LIST_CATALOGS`` — paginated list with optional type
    filter (COMPANY_LOCATION / MARKET / APP).
  * ``SHOPIFY_GET_CATALOG``   — single catalog with full price
    list + publication detail.

Pattern E note: gated by ``read_products`` scope (catalogs are
discoverable to any app with read access; the bind-to-price-list
write surface needs ``write_publications`` + ``write_price_lists``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CATALOG_FIELDS = """
__typename
id
title
status
priceList {
  id
  name
  currency
}
publication {
  id
  catalog {
    id
  }
}
""".strip()


_LIST_CATALOGS_QUERY = f"""
query catalogs(
  $first: Int!,
  $after: String,
  $type: CatalogType,
  $query: String
) {{
  catalogs(first: $first, after: $after, type: $type, query: $query) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_CATALOG_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_CATALOG_QUERY = f"""
query catalog($id: ID!) {{
  catalog(id: $id) {{
    {_CATALOG_FIELDS}
  }}
}}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250

_VALID_TYPES = {"COMPANY_LOCATION", "MARKET", "APP"}


class ShopifyCatalogsAdapter(ShopifyBaseAdapter):
    name = "shopify_catalogs"
    capabilities = {
        Capability.SHOPIFY_LIST_CATALOGS,
        Capability.SHOPIFY_GET_CATALOG,
    }
    # B2B catalog reads — same scope pair as price-list reads.
    required_scopes = frozenset({"read_products"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_CATALOGS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_CATALOG:
            return self._get(params)
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

        type_filter = params.get("type")
        if type_filter is not None:
            if (
                not isinstance(type_filter, str)
                or type_filter.upper() not in _VALID_TYPES
            ):
                raise AdapterValidationError(
                    self.name,
                    f"'type' must be one of: {sorted(_VALID_TYPES)}",
                )
            variables["type"] = type_filter.upper()

        query_filter = params.get("query")
        if query_filter is not None:
            if not isinstance(query_filter, str):
                raise AdapterValidationError(
                    self.name, "'query' must be a string",
                )
            variables["query"] = query_filter

        data = self._gql(_LIST_CATALOGS_QUERY, variables)
        envelope = data.get("catalogs") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        catalogs = [
            self._normalise_catalog(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_CATALOGS,
            data={
                "catalogs": catalogs,
                "count": len(catalogs),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        catalog_id = params.get("id") or params.get("catalog_id")
        if not isinstance(catalog_id, str) or not catalog_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the catalog) is required",
            )
        data = self._gql(_GET_CATALOG_QUERY, {"id": catalog_id.strip()})
        node = data.get("catalog") or {}
        return self._success(
            Capability.SHOPIFY_GET_CATALOG,
            data={
                "catalog": self._normalise_catalog(node),
                "found": bool(node),
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_catalog(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        # The Catalog type is a union: AppCatalog / MarketCatalog /
        # CompanyLocationCatalog. The __typename discriminates.
        kind = node.get("__typename", "") or ""
        # Map typename → friendly catalog_type.
        catalog_type = ""
        if kind == "CompanyLocationCatalog":
            catalog_type = "COMPANY_LOCATION"
        elif kind == "MarketCatalog":
            catalog_type = "MARKET"
        elif kind == "AppCatalog":
            catalog_type = "APP"

        price_list = node.get("priceList") or {}
        publication = node.get("publication") or {}
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "status": node.get("status", "") or "",
            "type": catalog_type,
            "kind": kind,
            "price_list_id": (
                price_list.get("id", "")
                if isinstance(price_list, dict) else ""
            ) or "",
            "price_list_name": (
                price_list.get("name", "")
                if isinstance(price_list, dict) else ""
            ) or "",
            "currency_code": (
                price_list.get("currency", "")
                if isinstance(price_list, dict) else ""
            ) or "",
            "publication_id": (
                publication.get("id", "")
                if isinstance(publication, dict) else ""
            ) or "",
        }
