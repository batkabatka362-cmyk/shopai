"""ShopifyGiftCardsAdapter — issue and manage gift cards.

Gift cards are a recurring engine touch-point: the goodwill engine
issues them as compensation for shipping delays, the loyalty engine
mints them as referral rewards, and the cart-abandon engine attaches
them to high-LTV customers as recovery incentives. Without an
adapter every one of those flows had to call the legacy REST client
or be done manually.

ShopAI use cases:

  * **Goodwill compensation.** Customer-service automation issues
    a $X gift card when the shipping ETA slips, instead of refunding
    (which sometimes the customer doesn't want — a credit-back is a
    win-win).
  * **Loyalty / referral rewards.** Loyalty engine mints gift cards
    when a referred customer places their first order.
  * **Win-back campaigns.** Retention engine attaches a gift card
    to a "we miss you" email for customers churning out of a cohort.
  * **Audit / claw-back.** Refunds-and-fraud engine deactivates a
    gift card when its source order gets refunded or the recipient
    address is flagged.

Capabilities:

  * ``SHOPIFY_CREATE_GIFT_CARD``     — mint a new gift card.
  * ``SHOPIFY_LIST_GIFT_CARDS``      — page through cards with
    optional query filter (e.g. ``"status:enabled"``).
  * ``SHOPIFY_GET_GIFT_CARD``        — fetch one by id; returns
    {found: False} on null instead of raising.
  * ``SHOPIFY_DEACTIVATE_GIFT_CARD`` — kill a card via
    ``giftCardDeactivate`` (the only way to invalidate one — there's
    no delete).

----

**Scope gating — important caveat.**

Gift card fields are hidden from the GraphQL schema until the app's
token carries ``read_gift_cards`` and/or ``write_gift_cards``.
``giftCards``, ``giftCard(id:)``, ``giftCardCreate``, and
``giftCardDeactivate`` will all return ``Access denied … Required
access: read_gift_cards`` / ``write_gift_cards`` errors otherwise.
Pattern E in CLAUDE.md (schema-gated fields).

If a smoke test against a fresh app rejects with that error, the fix
is to add the scopes to the app config and re-install (or re-mint
the access token via OAuth). The adapter wire format is correct;
only the access path needs unblocking.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


# Common selection set for gift card nodes — used by create / list /
# get so the normaliser only knows one shape.
_GIFT_CARD_NODE_FIELDS = """
id
maskedCode
lastCharacters
balance {
  amount
  currencyCode
}
initialValue {
  amount
  currencyCode
}
createdAt
updatedAt
expiresOn
enabled
note
customer {
  id
  email
  displayName
}
""".strip()


_CREATE_GIFT_CARD_MUTATION = f"""
mutation giftCardCreate($input: GiftCardCreateInput!) {{
  giftCardCreate(input: $input) {{
    giftCard {{
      {_GIFT_CARD_NODE_FIELDS}
    }}
    giftCardCode
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_GET_GIFT_CARD_QUERY = f"""
query giftCard($id: ID!) {{
  giftCard(id: $id) {{
    {_GIFT_CARD_NODE_FIELDS}
  }}
}}
""".strip()


_LIST_GIFT_CARDS_QUERY = f"""
query giftCards(
  $first: Int!, $after: String, $query: String,
  $sortKey: GiftCardSortKeys, $reverse: Boolean
) {{
  giftCards(
    first: $first, after: $after, query: $query,
    sortKey: $sortKey, reverse: $reverse
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_GIFT_CARD_NODE_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_DEACTIVATE_GIFT_CARD_MUTATION = f"""
mutation giftCardDeactivate($id: ID!) {{
  giftCardDeactivate(id: $id) {{
    giftCard {{
      {_GIFT_CARD_NODE_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyGiftCardsAdapter(ShopifyBaseAdapter):
    name = "shopify_gift_cards"
    capabilities = {
        Capability.SHOPIFY_CREATE_GIFT_CARD,
        Capability.SHOPIFY_LIST_GIFT_CARDS,
        Capability.SHOPIFY_GET_GIFT_CARD,
        Capability.SHOPIFY_DEACTIVATE_GIFT_CARD,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_GIFT_CARD:
            return self._create(params)
        if capability == Capability.SHOPIFY_LIST_GIFT_CARDS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_GIFT_CARD:
            return self._get(params)
        if capability == Capability.SHOPIFY_DEACTIVATE_GIFT_CARD:
            return self._deactivate(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        gift_card_input = self._build_create_input(params)
        data = self._gql(
            _CREATE_GIFT_CARD_MUTATION,
            {"input": gift_card_input},
        )
        self._check_user_errors(data, "giftCardCreate")
        payload = data.get("giftCardCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_GIFT_CARD,
            data={
                "gift_card": self._normalise_gift_card(
                    payload.get("giftCard") or {}
                ),
                # The full plaintext code is only returned ONCE at
                # creation; engines that want to email it must capture
                # it from this response.
                "code": payload.get("giftCardCode", "") or "",
            },
        )

    @staticmethod
    def _build_create_input(params: dict[str, Any]) -> dict[str, Any]:
        """Convert ShopAI's friendly call shape into ``GiftCardCreateInput``.

        Friendly form::

            {
              "initial_value": 25.00,                       # required
              "currency": "USD",                            # default USD
              "code":     "WELCOME25",                      # optional;
                                                            # Shopify auto-
                                                            # generates if
                                                            # omitted
              "customer_id": "gid://shopify/Customer/X",   # optional
              "expires_on": "2026-12-31",                  # optional Date
              "note":       "Goodwill: shipping delay",    # optional
              "template_suffix": "default",                # optional
              "recipient_email": "buyer@example.com",      # optional
              "recipient_name":  "Ada Lovelace",           # optional
            }
        """
        initial_value = params.get("initial_value") or params.get("initialValue")
        if initial_value is None:
            raise AdapterValidationError(
                "shopify_gift_cards",
                "'initial_value' is required (the gift card's value)",
            )
        try:
            value_num = float(initial_value)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                "shopify_gift_cards",
                f"'initial_value' must be numeric, got "
                f"{type(initial_value).__name__}",
            ) from exc
        if value_num <= 0:
            raise AdapterValidationError(
                "shopify_gift_cards",
                f"'initial_value' must be > 0, got {value_num}",
            )

        out: dict[str, Any] = {
            # GiftCardCreateInput.initialValue is a Decimal scalar;
            # send as 2-decimal string per Shopify convention.
            "initialValue": f"{value_num:.2f}",
        }

        # NOTE: ``GiftCardCreateInput`` does NOT have a currencyCode
        # field (caught live as 'Field is not defined on
        # GiftCardCreateInput'). Gift card currency is inherited from
        # the shop's primary currency. We accept ``currency`` in the
        # friendly call shape for forwards compatibility (and so
        # callers can document intent) but silently drop it on the
        # wire.
        currency = params.get("currency") or params.get("currencyCode")
        if currency is not None and not isinstance(currency, str):
            raise AdapterValidationError(
                "shopify_gift_cards", "'currency' must be a string",
            )
        # currency intentionally not added to ``out``.

        code = params.get("code")
        if code is not None:
            if not isinstance(code, str) or not code.strip():
                raise AdapterValidationError(
                    "shopify_gift_cards",
                    "'code' must be a non-empty string when provided",
                )
            # Shopify accepts custom codes 8-20 chars alphanumeric.
            # We don't enforce length client-side because the rule
            # has changed in past API versions; let userErrors flag
            # if needed.
            out["code"] = code.strip()

        customer_id = params.get("customer_id") or params.get("customerId")
        if customer_id:
            if not isinstance(customer_id, str):
                raise AdapterValidationError(
                    "shopify_gift_cards",
                    "'customer_id' must be a Shopify GID string",
                )
            out["customerId"] = customer_id.strip()

        expires_on = params.get("expires_on") or params.get("expiresOn")
        if expires_on:
            if not isinstance(expires_on, str):
                raise AdapterValidationError(
                    "shopify_gift_cards",
                    "'expires_on' must be a Date string (YYYY-MM-DD)",
                )
            out["expiresOn"] = expires_on

        note = params.get("note")
        if note:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    "shopify_gift_cards", "'note' must be a string",
                )
            out["note"] = note

        template_suffix = (
            params.get("template_suffix") or params.get("templateSuffix")
        )
        if template_suffix:
            if not isinstance(template_suffix, str):
                raise AdapterValidationError(
                    "shopify_gift_cards",
                    "'template_suffix' must be a string",
                )
            out["templateSuffix"] = template_suffix

        recipient_email = params.get("recipient_email") or params.get("recipientEmail")
        recipient_name = params.get("recipient_name") or params.get("recipientName")
        if recipient_email or recipient_name:
            attrs: dict[str, str] = {}
            if recipient_email:
                if not isinstance(recipient_email, str) or "@" not in recipient_email:
                    raise AdapterValidationError(
                        "shopify_gift_cards",
                        "'recipient_email' must be a valid email",
                    )
                attrs["email"] = recipient_email
            if recipient_name:
                if not isinstance(recipient_name, str):
                    raise AdapterValidationError(
                        "shopify_gift_cards",
                        "'recipient_name' must be a string",
                    )
                attrs["name"] = recipient_name
            out["recipientAttributes"] = attrs

        return out

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        gift_card_id = params.get("id") or params.get("gift_card_id")
        if not isinstance(gift_card_id, str) or not gift_card_id.strip():
            raise AdapterValidationError(
                "shopify_gift_cards",
                "'id' (Shopify GID for the gift card) is required",
            )
        data = self._gql(_GET_GIFT_CARD_QUERY, {"id": gift_card_id.strip()})
        node = data.get("giftCard")
        if not isinstance(node, dict):
            return self._success(
                Capability.SHOPIFY_GET_GIFT_CARD,
                data={"found": False, "gift_card": None},
            )
        return self._success(
            Capability.SHOPIFY_GET_GIFT_CARD,
            data={"found": True,
                  "gift_card": self._normalise_gift_card(node)},
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                "shopify_gift_cards", "'cursor' must be a string or None",
            )
        query = params.get("query")
        if query is not None and not isinstance(query, str):
            raise AdapterValidationError(
                "shopify_gift_cards", "'query' must be a string or None",
            )
        sort_key = params.get("sort_key") or params.get("sortKey")
        if sort_key is not None:
            if not isinstance(sort_key, str):
                raise AdapterValidationError(
                    "shopify_gift_cards",
                    "'sort_key' must be a string or None",
                )
            sort_key = sort_key.upper()
        reverse = bool(params.get("reverse", False))

        data = self._gql(_LIST_GIFT_CARDS_QUERY, {
            "first": limit,
            "after": cursor,
            "query": query,
            "sortKey": sort_key,
            "reverse": reverse,
        })
        envelope = data.get("giftCards") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        gift_cards = [
            self._normalise_gift_card(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_GIFT_CARDS,
            data={
                "gift_cards": gift_cards,
                "count": len(gift_cards),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Deactivate ─────────────────────────────────────────────────

    def _deactivate(self, params: dict[str, Any]) -> Any:
        gift_card_id = params.get("id") or params.get("gift_card_id")
        if not isinstance(gift_card_id, str) or not gift_card_id.strip():
            raise AdapterValidationError(
                "shopify_gift_cards",
                "'id' (Shopify GID for the gift card) is required",
            )
        data = self._gql(_DEACTIVATE_GIFT_CARD_MUTATION, {
            "id": gift_card_id.strip(),
        })
        self._check_user_errors(data, "giftCardDeactivate")
        payload = data.get("giftCardDeactivate") or {}
        return self._success(
            Capability.SHOPIFY_DEACTIVATE_GIFT_CARD,
            data={
                "gift_card": self._normalise_gift_card(
                    payload.get("giftCard") or {}
                ),
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_gift_card(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}

        def _money_at(key: str) -> tuple[float, str]:
            money = node.get(key) or {}
            try:
                amt = float(money.get("amount", 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            return amt, (money.get("currencyCode", "") or "")

        balance, currency = _money_at("balance")
        initial_value, _ = _money_at("initialValue")
        customer = node.get("customer") or {}
        return {
            "id": node.get("id", "") or "",
            # Shopify only returns the masked code after creation;
            # the full plaintext code is in the create payload's
            # giftCardCode field, NOT on the node.
            "masked_code": node.get("maskedCode", "") or "",
            "last_characters": node.get("lastCharacters", "") or "",
            "balance": balance,
            "initial_value": initial_value,
            "currency": currency,
            "enabled": bool(node.get("enabled", False)),
            "expires_on": node.get("expiresOn", "") or "",
            "note": node.get("note", "") or "",
            "customer_id": (
                customer.get("id", "") if isinstance(customer, dict) else ""
            ) or "",
            "customer_email": (
                customer.get("email", "") if isinstance(customer, dict) else ""
            ) or "",
            "customer_name": (
                customer.get("displayName", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
