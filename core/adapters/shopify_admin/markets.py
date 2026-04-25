"""Shopify Markets — international expansion via GraphQL.

Shopify Markets is the 2023+ replacement for the legacy
multi-region setup. Each Market defines:

  * ``regions``         — set of countries the market serves
  * ``currencySettings`` — local currency + rounding
  * ``webPresence``     — subdomain / subfolder / domain
    mapping + default locale
  * ``enabled``         — whether the market is live

Only exposed via GraphQL (Admin REST doesn't cover Markets).
Wave 4c closes the international gap the audit doc flagged
— before this, Deguar could only sell to the "Primary
market" (whatever country the store was set up in). With
Markets, owner can say "also sell to EU with local prices
in EUR and a German checkout" via one API call.

Key mutations:
  * ``marketCreate``       — add a new market
  * ``marketUpdate``       — change name / enabled / regions
  * ``marketDelete``       — remove (primary market is immune)
  * ``marketWebPresenceCreate`` — subdomain / subfolder mapping
  * ``marketCurrencySettingsUpdate`` — currency + rounding

Queries:
  * ``markets`` — list all
  * ``market`` — get by id
  * ``primaryMarket`` — read the non-deletable primary

Docs: https://shopify.dev/docs/api/admin-graphql/latest/queries/markets
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger("shopai.shopify_admin.markets")


_LIST_QUERY = """
query listMarkets($first: Int!) {
  markets(first: $first) {
    edges {
      node {
        id
        name
        handle
        enabled
        primary
        regions(first: 250) {
          edges { node { ... on MarketRegionCountry { code name } } }
        }
        webPresence {
          id
          defaultLocale
          subfolderSuffix
          domain { id host }
        }
      }
    }
  }
}
"""


_GET_QUERY = """
query getMarket($id: ID!) {
  market(id: $id) {
    id
    name
    handle
    enabled
    primary
    regions(first: 250) {
      edges { node { ... on MarketRegionCountry { code name } } }
    }
    webPresence {
      id
      defaultLocale
      subfolderSuffix
      domain { id host }
    }
    currencySettings {
      baseCurrency { currencyCode }
      localCurrencies
    }
  }
}
"""


_CREATE_MUTATION = """
mutation marketCreate($input: MarketCreateInput!) {
  marketCreate(input: $input) {
    market { id name handle enabled }
    userErrors { field message }
  }
}
"""


_UPDATE_MUTATION = """
mutation marketUpdate($id: ID!, $input: MarketUpdateInput!) {
  marketUpdate(id: $id, input: $input) {
    market { id name handle enabled }
    userErrors { field message }
  }
}
"""


_DELETE_MUTATION = """
mutation marketDelete($id: ID!) {
  marketDelete(id: $id) {
    deletedId
    userErrors { field message }
  }
}
"""


_WEB_PRESENCE_CREATE = """
mutation webPresenceCreate(
  $marketId: ID!, $input: MarketWebPresenceCreateInput!
) {
  marketWebPresenceCreate(marketId: $marketId, webPresence: $input) {
    market { id webPresence { id subfolderSuffix defaultLocale } }
    userErrors { field message }
  }
}
"""


_CURRENCY_UPDATE = """
mutation currencyUpdate(
  $marketId: ID!, $input: MarketCurrencySettingsUpdateInput!
) {
  marketCurrencySettingsUpdate(marketId: $marketId, input: $input) {
    market { id currencySettings { baseCurrency { currencyCode } localCurrencies } }
    userErrors { field message }
  }
}
"""


def _check_user_errors(
    payload: dict[str, Any],
    mutation: str,
) -> None:
    errors = (payload.get(mutation) or {}).get("userErrors") or []
    if errors:
        msgs = "; ".join(
            f"{e.get('field')}: {e.get('message')}"
            for e in errors if isinstance(e, dict)
        )
        raise ShopifyAdminError(
            f"{mutation} userErrors: {msgs}",
            path="graphql.json",
            body=str(payload),
        )


def _market_gid(market_id: int | str) -> str:
    """Accept either a bare numeric id or a full GID.
    GraphQL mutations require the GID form."""
    s = str(market_id).strip()
    if s.startswith("gid://"):
        return s
    return f"gid://shopify/Market/{s}"


class Markets:
    """International market CRUD. All methods take a
    ``ShopifyAdminClient`` and invoke GraphQL."""

    @staticmethod
    def list_markets(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        result = client.graphql(
            _LIST_QUERY,
            variables={"first": max(1, min(int(limit), 250))},
        )
        data = (result.get("data") or {}).get("markets") or {}
        edges = data.get("edges") or []
        return [
            e.get("node")
            for e in edges
            if isinstance(e, dict) and isinstance(e.get("node"), dict)
        ]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        market_id: int | str,
    ) -> dict[str, Any]:
        result = client.graphql(
            _GET_QUERY, variables={"id": _market_gid(market_id)},
        )
        market = (result.get("data") or {}).get("market")
        if not isinstance(market, dict):
            raise ShopifyAdminError(
                f"market {market_id} not returned",
                path="graphql.json",
            )
        return market

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        name: str,
        country_codes: list[str],
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a market serving the given country codes
        (ISO alpha-2, e.g. ``["DE", "FR", "IT"]`` for "Central
        EU"). Shopify creates the country regions under the
        hood."""
        if not name:
            raise ValueError("name: required")
        if not country_codes:
            raise ValueError(
                "country_codes: non-empty list required",
            )
        input_: dict[str, Any] = {
            "name": name,
            "enabled": bool(enabled),
            "regions": [
                {"countryCode": c.upper()}
                for c in country_codes
            ],
        }
        result = client.graphql(
            _CREATE_MUTATION, variables={"input": input_},
        )
        payload = result.get("data") or {}
        _check_user_errors(payload, "marketCreate")
        market = (payload.get("marketCreate") or {}).get("market")
        if not isinstance(market, dict):
            raise ShopifyAdminError(
                "marketCreate: market not returned",
                path="graphql.json",
                body=str(payload),
            )
        return market

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        market_id: int | str,
        *,
        name: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        input_: dict[str, Any] = {}
        if name is not None:
            input_["name"] = str(name)
        if enabled is not None:
            input_["enabled"] = bool(enabled)
        if not input_:
            raise ValueError(
                "at least one of name / enabled required",
            )
        result = client.graphql(
            _UPDATE_MUTATION,
            variables={
                "id": _market_gid(market_id),
                "input": input_,
            },
        )
        payload = result.get("data") or {}
        _check_user_errors(payload, "marketUpdate")
        market = (payload.get("marketUpdate") or {}).get("market")
        if not isinstance(market, dict):
            raise ShopifyAdminError(
                "marketUpdate: market not returned",
                path="graphql.json",
                body=str(payload),
            )
        return market

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        market_id: int | str,
    ) -> str:
        """Delete a market. The primary market cannot be
        deleted — Shopify returns a userError. Returns the
        deleted GID for confirmation."""
        result = client.graphql(
            _DELETE_MUTATION,
            variables={"id": _market_gid(market_id)},
        )
        payload = result.get("data") or {}
        _check_user_errors(payload, "marketDelete")
        deleted = (
            payload.get("marketDelete") or {}
        ).get("deletedId")
        if not deleted:
            raise ShopifyAdminError(
                "marketDelete: deletedId not returned",
                path="graphql.json",
                body=str(payload),
            )
        return str(deleted)


