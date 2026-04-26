"""ShopifyShopLocalesAdapter — storefront language WRITE surface.

A Shopify shop publishes its storefront in one or more LOCALES (one
primary + N alternates). Each locale gets its own translated copy of
products / collections / pages / theme strings. ShopAI's
internationalization engine writes these whenever:

  * The merchant unlocks a new market and needs a matching locale
    (e.g. "we just opened DE.example.com — enable de").
  * A locale is being retired because the market closed; disable
    keeps the translations on file but stops surfacing them on the
    storefront.
  * The market-presences-↔-locale binding changes mid-rollout
    (update the published flag or the marketWebPresenceIds list).

Companion to ``markets.py`` (which already exposes
``SHOPIFY_LIST_SHOP_LOCALES`` as a flat read), ``translations.py``
(which writes the actual translated content per resource), and
``market_web_presences.py`` (which scopes locales to specific market
storefronts).

Capabilities:

  * ``SHOPIFY_LIST_AVAILABLE_LOCALES`` — Shopify's full catalogue of
    supported locale codes (read-only, no args). Used to populate
    a "what locales can we add?" picker in the operator UI.
  * ``SHOPIFY_ENABLE_SHOP_LOCALE``     — shopLocaleEnable. locale
    code at field level + optional list of marketWebPresenceIds to
    activate the locale on.
  * ``SHOPIFY_DISABLE_SHOP_LOCALE``    — shopLocaleDisable. Removes
    the locale from the shop (translations preserved).
  * ``SHOPIFY_UPDATE_SHOP_LOCALE``     — shopLocaleUpdate. Flips the
    published flag and/or rewires marketWebPresenceIds.

Pattern A: locale code at field level for all three mutations.
Pattern F: all three mutations use the bare ``UserError`` type
(no ``code`` — confirmed via introspection).

Pattern E note: ``shopLocales`` query needs ``read_locales`` /
``read_markets_home`` scope; mutations need ``write_locales``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_LOCALE_FIELDS = """
locale
name
primary
published
""".strip()


_AVAILABLE_LOCALES_QUERY = """
query availableLocales {
  availableLocales {
    isoCode
    name
  }
}
""".strip()


_ENABLE_MUTATION = f"""
mutation shopLocaleEnable(
  $locale: String!,
  $marketWebPresenceIds: [ID!]
) {{
  shopLocaleEnable(
    locale: $locale,
    marketWebPresenceIds: $marketWebPresenceIds
  ) {{
    shopLocale {{
      {_LOCALE_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_DISABLE_MUTATION = """
mutation shopLocaleDisable($locale: String!) {
  shopLocaleDisable(locale: $locale) {
    locale
    userErrors {
      field
      message
    }
  }
}
""".strip()


_UPDATE_MUTATION = f"""
mutation shopLocaleUpdate(
  $locale: String!,
  $shopLocale: ShopLocaleInput!
) {{
  shopLocaleUpdate(locale: $locale, shopLocale: $shopLocale) {{
    shopLocale {{
      {_LOCALE_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


class ShopifyShopLocalesAdapter(ShopifyBaseAdapter):
    name = "shopify_shop_locales"
    capabilities = {
        Capability.SHOPIFY_LIST_AVAILABLE_LOCALES,
        Capability.SHOPIFY_ENABLE_SHOP_LOCALE,
        Capability.SHOPIFY_DISABLE_SHOP_LOCALE,
        Capability.SHOPIFY_UPDATE_SHOP_LOCALE,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_AVAILABLE_LOCALES:
            return self._list_available_locales(params)
        if capability == Capability.SHOPIFY_ENABLE_SHOP_LOCALE:
            return self._enable(params)
        if capability == Capability.SHOPIFY_DISABLE_SHOP_LOCALE:
            return self._disable(params)
        if capability == Capability.SHOPIFY_UPDATE_SHOP_LOCALE:
            return self._update(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List available locales ─────────────────────────────────────

    def _list_available_locales(self, params: dict[str, Any]) -> Any:
        data = self._gql(_AVAILABLE_LOCALES_QUERY, {})
        nodes = data.get("availableLocales") or []
        locales = []
        for n in nodes:
            if not isinstance(n, dict):
                continue
            locales.append({
                "iso_code": n.get("isoCode", "") or "",
                "name": n.get("name", "") or "",
            })
        return self._success(
            Capability.SHOPIFY_LIST_AVAILABLE_LOCALES,
            data={
                "locales": locales,
                "count": len(locales),
            },
        )

    # ── Enable ─────────────────────────────────────────────────────

    def _enable(self, params: dict[str, Any]) -> Any:
        locale = self._extract_locale(params)
        market_ids = self._build_market_ids(params)
        variables: dict[str, Any] = {
            "locale": locale,
            "marketWebPresenceIds": market_ids,
        }
        data = self._gql(_ENABLE_MUTATION, variables)
        self._check_user_errors(data, "shopLocaleEnable")
        payload = data.get("shopLocaleEnable") or {}
        return self._success(
            Capability.SHOPIFY_ENABLE_SHOP_LOCALE,
            data={
                "locale": self._normalise_shop_locale(
                    payload.get("shopLocale") or {},
                ),
            },
        )

    # ── Disable ────────────────────────────────────────────────────

    def _disable(self, params: dict[str, Any]) -> Any:
        locale = self._extract_locale(params)
        data = self._gql(_DISABLE_MUTATION, {"locale": locale})
        self._check_user_errors(data, "shopLocaleDisable")
        payload = data.get("shopLocaleDisable") or {}
        return self._success(
            Capability.SHOPIFY_DISABLE_SHOP_LOCALE,
            data={
                "disabled_locale":
                    payload.get("locale", "") or locale,
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        locale = self._extract_locale(params)
        body: dict[str, Any] = {}
        if "published" in params and params["published"] is not None:
            body["published"] = bool(params["published"])
        market_ids = self._build_market_ids(params)
        if market_ids is not None:
            body["marketWebPresenceIds"] = market_ids
        if not body:
            raise AdapterValidationError(
                self.name,
                "supply at least one of 'published' / "
                "'market_web_presence_ids'",
            )
        data = self._gql(_UPDATE_MUTATION, {
            "locale": locale, "shopLocale": body,
        })
        self._check_user_errors(data, "shopLocaleUpdate")
        payload = data.get("shopLocaleUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_SHOP_LOCALE,
            data={
                "locale": self._normalise_shop_locale(
                    payload.get("shopLocale") or {},
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_locale(self, params: dict[str, Any]) -> str:
        locale = (
            params.get("locale")
            or params.get("locale_code")
            or params.get("isoCode")
            or params.get("iso_code")
        )
        if not isinstance(locale, str) or not locale.strip():
            raise AdapterValidationError(
                self.name,
                "'locale' is required (ISO 639-1 code, e.g. 'de' / "
                "'fr-CA' / 'es')",
            )
        # Shopify stores locales as lower-case-region (de, fr-CA);
        # normalise to that form rather than fully upper.
        cleaned = locale.strip()
        # Standardise to lower-language[-UPPER-region].
        if "-" in cleaned:
            lang, _, region = cleaned.partition("-")
            cleaned = f"{lang.lower()}-{region.upper()}"
        else:
            cleaned = cleaned.lower()
        return cleaned

    def _build_market_ids(
        self, params: dict[str, Any],
    ) -> list[str] | None:
        raw = (
            params.get("market_web_presence_ids")
            or params.get("marketWebPresenceIds")
        )
        if raw is None:
            return None
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list) or not all(
            isinstance(v, str) for v in raw
        ):
            raise AdapterValidationError(
                self.name,
                "'market_web_presence_ids' must be a list of "
                "MarketWebPresence GIDs",
            )
        cleaned = [v.strip() for v in raw if v.strip()]
        return cleaned or None

    @staticmethod
    def _normalise_shop_locale(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        return {
            "locale": node.get("locale", "") or "",
            "name": node.get("name", "") or "",
            "primary": bool(node.get("primary", False)),
            "published": bool(node.get("published", False)),
        }
