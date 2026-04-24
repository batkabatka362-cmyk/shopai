"""Shopify shop + store-wide settings.

Bundles resources that describe the store itself (rather
than its contents):

  * ``Shop``              — ``shop.json`` (get), shop
                            metafields (list / create / update
                            / delete)
  * ``AccessScopes``      — introspection of the scopes the
                            current admin token carries
  * ``Locales``           — installed / available languages
                            + publish / unpublish (GraphQL)
  * ``Currencies``        — enabled presentment currencies
                            (GraphQL ``currencySettings``)

Shop metafields are owner-config surface: brand voice,
seo defaults, return-policy URLs, the kind of thing every
downstream engine reads when composing content. Access
scopes answers "can I actually call this endpoint?" —
useful before the brain escalates a write path.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger("shopai.shopify_admin.shop")


class Shop:
    """Store-level resource — one record per shop."""

    @staticmethod
    def get(client: ShopifyAdminClient) -> dict[str, Any]:
        """GET ``shop.json``. Returns the canonical shop
        record: name, email, domain, timezone, currency,
        country, plan, etc."""
        result = client.get("shop.json")
        shop = result.get("shop")
        if not isinstance(shop, dict):
            raise ShopifyAdminError(
                "shop not returned", path="shop.json",
            )
        return shop

    # ── Shop-level metafields ─────────────────────────

    @staticmethod
    def list_metafields(
        client: ShopifyAdminClient,
        *,
        namespace: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if namespace:
            params["namespace"] = str(namespace)
        result = client.get("metafields.json", params=params)
        rows = result.get("metafields") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def create_metafield(
        client: ShopifyAdminClient,
        *,
        namespace: str,
        key: str,
        value: str,
        value_type: str = "single_line_text_field",
    ) -> dict[str, Any]:
        if not namespace or not key:
            raise ValueError("namespace + key required")
        body = {
            "metafield": {
                "namespace": namespace,
                "key": key,
                "value": value,
                "type": value_type,
            },
        }
        result = client.post("metafields.json", body)
        mf = result.get("metafield")
        if not isinstance(mf, dict):
            raise ShopifyAdminError(
                "metafield not returned by create",
                path="metafields.json",
                body=str(result),
            )
        return mf

    @staticmethod
    def update_metafield(
        client: ShopifyAdminClient,
        metafield_id: int | str,
        *,
        value: str,
        value_type: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "metafield": {
                "id": int(metafield_id),
                "value": value,
            },
        }
        if value_type:
            body["metafield"]["type"] = value_type
        result = client.put(
            f"metafields/{metafield_id}.json", body,
        )
        mf = result.get("metafield")
        if not isinstance(mf, dict):
            raise ShopifyAdminError(
                "metafield not returned by update",
                path=f"metafields/{metafield_id}.json",
            )
        return mf

    @staticmethod
    def delete_metafield(
        client: ShopifyAdminClient,
        metafield_id: int | str,
    ) -> None:
        client.delete(f"metafields/{metafield_id}.json")


class AccessScopes:
    """Inspection of the current admin token's scopes.
    Used before write flows to fail fast when the token is
    under-scoped (better UX than a 403 from the real call)."""

    @staticmethod
    def list_scopes(
        client: ShopifyAdminClient,
    ) -> list[str]:
        # The ``/oauth/access_scopes.json`` endpoint lives
        # under ``/admin/`` directly, not ``/admin/api/{ver}/``.
        # We reuse the same send plumbing but override the path
        # by sending through GraphQL's currentAppInstallation
        # query instead — the REST alternative requires a
        # different host prefix the client doesn't support.
        query = """
        query currentScopes {
          currentAppInstallation {
            accessScopes { handle }
          }
        }
        """
        result = client.graphql(query)
        install = (
            (result.get("data") or {}).get(
                "currentAppInstallation",
            ) or {}
        )
        scopes = install.get("accessScopes") or []
        return [
            str(s.get("handle") or "")
            for s in scopes
            if isinstance(s, dict) and s.get("handle")
        ]

    @staticmethod
    def has_scope(
        client: ShopifyAdminClient, handle: str,
    ) -> bool:
        """True iff the current token carries ``handle``
        (e.g. ``"write_products"``)."""
        if not handle:
            return False
        return str(handle).strip() in AccessScopes.list_scopes(
            client,
        )


_LOCALES_QUERY = """
query listLocales {
  shopLocales {
    locale
    primary
    published
    name
  }
}
"""


_LOCALE_ENABLE = """
mutation shopLocaleEnable($locale: String!) {
  shopLocaleEnable(locale: $locale) {
    shopLocale { locale published primary }
    userErrors { field message }
  }
}
"""


_LOCALE_DISABLE = """
mutation shopLocaleDisable($locale: String!) {
  shopLocaleDisable(locale: $locale) {
    locale
    userErrors { field message }
  }
}
"""


_LOCALE_PUBLISH = """
mutation shopLocaleUpdate($locale: String!, $shopLocale: ShopLocaleInput!) {
  shopLocaleUpdate(locale: $locale, shopLocale: $shopLocale) {
    shopLocale { locale published }
    userErrors { field message }
  }
}
"""


def _check_user_errors(payload: dict[str, Any], key: str) -> None:
    errors = (payload.get(key) or {}).get("userErrors") or []
    if errors:
        msgs = "; ".join(
            f"{e.get('field')}: {e.get('message')}"
            for e in errors if isinstance(e, dict)
        )
        raise ShopifyAdminError(
            f"{key} userErrors: {msgs}",
            path="graphql.json",
            body=str(payload),
        )


class Locales:
    """Installed shop locales (i18n). GraphQL-only surface."""

    @staticmethod
    def list_locales(
        client: ShopifyAdminClient,
    ) -> list[dict[str, Any]]:
        result = client.graphql(_LOCALES_QUERY)
        rows = (result.get("data") or {}).get(
            "shopLocales",
        ) or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def enable(
        client: ShopifyAdminClient, locale: str,
    ) -> dict[str, Any]:
        if not locale:
            raise ValueError("locale: required (e.g. 'de')")
        result = client.graphql(
            _LOCALE_ENABLE,
            variables={"locale": str(locale)},
        )
        payload = result.get("data") or {}
        _check_user_errors(payload, "shopLocaleEnable")
        sl = (
            payload.get("shopLocaleEnable") or {}
        ).get("shopLocale")
        if not isinstance(sl, dict):
            raise ShopifyAdminError(
                "shopLocaleEnable: shopLocale missing",
                path="graphql.json",
            )
        return sl

    @staticmethod
    def disable(
        client: ShopifyAdminClient, locale: str,
    ) -> str:
        """Returns the deleted locale handle."""
        if not locale:
            raise ValueError("locale: required")
        result = client.graphql(
            _LOCALE_DISABLE,
            variables={"locale": str(locale)},
        )
        payload = result.get("data") or {}
        _check_user_errors(payload, "shopLocaleDisable")
        out = (
            payload.get("shopLocaleDisable") or {}
        ).get("locale")
        if not out:
            raise ShopifyAdminError(
                "shopLocaleDisable: locale missing",
                path="graphql.json",
            )
        return str(out)

    @staticmethod
    def set_published(
        client: ShopifyAdminClient,
        locale: str,
        *,
        published: bool,
    ) -> dict[str, Any]:
        """Publish (visible on storefront) or unpublish
        a locale. The locale must already be enabled."""
        if not locale:
            raise ValueError("locale: required")
        result = client.graphql(
            _LOCALE_PUBLISH,
            variables={
                "locale": str(locale),
                "shopLocale": {"published": bool(published)},
            },
        )
        payload = result.get("data") or {}
        _check_user_errors(payload, "shopLocaleUpdate")
        sl = (
            payload.get("shopLocaleUpdate") or {}
        ).get("shopLocale")
        if not isinstance(sl, dict):
            raise ShopifyAdminError(
                "shopLocaleUpdate: shopLocale missing",
                path="graphql.json",
            )
        return sl


_CURRENCY_QUERY = """
query currencySettings {
  shop {
    currencyCode
    enabledPresentmentCurrencies
    currencyFormats {
      moneyFormat
      moneyWithCurrencyFormat
    }
  }
}
"""


_CURRENCY_ENABLE = """
mutation currencyEnable($currencies: [CurrencyCode!]!) {
  currencyActivate(currencies: $currencies) {
    currencySettings {
      currencyCode
      enabled
    }
    userErrors { field message }
  }
}
"""


_CURRENCY_DISABLE = """
mutation currencyDisable($currencies: [CurrencyCode!]!) {
  currencyDeactivate(currencies: $currencies) {
    currencySettings {
      currencyCode
      enabled
    }
    userErrors { field message }
  }
}
"""


class Currencies:
    """Store-level presentment currencies.

    Shopify Markets (wave 4c) handles per-market currency
    overrides; this resource manages the global list of
    currencies the storefront is allowed to display."""

    @staticmethod
    def get_settings(
        client: ShopifyAdminClient,
    ) -> dict[str, Any]:
        result = client.graphql(_CURRENCY_QUERY)
        shop = (result.get("data") or {}).get("shop") or {}
        return {
            "base": str(shop.get("currencyCode") or ""),
            "enabled_presentment": [
                str(c)
                for c in (
                    shop.get(
                        "enabledPresentmentCurrencies",
                    ) or ()
                )
                if c
            ],
            "money_format": str(
                (shop.get("currencyFormats") or {}).get(
                    "moneyFormat",
                ) or "",
            ),
            "money_with_currency_format": str(
                (shop.get("currencyFormats") or {}).get(
                    "moneyWithCurrencyFormat",
                ) or "",
            ),
        }

    @staticmethod
    def enable(
        client: ShopifyAdminClient,
        currencies: list[str],
    ) -> list[dict[str, Any]]:
        if not currencies:
            raise ValueError(
                "currencies: non-empty list required",
            )
        upper = [c.upper() for c in currencies if c]
        result = client.graphql(
            _CURRENCY_ENABLE,
            variables={"currencies": upper},
        )
        payload = result.get("data") or {}
        _check_user_errors(payload, "currencyActivate")
        settings = (
            payload.get("currencyActivate") or {}
        ).get("currencySettings") or []
        return [s for s in settings if isinstance(s, dict)]

    @staticmethod
    def disable(
        client: ShopifyAdminClient,
        currencies: list[str],
    ) -> list[dict[str, Any]]:
        if not currencies:
            raise ValueError(
                "currencies: non-empty list required",
            )
        upper = [c.upper() for c in currencies if c]
        result = client.graphql(
            _CURRENCY_DISABLE,
            variables={"currencies": upper},
        )
        payload = result.get("data") or {}
        _check_user_errors(payload, "currencyDeactivate")
        settings = (
            payload.get("currencyDeactivate") or {}
        ).get("currencySettings") or []
        return [s for s in settings if isinstance(s, dict)]
