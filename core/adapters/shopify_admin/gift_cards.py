"""Shopify gift cards.

Gift cards are a dual-purpose revenue engine:

  * **Sales SKU** — owner lists a "Gift card" product that
    customers buy for friends. Shopify auto-issues a unique
    code at checkout (handled natively, no API work needed).
  * **Retention lever** — owner issues a one-off gift card
    to a lapsed customer ("We miss you — $20 on us"). This
    is where the API matters: create / disable / search /
    list balance.

Shopify REST surface (``gift_cards.json``):

  * ``GET  /gift_cards.json``         — list (paginated)
  * ``GET  /gift_cards/{id}.json``    — get one
  * ``POST /gift_cards.json``         — create with
    ``initial_value`` (+ optional ``note`` / ``expires_on`` /
    ``code`` — omit ``code`` to let Shopify generate one)
  * ``PUT  /gift_cards/{id}.json``    — update note / expiry
    (the value itself is immutable once issued)
  * ``POST /gift_cards/{id}/disable.json`` — cancel remaining
    balance. Shopify has no "delete" — disable is the
    terminal state.
  * ``GET  /gift_cards/count.json``   — total count
  * ``GET  /gift_cards/search.json``  — search by
    ``LAST_CHARACTERS`` (the last 4 chars of the code —
    customer-support use case: buyer calls in with "my code
    ends in ABCD").

Only the store owner app (not OAuth apps on other stores)
can issue gift cards — Shopify enforces the
``gift_card_adjustments`` scope internally. Calls from an
unscoped token fail with 403; the client surfaces that as
``ShopifyAdminError``.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger("shopai.shopify_admin.gift_cards")


class GiftCards:
    """Stateless gift-card CRUD. Every method is a
    ``@staticmethod`` — callers pass the same
    ``ShopifyAdminClient`` they use for any other resource."""

    # ── Read ───────────────────────────────────────────

    @staticmethod
    def list_cards(
        client: ShopifyAdminClient,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List gift cards. ``status`` filters to
        ``"enabled"`` or ``"disabled"``; omitting it returns
        both."""
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if status:
            params["status"] = str(status).lower()
        result = client.get("gift_cards.json", params=params)
        rows = result.get("gift_cards") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get_card(
        client: ShopifyAdminClient, card_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(f"gift_cards/{card_id}.json")
        card = result.get("gift_card")
        if not isinstance(card, dict):
            raise ShopifyAdminError(
                f"gift_card {card_id} not returned",
                path=f"gift_cards/{card_id}.json",
            )
        return card

    @staticmethod
    def count(
        client: ShopifyAdminClient,
        *,
        status: str | None = None,
    ) -> int:
        params: dict[str, Any] = {}
        if status:
            params["status"] = str(status).lower()
        result = client.get(
            "gift_cards/count.json",
            params=params or None,
        )
        try:
            return int(result.get("count") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def search(
        client: ShopifyAdminClient,
        *,
        last_characters: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search by the last 4 chars of the card code.
        Customer support use case: buyer reads last four
        over the phone."""
        last = (last_characters or "").strip()
        if not last:
            raise ValueError("last_characters: required")
        query = f"last_characters:{last}"
        result = client.get(
            "gift_cards/search.json",
            params={
                "query": query,
                "limit": max(1, min(int(limit), 250)),
            },
        )
        rows = result.get("gift_cards") or []
        return [r for r in rows if isinstance(r, dict)]

    # ── Write ─────────────────────────────────────────

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        initial_value: float | str,
        code: str | None = None,
        note: str | None = None,
        expires_on: str | None = None,
        currency: str | None = None,
        customer_id: int | str | None = None,
        template_suffix: str | None = None,
    ) -> dict[str, Any]:
        """Issue a new gift card.

        * ``initial_value`` — required. Dollars (or the store
          currency if ``currency`` is set explicitly).
        * ``code`` — optional. Omit to let Shopify generate
          a random 16-char code (the recommended path —
          owner-supplied codes are easier to guess).
        * ``note`` — owner-facing memo (e.g. "Winback lapsed
          customer #1234"). Never shown to the recipient.
        * ``expires_on`` — ISO date (``YYYY-MM-DD``). Omit
          for no expiry.
        * ``customer_id`` — associate with a customer record
          so the card appears on their profile.
        """
        try:
            value = float(initial_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"initial_value must be numeric (got "
                f"{initial_value!r})",
            ) from exc
        if value <= 0:
            raise ValueError(
                "initial_value must be > 0",
            )
        card: dict[str, Any] = {
            "initial_value": f"{value:.2f}",
        }
        if code:
            card["code"] = str(code).strip()
        if note:
            card["note"] = str(note)
        if expires_on:
            card["expires_on"] = str(expires_on)
        if currency:
            card["currency"] = str(currency).upper()
        if customer_id is not None:
            card["customer_id"] = int(customer_id)
        if template_suffix:
            card["template_suffix"] = str(template_suffix)
        result = client.post(
            "gift_cards.json", {"gift_card": card},
        )
        created = result.get("gift_card")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "gift_card not returned by create",
                path="gift_cards.json",
                body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        card_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Update ``note`` / ``expires_on`` / ``template_suffix``
        only — Shopify refuses balance-mutating updates
        (issue a new card or disable the old one instead)."""
        if not fields:
            raise ValueError("fields: non-empty dict required")
        immutable = {"initial_value", "balance", "code"}
        for k in fields:
            if k in immutable:
                raise ValueError(
                    f"'{k}' cannot be updated — issue a new "
                    "card or disable the old one",
                )
        result = client.put(
            f"gift_cards/{card_id}.json",
            {"gift_card": {"id": int(card_id), **fields}},
        )
        updated = result.get("gift_card")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "gift_card not returned by update",
                path=f"gift_cards/{card_id}.json",
            )
        return updated

    @staticmethod
    def disable(
        client: ShopifyAdminClient,
        card_id: int | str,
    ) -> dict[str, Any]:
        """Terminal state — any remaining balance is
        forfeited. §4b.D idempotent: disabling an already-
        disabled card returns the same response."""
        result = client.post(
            f"gift_cards/{card_id}/disable.json", {},
        )
        disabled = result.get("gift_card")
        if not isinstance(disabled, dict):
            raise ShopifyAdminError(
                "gift_card not returned by disable",
                path=f"gift_cards/{card_id}/disable.json",
            )
        return disabled
