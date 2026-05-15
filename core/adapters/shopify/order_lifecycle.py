"""ShopifyOrderLifecycleAdapter — order cancel/reopen/mark-paid.

Companion to ``orders.py`` (LIST/GET/CREATE/UPDATE/CLOSE) and
``order_edits.py`` (post-purchase line-item edits). The three
lifecycle transitions in this adapter sit outside both surfaces:

  * **Fraud cancellation.** Risk engine flags an order, operator
    confirms, adapter calls ``orderCancel`` with reason FRAUD,
    refund-to-original-payment-method, restock=true. One call
    closes the loop without round-tripping through admin.
  * **Reopen.** Manual reconciliation flow that re-opens a
    closed order so a refund / fulfillment-correction can be
    appended.
  * **Mark as paid.** When payment lands via an offline channel
    (wire transfer, COD, B2B net-30 invoice), the order needs an
    explicit ``orderMarkAsPaid`` call to flip its financial
    status — Shopify won't infer it.

Capabilities:

  * ``SHOPIFY_CANCEL_ORDER``        — orderCancel. Pattern A:
    orderId at field level; required reason (enum) + restock
    boolean; optional refundMethod, notifyCustomer, staffNote.
    Returns a Job (cancel runs async).
  * ``SHOPIFY_REOPEN_ORDER``        — orderOpen. Input dict
    ``{id}``.
  * ``SHOPIFY_MARK_ORDER_AS_PAID``  — orderMarkAsPaid. Input
    dict ``{id}``.

(``SHOPIFY_CLOSE_ORDER`` already lives on ``orders.py``.)

Pattern D (codified): ``orderCancel`` returns
``orderCancelUserErrors`` (NOT the standard ``userErrors``) of
type ``OrderCancelUserError`` (has ``code``). The adapter
extracts that custom key manually rather than relying on
``_check_user_errors``'s default lookup.

Pattern F: ``orderOpen`` and ``orderMarkAsPaid`` use the typed
``UserError`` (no ``code``). Adapter drops ``code`` from those
userErrors selections.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_ORDER_FIELDS = """
id
name
displayFinancialStatus
displayFulfillmentStatus
cancelledAt
closed
closedAt
""".strip()


_CANCEL_ORDER_MUTATION = """
mutation orderCancel(
  $orderId: ID!,
  $reason: OrderCancelReason!,
  $restock: Boolean!,
  $notifyCustomer: Boolean,
  $staffNote: String,
  $refundMethod: OrderCancelRefundMethodInput
) {
  orderCancel(
    orderId: $orderId,
    reason: $reason,
    restock: $restock,
    notifyCustomer: $notifyCustomer,
    staffNote: $staffNote,
    refundMethod: $refundMethod
  ) {
    job {
      id
      done
    }
    orderCancelUserErrors {
      field
      message
      code
    }
  }
}
""".strip()


_OPEN_ORDER_MUTATION = f"""
mutation orderOpen($input: OrderOpenInput!) {{
  orderOpen(input: $input) {{
    order {{
      {_ORDER_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_MARK_AS_PAID_MUTATION = f"""
mutation orderMarkAsPaid($input: OrderMarkAsPaidInput!) {{
  orderMarkAsPaid(input: $input) {{
    order {{
      {_ORDER_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_VALID_CANCEL_REASONS = {
    "CUSTOMER", "DECLINED", "FRAUD", "INVENTORY", "STAFF", "OTHER",
}


class ShopifyOrderLifecycleAdapter(ShopifyBaseAdapter):
    name = "shopify_order_lifecycle"
    capabilities = {
        Capability.SHOPIFY_CANCEL_ORDER,
        Capability.SHOPIFY_REOPEN_ORDER,
        Capability.SHOPIFY_MARK_ORDER_AS_PAID,
    }
    required_scopes = frozenset({"read_orders", "write_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CANCEL_ORDER:
            return self._cancel(params)
        if capability == Capability.SHOPIFY_REOPEN_ORDER:
            return self._toggle(
                params, _OPEN_ORDER_MUTATION, "orderOpen",
                Capability.SHOPIFY_REOPEN_ORDER,
            )
        if capability == Capability.SHOPIFY_MARK_ORDER_AS_PAID:
            return self._toggle(
                params, _MARK_AS_PAID_MUTATION, "orderMarkAsPaid",
                Capability.SHOPIFY_MARK_ORDER_AS_PAID,
            )
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Cancel ─────────────────────────────────────────────────────

    def _cancel(self, params: dict[str, Any]) -> Any:
        order_id = self._extract_order_id(params)
        reason_raw = params.get("reason")
        if not isinstance(reason_raw, str) or not reason_raw.strip():
            raise AdapterValidationError(
                self.name,
                f"'reason' is required — one of {sorted(_VALID_CANCEL_REASONS)}",
            )
        reason = reason_raw.strip().upper()
        if reason not in _VALID_CANCEL_REASONS:
            raise AdapterValidationError(
                self.name,
                f"'reason' must be one of {sorted(_VALID_CANCEL_REASONS)}",
            )

        if "restock" not in params:
            raise AdapterValidationError(
                self.name,
                "'restock' is required (bool) — Shopify needs an "
                "explicit restock decision on cancellation",
            )
        restock = bool(params["restock"])

        variables: dict[str, Any] = {
            "orderId": order_id,
            "reason": reason,
            "restock": restock,
        }

        notify = params.get("notify_customer")
        if notify is None:
            notify = params.get("notifyCustomer")
        if notify is not None:
            variables["notifyCustomer"] = bool(notify)

        staff_note = params.get("staff_note") or params.get("staffNote")
        if staff_note is not None:
            if not isinstance(staff_note, str):
                raise AdapterValidationError(
                    self.name, "'staff_note' must be a string",
                )
            variables["staffNote"] = staff_note

        refund_method = params.get("refund_method")
        if refund_method is None:
            refund_method = params.get("refundMethod")
        if refund_method is not None:
            variables["refundMethod"] = self._build_refund_method(
                refund_method,
            )

        data = self._gql(_CANCEL_ORDER_MUTATION, variables)
        # Pattern D: orderCancel uses orderCancelUserErrors, NOT
        # userErrors — the base helper's default lookup misses it.
        payload = data.get("orderCancel") or {}
        errors = payload.get("orderCancelUserErrors") or []
        if errors:
            messages = []
            for e in errors:
                if isinstance(e, dict):
                    field = ".".join(e.get("field", []) or [])
                    msg = e.get("message", "")
                    messages.append(
                        f"{field}: {msg}" if field else msg,
                    )
            raise AdapterValidationError(
                self.name,
                f"orderCancel userErrors: {'; '.join(messages)[:300]}",
            )

        job = payload.get("job") or {}
        return self._success(
            Capability.SHOPIFY_CANCEL_ORDER,
            data={
                "job_id": (
                    job.get("id", "") if isinstance(job, dict) else ""
                ) or "",
                "job_done": bool(
                    job.get("done", False) if isinstance(job, dict) else False
                ),
            },
        )

    # ── Close / Open / Mark-as-paid ────────────────────────────────

    def _toggle(
        self,
        params: dict[str, Any],
        mutation: str,
        op_name: str,
        capability: Capability,
    ) -> Any:
        order_id = self._extract_order_id(params)
        data = self._gql(mutation, {"input": {"id": order_id}})
        self._check_user_errors(data, op_name)
        payload = data.get(op_name) or {}
        order = payload.get("order") or {}
        return self._success(
            capability,
            data={"order": self._normalise_order(order)},
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_order_id(self, params: dict[str, Any]) -> str:
        order_id = (
            params.get("id")
            or params.get("order_id")
            or params.get("orderId")
        )
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the order) is required",
            )
        return order_id.strip()

    def _build_refund_method(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'refund_method' must be a dict — one of "
                "{original_payment_methods: True} / "
                "{store_credit: {...}}",
            )
        out: dict[str, Any] = {}
        original = (
            raw.get("original_payment_methods")
            or raw.get("originalPaymentMethodsRefund")
        )
        if original is not None:
            out["originalPaymentMethodsRefund"] = bool(original)

        store_credit = (
            raw.get("store_credit")
            or raw.get("storeCreditRefund")
        )
        if store_credit is not None:
            if not isinstance(store_credit, dict):
                raise AdapterValidationError(
                    self.name,
                    "'refund_method.store_credit' must be a dict",
                )
            # Pass through camelCase keys the caller supplies.
            out["storeCreditRefund"] = store_credit

        if not out:
            raise AdapterValidationError(
                self.name,
                "'refund_method' had no recognised keys — "
                "expected 'original_payment_methods' or 'store_credit'",
            )
        return out

    @staticmethod
    def _normalise_order(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "financial_status": (
                node.get("displayFinancialStatus", "") or ""
            ),
            "fulfillment_status": (
                node.get("displayFulfillmentStatus", "") or ""
            ),
            "cancelled_at": node.get("cancelledAt", "") or "",
            "closed": bool(node.get("closed", False)),
            "closed_at": node.get("closedAt", "") or "",
        }
