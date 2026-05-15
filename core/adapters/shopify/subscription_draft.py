"""ShopifySubscriptionDraftAdapter — modify live subscription contracts.

Companion to ``subscriptions.py`` (which lists / pauses / resumes /
cancels live SubscriptionContract records). The DRAFT surface is
how engines make GRANULAR EDITS to a live contract: change the next
billing date, swap a variant, adjust quantity, update billing
address, etc. — without cancelling and re-creating.

Workflow has THREE wire steps:

  1. ``subscriptionContractUpdate`` — opens a SubscriptionDraft
     against the live contract. Returns a draft GID engines edit.
  2. (Optional) ``subscriptionDraftUpdate`` — apply input mutations
     (next_billing_date / shipping_address / note / payment_method).
     Engines that need item-level edits (line add/remove/quantity)
     use the dedicated subscriptionDraftLine* mutations which live
     in their own sub-surface and are out of scope here.
  3. ``subscriptionDraftCommit`` — apply the draft back to the live
     contract atomically. After commit the draft is gone; the
     contract reflects the new state.

ShopAI's subscription engine uses these to:

  * Re-bill on a different cadence after a customer requests "every
    8 weeks instead of 4".
  * Update the shipping address on file when the customer moves.
  * Re-link to a fresh payment method after the previous one was
    revoked (the customer_payment_methods.py revoke flow).

Capabilities:

  * ``SHOPIFY_CREATE_SUBSCRIPTION_DRAFT`` — open a draft against
    a live contract.
  * ``SHOPIFY_UPDATE_SUBSCRIPTION_DRAFT`` — apply input mutations.
  * ``SHOPIFY_COMMIT_SUBSCRIPTION_DRAFT`` — atomically apply.

Pattern A: ``subscriptionContractUpdate`` takes the contract id at
field level. ``subscriptionDraftUpdate`` takes the draft id at
field level + an input. ``subscriptionDraftCommit`` takes only the
draft id. Same convention as orderEdit / orderClose.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_DRAFT_FIELDS = """
id
status
nextBillingDate
note
""".strip()


_CREATE_DRAFT_MUTATION = f"""
mutation subscriptionContractUpdate($contractId: ID!) {{
  subscriptionContractUpdate(contractId: $contractId) {{
    draft {{
      {_DRAFT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_DRAFT_MUTATION = f"""
mutation subscriptionDraftUpdate(
  $draftId: ID!,
  $input: SubscriptionDraftInput!
) {{
  subscriptionDraftUpdate(draftId: $draftId, input: $input) {{
    draft {{
      {_DRAFT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_COMMIT_DRAFT_MUTATION = """
mutation subscriptionDraftCommit($draftId: ID!) {
  subscriptionDraftCommit(draftId: $draftId) {
    contract {
      id
      status
      nextBillingDate
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


class ShopifySubscriptionDraftAdapter(ShopifyBaseAdapter):
    name = "shopify_subscription_draft"
    capabilities = {
        Capability.SHOPIFY_CREATE_SUBSCRIPTION_DRAFT,
        Capability.SHOPIFY_UPDATE_SUBSCRIPTION_DRAFT,
        Capability.SHOPIFY_COMMIT_SUBSCRIPTION_DRAFT,
    }
    required_scopes = frozenset({"write_own_subscription_contracts"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_SUBSCRIPTION_DRAFT:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_SUBSCRIPTION_DRAFT:
            return self._update(params)
        if capability == Capability.SHOPIFY_COMMIT_SUBSCRIPTION_DRAFT:
            return self._commit(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        contract_id = params.get("contract_id") or params.get("contractId")
        if not isinstance(contract_id, str) or not contract_id.strip():
            raise AdapterValidationError(
                self.name,
                "'contract_id' (Shopify GID for the SubscriptionContract) "
                "is required",
            )
        data = self._gql(_CREATE_DRAFT_MUTATION, {
            "contractId": contract_id.strip(),
        })
        self._check_user_errors(data, "subscriptionContractUpdate")
        payload = data.get("subscriptionContractUpdate") or {}
        draft = payload.get("draft") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_SUBSCRIPTION_DRAFT,
            data={
                "draft_id": draft.get("id", "") or "",
                "status": draft.get("status", "") or "",
                "next_billing_date": draft.get("nextBillingDate", "") or "",
                "note": draft.get("note", "") or "",
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        draft_id = params.get("draft_id") or params.get("draftId")
        if not isinstance(draft_id, str) or not draft_id.strip():
            raise AdapterValidationError(
                self.name,
                "'draft_id' (Shopify GID for the SubscriptionDraft) is required",
            )

        draft_input = self._build_input(params)
        if not draft_input:
            raise AdapterValidationError(
                self.name,
                "no updatable fields supplied (next_billing_date, note, "
                "payment_method_id)",
            )

        data = self._gql(_UPDATE_DRAFT_MUTATION, {
            "draftId": draft_id.strip(),
            "input": draft_input,
        })
        self._check_user_errors(data, "subscriptionDraftUpdate")
        payload = data.get("subscriptionDraftUpdate") or {}
        draft = payload.get("draft") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_SUBSCRIPTION_DRAFT,
            data={
                "draft_id": draft.get("id", "") or "",
                "status": draft.get("status", "") or "",
                "next_billing_date": draft.get("nextBillingDate", "") or "",
                "note": draft.get("note", "") or "",
            },
        )

    # ── Commit ────────────────────────────────────────────────────

    def _commit(self, params: dict[str, Any]) -> Any:
        draft_id = params.get("draft_id") or params.get("draftId")
        if not isinstance(draft_id, str) or not draft_id.strip():
            raise AdapterValidationError(
                self.name,
                "'draft_id' (Shopify GID for the SubscriptionDraft) is required",
            )
        data = self._gql(_COMMIT_DRAFT_MUTATION, {
            "draftId": draft_id.strip(),
        })
        self._check_user_errors(data, "subscriptionDraftCommit")
        payload = data.get("subscriptionDraftCommit") or {}
        contract = payload.get("contract") or {}
        return self._success(
            Capability.SHOPIFY_COMMIT_SUBSCRIPTION_DRAFT,
            data={
                "contract_id": contract.get("id", "") or "",
                "status": contract.get("status", "") or "",
                "next_billing_date": (
                    contract.get("nextBillingDate", "") or ""
                ),
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_input(self, params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}

        next_billing = params.get("next_billing_date") or params.get(
            "nextBillingDate"
        )
        if next_billing is not None:
            if not isinstance(next_billing, str):
                raise AdapterValidationError(
                    self.name,
                    "'next_billing_date' must be ISO-8601 string",
                )
            out["nextBillingDate"] = next_billing.strip()

        note = params.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    self.name, "'note' must be a string",
                )
            out["note"] = note

        payment_method_id = params.get("payment_method_id") or params.get(
            "paymentMethodId"
        )
        if payment_method_id is not None:
            if not isinstance(payment_method_id, str):
                raise AdapterValidationError(
                    self.name, "'payment_method_id' must be a string GID",
                )
            out["paymentMethodId"] = payment_method_id.strip()

        return out
