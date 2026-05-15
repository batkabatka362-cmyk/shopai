"""ShopifyDiscountActivateAdapter — toggle discount status.

Companion to all four discount-write adapters (discounts.py,
discount_automatic.py, discount_code_bxgy.py,
discount_code_free_shipping.py, discount_automatic_bxgy.py).
None of them currently expose the activate/deactivate primitives
even though Shopify ships them as separate mutations from
create/update.

ShopAI's pricing + campaign engines lean on this:

  * **Soft launch / staged rollout.** Create a discount in DRAFT
    (or with future startsAt), then activate it explicitly when
    the campaign timing window hits. Beats relying on Shopify's
    background scheduler.
  * **Emergency kill-switch.** Deactivate a buggy discount in one
    call without deleting it — keeps the audit trail intact and
    lets the operator re-activate after the fix.
  * **A/B rotation.** Toggle two parallel discount nodes
    (variant A active, variant B paused) without rebuilding them
    each cycle.

Capabilities:

  * ``SHOPIFY_ACTIVATE_AUTOMATIC_DISCOUNT``    — discountAutomaticActivate
  * ``SHOPIFY_DEACTIVATE_AUTOMATIC_DISCOUNT``  — discountAutomaticDeactivate
  * ``SHOPIFY_ACTIVATE_CODE_DISCOUNT``         — discountCodeActivate
  * ``SHOPIFY_DEACTIVATE_CODE_DISCOUNT``       — discountCodeDeactivate

All four take a single ``id`` argument at the GraphQL field level
(Pattern A) and return a ``DiscountUserError`` userErrors envelope
(has ``code``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_AUTOMATIC_NODE_FIELDS = """
id
automaticDiscount {
  __typename
  ... on DiscountAutomaticBasic {
    title status startsAt endsAt
  }
  ... on DiscountAutomaticBxgy {
    title status startsAt endsAt
  }
  ... on DiscountAutomaticFreeShipping {
    title status startsAt endsAt
  }
}
""".strip()


_CODE_NODE_FIELDS = """
id
codeDiscount {
  __typename
  ... on DiscountCodeBasic {
    title status startsAt endsAt
  }
  ... on DiscountCodeBxgy {
    title status startsAt endsAt
  }
  ... on DiscountCodeFreeShipping {
    title status startsAt endsAt
  }
}
""".strip()


_ACTIVATE_AUTOMATIC_MUTATION = f"""
mutation discountAutomaticActivate($id: ID!) {{
  discountAutomaticActivate(id: $id) {{
    automaticDiscountNode {{
      {_AUTOMATIC_NODE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DEACTIVATE_AUTOMATIC_MUTATION = f"""
mutation discountAutomaticDeactivate($id: ID!) {{
  discountAutomaticDeactivate(id: $id) {{
    automaticDiscountNode {{
      {_AUTOMATIC_NODE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_ACTIVATE_CODE_MUTATION = f"""
mutation discountCodeActivate($id: ID!) {{
  discountCodeActivate(id: $id) {{
    codeDiscountNode {{
      {_CODE_NODE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DEACTIVATE_CODE_MUTATION = f"""
mutation discountCodeDeactivate($id: ID!) {{
  discountCodeDeactivate(id: $id) {{
    codeDiscountNode {{
      {_CODE_NODE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


class ShopifyDiscountActivateAdapter(ShopifyBaseAdapter):
    name = "shopify_discount_activate"
    capabilities = {
        Capability.SHOPIFY_ACTIVATE_AUTOMATIC_DISCOUNT,
        Capability.SHOPIFY_DEACTIVATE_AUTOMATIC_DISCOUNT,
        Capability.SHOPIFY_ACTIVATE_CODE_DISCOUNT,
        Capability.SHOPIFY_DEACTIVATE_CODE_DISCOUNT,
    }
    required_scopes = frozenset({"write_discounts"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_ACTIVATE_AUTOMATIC_DISCOUNT:
            return self._toggle_automatic(
                params, _ACTIVATE_AUTOMATIC_MUTATION,
                "discountAutomaticActivate",
                Capability.SHOPIFY_ACTIVATE_AUTOMATIC_DISCOUNT,
            )
        if capability == Capability.SHOPIFY_DEACTIVATE_AUTOMATIC_DISCOUNT:
            return self._toggle_automatic(
                params, _DEACTIVATE_AUTOMATIC_MUTATION,
                "discountAutomaticDeactivate",
                Capability.SHOPIFY_DEACTIVATE_AUTOMATIC_DISCOUNT,
            )
        if capability == Capability.SHOPIFY_ACTIVATE_CODE_DISCOUNT:
            return self._toggle_code(
                params, _ACTIVATE_CODE_MUTATION,
                "discountCodeActivate",
                Capability.SHOPIFY_ACTIVATE_CODE_DISCOUNT,
            )
        if capability == Capability.SHOPIFY_DEACTIVATE_CODE_DISCOUNT:
            return self._toggle_code(
                params, _DEACTIVATE_CODE_MUTATION,
                "discountCodeDeactivate",
                Capability.SHOPIFY_DEACTIVATE_CODE_DISCOUNT,
            )
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Toggle helpers ─────────────────────────────────────────────

    def _toggle_automatic(
        self,
        params: dict[str, Any],
        mutation: str,
        op_name: str,
        capability: Capability,
    ) -> Any:
        discount_id = self._extract_id(params)
        data = self._gql(mutation, {"id": discount_id})
        self._check_user_errors(data, op_name)
        payload = data.get(op_name) or {}
        node = payload.get("automaticDiscountNode") or {}
        return self._success(
            capability,
            data={
                "id": (
                    node.get("id", "") if isinstance(node, dict) else ""
                ) or "",
                "discount": self._normalise_inner(
                    (node.get("automaticDiscount") or {})
                    if isinstance(node, dict) else {}
                ),
            },
        )

    def _toggle_code(
        self,
        params: dict[str, Any],
        mutation: str,
        op_name: str,
        capability: Capability,
    ) -> Any:
        discount_id = self._extract_id(params)
        data = self._gql(mutation, {"id": discount_id})
        self._check_user_errors(data, op_name)
        payload = data.get(op_name) or {}
        node = payload.get("codeDiscountNode") or {}
        return self._success(
            capability,
            data={
                "id": (
                    node.get("id", "") if isinstance(node, dict) else ""
                ) or "",
                "discount": self._normalise_inner(
                    (node.get("codeDiscount") or {})
                    if isinstance(node, dict) else {}
                ),
            },
        )

    def _extract_id(self, params: dict[str, Any]) -> str:
        discount_id = (
            params.get("id")
            or params.get("discount_id")
            or params.get("discountId")
        )
        if not isinstance(discount_id, str) or not discount_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the discount node) is required",
            )
        return discount_id.strip()

    @staticmethod
    def _normalise_inner(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        return {
            "type": node.get("__typename", "") or "",
            "title": node.get("title", "") or "",
            "status": node.get("status", "") or "",
            "starts_at": node.get("startsAt", "") or "",
            "ends_at": node.get("endsAt", "") or "",
        }
