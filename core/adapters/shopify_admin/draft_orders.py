"""Shopify Draft Orders — quotes, VIP upsells, manual orders.

Draft orders let the store stage an order without charging
the customer yet. Three common use cases ShopAI targets:

  * **Personalized quote** — custom line items + shipping
    override + send invoice email ("here's your custom
    bundle, pay when ready").
  * **VIP upsell follow-up** — after post_purchase email
    hits, generate a pre-built draft with recommendations +
    VIP discount applied.
  * **Cart recovery with custom pricing** — abandoned-cart
    flow could generate a draft with a one-time promotion
    attached rather than sending a generic code.

Three-phase lifecycle:

  1. ``create`` — stage the order (no money moves)
  2. ``send_invoice`` — email the customer a payment link
  3. ``complete`` — convert the draft to a real order (either
     mark_as_paid=True for pre-paid invoices or leave pending)

All three surface returns the full draft record so callers can
read line-item pricing, shipping quote, tax breakdown, etc.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger(
    "shopai.shopify_admin.draft_orders",
)


class DraftOrders:
    """Stateless draft-order CRUD + lifecycle ops."""

    # ── CRUD ────────────────────────────────────────────

    @staticmethod
    def list_drafts(
        client: ShopifyAdminClient,
        *,
        status: str = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Status values: ``open`` (new), ``invoice_sent``
        (customer received email), ``completed`` (converted
        to an Order)."""
        result = client.get(
            "draft_orders.json",
            params={
                "status": status,
                "limit": max(1, min(int(limit), 250)),
            },
        )
        rows = result.get("draft_orders") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient, draft_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"draft_orders/{draft_id}.json",
        )
        draft = result.get("draft_order")
        if not isinstance(draft, dict):
            raise ShopifyAdminError(
                f"draft_order {draft_id} not returned",
                path=f"draft_orders/{draft_id}.json",
            )
        return draft

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        line_items: list[dict[str, Any]],
        customer_email: str = "",
        customer_id: int | str | None = None,
        shipping_address: dict[str, Any] | None = None,
        billing_address: dict[str, Any] | None = None,
        note: str = "",
        tags: list[str] | None = None,
        applied_discount: dict[str, Any] | None = None,
        use_customer_default_address: bool = False,
    ) -> dict[str, Any]:
        """Build a draft order.

        ``line_items`` elements accept either ``variant_id``
        (most common) or the custom-line-item shape
        ``{title, price, quantity}`` for products that aren't
        in the Shopify catalogue (rare in our flows).

        ``applied_discount`` example::

            {"title": "VIP comeback",
             "description": "20% off",
             "value_type": "percentage", "value": "20.0"}

        Returns the full draft record including ``id`` (used
        by ``send_invoice`` + ``complete``)."""
        if not isinstance(line_items, list) or not line_items:
            raise ValueError(
                "line_items: non-empty list required",
            )
        items_out: list[dict[str, Any]] = []
        for it in line_items:
            if not isinstance(it, dict):
                continue
            row: dict[str, Any] = {
                "quantity": max(
                    1, int(it.get("quantity") or 1),
                ),
            }
            if it.get("variant_id"):
                row["variant_id"] = int(it["variant_id"])
            elif it.get("title") and it.get("price") is not None:
                # Custom line item
                row["title"] = str(it["title"])
                row["price"] = f"{float(it['price']):.2f}"
            else:
                raise ValueError(
                    f"line_item invalid: {it!r} — needs "
                    "variant_id OR (title + price)",
                )
            if it.get("applied_discount"):
                row["applied_discount"] = it["applied_discount"]
            items_out.append(row)

        body: dict[str, Any] = {
            "draft_order": {"line_items": items_out},
        }
        draft = body["draft_order"]
        if customer_email:
            draft["email"] = str(customer_email).strip().lower()
        if customer_id is not None:
            draft["customer"] = {
                "id": int(customer_id),
            }
        if shipping_address:
            draft["shipping_address"] = dict(shipping_address)
        if billing_address:
            draft["billing_address"] = dict(billing_address)
        if note:
            draft["note"] = str(note)
        if tags:
            draft["tags"] = ",".join(str(t) for t in tags)
        if applied_discount:
            draft["applied_discount"] = dict(applied_discount)
        if use_customer_default_address:
            draft["use_customer_default_address"] = True

        result = client.post("draft_orders.json", body)
        created = result.get("draft_order")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "draft_order not returned by create",
                path="draft_orders.json", body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        draft_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"draft_orders/{draft_id}.json",
            {"draft_order": dict(fields)},
        )
        updated = result.get("draft_order")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "draft_order not returned by update",
                path=f"draft_orders/{draft_id}.json",
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient, draft_id: int | str,
    ) -> None:
        """Only ``open`` drafts can be deleted;
        ``invoice_sent`` + ``completed`` are immutable."""
        client.delete(f"draft_orders/{draft_id}.json")

    # ── Lifecycle ops ──────────────────────────────────

    @staticmethod
    def send_invoice(
        client: ShopifyAdminClient,
        draft_id: int | str,
        *,
        to: str = "",
        from_: str = "",
        subject: str = "",
        custom_message: str = "",
        bcc: list[str] | None = None,
    ) -> dict[str, Any]:
        """Email the customer a payment link. Returns the
        ``draft_order_invoice`` shape Shopify sends back."""
        body: dict[str, Any] = {"draft_order_invoice": {}}
        invoice = body["draft_order_invoice"]
        if to:
            invoice["to"] = str(to).strip().lower()
        if from_:
            invoice["from"] = str(from_)
        if subject:
            invoice["subject"] = str(subject)
        if custom_message:
            invoice["custom_message"] = str(custom_message)
        if bcc:
            invoice["bcc"] = [str(x) for x in bcc]
        result = client.post(
            f"draft_orders/{draft_id}/send_invoice.json",
            body,
        )
        record = result.get("draft_order_invoice")
        if not isinstance(record, dict):
            raise ShopifyAdminError(
                "draft_order_invoice not returned",
                path=(
                    f"draft_orders/{draft_id}/"
                    "send_invoice.json"
                ),
                body=str(result),
            )
        return record

    @staticmethod
    def complete(
        client: ShopifyAdminClient,
        draft_id: int | str,
        *,
        payment_pending: bool = True,
    ) -> dict[str, Any]:
        """Convert draft → real order.

        ``payment_pending=True`` (default) means "customer
        still owes us money" — they'll see an unpaid invoice
        in their Shopify checkout. ``False`` means "I already
        got paid out of band (cash, bank transfer) — mark
        paid immediately".
        """
        path = f"draft_orders/{draft_id}/complete.json"
        params = {
            "payment_pending": (
                "true" if payment_pending else "false"
            ),
        }
        result = client.put(
            path, {}, params=params,
        )
        order = result.get("draft_order")
        if not isinstance(order, dict):
            raise ShopifyAdminError(
                "draft_order not returned by complete",
                path=path, body=str(result),
            )
        return order
