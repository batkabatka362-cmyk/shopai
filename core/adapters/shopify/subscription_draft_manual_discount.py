"""ShopifySubscriptionDraftManualDiscountAdapter — manual + code disc.

Companion to ``subscription_draft_free_shipping.py`` (Phase 26.5,
free-shipping incentives) and ``subscription_draft.py`` (which opens
and commits the draft itself). Inside an open SubscriptionDraft, a
merchant can attach two flavours of incentive that aren't free
shipping:

  * **Manual discount** — operator-defined percentage off (e.g. 10%
    off all line items for the next 6 cycles) or fixed-amount
    (e.g. $5 off shipping per cycle for 12 cycles). Bypasses the
    storefront discount-code system entirely; the discount lives
    entirely inside the contract.
  * **Discount code application** — apply an existing storefront
    discount code (already minted via discount_code_basic etc.) to
    the contract. The merchant's normal SUBSCRIBE10 code can be
    re-applied per-customer through this flow.

ShopAI's retention engine writes these:
  * Save-the-customer goodwill ("here's 15% off your next 4 boxes
    while we sort out the supply issue").
  * Tier upgrade ("you're now a $5/box Gold member — apply that
    rate going forward").
  * Re-apply a CYBERMONDAY storefront code post-purchase to a
    customer who had a checkout error and lost the discount.

Capabilities:

  * ``SHOPIFY_SUBSCRIPTION_DRAFT_ADD_MANUAL_DISCOUNT`` —
    subscriptionDraftDiscountAdd. Pattern A: draftId at field
    level + ``input`` (SubscriptionManualDiscountInput).
  * ``SHOPIFY_SUBSCRIPTION_DRAFT_UPDATE_MANUAL_DISCOUNT`` —
    subscriptionDraftDiscountUpdate. Same shape + discountId.
  * ``SHOPIFY_SUBSCRIPTION_DRAFT_APPLY_DISCOUNT_CODE`` —
    subscriptionDraftDiscountCodeApply. draftId + plain redeemCode
    string.

Friendly call shape (manual percentage, all lines)::

    {"draft_id":              "gid://shopify/SubscriptionDraft/1",
     "title":                 "Goodwill 15%",
     "value": {"percentage": 15},
     "recurring_cycle_limit": 4,
     "entitled_lines":  {"all": True}}

Friendly call shape (fixed amount, scoped lines)::

    {"draft_id":              "gid://shopify/SubscriptionDraft/1",
     "title":                 "$5 line credit",
     "value": {"fixed_amount": {"amount": 5.00,
                                "applies_on_each_item": True}},
     "entitled_lines": {"lines": {"add": [
        "gid://shopify/SubscriptionLine/9",
     ]}}}

Pattern A — draftId / discountId at field level.
Pattern F — SubscriptionDraftUserError carries `code`.
Note: the ADD mutation's ``discountAdded`` returns the concrete
``SubscriptionManualDiscount`` type (NOT a union — distinct from
the REMOVE mutation in Phase 26.5 which returns the
``SubscriptionDiscount`` union).

Pattern E note: gated by ``write_own_subscription_contracts``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_MANUAL_DISCOUNT_FIELDS = """
id
title
type
targetType
recurringCycleLimit
usageCount
""".strip()


_ADD_MUTATION = f"""
mutation subscriptionDraftDiscountAdd(
  $draftId: ID!,
  $input: SubscriptionManualDiscountInput!
) {{
  subscriptionDraftDiscountAdd(
    draftId: $draftId, input: $input
  ) {{
    discountAdded {{
      {_MANUAL_DISCOUNT_FIELDS}
    }}
    draft {{ id }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_MUTATION = f"""
mutation subscriptionDraftDiscountUpdate(
  $draftId: ID!,
  $discountId: ID!,
  $input: SubscriptionManualDiscountInput!
) {{
  subscriptionDraftDiscountUpdate(
    draftId: $draftId,
    discountId: $discountId,
    input: $input
  ) {{
    discountUpdated {{
      {_MANUAL_DISCOUNT_FIELDS}
    }}
    draft {{ id }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_APPLY_CODE_MUTATION = """
mutation subscriptionDraftDiscountCodeApply(
  $draftId: ID!,
  $redeemCode: String!
) {
  subscriptionDraftDiscountCodeApply(
    draftId: $draftId, redeemCode: $redeemCode
  ) {
    appliedDiscount {
      id
      redeemCode
      rejectionReason
    }
    draft { id }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


class ShopifySubscriptionDraftManualDiscountAdapter(ShopifyBaseAdapter):
    name = "shopify_subscription_draft_manual_discount"
    capabilities = {
        Capability.SHOPIFY_SUBSCRIPTION_DRAFT_ADD_MANUAL_DISCOUNT,
        Capability.SHOPIFY_SUBSCRIPTION_DRAFT_UPDATE_MANUAL_DISCOUNT,
        Capability.SHOPIFY_SUBSCRIPTION_DRAFT_APPLY_DISCOUNT_CODE,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_SUBSCRIPTION_DRAFT_ADD_MANUAL_DISCOUNT:
            return self._add(params)
        if capability == \
                Capability.SHOPIFY_SUBSCRIPTION_DRAFT_UPDATE_MANUAL_DISCOUNT:
            return self._update(params)
        if capability == \
                Capability.SHOPIFY_SUBSCRIPTION_DRAFT_APPLY_DISCOUNT_CODE:
            return self._apply_code(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Add ────────────────────────────────────────────────────────

    def _add(self, params: dict[str, Any]) -> Any:
        draft_id = self._extract_draft_id(params)
        body = self._build_input(params, require_title=True)
        data = self._gql(_ADD_MUTATION, {
            "draftId": draft_id, "input": body,
        })
        self._check_user_errors(data, "subscriptionDraftDiscountAdd")
        payload = data.get("subscriptionDraftDiscountAdd") or {}
        return self._success(
            Capability.SHOPIFY_SUBSCRIPTION_DRAFT_ADD_MANUAL_DISCOUNT,
            data={
                "discount": self._normalise_manual(
                    payload.get("discountAdded") or {},
                ),
                "draft_id": (
                    (payload.get("draft") or {}).get("id", "")
                    or draft_id
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        draft_id = self._extract_draft_id(params)
        discount_id = self._extract_discount_id(params)
        body = self._build_input(params, require_title=False)
        if not body:
            raise AdapterValidationError(
                self.name,
                "supply at least one of: title, value, "
                "recurring_cycle_limit, entitled_lines",
            )
        data = self._gql(_UPDATE_MUTATION, {
            "draftId": draft_id,
            "discountId": discount_id,
            "input": body,
        })
        self._check_user_errors(data, "subscriptionDraftDiscountUpdate")
        payload = data.get("subscriptionDraftDiscountUpdate") or {}
        return self._success(
            Capability.SHOPIFY_SUBSCRIPTION_DRAFT_UPDATE_MANUAL_DISCOUNT,
            data={
                "discount": self._normalise_manual(
                    payload.get("discountUpdated") or {},
                ),
                "draft_id": (
                    (payload.get("draft") or {}).get("id", "")
                    or draft_id
                ),
            },
        )

    # ── Apply discount code ────────────────────────────────────────

    def _apply_code(self, params: dict[str, Any]) -> Any:
        draft_id = self._extract_draft_id(params)
        redeem_code = (
            params.get("redeem_code")
            or params.get("redeemCode")
            or params.get("code")
        )
        if not isinstance(redeem_code, str) or not redeem_code.strip():
            raise AdapterValidationError(
                self.name,
                "'redeem_code' is required (the storefront discount "
                "code to re-apply to the contract draft)",
            )
        data = self._gql(_APPLY_CODE_MUTATION, {
            "draftId": draft_id,
            "redeemCode": redeem_code.strip(),
        })
        self._check_user_errors(
            data, "subscriptionDraftDiscountCodeApply",
        )
        payload = data.get(
            "subscriptionDraftDiscountCodeApply",
        ) or {}
        applied = payload.get("appliedDiscount") or {}
        return self._success(
            Capability.SHOPIFY_SUBSCRIPTION_DRAFT_APPLY_DISCOUNT_CODE,
            data={
                "discount_id": (
                    applied.get("id", "")
                    if isinstance(applied, dict) else ""
                ) or "",
                "redeem_code": (
                    applied.get("redeemCode", "")
                    if isinstance(applied, dict) else ""
                ) or redeem_code.strip(),
                "rejection_reason": (
                    applied.get("rejectionReason", "")
                    if isinstance(applied, dict) else ""
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
                "manual discount on the draft) is required",
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
                    self.name, "'title' must be a non-empty string",
                )
            out["title"] = title.strip()
        elif require_title:
            raise AdapterValidationError(
                self.name,
                "'title' is required (the operator-facing label "
                "for this manual discount)",
            )

        value = params.get("value")
        if value is not None:
            out["value"] = self._build_value(value)

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

        entitled = params.get("entitled_lines") or params.get(
            "entitledLines",
        )
        if entitled is not None:
            out["entitledLines"] = self._build_entitled_lines(entitled)

        return out

    def _build_value(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'value' must be a dict — supply 'percentage' (int) "
                "OR 'fixed_amount' (dict)",
            )
        percentage = raw.get("percentage")
        fixed = raw.get("fixed_amount") or raw.get("fixedAmount")
        if percentage is not None and fixed is not None:
            raise AdapterValidationError(
                self.name,
                "'value' may set 'percentage' OR 'fixed_amount' — "
                "not both",
            )
        if percentage is not None:
            try:
                pct_int = int(percentage)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'value.percentage' must be an integer 1-100",
                ) from exc
            if pct_int < 1 or pct_int > 100:
                raise AdapterValidationError(
                    self.name,
                    "'value.percentage' must be between 1 and 100",
                )
            return {"percentage": pct_int}
        if fixed is not None:
            if not isinstance(fixed, dict):
                raise AdapterValidationError(
                    self.name,
                    "'value.fixed_amount' must be a dict {amount, "
                    "applies_on_each_item?}",
                )
            amount = fixed.get("amount")
            try:
                amount_float = float(amount)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'value.fixed_amount.amount' must be numeric",
                ) from exc
            if amount_float < 0:
                raise AdapterValidationError(
                    self.name,
                    "'value.fixed_amount.amount' must be >= 0",
                )
            applies_each = (
                fixed.get("applies_on_each_item")
                if "applies_on_each_item" in fixed
                else fixed.get("appliesOnEachItem")
            )
            out: dict[str, Any] = {"amount": amount_float}
            if applies_each is not None:
                out["appliesOnEachItem"] = bool(applies_each)
            return {"fixedAmount": out}
        raise AdapterValidationError(
            self.name,
            "'value' must include 'percentage' or 'fixed_amount'",
        )

    def _build_entitled_lines(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'entitled_lines' must be a dict — supply 'all' OR "
                "'lines' (with add/remove)",
            )
        if raw.get("all"):
            return {"all": True}
        lines_raw = raw.get("lines")
        if not isinstance(lines_raw, dict):
            raise AdapterValidationError(
                self.name,
                "'entitled_lines.lines' must be a dict {add?, remove?}",
            )
        out: dict[str, Any] = {}
        for key in ("add", "remove"):
            ids = lines_raw.get(key)
            if ids is None:
                continue
            if isinstance(ids, str):
                ids = [ids]
            if not isinstance(ids, list) or not all(
                isinstance(v, str) for v in ids
            ):
                raise AdapterValidationError(
                    self.name,
                    f"'entitled_lines.lines.{key}' must be a list "
                    "of SubscriptionLine GIDs",
                )
            cleaned = [v.strip() for v in ids if v.strip()]
            if cleaned:
                out[key] = cleaned
        if not out:
            raise AdapterValidationError(
                self.name,
                "'entitled_lines.lines' must include 'add' or "
                "'remove'",
            )
        return {"lines": out}

    @staticmethod
    def _normalise_manual(node: dict[str, Any]) -> dict[str, Any]:
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
