"""ShopifySubscriptionBillingAdapter — billing cycle ops.

Companions:
  * ``subscriptions.py`` reads contracts.
  * ``subscription_draft.py`` covers contract-edit drafts (the
    full-fledged way to mutate a live contract).

This adapter ships the per-billing-cycle primitives that sit
between the contract-level edits and the underlying transaction
machinery — manual billing retries, skipping a cycle, undoing a
skip, and rescheduling a single cycle's billing date:

  * **Manual billing retry.** Subscription contract's first
    auto-charge fails (e.g. card declined). Engine calls
    ``subscriptionBillingAttemptCreate`` with a fresh
    idempotency key to retry — separate from waiting for the
    next scheduled cycle.
  * **Skip a cycle.** Customer pauses for a single month
    without cancelling the contract. Engine calls
    ``subscriptionBillingCycleSkip`` on the upcoming cycle.
  * **Undo a skip.** Customer changes their mind before the
    cycle window closes; ``subscriptionBillingCycleUnskip``
    reverses it.
  * **Reschedule a single cycle.** Vacation hold — push next
    week's billing out by 14 days without changing the
    contract's underlying cadence.

Capabilities:

  * ``SHOPIFY_CREATE_SUBSCRIPTION_BILLING_ATTEMPT`` —
    subscriptionBillingAttemptCreate. Pattern A:
    subscriptionContractId at field level; the input dict
    carries the idempotencyKey (required) + optional
    originTime / billingCycleSelector / inventoryPolicy.
  * ``SHOPIFY_SKIP_SUBSCRIPTION_BILLING_CYCLE`` —
    subscriptionBillingCycleSkip. The cycle is selected via
    a billingCycleInput dict (contractId + selector).
  * ``SHOPIFY_UNSKIP_SUBSCRIPTION_BILLING_CYCLE`` —
    subscriptionBillingCycleUnskip. Same selector shape.
  * ``SHOPIFY_RESCHEDULE_SUBSCRIPTION_BILLING_CYCLE`` —
    subscriptionBillingCycleScheduleEdit. Same selector +
    a separate input dict carrying billingDate + a required
    reason enum (BUYER_INITIATED / MERCHANT_INITIATED /
    DEV_INITIATED).

Cycle selectors accept ONE of:
  * ``cycle_index`` (1-based, the Nth cycle of this contract), OR
  * ``date`` (ISO-8601 datetime falling within the cycle).

All four mutations have UserError variants with ``code``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_BILLING_CYCLE_FIELDS = """
cycleIndex
cycleStartAt
cycleEndAt
billingAttemptExpectedDate
skipped
edited
status
""".strip()


_CREATE_BILLING_ATTEMPT_MUTATION = """
mutation subscriptionBillingAttemptCreate(
  $subscriptionContractId: ID!,
  $subscriptionBillingAttemptInput: SubscriptionBillingAttemptInput!
) {
  subscriptionBillingAttemptCreate(
    subscriptionContractId: $subscriptionContractId,
    subscriptionBillingAttemptInput: $subscriptionBillingAttemptInput
  ) {
    subscriptionBillingAttempt {
      id
      ready
      idempotencyKey
      nextActionUrl
      errorCode
      errorMessage
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_SKIP_CYCLE_MUTATION = f"""
mutation subscriptionBillingCycleSkip(
  $billingCycleInput: SubscriptionBillingCycleInput!
) {{
  subscriptionBillingCycleSkip(
    billingCycleInput: $billingCycleInput
  ) {{
    billingCycle {{
      {_BILLING_CYCLE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UNSKIP_CYCLE_MUTATION = f"""
mutation subscriptionBillingCycleUnskip(
  $billingCycleInput: SubscriptionBillingCycleInput!
) {{
  subscriptionBillingCycleUnskip(
    billingCycleInput: $billingCycleInput
  ) {{
    billingCycle {{
      {_BILLING_CYCLE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_RESCHEDULE_CYCLE_MUTATION = f"""
mutation subscriptionBillingCycleScheduleEdit(
  $billingCycleInput: SubscriptionBillingCycleInput!,
  $input: SubscriptionBillingCycleScheduleEditInput!
) {{
  subscriptionBillingCycleScheduleEdit(
    billingCycleInput: $billingCycleInput,
    input: $input
  ) {{
    billingCycle {{
      {_BILLING_CYCLE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_VALID_REASONS = {"BUYER_INITIATED", "MERCHANT_INITIATED", "DEV_INITIATED"}
_VALID_INVENTORY_POLICIES = {
    "PRODUCT_VARIANT_INVENTORY_POLICY", "ALLOW_OVERSELLING",
}


class ShopifySubscriptionBillingAdapter(ShopifyBaseAdapter):
    name = "shopify_subscription_billing"
    capabilities = {
        Capability.SHOPIFY_CREATE_SUBSCRIPTION_BILLING_ATTEMPT,
        Capability.SHOPIFY_SKIP_SUBSCRIPTION_BILLING_CYCLE,
        Capability.SHOPIFY_UNSKIP_SUBSCRIPTION_BILLING_CYCLE,
        Capability.SHOPIFY_RESCHEDULE_SUBSCRIPTION_BILLING_CYCLE,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_CREATE_SUBSCRIPTION_BILLING_ATTEMPT:
            return self._create_attempt(params)
        if capability == Capability.SHOPIFY_SKIP_SUBSCRIPTION_BILLING_CYCLE:
            return self._skip_or_unskip(
                params, _SKIP_CYCLE_MUTATION,
                "subscriptionBillingCycleSkip",
                Capability.SHOPIFY_SKIP_SUBSCRIPTION_BILLING_CYCLE,
            )
        if capability == \
                Capability.SHOPIFY_UNSKIP_SUBSCRIPTION_BILLING_CYCLE:
            return self._skip_or_unskip(
                params, _UNSKIP_CYCLE_MUTATION,
                "subscriptionBillingCycleUnskip",
                Capability.SHOPIFY_UNSKIP_SUBSCRIPTION_BILLING_CYCLE,
            )
        if capability == \
                Capability.SHOPIFY_RESCHEDULE_SUBSCRIPTION_BILLING_CYCLE:
            return self._reschedule(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Billing attempt create ─────────────────────────────────────

    def _create_attempt(self, params: dict[str, Any]) -> Any:
        contract_id = (
            params.get("contract_id")
            or params.get("subscription_contract_id")
            or params.get("subscriptionContractId")
        )
        if not isinstance(contract_id, str) or not contract_id.strip():
            raise AdapterValidationError(
                self.name,
                "'contract_id' (Shopify GID for the SubscriptionContract) "
                "is required",
            )

        idempotency_key = (
            params.get("idempotency_key")
            or params.get("idempotencyKey")
        )
        if not isinstance(idempotency_key, str) or \
                not idempotency_key.strip():
            raise AdapterValidationError(
                self.name,
                "'idempotency_key' is required (caller-generated unique "
                "string that prevents double-billing on retry)",
            )

        attempt_input: dict[str, Any] = {
            "idempotencyKey": idempotency_key.strip(),
        }

        origin_time = (
            params.get("origin_time") or params.get("originTime")
        )
        if origin_time is not None:
            if not isinstance(origin_time, str):
                raise AdapterValidationError(
                    self.name,
                    "'origin_time' must be ISO-8601 datetime string",
                )
            attempt_input["originTime"] = origin_time.strip()

        selector = params.get("cycle_selector") or params.get(
            "billing_cycle_selector",
        )
        if selector is None:
            # Allow inline selector params (cycle_index / date) at the
            # top level of the call for ergonomics.
            if "cycle_index" in params or "date" in params:
                selector = self._build_selector(params)
        else:
            selector = self._build_selector(selector)
        if selector is not None:
            attempt_input["billingCycleSelector"] = selector

        inventory_policy = (
            params.get("inventory_policy") or params.get("inventoryPolicy")
        )
        if inventory_policy is not None:
            if not isinstance(inventory_policy, str):
                raise AdapterValidationError(
                    self.name, "'inventory_policy' must be a string",
                )
            up = inventory_policy.strip().upper()
            if up not in _VALID_INVENTORY_POLICIES:
                raise AdapterValidationError(
                    self.name,
                    f"'inventory_policy' must be one of "
                    f"{sorted(_VALID_INVENTORY_POLICIES)}",
                )
            attempt_input["inventoryPolicy"] = up

        data = self._gql(_CREATE_BILLING_ATTEMPT_MUTATION, {
            "subscriptionContractId": contract_id.strip(),
            "subscriptionBillingAttemptInput": attempt_input,
        })
        self._check_user_errors(data, "subscriptionBillingAttemptCreate")
        payload = data.get("subscriptionBillingAttemptCreate") or {}
        attempt = payload.get("subscriptionBillingAttempt") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_SUBSCRIPTION_BILLING_ATTEMPT,
            data={
                "id": (
                    attempt.get("id", "")
                    if isinstance(attempt, dict) else ""
                ) or "",
                "ready": bool(
                    attempt.get("ready", False)
                    if isinstance(attempt, dict) else False
                ),
                "idempotency_key": (
                    attempt.get("idempotencyKey", "")
                    if isinstance(attempt, dict) else ""
                ) or "",
                "next_action_url": (
                    attempt.get("nextActionUrl", "")
                    if isinstance(attempt, dict) else ""
                ) or "",
                "error_code": (
                    attempt.get("errorCode", "")
                    if isinstance(attempt, dict) else ""
                ) or "",
                "error_message": (
                    attempt.get("errorMessage", "")
                    if isinstance(attempt, dict) else ""
                ) or "",
            },
        )

    # ── Skip / Unskip ──────────────────────────────────────────────

    def _skip_or_unskip(
        self,
        params: dict[str, Any],
        mutation: str,
        op_name: str,
        capability: Capability,
    ) -> Any:
        billing_cycle_input = self._build_billing_cycle_input(params)
        data = self._gql(mutation, {
            "billingCycleInput": billing_cycle_input,
        })
        self._check_user_errors(data, op_name)
        payload = data.get(op_name) or {}
        return self._success(
            capability,
            data={
                "billing_cycle": self._normalise_cycle(
                    payload.get("billingCycle") or {}
                ),
            },
        )

    # ── Reschedule ─────────────────────────────────────────────────

    def _reschedule(self, params: dict[str, Any]) -> Any:
        billing_cycle_input = self._build_billing_cycle_input(params)

        billing_date = (
            params.get("billing_date") or params.get("billingDate")
        )
        skip = params.get("skip")
        if (
            (not isinstance(billing_date, str) or not billing_date.strip())
            and skip is None
        ):
            raise AdapterValidationError(
                self.name,
                "reschedule needs at least one of 'billing_date' "
                "(ISO-8601) or 'skip' (bool)",
            )

        reason = params.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise AdapterValidationError(
                self.name,
                f"'reason' is required — one of "
                f"{sorted(_VALID_REASONS)}",
            )
        reason_up = reason.strip().upper()
        if reason_up not in _VALID_REASONS:
            raise AdapterValidationError(
                self.name,
                f"'reason' must be one of {sorted(_VALID_REASONS)}",
            )

        edit_input: dict[str, Any] = {"reason": reason_up}
        if isinstance(billing_date, str) and billing_date.strip():
            edit_input["billingDate"] = billing_date.strip()
        if skip is not None:
            edit_input["skip"] = bool(skip)

        data = self._gql(_RESCHEDULE_CYCLE_MUTATION, {
            "billingCycleInput": billing_cycle_input,
            "input": edit_input,
        })
        self._check_user_errors(data, "subscriptionBillingCycleScheduleEdit")
        payload = data.get(
            "subscriptionBillingCycleScheduleEdit"
        ) or {}
        return self._success(
            Capability.SHOPIFY_RESCHEDULE_SUBSCRIPTION_BILLING_CYCLE,
            data={
                "billing_cycle": self._normalise_cycle(
                    payload.get("billingCycle") or {}
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _build_billing_cycle_input(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        contract_id = (
            params.get("contract_id")
            or params.get("subscription_contract_id")
            or params.get("subscriptionContractId")
            or params.get("contractId")
        )
        if not isinstance(contract_id, str) or not contract_id.strip():
            raise AdapterValidationError(
                self.name,
                "'contract_id' (Shopify GID for the SubscriptionContract) "
                "is required",
            )
        selector = self._build_selector(params)
        return {
            "contractId": contract_id.strip(),
            "selector": selector,
        }

    def _build_selector(self, params: dict[str, Any]) -> dict[str, Any]:
        cycle_index = params.get("cycle_index") or params.get("cycleIndex")
        date = params.get("date")
        if cycle_index is None and date is None:
            raise AdapterValidationError(
                self.name,
                "selector needs 'cycle_index' (int, 1-based) OR "
                "'date' (ISO-8601 datetime)",
            )
        if cycle_index is not None and date is not None:
            raise AdapterValidationError(
                self.name,
                "selector takes 'cycle_index' OR 'date', not both",
            )
        out: dict[str, Any] = {}
        if cycle_index is not None:
            try:
                idx = int(cycle_index)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, "'cycle_index' must be an int",
                ) from exc
            if idx < 1:
                raise AdapterValidationError(
                    self.name,
                    "'cycle_index' must be >= 1 (1-based)",
                )
            out["index"] = idx
        if date is not None:
            if not isinstance(date, str):
                raise AdapterValidationError(
                    self.name,
                    "'date' must be ISO-8601 datetime string",
                )
            out["date"] = date.strip()
        return out

    @staticmethod
    def _normalise_cycle(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        try:
            cycle_idx = int(node.get("cycleIndex") or 0)
        except (TypeError, ValueError):
            cycle_idx = 0
        return {
            "cycle_index": cycle_idx,
            "cycle_start_at": node.get("cycleStartAt", "") or "",
            "cycle_end_at": node.get("cycleEndAt", "") or "",
            "billing_attempt_expected_date": (
                node.get("billingAttemptExpectedDate", "") or ""
            ),
            "skipped": bool(node.get("skipped", False)),
            "edited": bool(node.get("edited", False)),
            "status": node.get("status", "") or "",
        }
