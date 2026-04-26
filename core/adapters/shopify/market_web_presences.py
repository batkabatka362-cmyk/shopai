"""ShopifyMarketWebPresencesAdapter — locale-domain mappings per market.

Companion to ``markets.py`` (which lists Markets and shop locales).
A MarketWebPresence binds a Market to its public-facing presence:
which subdomain/subfolder, which locales (alternates), and which
default locale visitors land on.

ShopAI's international + SEO engines read these to:

  * Generate hreflang tags pointing at the right locale-domain
    pair (a US visitor on .com → en-us; a French visitor on /fr →
    fr-fr).
  * Build per-market sitemap URLs the search-console engine submits.
  * Detect missing presences ("you have a France market but no
    web presence — visitors get the default storefront language").

Capabilities (read-only — managing presences is a merchant decision
that affects the entire storefront URL structure; out of scope for
autonomous default):

  * ``SHOPIFY_LIST_MARKET_WEB_PRESENCES`` — flatten across all
    markets to give the SEO engine a single iterable.
  * ``SHOPIFY_GET_MARKET_WEB_PRESENCE``   — single presence by GID.

Pattern A note: there's no top-level ``Query.marketWebPresences``
connection — the adapter walks ``markets`` and pulls each market's
``webPresence`` sub-field. Same shape as fulfillment_services
(which walks ``shop.fulfillmentServices``).

Pattern E note: gated by ``read_markets`` scope.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_PRESENCE_FIELDS = """
id
defaultLocale {
  locale
  name
  primary
  published
}
alternateLocales {
  locale
  name
  primary
  published
}
subfolderSuffix
domain {
  id
  host
  url
  sslEnabled
}
rootUrls {
  locale
  url
}
""".strip()


_LIST_MARKETS_WITH_PRESENCES_QUERY = f"""
query marketWebPresences($first: Int!, $after: String) {{
  markets(first: $first, after: $after) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        id
        name
        primary
        enabled
        webPresence {{
          {_PRESENCE_FIELDS}
        }}
      }}
    }}
  }}
}}
""".strip()


_GET_PRESENCE_QUERY = f"""
query marketWebPresence($id: ID!) {{
  node(id: $id) {{
    ... on MarketWebPresence {{
      {_PRESENCE_FIELDS}
      market {{
        id
        name
        primary
        enabled
      }}
    }}
  }}
}}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyMarketWebPresencesAdapter(ShopifyBaseAdapter):
    name = "shopify_market_web_presences"
    capabilities = {
        Capability.SHOPIFY_LIST_MARKET_WEB_PRESENCES,
        Capability.SHOPIFY_GET_MARKET_WEB_PRESENCE,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_MARKET_WEB_PRESENCES:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_MARKET_WEB_PRESENCE:
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

        data = self._gql(_LIST_MARKETS_WITH_PRESENCES_QUERY, {
            "first": limit, "after": cursor,
        })
        envelope = data.get("markets") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []

        presences: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            market_node = edge.get("node") or {}
            presence = market_node.get("webPresence")
            if not isinstance(presence, dict) or not presence:
                # Markets without a configured web presence — engines
                # may want to know about them for the "missing
                # presence" diagnostic. Return a stub with
                # has_presence=False so callers don't have to inspect
                # for None.
                presences.append({
                    "market_id": market_node.get("id", "") or "",
                    "market_name": market_node.get("name", "") or "",
                    "market_primary": bool(market_node.get("primary", False)),
                    "market_enabled": bool(market_node.get("enabled", False)),
                    "has_presence": False,
                })
                continue
            normalised = self._normalise_presence(presence)
            normalised.update({
                "market_id": market_node.get("id", "") or "",
                "market_name": market_node.get("name", "") or "",
                "market_primary": bool(market_node.get("primary", False)),
                "market_enabled": bool(market_node.get("enabled", False)),
                "has_presence": True,
            })
            presences.append(normalised)

        return self._success(
            Capability.SHOPIFY_LIST_MARKET_WEB_PRESENCES,
            data={
                "presences": presences,
                "count": len(presences),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        presence_id = params.get("id") or params.get("presence_id")
        if not isinstance(presence_id, str) or not presence_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the market web presence) is required",
            )
        data = self._gql(_GET_PRESENCE_QUERY, {"id": presence_id.strip()})
        node = data.get("node") or {}
        normalised = self._normalise_presence(node) if node else {}
        if normalised:
            market = node.get("market") or {}
            normalised.update({
                "market_id": (
                    market.get("id", "")
                    if isinstance(market, dict) else ""
                ) or "",
                "market_name": (
                    market.get("name", "")
                    if isinstance(market, dict) else ""
                ) or "",
                "market_primary": bool(
                    market.get("primary", False)
                    if isinstance(market, dict) else False
                ),
                "market_enabled": bool(
                    market.get("enabled", False)
                    if isinstance(market, dict) else False
                ),
                "has_presence": True,
            })
        return self._success(
            Capability.SHOPIFY_GET_MARKET_WEB_PRESENCE,
            data={
                "presence": normalised,
                "found": bool(node),
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_presence(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        domain = node.get("domain") or {}
        root_urls_raw = node.get("rootUrls") or []
        root_urls = [
            {
                "locale": r.get("locale", "") or "",
                "url": r.get("url", "") or "",
            }
            for r in root_urls_raw if isinstance(r, dict)
        ]

        # Pattern D: defaultLocale + alternateLocales are ShopLocale
        # objects in 2024-01 (not bare strings). Extract the .locale
        # code so engines see flat strings like "en" / "fr".
        default_locale_raw = node.get("defaultLocale")
        if isinstance(default_locale_raw, dict):
            default_locale_code = default_locale_raw.get("locale", "") or ""
        else:
            default_locale_code = default_locale_raw or ""

        alt_locales_raw = node.get("alternateLocales") or []
        alternate_locales = []
        for loc in alt_locales_raw:
            if isinstance(loc, dict):
                alternate_locales.append(loc.get("locale", "") or "")
            elif isinstance(loc, str):
                alternate_locales.append(loc)

        return {
            "id": node.get("id", "") or "",
            "default_locale": default_locale_code,
            "alternate_locales": alternate_locales,
            "subfolder_suffix": node.get("subfolderSuffix", "") or "",
            "domain_id": (
                domain.get("id", "") if isinstance(domain, dict) else ""
            ) or "",
            "domain_host": (
                domain.get("host", "") if isinstance(domain, dict) else ""
            ) or "",
            "domain_url": (
                domain.get("url", "") if isinstance(domain, dict) else ""
            ) or "",
            "domain_ssl_enabled": bool(
                domain.get("sslEnabled", False)
                if isinstance(domain, dict) else False
            ),
            "root_urls": root_urls,
        }
