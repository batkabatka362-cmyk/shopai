"""Shopify refunds + order transactions.

Shopify's refund flow is two-step:

  1. ``calculate`` — given a refund plan (items + shipping +
     reason), Shopify returns the exact refund breakdown
     including tax adjustments and suggested transaction
     amounts. This is a GET-like idempotent read; no money
     moves.
  2. ``create`` — commit the refund. Actually moves money
     back to the customer. Shopify returns the full refund
     record including the negative transactions recorded
     against the payment gateway.

The 2-step pattern is important — owner policies often want
to show "you'll get back $X" before committing. The
calculate call supports that UX.

Transactions (payment gateway captures / voids / refunds)
have their own CRUD that sits independently. ``list_for_order``
+ ``get`` are the common read ops.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger(
    "shopai.shopify_admin.refunds",
)


class Refunds:
    """Refund CRUD against an order."""

    @staticmethod
    def list_for_order(
        client: ShopifyAdminClient,
        order_id: int | str,
    ) -> list[dict[str, Any]]:
        """Every refund ever recorded on this order."""
        result = client.get(
            f"orders/{order_id}/refunds.json",
        )
        rows = result.get("refunds") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        order_id: int | str,
        refund_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"orders/{order_id}/refunds/{refund_id}.json",
        )
        refund = result.get("refund")
        if not isinstance(refund, dict):
            raise ShopifyAdminError(
                f"refund {refund_id} not returned",
                path=(
                    f"orders/{order_id}/"
                    f"refunds/{refund_id}.json"
                ),
            )
        return refund

    @staticmethod
    def calculate(
        client: ShopifyAdminClient,
        order_id: int | str,
        *,
        refund_line_items: list[dict[str, Any]] | None = None,
        shipping: dict[str, Any] | None = None,
        currency: str = "",
    ) -> dict[str, Any]:
        """Preview a refund — Shopify computes tax + fee
        deductions, returns the refund shape with suggested
        ``transactions`` pre-filled. Does NOT move money.

        ``refund_line_items`` example::

            [{"line_item_id": 123, "quantity": 1,
              "restock_type": "return",
              "location_id": 456}]

        ``shipping`` example::

            {"full_refund": True}
            # or
            {"amount": "5.00"}
        """
        body: dict[str, Any] = {"refund": {}}
        refund = body["refund"]
        if refund_line_items:
            refund["refund_line_items"] = list(
                refund_line_items,
            )
        if shipping is not None:
            refund["shipping"] = dict(shipping)
        if currency:
            refund["currency"] = currency
        result = client.post(
            f"orders/{order_id}/refunds/calculate.json",
            body,
        )
        preview = result.get("refund")
        if not isinstance(preview, dict):
            raise ShopifyAdminError(
                "refund preview not returned",
                path=(
                    f"orders/{order_id}/"
                    "refunds/calculate.json"
                ),
                body=str(result),
            )
        return preview

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        order_id: int | str,
        *,
        refund_line_items: list[dict[str, Any]] | None = None,
        shipping: dict[str, Any] | None = None,
        transactions: list[dict[str, Any]] | None = None,
        note: str = "",
        notify: bool = True,
        currency: str = "",
    ) -> dict[str, Any]:
        """Commit a refund. Best practice is to call
        ``calculate`` first, pass its ``transactions`` list
        unchanged into ``create`` — that way Shopify's
        fee + tax calculations stay authoritative.

        ``transactions`` each: ``{"parent_id": ..., "amount":
        "...", "kind": "refund", "gateway": "...", "currency":
        "USD"}``. Usually 1:1 with the original capture(s).

        ``notify=True`` sends the customer the Shopify
        refund email.
        """
        body: dict[str, Any] = {
            "refund": {"notify": bool(notify)},
        }
        refund = body["refund"]
        if refund_line_items:
            refund["refund_line_items"] = list(
                refund_line_items,
            )
        if shipping is not None:
            refund["shipping"] = dict(shipping)
        if transactions:
            refund["transactions"] = list(transactions)
        if note:
            refund["note"] = str(note)
        if currency:
            refund["currency"] = currency
        result = client.post(
            f"orders/{order_id}/refunds.json", body,
        )
        created = result.get("refund")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "refund not returned by create",
                path=f"orders/{order_id}/refunds.json",
                body=str(result),
            )
        return created


class Transactions:
    """Payment gateway transactions — captures, voids, refunds.

    Most transactions are created automatically by Shopify when
    payment events happen. The manual ``create`` here is for
    marking external payments (cash, bank transfer) against a
    draft-completed order.
    """

    @staticmethod
    def list_for_order(
        client: ShopifyAdminClient,
        order_id: int | str,
    ) -> list[dict[str, Any]]:
        result = client.get(
            f"orders/{order_id}/transactions.json",
        )
        rows = result.get("transactions") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        order_id: int | str,
        transaction_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"orders/{order_id}/"
            f"transactions/{transaction_id}.json",
        )
        tx = result.get("transaction")
        if not isinstance(tx, dict):
            raise ShopifyAdminError(
                f"transaction {transaction_id} not returned",
                path=(
                    f"orders/{order_id}/"
                    f"transactions/{transaction_id}.json"
                ),
            )
        return tx

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        order_id: int | str,
        *,
        kind: str,
        amount: float | str,
        currency: str = "USD",
        parent_id: int | str | None = None,
        gateway: str = "manual",
        source: str = "external",
    ) -> dict[str, Any]:
        """Record a manual transaction. Common ``kind`` values:
        ``capture`` (charge a pre-auth), ``refund`` (return
        money, requires parent_id), ``void`` (cancel pre-auth),
        ``sale`` (manual external payment)."""
        body: dict[str, Any] = {
            "transaction": {
                "kind": str(kind),
                "amount": (
                    f"{float(amount):.2f}"
                    if not isinstance(amount, str) else amount
                ),
                "currency": currency,
                "gateway": gateway,
                "source": source,
            },
        }
        if parent_id is not None:
            body["transaction"]["parent_id"] = int(parent_id)
        result = client.post(
            f"orders/{order_id}/transactions.json",
            body,
        )
        tx = result.get("transaction")
        if not isinstance(tx, dict):
            raise ShopifyAdminError(
                "transaction not returned by create",
                path=f"orders/{order_id}/transactions.json",
                body=str(result),
            )
        return tx