class MarketWebPresences:
    """Storefront binding per market — which domain or
    subfolder carries this market's pricing + language."""

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        market_id: int | str,
        default_locale: str,
        subfolder_suffix: str | None = None,
        domain_id: int | str | None = None,
    ) -> dict[str, Any]:
        """Bind the market to either a subfolder
        (``subfolder_suffix="de"`` → ``shop.com/de``) or a
        dedicated domain (``domain_id`` pointing at an
        already-registered domain in Shopify). Exactly one of
        the two must be supplied."""
        if not default_locale:
            raise ValueError("default_locale: required")
        if (
            (subfolder_suffix and domain_id)
            or (not subfolder_suffix and not domain_id)
        ):
            raise ValueError(
                "exactly one of subfolder_suffix or domain_id "
                "must be supplied",
            )
        input_: dict[str, Any] = {
            "defaultLocale": str(default_locale),
        }
        if subfolder_suffix:
            input_["subfolderSuffix"] = str(subfolder_suffix)
        if domain_id is not None:
            input_["domainId"] = (
                str(domain_id)
                if str(domain_id).startswith("gid://")
                else f"gid://shopify/Domain/{domain_id}"
            )
        result = client.graphql(
            _WEB_PRESENCE_CREATE,
            variables={
                "marketId": _market_gid(market_id),
                "input": input_,
            },
        )
        payload = result.get("data") or {}
        _check_user_errors(payload, "marketWebPresenceCreate")
        market = (
            payload.get("marketWebPresenceCreate") or {}
        ).get("market")
        if not isinstance(market, dict):
            raise ShopifyAdminError(
                "marketWebPresenceCreate: market not returned",
                path="graphql.json",
                body=str(payload),
            )
        return market


class MarketCurrencies:
    """Currency + rounding for a market."""

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        *,
        market_id: int | str,
        base_currency: str | None = None,
        local_currencies: bool | None = None,
    ) -> dict[str, Any]:
        """Set the market's currency behaviour.

        * ``base_currency`` — ISO-4217 code (e.g. ``"EUR"``).
          Shopify converts store-default prices to this
          currency automatically.
        * ``local_currencies`` — whether buyers are charged
          in their own currency (auto-convert using Shopify's
          daily rate).
        """
        input_: dict[str, Any] = {}
        if base_currency:
            input_["baseCurrency"] = str(base_currency).upper()
        if local_currencies is not None:
            input_["localCurrencies"] = bool(local_currencies)
        if not input_:
            raise ValueError(
                "at least one of base_currency / "
                "local_currencies required",
            )
        result = client.graphql(
            _CURRENCY_UPDATE,
            variables={
                "marketId": _market_gid(market_id),
                "input": input_,
            },
        )
        payload = result.get("data") or {}
        _check_user_errors(
            payload, "marketCurrencySettingsUpdate",
        )
        market = (
            payload.get("marketCurrencySettingsUpdate") or {}
        ).get("market")
        if not isinstance(market, dict):
            raise ShopifyAdminError(
                "marketCurrencySettingsUpdate: market not "
                "returned",
                path="graphql.json",
                body=str(payload),
            )
        return market
