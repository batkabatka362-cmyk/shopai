"""ShopifyGiftCardCRUDAdapter — gift card write extensions.

Companion to ``gift_cards.py``, which already covers LIST / GET /
CREATE / DEACTIVATE. This adapter fills the remaining
write-side gaps that several engines depend on:

  * **Recovery & retention engine.** Updates note / expiry on an
    existing goodwill card without re-issuing it.
  * **Refund engine.** Credits an existing gift card when a
    customer returns an item paid with that card — keeps the
    money inside ShopAI's economy rather than refunding to
    payment method.
  * **Compliance / fraud engine.** Debits cards that were issued
    in error, adjusts balances after manual reconciliation.

Capabilities:

  * ``SHOPIFY_UPDATE_GIFT_CARD``  — giftCardUpdate. Patch note /
    expiry / customer / template suffix on an existing card.
    Pattern A: id at field level.
  * ``SHOPIFY_CREDIT_GIFT_CARD``  — giftCardCredit. Add value to
    an existing card. Pattern A.
  * ``SHOPIFY_DEBIT_GIFT_CARD``   — giftCardDebit. Deduct value
    from an existing card (manual adjustment). Pattern A.

Pattern G (per-adapter money input): both credit + debit accept
``amount`` + ``currency_code`` and shape into ``MoneyInput``
inline rather than reaching for a shared util.
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
lastCharacters
enabled
note
expiresOn
createdAt
updatedAt
deactivatedAt
templateSuffix
balance {
  amount
  currencyCode
}
initialValue {
  amount
  currencyCode
}
customer {
  id
  email
}
""".strip()


_UPDATE_GIFT_CARD_MUTATION = f"""
mutation giftCardUpdate($id: ID!, $input: GiftCardUpdateInput!) {{
  giftCardUpdate(id: $id, input: $input) {{
    giftCard {{
      {_GIFT_CARD_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_CREDIT_GIFT_CARD_MUTATION = """
