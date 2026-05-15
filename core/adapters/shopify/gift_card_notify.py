"""ShopifyGiftCardNotifyAdapter — gift card delivery emails.

Companions:
  * ``gift_cards.py`` — LIST / GET / CREATE / DEACTIVATE.
  * ``gift_card_crud.py`` — UPDATE / CREDIT / DEBIT.

The notification side — the email that delivers the gift card
to the buyer or the gift recipient — sat outside both. Two
mutations cover the two recipients:

  * ``giftCardSendNotificationToCustomer`` — sends to the
    customer who BOUGHT the card. Useful for "your purchase
    of $50 in store credit is ready" confirmations.
  * ``giftCardSendNotificationToRecipient`` — sends to the
    recipient the buyer specified when minting the card (the
    recipient field on the gift card record). The classic
    "you've been gifted $X" delivery email.

ShopAI's recovery + retention engines use the customer
notification when re-sending forgotten goodwill credits;
gift-shop and corporate-gifting flows use the recipient
notification.

Capabilities:

  * ``SHOPIFY_SEND_GIFT_CARD_TO_CUSTOMER`` —
    giftCardSendNotificationToCustomer. Pattern A: id at
    field level.
  * ``SHOPIFY_SEND_GIFT_CARD_TO_RECIPIENT`` —
    giftCardSendNotificationToRecipient. Pattern A: id.

UserError variants are per-mutation
(``GiftCardSendNotificationTo*UserError``, both with
``code``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_GIFT_CARD_FIELDS = """
id
maskedCode
enabled
balance {
  amount
  currencyCode
}
customer {
  id
  email
}
recipientAttributes {
  preferredName
  message
}
""".strip()


_SEND_TO_CUSTOMER_MUTATION = f"""
mutation giftCardSendNotificationToCustomer($id: ID!) {{
  giftCardSendNotificationToCustomer(id: $id) {{
    giftCard {{
      {_GIFT_CARD_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_SEND_TO_RECIPIENT_MUTATION = f"""
mutation giftCardSendNotificationToRecipient($id: ID!) {{
  giftCardSendNotificationToRecipient(id: $id) {{
    giftCard {{
      {_GIFT_CARD_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


class ShopifyGiftCardNotifyAdapter(ShopifyBaseAdapter):
    name = "shopify_gift_card_notify"
    capabilities = {
        Capability.SHOPIFY_SEND_GIFT_CARD_TO_CUSTOMER,
        Capability.SHOPIFY_SEND_GIFT_CARD_TO_RECIPIENT,
    }
    required_scopes = frozenset({"write_gift_cards"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_SEND_GIFT_CARD_TO_CUSTOMER:
            return self._send(
                params, _SEND_TO_CUSTOMER_MUTATION,
                "giftCardSendNotificationToCustomer",
                Capability.SHOPIFY_SEND_GIFT_CARD_TO_CUSTOMER,
            )
        if capability == Capability.SHOPIFY_SEND_GIFT_CARD_TO_RECIPIENT:
            return self._send(
                params, _SEND_TO_RECIPIENT_MUTATION,
                "giftCardSendNotificationToRecipient",
                Capability.SHOPIFY_SEND_GIFT_CARD_TO_RECIPIENT,
            )
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    def _send(
        self,
        params: dict[str, Any],
        mutation: str,
        op_name: str,
        capability: Capability,
    ) -> Any:
        gift_card_id = (
            params.get("id")
            or params.get("gift_card_id")
            or params.get("giftCardId")
        )
        if not isinstance(gift_card_id, str) or not gift_card_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the gift card) is required",
            )
        data = self._gql(mutation, {"id": gift_card_id.strip()})
        self._check_user_errors(data, op_name)
        payload = data.get(op_name) or {}
        return self._success(
            capability,
            data={
                "gift_card": self._normalise_card(
                    payload.get("giftCard") or {}
                ),
            },
        )

    @staticmethod
    def _normalise_card(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        balance = node.get("balance") or {}
        try:
            balance_amount = float(balance.get("amount", 0) or 0)
        except (TypeError, ValueError):
            balance_amount = 0.0
        customer = node.get("customer") or {}
        recipient = node.get("recipientAttributes") or {}
        return {
            "id": node.get("id", "") or "",
            "masked_code": node.get("maskedCode", "") or "",
            "enabled": bool(node.get("enabled", False)),
            "balance": {
                "amount": balance_amount,
                "currency_code": balance.get("currencyCode", "") or "",
            },
            "customer_id": (
                customer.get("id", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "customer_email": (
                customer.get("email", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "recipient_preferred_name": (
                recipient.get("preferredName", "")
                if isinstance(recipient, dict) else ""
            ) or "",
            "recipient_message": (
                recipient.get("message", "")
                if isinstance(recipient, dict) else ""
            ) or "",
        }
