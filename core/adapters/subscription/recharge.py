"""ReChargeAdapter — ReCharge Payments subscription management.

ReCharge is the leading subscription platform for Shopify,
powering subscriptions for thousands of DTC brands. The adapter
wraps the ReCharge API 2021-11 for:

  * **List** — list active subscriptions with pagination
  * **Get** — fetch a single subscription by ID
  * **Create** — create a new subscription for a customer
  * **Update** — update frequency, next charge date, etc.
  * **Cancel** — cancel a subscription with cancellation reason

Authentication: ``X-Recharge-Access-Token`` header with API token.

Pricing: Free for Shopify, paid plans from $99/month for advanced.
Reference: https://developer.rechargepayments.com/2021-11
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ..errors import AdapterValidationError
from ._base import SubscriptionBaseAdapter


_RECHARGE_API_VERSION = "2021-11"


class ReChargeAdapter(SubscriptionBaseAdapter):
    name = "recharge"
    base_url = "https://api.rechargeapps.com"
    config_alias = "recharge"

    priority = 90
    cost_per_call = 0.0

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-Recharge-Access-Token": self._api_key(),
            "X-Recharge-Version": _RECHARGE_API_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── List subscriptions ─────────────────────────────────────

    def _list_subscriptions(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        url = f"{self.base_url}/subscriptions"
        query_parts = []
        if params.get("customer_id"):
            query_parts.append(f"customer_id={params['customer_id']}")
        if params.get("status"):
            query_parts.append(f"status={params['status']}")
        limit = params.get("limit", 25)
        query_parts.append(f"limit={limit}")
        if params.get("page"):
            query_parts.append(f"page={params['page']}")
        if query_parts:
            url += "?" + "&".join(query_parts)

        raw = self._http_request("GET", url)
        subscriptions = raw.get("subscriptions", [])

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "subscriptions": subscriptions,
                "count": len(subscriptions),
            },
            raw=raw,
        )

    # ── Get subscription ───────────────────────────────────────

    def _get_subscription(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        sub_id = params.get("subscription_id")
        if not sub_id:
            raise AdapterValidationError(
                self.name, "'subscription_id' is required",
            )

        url = f"{self.base_url}/subscriptions/{sub_id}"
        raw = self._http_request("GET", url)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"subscription": raw.get("subscription", raw)},
            raw=raw,
        )

    # ── Create subscription ────────────────────────────────────

    def _create_subscription(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        required = ("address_id", "next_charge_scheduled_at",
                     "shopify_variant_id", "quantity")
        missing = [f for f in required if not params.get(f)]
        if missing:
            raise AdapterValidationError(
                self.name,
                f"missing required fields: {', '.join(missing)}",
            )

        url = f"{self.base_url}/subscriptions"
        body = {
            "address_id": params["address_id"],
            "next_charge_scheduled_at": params["next_charge_scheduled_at"],
            "shopify_variant_id": params["shopify_variant_id"],
            "quantity": params["quantity"],
            "order_interval_unit": params.get("order_interval_unit", "month"),
            "order_interval_frequency": params.get(
                "order_interval_frequency", "1",
            ),
        }
        if params.get("charge_interval_frequency"):
            body["charge_interval_frequency"] = params[
                "charge_interval_frequency"
            ]
        if params.get("price"):
            body["price"] = params["price"]

        raw = self._http_request("POST", url, body=body)
        sub = raw.get("subscription", raw)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "subscription_id": sub.get("id", ""),
                "status": sub.get("status", ""),
            },
            raw=raw,
        )

    # ── Update subscription ────────────────────────────────────

    def _update_subscription(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        sub_id = params.get("subscription_id")
        if not sub_id:
            raise AdapterValidationError(
                self.name, "'subscription_id' is required",
            )

        url = f"{self.base_url}/subscriptions/{sub_id}"
        update_fields = {}
        for field in (
            "quantity", "price", "order_interval_unit",
            "order_interval_frequency", "charge_interval_frequency",
            "next_charge_scheduled_at", "status",
        ):
            if field in params:
                update_fields[field] = params[field]

        if not update_fields:
            raise AdapterValidationError(
                self.name, "no update fields provided",
            )

        raw = self._http_request("POST", url, body=update_fields)
        sub = raw.get("subscription", raw)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "subscription_id": sub_id,
                "updated_fields": list(update_fields.keys()),
            },
            raw=raw,
        )

    # ── Cancel subscription ────────────────────────────────────

    def _cancel_subscription(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        sub_id = params.get("subscription_id")
        if not sub_id:
            raise AdapterValidationError(
                self.name, "'subscription_id' is required",
            )

        url = f"{self.base_url}/subscriptions/{sub_id}/cancel"
        body = {
            "cancellation_reason": params.get(
                "cancellation_reason", "other",
            ),
        }
        if params.get("cancellation_reason_comments"):
            body["cancellation_reason_comments"] = params[
                "cancellation_reason_comments"
            ]

        raw = self._http_request("POST", url, body=body)
        sub = raw.get("subscription", raw)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "subscription_id": sub_id,
                "status": sub.get("status", "cancelled"),
            },
            raw=raw,
        )