mutation giftCardCredit($id: ID!, $creditInput: GiftCardCreditInput!) {
  giftCardCredit(id: $id, creditInput: $creditInput) {
    giftCardCreditTransaction {
      id
      amount {
        amount
        currencyCode
      }
      processedAt
      note
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_DEBIT_GIFT_CARD_MUTATION = """
mutation giftCardDebit($id: ID!, $debitInput: GiftCardDebitInput!) {
  giftCardDebit(id: $id, debitInput: $debitInput) {
    giftCardDebitTransaction {
      id
      amount {
        amount
        currencyCode
      }
      processedAt
      note
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


class ShopifyGiftCardCRUDAdapter(ShopifyBaseAdapter):
    name = "shopify_gift_card_crud"
    capabilities = {
        Capability.SHOPIFY_UPDATE_GIFT_CARD,
        Capability.SHOPIFY_CREDIT_GIFT_CARD,
        Capability.SHOPIFY_DEBIT_GIFT_CARD,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_UPDATE_GIFT_CARD:
            return self._update(params)
        if capability == Capability.SHOPIFY_CREDIT_GIFT_CARD:
            return self._credit(params)
        if capability == Capability.SHOPIFY_DEBIT_GIFT_CARD:
            return self._debit(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        card_id = self._extract_card_id(params)
        card_input = self._build_update_input(params)
        if not card_input:
            raise AdapterValidationError(
                self.name,
                "no patchable fields supplied — pass at least one of "
                "note/expires_on/customer_id/template_suffix",
            )
        data = self._gql(_UPDATE_GIFT_CARD_MUTATION, {
            "id": card_id, "input": card_input,
        })
        self._check_user_errors(data, "giftCardUpdate")
        payload = data.get("giftCardUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_GIFT_CARD,
            data={
                "gift_card": self._normalise_card(
                    payload.get("giftCard") or {}
                ),
            },
        )

    # ── Credit ─────────────────────────────────────────────────────

    def _credit(self, params: dict[str, Any]) -> Any:
        card_id = self._extract_card_id(params)
        credit_input = self._build_money_op_input(
            params, amount_field="creditAmount", label="credit",
        )
        data = self._gql(_CREDIT_GIFT_CARD_MUTATION, {
            "id": card_id, "creditInput": credit_input,
        })
        self._check_user_errors(data, "giftCardCredit")
        payload = data.get("giftCardCredit") or {}
        return self._success(
            Capability.SHOPIFY_CREDIT_GIFT_CARD,
            data={
                "transaction": self._normalise_transaction(
                    payload.get("giftCardCreditTransaction") or {}
                ),
            },
        )

    # ── Debit ──────────────────────────────────────────────────────

    def _debit(self, params: dict[str, Any]) -> Any:
        card_id = self._extract_card_id(params)
        debit_input = self._build_money_op_input(
            params, amount_field="debitAmount", label="debit",
        )
        data = self._gql(_DEBIT_GIFT_CARD_MUTATION, {
            "id": card_id, "debitInput": debit_input,
        })
        self._check_user_errors(data, "giftCardDebit")
        payload = data.get("giftCardDebit") or {}
        return self._success(
            Capability.SHOPIFY_DEBIT_GIFT_CARD,
            data={
                "transaction": self._normalise_transaction(
                    payload.get("giftCardDebitTransaction") or {}
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_card_id(self, params: dict[str, Any]) -> str:
        card_id = (
            params.get("id")
            or params.get("gift_card_id")
            or params.get("giftCardId")
        )
        if not isinstance(card_id, str) or not card_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the gift card) is required",
            )
        return card_id.strip()

    def _build_update_input(self, params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}

        if "note" in params and params["note"] is not None:
            if not isinstance(params["note"], str):
                raise AdapterValidationError(
                    self.name, "'note' must be a string",
                )
            out["note"] = params["note"]

        expires_on = params.get("expires_on") or params.get("expiresOn")
        if expires_on is not None:
            if not isinstance(expires_on, str):
                raise AdapterValidationError(
                    self.name,
                    "'expires_on' must be ISO-8601 date string",
                )
            out["expiresOn"] = expires_on.strip()

        customer_id = params.get("customer_id") or params.get("customerId")
        if customer_id is not None:
            if not isinstance(customer_id, str):
                raise AdapterValidationError(
                    self.name, "'customer_id' must be a Shopify GID string",
                )
            out["customerId"] = customer_id.strip()

        template_suffix = (
            params.get("template_suffix") or params.get("templateSuffix")
        )
        if template_suffix is not None:
            if not isinstance(template_suffix, str):
                raise AdapterValidationError(
                    self.name, "'template_suffix' must be a string",
                )
            out["templateSuffix"] = template_suffix

        return out

    def _build_money_op_input(
        self, params: dict[str, Any], *, amount_field: str, label: str,
    ) -> dict[str, Any]:
        amount = params.get("amount")
        if amount is None:
            raise AdapterValidationError(
                self.name,
                f"'amount' is required for {label} (e.g. 5.00)",
            )
        try:
            amount_decimal = float(amount)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name, f"'amount' must be numeric for {label}",
            ) from exc
        if amount_decimal <= 0:
            raise AdapterValidationError(
                self.name, f"'amount' must be > 0 for {label}",
            )
        currency = (
            params.get("currency_code")
            or params.get("currencyCode")
            or params.get("currency")
        )
        if not isinstance(currency, str) or not currency.strip():
            raise AdapterValidationError(
                self.name,
                f"'currency_code' is required for {label} (e.g. 'USD')",
            )
        out: dict[str, Any] = {
            amount_field: {
                "amount": f"{amount_decimal:.2f}",
                "currencyCode": currency.strip().upper(),
            },
        }

        note = params.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    self.name, "'note' must be a string",
                )
            out["note"] = note

        processed_at = (
            params.get("processed_at") or params.get("processedAt")
        )
        if processed_at is not None:
            if not isinstance(processed_at, str):
                raise AdapterValidationError(
                    self.name,
                    "'processed_at' must be ISO-8601 datetime string",
                )
            out["processedAt"] = processed_at.strip()

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_money(node: Any) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {"amount": 0.0, "currency_code": ""}
        try:
            amount = float(node.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        return {
            "amount": amount,
            "currency_code": node.get("currencyCode", "") or "",
        }

    @classmethod
    def _normalise_card(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        customer = node.get("customer") or {}
        return {
            "id": node.get("id", "") or "",
            "masked_code": node.get("maskedCode", "") or "",
            "last_characters": node.get("lastCharacters", "") or "",
            "enabled": bool(node.get("enabled", False)),
            "note": node.get("note", "") or "",
            "expires_on": node.get("expiresOn", "") or "",
            "deactivated_at": node.get("deactivatedAt", "") or "",
            "template_suffix": node.get("templateSuffix", "") or "",
            "balance": cls._normalise_money(node.get("balance")),
            "initial_value": cls._normalise_money(node.get("initialValue")),
            "customer_id": (
                customer.get("id", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "customer_email": (
                customer.get("email", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }

    @classmethod
    def _normalise_transaction(
        cls, node: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        return {
            "id": node.get("id", "") or "",
            "amount": cls._normalise_money(node.get("amount")),
            "processed_at": node.get("processedAt", "") or "",
            "note": node.get("note", "") or "",
        }
