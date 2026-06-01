"""ShopifyAppSubscriptionsAdapter — recurring app billing management.

Companion to ``apps.py`` (which lists installed apps + reads the
current installation's scopes). The subscription surface is how an
APP charges the merchant for recurring usage — Shopify's billing API
handles the merchant-approval flow + the actual money movement; the
adapter just creates / lists / cancels the subscription record.

ShopAI's billing + lifecycle engines use these to:

  * Charge merchants on the standard 30-day cycle when they upgrade
    from the free tier to a paid plan.
  * Surface "your trial ends in N days" + active subscription
    metadata in the operator dashboard.
  * Cancel the subscription cleanly on uninstall (Shopify auto-
    revokes anyway, but explicit cancel keeps the audit trail
    clean).

Capabilities:

  * ``SHOPIFY_LIST_APP_SUBSCRIPTIONS``    — paginated list of the
    calling app's active subscriptions (current shop only).
  * ``SHOPIFY_CREATE_APP_SUBSCRIPTION``   — create a new recurring
    charge with line items (recurring + usage-based). Returns a
    confirmation URL the merchant must visit to approve.
  * ``SHOPIFY_CANCEL_APP_SUBSCRIPTION``   — cancel by GID. Optional
    prorate flag refunds unused trial days.

Friendly create call shape::

    {"name":            "ShopAI Pro plan",
     "return_url":      "https://shopai.dev/billing/success",
     "test":            False,    # True → no real money
     "trial_days":      14,
     "line_items": [
        {"recurring": {
            "interval": "EVERY_30_DAYS",
            "price": "29.99",
            "discount": {
              "duration_limit_in_intervals": 3,
              "value": {"percentage": 0.5}
            }
         }},
        {"usage": {
            "terms": "Per metaobject upsert",
            "capped_amount": "100.00"
         }}
     ]}

Pattern A: ``appSubscriptionCreate`` takes ``name`` / ``returnUrl``
/ ``test`` / ``trialDays`` at field level + a ``lineItems`` list.
Same convention as fulfillmentEventCreate / paymentTermsCreate.

Pattern E note: the ``currentAppInstallation.activeSubscriptions``
list and the ``appSubscriptionCreate`` mutation are gated by the
caller being an actual Shopify App (not a custom token-only access
flow). Custom-installed apps that don't go through the App Store
flow will get ACCESS_DENIED — engines using token-only auth should
treat the subscription surface as unavailable.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_SUBSCRIPTION_FIELDS = """
id
name
status
test
trialDays
currentPeriodEnd
createdAt
returnUrl
lineItems {
  id
  plan {
    pricingDetails {
      __typename
      ... on AppRecurringPricing {
        interval
        price {
          amount
          currencyCode
        }
        discount {
          durationLimitInIntervals
          remainingDurationInIntervals
          priceAfterDiscount {
            amount
            currencyCode
          }
          value {
            __typename
            ... on AppSubscriptionDiscountAmount {
              amount {
                amount
                currencyCode
              }
            }
            ... on AppSubscriptionDiscountPercentage {
              percentage
            }
          }
        }
      }
      ... on AppUsagePricing {
        terms
        cappedAmount {
          amount
          currencyCode
        }
        balanceUsed {
          amount
          currencyCode
        }
        interval
      }
    }
  }
}
""".strip()


_LIST_SUBSCRIPTIONS_QUERY = f"""
query appSubscriptions {{
  currentAppInstallation {{
    activeSubscriptions {{
      {_SUBSCRIPTION_FIELDS}
    }}
  }}
}}
""".strip()


_CREATE_SUBSCRIPTION_MUTATION = f"""
mutation appSubscriptionCreate(
  $name: String!,
  $returnUrl: URL!,
  $test: Boolean,
  $trialDays: Int,
  $lineItems: [AppSubscriptionLineItemInput!]!
) {{
  appSubscriptionCreate(
    name: $name,
    returnUrl: $returnUrl,
    test: $test,
    trialDays: $trialDays,
    lineItems: $lineItems
  ) {{
    appSubscription {{
      {_SUBSCRIPTION_FIELDS}
    }}
    confirmationUrl
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_CANCEL_SUBSCRIPTION_MUTATION = f"""
mutation appSubscriptionCancel($id: ID!, $prorate: Boolean) {{
  appSubscriptionCancel(id: $id, prorate: $prorate) {{
    appSubscription {{
      id
      status
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_VALID_INTERVALS = {"EVERY_30_DAYS", "ANNUAL"}


class ShopifyAppSubscriptionsAdapter(ShopifyBaseAdapter):
    name = "shopify_app_subscriptions"
    capabilities = {
        Capability.SHOPIFY_LIST_APP_SUBSCRIPTIONS,
        Capability.SHOPIFY_CREATE_APP_SUBSCRIPTION,
        Capability.SHOPIFY_CANCEL_APP_SUBSCRIPTION,
    }
    # App-level subscription management — no extra OAuth scope.
    scope_independent = True

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_APP_SUBSCRIPTIONS:
            return self._list(params)
        if capability == Capability.SHOPIFY_CREATE_APP_SUBSCRIPTION:
            return self._create(params)
        if capability == Capability.SHOPIFY_CANCEL_APP_SUBSCRIPTION:
            return self._cancel(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, _params: dict[str, Any]) -> Any:
        # Pattern B: subscriptions hang off currentAppInstallation —
        # there's no top-level Query.appSubscriptions connection.
        # Returns a flat list (all active subscriptions for the
        # calling app on the calling shop).
        data = self._gql(_LIST_SUBSCRIPTIONS_QUERY, {})
        installation = data.get("currentAppInstallation") or {}
        subs_raw = installation.get("activeSubscriptions") or []
        subs = [
            self._normalise_subscription(s)
            for s in subs_raw if isinstance(s, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_APP_SUBSCRIPTIONS,
            data={
                "subscriptions": subs,
                "count": len(subs),
                "installation_found": bool(installation),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AdapterValidationError(
                self.name, "'name' is required",
            )

        return_url = params.get("return_url") or params.get("returnUrl")
        if not isinstance(return_url, str) or not return_url.strip():
            raise AdapterValidationError(
                self.name, "'return_url' is required",
            )
        if not return_url.startswith(("http://", "https://")):
            raise AdapterValidationError(
                self.name,
                "'return_url' must start with http(s)://",
            )

        line_items_raw = params.get("line_items") or params.get("lineItems")
        if not isinstance(line_items_raw, list) or not line_items_raw:
            raise AdapterValidationError(
                self.name,
                "'line_items' must be a non-empty list of recurring/usage entries",
            )
        line_items = [
            self._build_line_item(li, i)
            for i, li in enumerate(line_items_raw)
        ]

        variables: dict[str, Any] = {
            "name": name.strip(),
            "returnUrl": return_url.strip(),
            "lineItems": line_items,
        }

        test = params.get("test")
        if test is not None:
            variables["test"] = bool(test)

        # W962-12: sentinel-cascade so explicit `trial_days=0`
        # (no trial) survives instead of being dropped to None
        # by `or` short-circuit. Pre-fix, Shopify defaulted to
        # 14-day trial on the absent field, costing billable
        # revenue.
        _MISSING = object()
        trial_days = params.get("trial_days", _MISSING)
        if trial_days is _MISSING:
            trial_days = params.get("trialDays", _MISSING)
        if trial_days is not _MISSING:
            try:
                variables["trialDays"] = int(trial_days)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, "'trial_days' must be an integer",
                ) from exc

        data = self._gql(_CREATE_SUBSCRIPTION_MUTATION, variables)
        self._check_user_errors(data, "appSubscriptionCreate")
        payload = data.get("appSubscriptionCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_APP_SUBSCRIPTION,
            data={
                "subscription": self._normalise_subscription(
                    payload.get("appSubscription") or {},
                ),
                "confirmation_url": (
                    payload.get("confirmationUrl", "") or ""
                ),
            },
        )

    # ── Cancel ─────────────────────────────────────────────────────

    def _cancel(self, params: dict[str, Any]) -> Any:
        sub_id = params.get("id") or params.get("subscription_id")
        if not isinstance(sub_id, str) or not sub_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the subscription) is required",
            )
        variables: dict[str, Any] = {"id": sub_id.strip()}

        prorate = params.get("prorate")
        if prorate is not None:
            variables["prorate"] = bool(prorate)

        data = self._gql(_CANCEL_SUBSCRIPTION_MUTATION, variables)
        self._check_user_errors(data, "appSubscriptionCancel")
        payload = data.get("appSubscriptionCancel") or {}
        sub = payload.get("appSubscription") or {}
        return self._success(
            Capability.SHOPIFY_CANCEL_APP_SUBSCRIPTION,
            data={
                "id": sub.get("id", "") or "",
                "status": sub.get("status", "") or "",
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_line_item(
        self, raw: Any, index: int,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name, f"line_items[{index}] must be a dict",
            )

        recurring = raw.get("recurring")
        usage = raw.get("usage")
        if recurring is not None and usage is not None:
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}] must specify either 'recurring' or "
                "'usage', not both",
            )
        if recurring is not None:
            return {"plan": {
                "appRecurringPricingDetails":
                    self._build_recurring(recurring, index),
            }}
        if usage is not None:
            return {"plan": {
                "appUsagePricingDetails":
                    self._build_usage(usage, index),
            }}
        raise AdapterValidationError(
            self.name,
            f"line_items[{index}] must contain 'recurring' or 'usage'",
        )

    def _build_recurring(
        self, raw: Any, index: int,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}].recurring must be a dict",
            )
        price = raw.get("price")
        if price is None:
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}].recurring.price is required",
            )
        try:
            price_float = float(price)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}].recurring.price must be numeric",
            ) from exc

        currency = raw.get("currency_code") or raw.get("currencyCode") or "USD"
        if not isinstance(currency, str):
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}].recurring.currency_code "
                "must be a string",
            )

        out: dict[str, Any] = {
            "price": {
                "amount": price_float,
                "currencyCode": currency.upper(),
            },
        }

        interval = raw.get("interval", "EVERY_30_DAYS")
        if not isinstance(interval, str) or interval.upper() not in _VALID_INTERVALS:
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}].recurring.interval must be one of: "
                f"{sorted(_VALID_INTERVALS)}",
            )
        out["interval"] = interval.upper()

        discount = raw.get("discount")
        if discount is not None:
            out["discount"] = self._build_discount(discount, index)

        return out

    def _build_discount(
        self, raw: Any, index: int,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}].recurring.discount must be a dict",
            )
        out: dict[str, Any] = {}

        duration = raw.get("duration_limit_in_intervals") or raw.get(
            "durationLimitInIntervals"
        )
        if duration is not None:
            try:
                out["durationLimitInIntervals"] = int(duration)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"line_items[{index}].recurring.discount."
                    "duration_limit_in_intervals must be an integer",
                ) from exc

        value = raw.get("value")
        if not isinstance(value, dict):
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}].recurring.discount.value must be "
                "a dict — {percentage: 0-1} or {amount: '...'}",
            )
        if "percentage" in value:
            try:
                pct = float(value["percentage"])
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"line_items[{index}].recurring.discount.value."
                    "percentage must be numeric (0-1 fraction)",
                ) from exc
            # Shopify's billing API uses 0-1 fractions directly here
            # (unlike storefront discounts which take 0-100).
            out["value"] = {"percentage": pct}
        elif "amount" in value:
            try:
                amount_float = float(value["amount"])
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"line_items[{index}].recurring.discount.value."
                    "amount must be numeric",
                ) from exc
            currency = value.get("currency_code") or value.get(
                "currencyCode"
            ) or "USD"
            out["value"] = {
                "amount": {
                    "amount": amount_float,
                    "currencyCode": currency.upper(),
                },
            }
        else:
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}].recurring.discount.value must "
                "contain 'percentage' or 'amount'",
            )
        return out

    def _build_usage(
        self, raw: Any, index: int,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}].usage must be a dict",
            )
        terms = raw.get("terms")
        if not isinstance(terms, str) or not terms.strip():
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}].usage.terms is required",
            )
        capped = raw.get("capped_amount") or raw.get("cappedAmount")
        if capped is None:
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}].usage.capped_amount is required",
            )
        try:
            capped_float = float(capped)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name,
                f"line_items[{index}].usage.capped_amount must be numeric",
            ) from exc

        currency = raw.get("currency_code") or raw.get(
            "currencyCode"
        ) or "USD"

        return {
            "terms": terms.strip(),
            "cappedAmount": {
                "amount": capped_float,
                "currencyCode": currency.upper(),
            },
        }

    # ── Normalisation ──────────────────────────────────────────────

    @classmethod
    def _normalise_subscription(
        cls, node: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        line_items_raw = node.get("lineItems") or []
        line_items = []
        for li in line_items_raw:
            if not isinstance(li, dict):
                continue
            plan = li.get("plan") or {}
            pricing = (
                plan.get("pricingDetails") or {}
                if isinstance(plan, dict) else {}
            )
            kind = (
                pricing.get("__typename", "")
                if isinstance(pricing, dict) else ""
            ) or ""
            entry: dict[str, Any] = {
                "id": li.get("id", "") or "",
                "kind": kind,
            }
            if kind == "AppRecurringPricing":
                price = (
                    pricing.get("price", {})
                    if isinstance(pricing, dict) else {}
                ) or {}
                entry.update({
                    "interval": (
                        pricing.get("interval", "")
                        if isinstance(pricing, dict) else ""
                    ) or "",
                    "price": (
                        price.get("amount", "")
                        if isinstance(price, dict) else ""
                    ) or "",
                    "currency_code": (
                        price.get("currencyCode", "")
                        if isinstance(price, dict) else ""
                    ) or "",
                })
            elif kind == "AppUsagePricing":
                capped = (
                    pricing.get("cappedAmount", {})
                    if isinstance(pricing, dict) else {}
                ) or {}
                balance = (
                    pricing.get("balanceUsed", {})
                    if isinstance(pricing, dict) else {}
                ) or {}
                entry.update({
                    "terms": (
                        pricing.get("terms", "")
                        if isinstance(pricing, dict) else ""
                    ) or "",
                    "capped_amount": (
                        capped.get("amount", "")
                        if isinstance(capped, dict) else ""
                    ) or "",
                    "balance_used": (
                        balance.get("amount", "")
                        if isinstance(balance, dict) else ""
                    ) or "",
                    "currency_code": (
                        capped.get("currencyCode", "")
                        if isinstance(capped, dict) else ""
                    ) or "",
                })
            line_items.append(entry)

        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "status": node.get("status", "") or "",
            "test": bool(node.get("test", False)),
            "trial_days": int(node.get("trialDays") or 0) or 0,
            "current_period_end": node.get("currentPeriodEnd", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "return_url": node.get("returnUrl", "") or "",
            "line_items": line_items,
        }
