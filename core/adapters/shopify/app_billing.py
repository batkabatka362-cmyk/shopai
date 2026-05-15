"""ShopifyAppBillingAdapter — one-time + usage + trial-extend billing.

Companion to ``app_subscriptions.py`` (which covers LIST / CREATE /
CANCEL of recurring subscriptions). The Shopify billing API has
four other money-moving mutations that fell outside that adapter:

  * **One-time charges.** ``appPurchaseOneTimeCreate`` — flat,
    non-recurring fee. ShopAI uses these for the "unlock the
    creative archive for $99" or "audit my whole ROAS history once"
    one-shots, separate from the monthly plan.
  * **Adjust usage caps mid-cycle.** ``appSubscriptionLineItemUpdate``
    raises (or lowers) the ``cappedAmount`` on a usage line item.
    Required when a merchant blows through their initial cap and
    needs to re-approve a higher one.
  * **Extend trials.** ``appSubscriptionTrialExtend`` adds N days
    to the trial. Used by the goodwill engine when a merchant
    asks for more time, or programmatically after onboarding
    delays.
  * **Record usage.** ``appUsageRecordCreate`` is the actual money
    trigger for usage-based pricing — every metaobject upsert,
    every campaign launch, every API hit charged to the merchant
    bottoms out here. Idempotency-keyed so re-fires don't
    double-charge.

Capabilities:

  * ``SHOPIFY_CREATE_APP_PURCHASE_ONE_TIME``  — appPurchaseOneTimeCreate.
  * ``SHOPIFY_UPDATE_APP_SUBSCRIPTION_LINE_ITEM`` — appSubscriptionLineItemUpdate.
  * ``SHOPIFY_EXTEND_APP_SUBSCRIPTION_TRIAL`` — appSubscriptionTrialExtend.
  * ``SHOPIFY_CREATE_APP_USAGE_RECORD`` — appUsageRecordCreate.

Pattern A: every mutation puts the resource id (and other args)
at the GraphQL field level — no *Input wrapper.

Pattern F: all four payloads use the bare ``UserError`` type
(no ``code`` field). Selection drops ``code`` for all of them.

Pattern G: money inputs are inlined per-mutation rather than
shared, matching the pattern in marketing_events / draft_orders /
app_subscriptions.

Pattern E note: same as app_subscriptions — these mutations are
gated by being a Shopify-App-Store-installed app; custom token-only
installs receive ACCESS_DENIED. Engines using token-only auth
should treat this surface as unavailable.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_ONE_TIME_CREATE_MUTATION = """
mutation appPurchaseOneTimeCreate(
  $name: String!,
  $price: MoneyInput!,
  $returnUrl: URL!,
  $test: Boolean
) {
  appPurchaseOneTimeCreate(
    name: $name,
    price: $price,
    returnUrl: $returnUrl,
    test: $test
  ) {
    appPurchaseOneTime {
      id
      name
      status
      test
      createdAt
      price {
        amount
        currencyCode
      }
    }
    confirmationUrl
    userErrors {
      field
      message
    }
  }
}
""".strip()


_LINE_ITEM_UPDATE_MUTATION = """
mutation appSubscriptionLineItemUpdate(
  $id: ID!,
  $cappedAmount: MoneyInput!
) {
  appSubscriptionLineItemUpdate(
    id: $id,
    cappedAmount: $cappedAmount
  ) {
    appSubscription {
      id
      name
      status
      currentPeriodEnd
    }
    confirmationUrl
    userErrors {
      field
      message
    }
  }
}
""".strip()


_TRIAL_EXTEND_MUTATION = """
mutation appSubscriptionTrialExtend(
  $id: ID!,
  $days: Int!
) {
  appSubscriptionTrialExtend(id: $id, days: $days) {
    appSubscription {
      id
      name
      status
      trialDays
      currentPeriodEnd
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_USAGE_RECORD_CREATE_MUTATION = """
mutation appUsageRecordCreate(
  $subscriptionLineItemId: ID!,
  $price: MoneyInput!,
  $description: String!,
  $idempotencyKey: String
) {
  appUsageRecordCreate(
    subscriptionLineItemId: $subscriptionLineItemId,
    price: $price,
    description: $description,
    idempotencyKey: $idempotencyKey
  ) {
    appUsageRecord {
      id
      description
      idempotencyKey
      createdAt
      price {
        amount
        currencyCode
      }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_DEFAULT_CURRENCY = "USD"


class ShopifyAppBillingAdapter(ShopifyBaseAdapter):
    name = "shopify_app_billing"
    capabilities = {
        Capability.SHOPIFY_CREATE_APP_PURCHASE_ONE_TIME,
        Capability.SHOPIFY_UPDATE_APP_SUBSCRIPTION_LINE_ITEM,
        Capability.SHOPIFY_EXTEND_APP_SUBSCRIPTION_TRIAL,
        Capability.SHOPIFY_CREATE_APP_USAGE_RECORD,
    }
    # App-level billing — available to any installed app, no
    # extra OAuth scope needed.
    scope_independent = True

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_CREATE_APP_PURCHASE_ONE_TIME:
            return self._one_time(params)
        if capability == \
                Capability.SHOPIFY_UPDATE_APP_SUBSCRIPTION_LINE_ITEM:
            return self._line_item_update(params)
        if capability == \
                Capability.SHOPIFY_EXTEND_APP_SUBSCRIPTION_TRIAL:
            return self._trial_extend(params)
        if capability == Capability.SHOPIFY_CREATE_APP_USAGE_RECORD:
            return self._usage_record(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── One-time charge ────────────────────────────────────────────

    def _one_time(self, params: dict[str, Any]) -> Any:
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AdapterValidationError(
                self.name,
                "'name' is required (the human-readable charge "
                "label shown on the merchant's bill)",
            )
        return_url = params.get("return_url") or params.get("returnUrl")
        if not isinstance(return_url, str) or not return_url.strip():
            raise AdapterValidationError(
                self.name,
                "'return_url' is required (Shopify redirects the "
                "merchant here after they approve)",
            )
        price = self._money_input(params, "price")
        test = params.get("test")
        variables: dict[str, Any] = {
            "name": name.strip(),
            "price": price,
            "returnUrl": return_url.strip(),
        }
        if test is not None:
            variables["test"] = bool(test)
        else:
            variables["test"] = None

        data = self._gql(_ONE_TIME_CREATE_MUTATION, variables)
        self._check_user_errors(data, "appPurchaseOneTimeCreate")
        payload = data.get("appPurchaseOneTimeCreate") or {}
        purchase = payload.get("appPurchaseOneTime") or {}
        purchase_price = purchase.get("price") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_APP_PURCHASE_ONE_TIME,
            data={
                "purchase_id": (
                    purchase.get("id", "")
                    if isinstance(purchase, dict) else ""
                ) or "",
                "name": (
                    purchase.get("name", "")
                    if isinstance(purchase, dict) else ""
                ) or "",
                "status": (
                    purchase.get("status", "")
                    if isinstance(purchase, dict) else ""
                ) or "",
                "test": bool(
                    purchase.get("test", False)
                    if isinstance(purchase, dict) else False
                ),
                "created_at": (
                    purchase.get("createdAt", "")
                    if isinstance(purchase, dict) else ""
                ) or "",
                "price": self._normalise_money(purchase_price),
                "confirmation_url": (
                    payload.get("confirmationUrl", "") or ""
                ),
            },
        )

    # ── Line item update ───────────────────────────────────────────

    def _line_item_update(self, params: dict[str, Any]) -> Any:
        line_item_id = (
            params.get("id")
            or params.get("line_item_id")
            or params.get("lineItemId")
        )
        if not isinstance(line_item_id, str) or \
                not line_item_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the AppSubscriptionLineItem) "
                "is required",
            )
        capped_amount = self._money_input(params, "capped_amount")
        data = self._gql(_LINE_ITEM_UPDATE_MUTATION, {
            "id": line_item_id.strip(),
            "cappedAmount": capped_amount,
        })
        self._check_user_errors(data, "appSubscriptionLineItemUpdate")
        payload = data.get("appSubscriptionLineItemUpdate") or {}
        sub = payload.get("appSubscription") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_APP_SUBSCRIPTION_LINE_ITEM,
            data={
                "subscription_id": (
                    sub.get("id", "") if isinstance(sub, dict) else ""
                ) or "",
                "subscription_name": (
                    sub.get("name", "") if isinstance(sub, dict) else ""
                ) or "",
                "subscription_status": (
                    sub.get("status", "")
                    if isinstance(sub, dict) else ""
                ) or "",
                "current_period_end": (
                    sub.get("currentPeriodEnd", "")
                    if isinstance(sub, dict) else ""
                ) or "",
                "confirmation_url": (
                    payload.get("confirmationUrl", "") or ""
                ),
                "new_capped_amount": capped_amount["amount"],
                "currency_code": capped_amount["currencyCode"],
            },
        )

    # ── Trial extend ───────────────────────────────────────────────

    def _trial_extend(self, params: dict[str, Any]) -> Any:
        sub_id = (
            params.get("id")
            or params.get("subscription_id")
            or params.get("subscriptionId")
        )
        if not isinstance(sub_id, str) or not sub_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the AppSubscription) "
                "is required",
            )
        days = params.get("days")
        if days is None:
            raise AdapterValidationError(
                self.name, "'days' is required (number of trial days "
                "to add)",
            )
        try:
            days_int = int(days)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name, "'days' must be an integer",
            ) from exc
        if days_int < 1:
            raise AdapterValidationError(
                self.name, "'days' must be >= 1",
            )

        data = self._gql(_TRIAL_EXTEND_MUTATION, {
            "id": sub_id.strip(),
            "days": days_int,
        })
        self._check_user_errors(data, "appSubscriptionTrialExtend")
        payload = data.get("appSubscriptionTrialExtend") or {}
        sub = payload.get("appSubscription") or {}
        return self._success(
            Capability.SHOPIFY_EXTEND_APP_SUBSCRIPTION_TRIAL,
            data={
                "subscription_id": (
                    sub.get("id", "") if isinstance(sub, dict) else ""
                ) or "",
                "subscription_name": (
                    sub.get("name", "") if isinstance(sub, dict) else ""
                ) or "",
                "subscription_status": (
                    sub.get("status", "")
                    if isinstance(sub, dict) else ""
                ) or "",
                "trial_days": int(
                    sub.get("trialDays", 0) or 0
                    if isinstance(sub, dict) else 0
                ),
                "current_period_end": (
                    sub.get("currentPeriodEnd", "")
                    if isinstance(sub, dict) else ""
                ) or "",
                "days_added": days_int,
            },
        )

    # ── Usage record ───────────────────────────────────────────────

    def _usage_record(self, params: dict[str, Any]) -> Any:
        line_item_id = (
            params.get("subscription_line_item_id")
            or params.get("subscriptionLineItemId")
            or params.get("line_item_id")
        )
        if not isinstance(line_item_id, str) or \
                not line_item_id.strip():
            raise AdapterValidationError(
                self.name,
                "'subscription_line_item_id' (Shopify GID for the "
                "AppSubscriptionLineItem this usage bills against) "
                "is required",
            )
        description = params.get("description")
        if not isinstance(description, str) or not description.strip():
            raise AdapterValidationError(
                self.name,
                "'description' is required — appears on the merchant's "
                "invoice line",
            )
        price = self._money_input(params, "price")
        idempotency_key = (
            params.get("idempotency_key")
            or params.get("idempotencyKey")
        )
        if idempotency_key is not None and \
                not isinstance(idempotency_key, str):
            raise AdapterValidationError(
                self.name,
                "'idempotency_key' must be a string or None",
            )
        idempotency_key = (
            idempotency_key.strip() if idempotency_key else None
        )

        data = self._gql(_USAGE_RECORD_CREATE_MUTATION, {
            "subscriptionLineItemId": line_item_id.strip(),
            "price": price,
            "description": description.strip(),
            "idempotencyKey": idempotency_key,
        })
        self._check_user_errors(data, "appUsageRecordCreate")
        payload = data.get("appUsageRecordCreate") or {}
        record = payload.get("appUsageRecord") or {}
        record_price = record.get("price") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_APP_USAGE_RECORD,
            data={
                "usage_record_id": (
                    record.get("id", "")
                    if isinstance(record, dict) else ""
                ) or "",
                "description": (
                    record.get("description", "")
                    if isinstance(record, dict) else ""
                ) or "",
                "idempotency_key": (
                    record.get("idempotencyKey", "")
                    if isinstance(record, dict) else ""
                ) or "",
                "created_at": (
                    record.get("createdAt", "")
                    if isinstance(record, dict) else ""
                ) or "",
                "price": self._normalise_money(record_price),
            },
        )

    # ── Money helper (Pattern G — inlined per adapter) ─────────────

    def _money_input(
        self, params: dict[str, Any], key: str,
    ) -> dict[str, Any]:
        raw = params.get(key)
        if raw is None:
            raise AdapterValidationError(
                self.name, f"'{key}' is required",
            )
        if isinstance(raw, dict):
            amount = raw.get("amount")
            currency = (
                raw.get("currency_code")
                or raw.get("currencyCode")
                or _DEFAULT_CURRENCY
            )
        else:
            amount = raw
            currency = (
                params.get("currency_code")
                or params.get("currencyCode")
                or _DEFAULT_CURRENCY
            )
        try:
            amount_float = float(amount)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name, f"'{key}' amount must be numeric",
            ) from exc
        if amount_float < 0:
            raise AdapterValidationError(
                self.name, f"'{key}' amount must be >= 0",
            )
        if not isinstance(currency, str) or not currency.strip():
            raise AdapterValidationError(
                self.name, f"'{key}' currency_code must be a string",
            )
        return {
            "amount": amount_float,
            "currencyCode": currency.strip().upper(),
        }

    @staticmethod
    def _normalise_money(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {"amount": 0.0, "currency_code": ""}
        try:
            amount = float(node.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        return {
            "amount": amount,
            "currency_code": node.get("currencyCode", "") or "",
        }
