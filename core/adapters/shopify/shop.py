"""ShopifyShopAdapter — store-level metadata read.

The ``shop`` query is the catch-all for "what kind of store is
this?" — primary currency, plan, timezone, contact email, billing
address, enabled features. Almost every engine asks one of these
at startup; centralising the read here means only one
``shop { … }`` query traverses the wire per session.

Capabilities:

  * ``SHOPIFY_GET_SHOP``           — primary fields used by engines.
  * ``SHOPIFY_GET_SHOP_POLICIES``  — refund / privacy / terms text.
  * ``SHOPIFY_LIST_CURRENCIES``    — enabled presentment currencies.

These are read-only — there is no shopUpdate mutation in the public
admin API; merchants change shop settings via the admin UI or the
billing API (out of scope for an autonomous operator).

Pattern E note: ``shopPolicies`` is gated by ``read_legal_policies``
scope (separate from the basic ``read_products``/``read_orders``
core scopes). Live-verified: the dev store rejects with a precise
``ACCESS_DENIED`` until that scope is granted.

Pattern D note: ``ShopFeatures`` drifts across API versions —
``multiLocation`` and ``onlineStore`` were renamed/removed from the
2024-01 schema. The query asks only for stable feature flags
(branding, giftCards, reports, …); engines treat unknown features
as absent.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_GET_SHOP_QUERY = """
query shop {
  shop {
    id
    name
    email
    contactEmail
    myshopifyDomain
    primaryDomain {
      url
      host
      sslEnabled
    }
    url
    ianaTimezone
    timezoneAbbreviation
    timezoneOffsetMinutes
    weightUnit
    currencyCode
    enabledPresentmentCurrencies
    plan {
      displayName
      partnerDevelopment
      shopifyPlus
    }
    billingAddress {
      address1
      address2
      city
      province
      country
      countryCodeV2
      zip
      phone
    }
    features {
      branding
      captcha
      giftCards
      harmonizedSystemCode
      internationalDomains
      internationalPriceOverrides
      internationalPriceRules
      legacySubscriptionGatewayEnabled
      reports
      sellsSubscriptions
      showMetrics
      storefront
    }
    setupRequired
    checkoutApiSupported
  }
}
""".strip()


_GET_SHOP_POLICIES_QUERY = """
query shopPolicies {
  shop {
    shopPolicies {
      id
      type
      title
      url
      body
      createdAt
      updatedAt
    }
  }
}
""".strip()


_LIST_CURRENCIES_QUERY = """
query shopCurrencies {
  shop {
    currencyCode
    enabledPresentmentCurrencies
    currencyFormats {
      moneyFormat
      moneyInEmailsFormat
      moneyWithCurrencyFormat
      moneyWithCurrencyInEmailsFormat
    }
  }
}
""".strip()


class ShopifyShopAdapter(ShopifyBaseAdapter):
    name = "shopify_shop"
    capabilities = {
        Capability.SHOPIFY_GET_SHOP,
        Capability.SHOPIFY_GET_SHOP_POLICIES,
        Capability.SHOPIFY_LIST_CURRENCIES,
    }
    # Shop is the root object — basic shop info, policies, and
    # currency lists are available to any installed app without
    # an additional OAuth scope.
    scope_independent = True

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_GET_SHOP:
            return self._get_shop(params)
        if capability == Capability.SHOPIFY_GET_SHOP_POLICIES:
            return self._get_policies(params)
        if capability == Capability.SHOPIFY_LIST_CURRENCIES:
            return self._list_currencies(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Get shop ───────────────────────────────────────────────────

    def _get_shop(self, _params: dict[str, Any]) -> Any:
        data = self._gql(_GET_SHOP_QUERY, {})
        node = data.get("shop") or {}
        return self._success(
            Capability.SHOPIFY_GET_SHOP,
            data={"shop": self._normalise_shop(node), "found": bool(node)},
        )

    # ── Get policies ───────────────────────────────────────────────

    def _get_policies(self, _params: dict[str, Any]) -> Any:
        data = self._gql(_GET_SHOP_POLICIES_QUERY, {})
        shop = data.get("shop") or {}
        raw = shop.get("shopPolicies") or []
        policies = [
            {
                "id": p.get("id", "") or "",
                "type": p.get("type", "") or "",
                "title": p.get("title", "") or "",
                "url": p.get("url", "") or "",
                "body": p.get("body", "") or "",
                "created_at": p.get("createdAt", "") or "",
                "updated_at": p.get("updatedAt", "") or "",
            }
            for p in raw if isinstance(p, dict)
        ]
        return self._success(
            Capability.SHOPIFY_GET_SHOP_POLICIES,
            data={"policies": policies, "count": len(policies)},
        )

    # ── List currencies ────────────────────────────────────────────

    def _list_currencies(self, _params: dict[str, Any]) -> Any:
        data = self._gql(_LIST_CURRENCIES_QUERY, {})
        shop = data.get("shop") or {}
        formats = shop.get("currencyFormats") or {}
        return self._success(
            Capability.SHOPIFY_LIST_CURRENCIES,
            data={
                "primary_currency": shop.get("currencyCode", "") or "",
                "presentment_currencies": list(
                    shop.get("enabledPresentmentCurrencies") or []
                ),
                "money_format": (
                    formats.get("moneyFormat", "")
                    if isinstance(formats, dict) else ""
                ) or "",
                "money_in_emails_format": (
                    formats.get("moneyInEmailsFormat", "")
                    if isinstance(formats, dict) else ""
                ) or "",
                "money_with_currency_format": (
                    formats.get("moneyWithCurrencyFormat", "")
                    if isinstance(formats, dict) else ""
                ) or "",
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_shop(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        primary_domain = node.get("primaryDomain") or {}
        plan = node.get("plan") or {}
        billing = node.get("billingAddress") or {}
        features = node.get("features") or {}
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "email": node.get("email", "") or "",
            "contact_email": node.get("contactEmail", "") or "",
            "myshopify_domain": node.get("myshopifyDomain", "") or "",
            "primary_url": (
                primary_domain.get("url", "")
                if isinstance(primary_domain, dict) else ""
            ) or "",
            "primary_host": (
                primary_domain.get("host", "")
                if isinstance(primary_domain, dict) else ""
            ) or "",
            "ssl_enabled": bool(
                primary_domain.get("sslEnabled", False)
                if isinstance(primary_domain, dict) else False
            ),
            "url": node.get("url", "") or "",
            "timezone": node.get("ianaTimezone", "") or "",
            "timezone_abbreviation": node.get("timezoneAbbreviation", "") or "",
            "timezone_offset_minutes": int(
                node.get("timezoneOffsetMinutes") or 0
            ),
            "weight_unit": node.get("weightUnit", "") or "",
            "currency_code": node.get("currencyCode", "") or "",
            "presentment_currencies": list(
                node.get("enabledPresentmentCurrencies") or []
            ),
            "plan_name": (
                plan.get("displayName", "")
                if isinstance(plan, dict) else ""
            ) or "",
            "plan_is_partner_dev": bool(
                plan.get("partnerDevelopment", False)
                if isinstance(plan, dict) else False
            ),
            "plan_is_shopify_plus": bool(
                plan.get("shopifyPlus", False)
                if isinstance(plan, dict) else False
            ),
            "billing_country": (
                billing.get("countryCodeV2", "")
                if isinstance(billing, dict) else ""
            ) or "",
            "billing_city": (
                billing.get("city", "")
                if isinstance(billing, dict) else ""
            ) or "",
            "features": {
                k: bool(v) for k, v in (features or {}).items()
                if isinstance(k, str)
            } if isinstance(features, dict) else {},
            "setup_required": bool(node.get("setupRequired", False)),
            "checkout_api_supported": bool(
                node.get("checkoutApiSupported", False)
            ),
        }
