"""ShopifyPaymentTermsAdapter — B2B net-30/60 payment terms.

Payment terms attach a "pay later by date X" promise to an order
or draft order. Standard B2B flavours: NET (pay in N days),
FIXED (pay by specific date), DUE_ON_RECEIPT, DUE_ON_FULFILLMENT.
ShopAI's B2B engine reads + writes these to:

  * Quote NET-30 / NET-60 to qualified company-tier customers in
    cart preview.
  * Update order payment terms when a buyer's company tier changes
    mid-flight.
  * Surface "this order is overdue" diagnostics for AR follow-up.

Capabilities:

  * ``SHOPIFY_LIST_PAYMENT_TERMS_TEMPLATES`` — list available
    templates the merchant has configured.
  * ``SHOPIFY_CREATE_PAYMENT_TERMS``   — attach payment terms to
    an order or draft order.
  * ``SHOPIFY_UPDATE_PAYMENT_TERMS``   — change terms / due date
    on an existing order.
  * ``SHOPIFY_DELETE_PAYMENT_TERMS``   — remove terms (revert to
    standard checkout).

Friendly create call shape::

    {"reference_type":     "ORDER",  # or DRAFT_ORDER
     "reference_id":       "gid://shopify/Order/1",
     "payment_terms_template_id": "gid://shopify/PaymentTermsTemplate/1",
     "schedules": [
       {"due_at": "2026-05-30T00:00:00Z"},
     ]}

Pattern E note: gated by ``write_payment_terms`` scope; terms only
work with the manual / "Payment by invoice" gateway. Live verify
will fail with ACCESS_DENIED unless the scope is granted AND the
manual-payment gateway is enabled.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_TEMPLATE_FIELDS = """
id
name
description
paymentTermsType
dueInDays
translatedName
""".strip()


_PAYMENT_TERMS_FIELDS = """
id
paymentTermsName
paymentTermsType
dueInDays
overdue
translatedName
paymentSchedules(first: 50) {
  edges {
    node {
      id
      dueAt
      issuedAt
      completedAt
      amount {
        amount
        currencyCode
      }
    }
  }
}
""".strip()


_LIST_TEMPLATES_QUERY = f"""
query paymentTermsTemplates {{
  paymentTermsTemplates {{
    {_TEMPLATE_FIELDS}
  }}
}}
""".strip()


_CREATE_PAYMENT_TERMS_MUTATION = f"""
mutation paymentTermsCreate(
  $referenceId: ID!,
  $paymentTermsAttributes: PaymentTermsCreateInput!
) {{
  paymentTermsCreate(
    referenceId: $referenceId,
    paymentTermsAttributes: $paymentTermsAttributes
  ) {{
    paymentTerms {{
      {_PAYMENT_TERMS_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_PAYMENT_TERMS_MUTATION = f"""
mutation paymentTermsUpdate(
  $input: PaymentTermsUpdateInput!
) {{
  paymentTermsUpdate(input: $input) {{
    paymentTerms {{
      {_PAYMENT_TERMS_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_PAYMENT_TERMS_MUTATION = """
mutation paymentTermsDelete($input: PaymentTermsDeleteInput!) {
  paymentTermsDelete(input: $input) {
    deletedId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_VALID_REFERENCE_TYPES = {"ORDER", "DRAFT_ORDER"}


class ShopifyPaymentTermsAdapter(ShopifyBaseAdapter):
    name = "shopify_payment_terms"
    capabilities = {
        Capability.SHOPIFY_LIST_PAYMENT_TERMS_TEMPLATES,
        Capability.SHOPIFY_CREATE_PAYMENT_TERMS,
        Capability.SHOPIFY_UPDATE_PAYMENT_TERMS,
        Capability.SHOPIFY_DELETE_PAYMENT_TERMS,
    }
    required_scopes = frozenset({"read_orders", "write_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_PAYMENT_TERMS_TEMPLATES:
            return self._list_templates(params)
        if capability == Capability.SHOPIFY_CREATE_PAYMENT_TERMS:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_PAYMENT_TERMS:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_PAYMENT_TERMS:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List templates ─────────────────────────────────────────────

    def _list_templates(self, _params: dict[str, Any]) -> Any:
        # Pattern B-adjacent: paymentTermsTemplates returns a flat
        # list, not an edges/node connection — small cardinality
        # (3-5 typical) so no pagination needed.
        data = self._gql(_LIST_TEMPLATES_QUERY, {})
        templates_raw = data.get("paymentTermsTemplates") or []
        templates = [
            self._normalise_template(t)
            for t in templates_raw if isinstance(t, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_PAYMENT_TERMS_TEMPLATES,
            data={
                "templates": templates,
                "count": len(templates),
            },
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        reference_id = params.get("reference_id") or params.get("referenceId")
        if not isinstance(reference_id, str) or not reference_id.strip():
            raise AdapterValidationError(
                self.name,
                "'reference_id' (Shopify GID for the Order or DraftOrder) "
                "is required",
            )

        attributes = self._build_create_attributes(params)
        data = self._gql(_CREATE_PAYMENT_TERMS_MUTATION, {
            "referenceId": reference_id.strip(),
            "paymentTermsAttributes": attributes,
        })
        self._check_user_errors(data, "paymentTermsCreate")
        payload = data.get("paymentTermsCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_PAYMENT_TERMS,
            data={
                "payment_terms": self._normalise_payment_terms(
                    payload.get("paymentTerms") or {},
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        terms_id = params.get("id") or params.get("payment_terms_id")
        if not isinstance(terms_id, str) or not terms_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the payment terms) is required",
            )

        out: dict[str, Any] = {"paymentTermsId": terms_id.strip()}

        template_id = params.get("payment_terms_template_id") or params.get(
            "paymentTermsTemplateId"
        )
        if template_id is not None:
            if not isinstance(template_id, str):
                raise AdapterValidationError(
                    self.name,
                    "'payment_terms_template_id' must be a string GID",
                )
            out["paymentTermsTemplateId"] = template_id.strip()

        schedules = self._build_schedules(params.get("schedules"))
        if schedules:
            out["paymentSchedules"] = schedules

        if len(out) == 1:
            raise AdapterValidationError(
                self.name,
                "no updatable fields supplied (payment_terms_template_id, "
                "schedules)",
            )

        data = self._gql(_UPDATE_PAYMENT_TERMS_MUTATION, {"input": out})
        self._check_user_errors(data, "paymentTermsUpdate")
        payload = data.get("paymentTermsUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_PAYMENT_TERMS,
            data={
                "payment_terms": self._normalise_payment_terms(
                    payload.get("paymentTerms") or {},
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        terms_id = params.get("id") or params.get("payment_terms_id")
        if not isinstance(terms_id, str) or not terms_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the payment terms) is required",
            )
        data = self._gql(_DELETE_PAYMENT_TERMS_MUTATION, {
            "input": {"paymentTermsId": terms_id.strip()},
        })
        self._check_user_errors(data, "paymentTermsDelete")
        payload = data.get("paymentTermsDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_PAYMENT_TERMS,
            data={
                "deleted_id": payload.get("deletedId", "") or "",
            },
        )

    # ── Input builders ─────────────────────────────────────────────

    def _build_create_attributes(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        template_id = params.get("payment_terms_template_id") or params.get(
            "paymentTermsTemplateId"
        )
        if not isinstance(template_id, str) or not template_id.strip():
            raise AdapterValidationError(
                self.name,
                "'payment_terms_template_id' is required (Shopify GID)",
            )
        out["paymentTermsTemplateId"] = template_id.strip()

        schedules = self._build_schedules(params.get("schedules"))
        if schedules:
            out["paymentSchedules"] = schedules

        return out

    def _build_schedules(self, raw: Any) -> list[dict[str, Any]]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise AdapterValidationError(
                self.name,
                "'schedules' must be a list of {due_at, issued_at?} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, s in enumerate(raw):
            if not isinstance(s, dict):
                raise AdapterValidationError(
                    self.name, f"schedules[{i}] must be a dict",
                )
            entry: dict[str, Any] = {}

            due_at = s.get("due_at") or s.get("dueAt")
            if due_at is not None:
                if not isinstance(due_at, str):
                    raise AdapterValidationError(
                        self.name,
                        f"schedules[{i}].due_at must be a string ISO-8601",
                    )
                entry["dueAt"] = due_at.strip()

            issued_at = s.get("issued_at") or s.get("issuedAt")
            if issued_at is not None:
                if not isinstance(issued_at, str):
                    raise AdapterValidationError(
                        self.name,
                        f"schedules[{i}].issued_at must be a string ISO-8601",
                    )
                entry["issuedAt"] = issued_at.strip()

            if not entry:
                raise AdapterValidationError(
                    self.name,
                    f"schedules[{i}] needs at least one of "
                    "'due_at' / 'issued_at'",
                )
            out.append(entry)
        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_template(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "translated_name": node.get("translatedName", "") or "",
            "description": node.get("description", "") or "",
            "type": node.get("paymentTermsType", "") or "",
            "due_in_days": int(node.get("dueInDays") or 0),
        }

    @classmethod
    def _normalise_payment_terms(
        cls, node: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        schedule_edges = (
            (node.get("paymentSchedules") or {}).get("edges") or []
        )
        schedules = [
            cls._normalise_schedule(edge.get("node") or {})
            for edge in schedule_edges if isinstance(edge, dict)
        ]
        return {
            "id": node.get("id", "") or "",
            "name": node.get("paymentTermsName", "") or "",
            "translated_name": node.get("translatedName", "") or "",
            "type": node.get("paymentTermsType", "") or "",
            "due_in_days": int(node.get("dueInDays") or 0),
            "overdue": bool(node.get("overdue", False)),
            "schedules": schedules,
        }

    @staticmethod
    def _normalise_schedule(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        amount = node.get("amount") or {}
        return {
            "id": node.get("id", "") or "",
            "due_at": node.get("dueAt", "") or "",
            "issued_at": node.get("issuedAt", "") or "",
            "completed_at": node.get("completedAt", "") or "",
            "is_paid": bool(node.get("completedAt")),
            "amount": (
                amount.get("amount", "")
                if isinstance(amount, dict) else ""
            ) or "",
            "currency_code": (
                amount.get("currencyCode", "")
                if isinstance(amount, dict) else ""
            ) or "",
        }
