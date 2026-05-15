"""ShopifyPaymentReminderAdapter — chase outstanding B2B invoices.

Companion to ``payment_terms.py`` (read-side: lists outstanding
schedules + their due dates) and ``order_invoice.py`` (one-shot
invoice email re-send for fully paid orders).

Payment reminders apply specifically to net-N B2B invoices —
when a schedule's due date passes without payment, the engine
fires ``paymentReminderSend`` to nudge the buyer's AP team. The
recipient list, template, and timing are all owner-side
configuration; this adapter just triggers the send.

ShopAI's accounts-receivable engine uses this on a cadence:

  * Net-30 invoice issued T+0
  * Reminder T+25 (5 days before due)
  * Reminder T+30 (due date)
  * Reminder T+33 (3 days overdue)
  * Reminder T+45, T+60 escalation
  * Past T+90 → handed off to collections (different workflow)

Capability:

  * ``SHOPIFY_SEND_PAYMENT_REMINDER`` — paymentReminderSend.
    Pattern A: paymentScheduleId at field level.

UserError variant is ``PaymentReminderSendUserError`` (has
``code``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


_SEND_REMINDER_MUTATION = """
mutation paymentReminderSend($paymentScheduleId: ID!) {
  paymentReminderSend(paymentScheduleId: $paymentScheduleId) {
    success
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


class ShopifyPaymentReminderAdapter(ShopifyBaseAdapter):
    name = "shopify_payment_reminder"
    capabilities = {Capability.SHOPIFY_SEND_PAYMENT_REMINDER}
    required_scopes = frozenset({"write_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_SEND_PAYMENT_REMINDER:
            return self._send(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _send(self, params: dict[str, Any]) -> Any:
        schedule_id = (
            params.get("payment_schedule_id")
            or params.get("paymentScheduleId")
            or params.get("id")
        )
        if not isinstance(schedule_id, str) or not schedule_id.strip():
            raise AdapterValidationError(
                self.name,
                "'payment_schedule_id' (Shopify GID for the "
                "PaymentSchedule) is required",
            )
        data = self._gql(_SEND_REMINDER_MUTATION, {
            "paymentScheduleId": schedule_id.strip(),
        })
        self._check_user_errors(data, "paymentReminderSend")
        payload = data.get("paymentReminderSend") or {}
        return self._success(
            Capability.SHOPIFY_SEND_PAYMENT_REMINDER,
            data={"success": bool(payload.get("success", False))},
        )
