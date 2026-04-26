"""ShopifySubscriptionDraftFreeShippingAdapter — sub-draft free-ship.

Companion to ``subscription_draft.py`` (which opens / commits the
draft) and ``subscription_billing.py`` (charge / refund cycles).
Inside an open SubscriptionDraft, a merchant can attach a
free-shipping incentive that applies to all subsequent billings
of the contract for a bounded number of cycles. Distinct from
storefront-level free-shipping discounts (Phase 25.3) — this one
lives entirely inside the subscription contract and bypasses
discount-code redemption.

ShopAI's retention engine writes these:

  * Goodwill credit on a save-the-customer flow ("free shipping for
    your next 3 deliveries while we sort out the supply issue").
  * Tier promotion ("you're now Gold tier — free shipping on every
    monthly box for the rest of the year").
  * Refresh the cycle limit when the merchant decides to extend
    a previously-applied incentive.

Capabilities:

  * ``SHOPIFY_SUBSCRIPTION_DRAFT_ADD_FREE_SHIPPING`` —
    subscriptionDraftFreeShippingDiscountAdd. Pattern A: draftId
    at field level + ``input`` body
    (SubscriptionFreeShippingDiscountInput: title +
    recurringCycleLimit).
  * ``SHOPIFY_SUBSCRIPTION_DRAFT_UPDATE_FREE_SHIPPING`` —
    subscriptionDraftFreeShippingDiscountUpdate. Same shape +
    discountId at field level.
  * ``SHOPIFY_SUBSCRIPTION_DRAFT_REMOVE_DISCOUNT`` —
    subscriptionDraftDiscountRemove. Covers removing the free-
    shipping discount AND manual percentage/amount discounts;
    Shopify's mutation is type-agnostic.

Friendly call shape (add)::

    {"draft_id":               "gid://shopify/SubscriptionDraft/1",
     "title":                  "Gold tier free shipping",
     "recurring_cycle_limit":  12}

Pattern A — draftId / discountId at field level.
Pattern F — SubscriptionDraftUserError carries the ``code`` field
(introspection confirmed).

Pattern E note: gated by ``write_own_subscription_contracts`` /
``write_subscription_contracts``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_DISCOUNT_FIELDS = """
id
title
type
targetType
recurringCycleLimit
usageCount
""".strip()


_ADD_FREE_SHIPPING_MUTATION = f"""
mutation subscriptionDraftFreeShippingDiscountAdd(
  $draftId: ID!,
  $input: SubscriptionFreeShippingDiscountInput!
) {{
  subscriptionDraftFreeShippingDiscountAdd(
    draftId: $draftId, input: $input
  ) {{
    discountAdded {{
      {_DISCOUNT_FIELDS}
    }}
    draft {{
      id
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_FREE_SHIPPING_MUTATION = f"""
mutation subscriptionDraftFreeShippingDiscountUpdate(
  $draftId: ID!,
  $discountId: ID!,
  $input: SubscriptionFreeShippingDiscountInput!
) {{
  subscriptionDraftFreeShippingDiscountUpdate(
    draftId: $draftId,
    discountId: $discountId,
    input: $input
  ) {{
    discountUpdated {{
      {_DISCOUNT_FIELDS}
    }}
    draft {{
      id
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_REMOVE_DISCOUNT_MUTATION = """
mutation subscriptionDraftDiscountRemove(
  $draftId: ID!,
  $discountId: ID!
) {
  subscriptionDraftDiscountRemove(
    draftId: $draftId, discountId: $discountId
  ) {
    discountRemoved {
      ... on SubscriptionManualDiscount {
        id
        title
      }
      ... on SubscriptionAppliedCodeDiscount {
        id
      }
    }
    draft {
      id
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


class ShopifySubscriptionDraftFreeShippingAdapter(ShopifyBaseAdapter):
    name = "shopify_subscription_draft_free_shipping"
    capabilities = {
        Capability.SHOPIFY_SUBSCRIPTION_DRAFT_ADD_FREE_SHIPPING,
        Capability.SHOPIFY_SUBSCRIPTION_DRAFT_UPDATE_FREE_SHIPPING,
        Capability.SHOPIFY_SUBSCRIPTION_DRAFT_REMOVE_DISCOUNT,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_SUBSCRIPTION_DRAFT_ADD_FREE_SHIPPING:
            return self._add(params)
        if capability == \
                Capability.SHOPIFY_SUBSCRIPTION_DRAFT_UPDATE_FREE_SHIPPING:
            return self._update(params)
        if capability == \
                Capability.SHOPIFY_SUBSCRIPTION_DRAFT_REMOVE_DISCOUNT:
            return self._remove(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Add free shipping ──────────────────────────────────────────

    def _add(self, params: dict[str, Any]) -> Any:
        draft_id = self._extract_draft_id(params)
        body = self._build_input(params, require_title=True)
        data = self._gql(_ADD_FREE_SHIPPING_MUTATION, {
            "draftId": draft_id, "input": body,
        })
        self._check_user_errors(
            data, "subscriptionDraftFreeShippingDiscountAdd",
        )
        payload = data.get(
            "subscriptionDraftFreeShippingDiscountAdd",
        ) or {}
        return self._success(
            Capability.SHOPIFY_SUBSCRIPTION_DRAFT_ADD_FREE_SHIPPING,
            data={
                "discount": self._normalise(
                    payload.get("discountAdded") or {},
                ),
                "draft_id": (
                    (payload.get("draft") or {}).get("id", "")
                    or draft_id
                ),
            },
        )

    # ── Update free shipping ───────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        draft_id = self._extract_draft_id(params)
        discount_id = self._extract_discount_id(params)
        body = self._build_input(params, require_title=False)
        if not body:
            raise AdapterValidationError(
                self.name,
                "supply at least one of 'title' / "
                "'recurring_cycle_limit'",
            )
        data = self._gql(_UPDATE_FREE_SHIPPING_MUTATION, {
            "draftId": draft_id,
            "discountId": discount_id,
            "input": body,
        })
        self._check_user_errors(
            data, "subscriptionDraftFreeShippingDiscountUpdate",
        )
        payload = data.get(
            "subscriptionDraftFreeShippingDiscountUpdate",
        ) or {}
        return self._success(
            Capability.SHOPIFY_SUBSCRIPTION_DRAFT_UPDATE_FREE_SHIPPING,
            data={
                "discount": self._normalise(
                    payload.get("discountUpdated") or {},
                ),
                "draft_id": (
                    (payload.get("draft") or {}).get("id", "")
                    or draft_id
                ),
            },
        )

    # ── Remove discount ────────────────────────────────────────────

    def _remove(self, params: dict[str, Any]) -> Any:
        draft_id = self._extract_draft_id(params)
        discount_id = self._extract_discount_id(params)
        data = self._gql(_REMOVE_DISCOUNT_MUTATION, {
            "draftId": draft_id, "discountId": discount_id,
        })
        self._check_user_errors(
            data, "subscriptionDraftDiscountRemove",
        )
        payload = data.get(
            "subscriptionDraftDiscountRemove",
        ) or {}
        removed = payload.get("discountRemoved") or {}
        return self._success(
            Capability.SHOPIFY_SUBSCRIPTION_DRAFT_REMOVE_DISCOUNT,
            data={
                "removed_id": (
                    removed.get("id", "")
                    if isinstance(removed, dict) else ""
                ) or discount_id,
                "removed_title": (
                    removed.get("title", "")
                    if isinstance(removed, dict) else ""
                ) or "",
                "draft_id": (
                    (payload.get("draft") or {}).get("id", "")
                    or draft_id
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_draft_id(self, params: dict[str, Any]) -> str:
        draft_id = (
            params.get("draft_id")
            or params.get("draftId")
            or params.get("subscription_draft_id")
        )
        if not isinstance(draft_id, str) or not draft_id.strip():
            raise AdapterValidationError(
                self.name,
                "'draft_id' (Shopify GID for the open "
                "SubscriptionDraft) is required",
            )
        return draft_id.strip()

    def _extract_discount_id(self, params: dict[str, Any]) -> str:
        discount_id = (
            params.get("discount_id")
            or params.get("discountId")
        )
        if not isinstance(discount_id, str) or \
                not discount_id.strip():
            raise AdapterValidationError(
                self.name,
                "'discount_id' (Shopify GID for the existing "
                "discount on the draft) is required",
            )
        return discount_id.strip()

    def _build_input(
        self, params: dict[str, Any], *, require_title: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        title = params.get("title")
        if title is not None:
            if not isinstance(title, str) or not title.strip():
                raise AdapterValidationError(
                    self.name,
                    "'title' must be a non-empty string",
                )
            out["title"] = title.strip()
        elif require_title:
            raise AdapterValidationError(
                self.name,
                "'title' is required (the operator-facing label "
                "for the free-shipping incentive)",
            )

        if "recurring_cycle_limit" in params:
            cycles = params["recurring_cycle_limit"]
        elif "recurringCycleLimit" in params:
            cycles = params["recurringCycleLimit"]
        else:
            cycles = None
        if cycles is not None:
            try:
                cycles_int = int(cycles)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'recurring_cycle_limit' must be an integer",
                ) from exc
            if cycles_int < 1:
                raise AdapterValidationError(
                    self.name,
                    "'recurring_cycle_limit' must be >= 1",
                )
            out["recurringCycleLimit"] = cycles_int

        return out

    @staticmethod
    def _normalise(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "type": node.get("type", "") or "",
            "target_type": node.get("targetType", "") or "",
            "recurring_cycle_limit": int(
                node.get("recurringCycleLimit", 0) or 0,
            ),
            "usage_count": int(node.get("usageCount", 0) or 0),
        }
