"""ShopifyMarketsAdapter — read markets and shop locales.

Markets and locales are read-only inputs to two ShopAI engines:

  * **Translation engine.** Before AI-translating product copy the
    engine asks: "what locales does the shop actually serve?" If
    the shop only sells in English + Spanish there's no point
    spending tokens to generate French translations. List-shop-
    locales answers that.

  * **Pricing / margin engine.** Per-market pricing rules
    (different currencies, regional taxes, market-specific
    shipping zones) feed the per-market margin calculation. The
    engine reads markets to know what regional configurations
    exist before applying its rules.

Capabilities (read-only):

  * ``SHOPIFY_LIST_MARKETS``       — paginate markets configured
    for the shop, with their primary regions, currencies, and
    enabled status.
  * ``SHOPIFY_GET_MARKET``         — fetch one market with full
    region / currency / web-presence detail.
  * ``SHOPIFY_LIST_SHOP_LOCALES``  — flat list of enabled
    storefront locales (Translation engine's primary input).

Market mutations (create / update / delete) are intentionally NOT
in this adapter. Markets are merchant-configured one-time setup;
engines that want to spin up new markets autonomously are an
expansion play that needs explicit operator approval, not a
runtime engine call.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_MARKET_NODE_FIELDS = """
id
name
handle
enabled
primary
currencySettings {
  baseCurrency {
    currencyCode
    currencyName
  }
}
regions(first: 50) {
  edges {
    node {
      id
      name
      ... on MarketRegionCountry {
        code
      }
    }
  }
}
""".strip()


_LIST_MARKETS_QUERY = f"""
query markets($first: Int!, $after: String) {{
  markets(first: $first, after: $after) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_MARKET_NODE_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_MARKET_QUERY = f"""
query market($id: ID!) {{
  market(id: $id) {{
    {_MARKET_NODE_FIELDS}
  }}
}}
""".strip()


_LIST_SHOP_LOCALES_QUERY = """
query shopLocales {
  shopLocales {
    locale
    name
    primary
    published
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyMarketsAdapter(ShopifyBaseAdapter):
    name = "shopify_markets"
    capabilities = {
        Capability.SHOPIFY_LIST_MARKETS,
        Capability.SHOPIFY_GET_MARKET,
        Capability.SHOPIFY_LIST_SHOP_LOCALES,
    }
    required_scopes = frozenset({"read_markets", "write_markets"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_MARKETS:
            return self._list_markets(params)
        if capability == Capability.SHOPIFY_GET_MARKET:
            return self._get_market(params)
        if capability == Capability.SHOPIFY_LIST_SHOP_LOCALES:
            return self._list_shop_locales(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List markets ──────────────────────────────────────────────

    def _list_markets(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                "shopify_markets", "'cursor' must be a string or None",
            )

        data = self._gql(_LIST_MARKETS_QUERY, {
            "first": limit, "after": cursor,
        })
        envelope = data.get("markets") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        markets = [
            self._normalise_market(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_MARKETS,
            data={
                "markets": markets,
                "count": len(markets),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get market ────────────────────────────────────────────────

    def _get_market(self, params: dict[str, Any]) -> Any:
        market_id = params.get("id") or params.get("market_id")
        if not isinstance(market_id, str) or not market_id.strip():
            raise AdapterValidationError(
                "shopify_markets",
                "'id' (Shopify GID for the market) is required",
            )
        data = self._gql(_GET_MARKET_QUERY, {"id": market_id.strip()})
        node = data.get("market")
        if not isinstance(node, dict):
            return self._success(
                Capability.SHOPIFY_GET_MARKET,
                data={"found": False, "market": None},
            )
        return self._success(
            Capability.SHOPIFY_GET_MARKET,
            data={"found": True,
                  "market": self._normalise_market(node)},
        )

    # ── List shop locales ─────────────────────────────────────────

    def _list_shop_locales(self, _params: dict[str, Any]) -> Any:
        # ``shopLocales`` is a top-level list, not a connection — no
        # pagination, just the full set every time. Cheap query.
        data = self._gql(_LIST_SHOP_LOCALES_QUERY, {})
        raw = data.get("shopLocales") or []
        if not isinstance(raw, list):
            raw = []
        locales: list[dict[str, Any]] = []
        for loc in raw:
            if not isinstance(loc, dict):
                continue
            locales.append({
                "locale": loc.get("locale", "") or "",
                "name": loc.get("name", "") or "",
                "primary": bool(loc.get("primary", False)),
                "published": bool(loc.get("published", False)),
            })
        return self._success(
            Capability.SHOPIFY_LIST_SHOP_LOCALES,
            data={
                "locales": locales,
                "count": len(locales),
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_market(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        currency_settings = node.get("currencySettings") or {}
        base = (
            currency_settings.get("baseCurrency")
            if isinstance(currency_settings, dict) else None
        ) or {}
        regions_raw = (node.get("regions") or {}).get("edges") or []
        regions: list[dict[str, str]] = []
        for edge in regions_raw:
            if not isinstance(edge, dict):
                continue
            r = edge.get("node") or {}
            regions.append({
                "id": r.get("id", "") or "",
                "name": r.get("name", "") or "",
                "country_code": r.get("code", "") or "",
            })
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "handle": node.get("handle", "") or "",
            "enabled": bool(node.get("enabled", False)),
            "primary": bool(node.get("primary", False)),
            "currency_code": base.get("currencyCode", "") or "",
            "currency_name": base.get("currencyName", "") or "",
            "regions": regions,
        }
