"""ShopifyPriceListAdapter — B2B / market-tiered price lists.

A price list is a per-customer-segment override of catalog pricing
(B2B "tier 1 wholesale" gets 30% off; "France market" sees prices
in EUR with a +10% markup). ShopAI's B2B engine + the
international-pricing engine read these to:

  * Quote the right price in cart preview when the customer is
    associated with a company / market.
  * Trigger a "price list refresh" when global product prices
    change (recompute the percentage markups).
  * Surface "this product is missing a price in the EUR list"
    diagnostics for catalog completeness.

Capabilities (read + create + delete; full per-product price-list
PRICE management uses the dedicated priceListFixedPricesAdd
mutation which lives in a separate sub-surface — out of scope for
this adapter):

  * ``SHOPIFY_LIST_PRICE_LISTS``    — paginated list with filter.
  * ``SHOPIFY_GET_PRICE_LIST``      — single price list with
    catalog + parent + adjustment detail.
  * ``SHOPIFY_CREATE_PRICE_LIST``   — create a new list with
    currency + parent (the global catalog) + adjustment rule.
  * ``SHOPIFY_DELETE_PRICE_LIST``   — delete.

Friendly call shape::

    {"name":          "Wholesale Tier 1",
     "currency_code": "USD",
     "catalog_id":    "gid://shopify/CompanyLocationCatalog/123",
     "parent": {
        "adjustment": {
          "type":  "PERCENTAGE_DECREASE",  # or PERCENTAGE_INCREASE
          "value": 30.0
        }}}

Pattern E note: gated by ``read_price_lists`` /
``write_price_lists`` scopes. Some price-list flavours additionally
require Plus tier (the catalog-attached B2B variant in particular).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_PRICE_LIST_FIELDS = """
id
name
currency
parent {
  settings {
    compareAtMode
  }
  adjustment {
    type
    value
  }
}
catalog {
  id
  title
  status
}
fixedPricesCount
""".strip()


_LIST_PRICE_LISTS_QUERY = f"""
query priceLists($first: Int!, $after: String) {{
  priceLists(first: $first, after: $after) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_PRICE_LIST_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_PRICE_LIST_QUERY = f"""
query priceList($id: ID!) {{
  priceList(id: $id) {{
    {_PRICE_LIST_FIELDS}
  }}
}}
""".strip()


_CREATE_PRICE_LIST_MUTATION = f"""
mutation priceListCreate($input: PriceListCreateInput!) {{
  priceListCreate(input: $input) {{
    priceList {{
      {_PRICE_LIST_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_PRICE_LIST_MUTATION = """
mutation priceListDelete($id: ID!) {
  priceListDelete(id: $id) {
    deletedId
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

_VALID_ADJUSTMENT_TYPES = {
    "PERCENTAGE_DECREASE", "PERCENTAGE_INCREASE",
}

_VALID_COMPARE_AT_MODES = {"NULLIFY", "ADJUSTED"}


class ShopifyPriceListAdapter(ShopifyBaseAdapter):
    name = "shopify_price_lists"
    capabilities = {
        Capability.SHOPIFY_LIST_PRICE_LISTS,
        Capability.SHOPIFY_GET_PRICE_LIST,
        Capability.SHOPIFY_CREATE_PRICE_LIST,
        Capability.SHOPIFY_DELETE_PRICE_LIST,
    }
    required_scopes = frozenset({"read_products", "write_products"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_PRICE_LISTS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_PRICE_LIST:
            return self._get(params)
        if capability == Capability.SHOPIFY_CREATE_PRICE_LIST:
            return self._create(params)
        if capability == Capability.SHOPIFY_DELETE_PRICE_LIST:
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

        # Pattern D: priceLists connection does NOT accept a query
        # filter argument (unlike most connections). Engines that pass
        # query for consistency get it silently dropped.
        variables: dict[str, Any] = {"first": limit, "after": cursor}

        data = self._gql(_LIST_PRICE_LISTS_QUERY, variables)
        envelope = data.get("priceLists") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        price_lists = [
            self._normalise_price_list(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_PRICE_LISTS,
            data={
                "price_lists": price_lists,
                "count": len(price_lists),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        list_id = params.get("id") or params.get("price_list_id")
        if not isinstance(list_id, str) or not list_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the price list) is required",
            )
        data = self._gql(_GET_PRICE_LIST_QUERY, {"id": list_id.strip()})
        node = data.get("priceList") or {}
        return self._success(
            Capability.SHOPIFY_GET_PRICE_LIST,
            data={
                "price_list": self._normalise_price_list(node),
                "found": bool(node),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        list_input = self._build_create_input(params)
        data = self._gql(_CREATE_PRICE_LIST_MUTATION, {"input": list_input})
        self._check_user_errors(data, "priceListCreate")
        payload = data.get("priceListCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_PRICE_LIST,
            data={
                "price_list": self._normalise_price_list(
                    payload.get("priceList") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        list_id = params.get("id") or params.get("price_list_id")
        if not isinstance(list_id, str) or not list_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the price list) is required",
            )
        data = self._gql(_DELETE_PRICE_LIST_MUTATION, {"id": list_id.strip()})
        self._check_user_errors(data, "priceListDelete")
        payload = data.get("priceListDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_PRICE_LIST,
            data={
                "deleted_id": payload.get("deletedId", "") or "",
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_create_input(self, params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}

        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AdapterValidationError(
                self.name, "'name' is required",
            )
        out["name"] = name.strip()

        currency = params.get("currency_code") or params.get("currency")
        if not isinstance(currency, str) or not currency.strip():
            raise AdapterValidationError(
                self.name,
                "'currency_code' is required (ISO-4217 e.g. 'USD')",
            )
        out["currency"] = currency.strip().upper()

        catalog_id = params.get("catalog_id") or params.get("catalogId")
        if catalog_id is not None:
            if not isinstance(catalog_id, str):
                raise AdapterValidationError(
                    self.name, "'catalog_id' must be a string GID",
                )
            out["catalogId"] = catalog_id.strip()

        # Parent (the global catalog rule the list overrides) is
        # required by Shopify for every price list. The "type" /
        # "value" pair is what the marketing engine actually sets.
        parent = params.get("parent")
        if not isinstance(parent, dict):
            raise AdapterValidationError(
                self.name,
                "'parent' is required and must be a dict with "
                "'adjustment' (and optional 'settings')",
            )

        adjustment = parent.get("adjustment")
        if not isinstance(adjustment, dict):
            raise AdapterValidationError(
                self.name,
                "'parent.adjustment' is required (type + value)",
            )

        adj_type = adjustment.get("type")
        if not isinstance(adj_type, str) or adj_type.upper() not in _VALID_ADJUSTMENT_TYPES:
            raise AdapterValidationError(
                self.name,
                f"'parent.adjustment.type' must be one of: "
                f"{sorted(_VALID_ADJUSTMENT_TYPES)}",
            )

        adj_value = adjustment.get("value")
        if adj_value is None:
            raise AdapterValidationError(
                self.name,
                "'parent.adjustment.value' is required (a percentage)",
            )
        try:
            adj_value_float = float(adj_value)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name,
                "'parent.adjustment.value' must be numeric",
            ) from exc

        parent_input: dict[str, Any] = {
            "adjustment": {
                "type": adj_type.upper(),
                "value": adj_value_float,
            },
        }

        settings = parent.get("settings")
        if settings is not None:
            if not isinstance(settings, dict):
                raise AdapterValidationError(
                    self.name, "'parent.settings' must be a dict",
                )
            compare_at_mode = settings.get("compare_at_mode") or settings.get(
                "compareAtMode"
            )
            if compare_at_mode is not None:
                if (
                    not isinstance(compare_at_mode, str)
                    or compare_at_mode.upper() not in _VALID_COMPARE_AT_MODES
                ):
                    raise AdapterValidationError(
                        self.name,
                        f"'parent.settings.compare_at_mode' must be one of: "
                        f"{sorted(_VALID_COMPARE_AT_MODES)}",
                    )
                parent_input["settings"] = {
                    "compareAtMode": compare_at_mode.upper(),
                }

        out["parent"] = parent_input
        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_price_list(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        parent = node.get("parent") or {}
        adjustment = (
            parent.get("adjustment", {}) if isinstance(parent, dict) else {}
        ) or {}
        settings = (
            parent.get("settings", {}) if isinstance(parent, dict) else {}
        ) or {}
        catalog = node.get("catalog") or {}

        # fixedPricesCount may be Count wrapper (Pattern D) or scalar.
        count_raw = node.get("fixedPricesCount", 0)
        if isinstance(count_raw, dict):
            count_raw = count_raw.get("count", 0)
        try:
            fixed_prices_count = int(count_raw or 0)
        except (TypeError, ValueError):
            fixed_prices_count = 0

        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "currency_code": node.get("currency", "") or "",
            "adjustment_type": (
                adjustment.get("type", "")
                if isinstance(adjustment, dict) else ""
            ) or "",
            "adjustment_value": float(
                (adjustment.get("value") or 0)
                if isinstance(adjustment, dict) else 0
            ),
            "compare_at_mode": (
                settings.get("compareAtMode", "")
                if isinstance(settings, dict) else ""
            ) or "",
            "catalog_id": (
                catalog.get("id", "") if isinstance(catalog, dict) else ""
            ) or "",
            "catalog_title": (
                catalog.get("title", "")
                if isinstance(catalog, dict) else ""
            ) or "",
            "catalog_status": (
                catalog.get("status", "")
                if isinstance(catalog, dict) else ""
            ) or "",
            "fixed_prices_count": fixed_prices_count,
        }
