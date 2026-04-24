"""Shopify orders — read + cancel / close / open / tag update.

The order write path beyond what webhook listeners already
read. Covers:

  * ``list`` / ``get`` / ``count`` — observability for
    owner-facing surfaces (dashboard, shopai orders)
  * ``cancel`` / ``close`` / ``open`` — explicit state
    transitions (Shopify's closure flow: an order can be
    open, closed, or cancelled; cancelled ⇒ refund + restock
    optional; closed ⇒ archived without refund)
  * ``update`` — partial field updates (tags, notes,
    email, phone, shipping_address)
  * ``add_tags`` / ``remove_tags`` — merge-safe tag writes
    that don't clobber existing tags
  * ``OrderRisks`` — per-order risk flag CRUD (Shopify
    Fraud Protect integrations populate these)

All methods stateless `@staticmethod`, take a
``ShopifyAdminClient``. Mirror the ``Customers`` module's
tag-merge pattern.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger("shopai.shopify_admin.orders")


#: Cancel reasons Shopify accepts (any other string → 422)
_VALID_CANCEL_REASONS = {
    "customer", "fraud", "inventory",
    "declined", "other",
}


class Orders:
    """Orders read + light write (cancel / close / update)."""

    # ── Read ────────────────────────────────────────────

    @staticmethod
    def list_orders(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
        status: str = "any",
        financial_status: str = "",
        fulfillment_status: str = "",
        since_id: int | str | None = None,
        created_at_min: str = "",
        created_at_max: str = "",
        fields: str = "",
    ) -> list[dict[str, Any]]:
        """List orders. ``status`` values: any / open /
        closed / cancelled. ``financial_status``: paid /
        pending / partially_paid / refunded / voided /
        authorized. ``fulfillment_status``: fulfilled /
        partial / unfulfilled / unshipped.

        ``created_at_min/max`` expect ISO-8601 strings."""
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
            "status": status,
        }
        if financial_status:
            params["financial_status"] = financial_status
        if fulfillment_status:
            params["fulfillment_status"] = fulfillment_status
        if since_id is not None:
            params["since_id"] = str(since_id)
        if created_at_min:
            params["created_at_min"] = created_at_min
        if created_at_max:
            params["created_at_max"] = created_at_max
        if fields:
            params["fields"] = fields
        result = client.get("orders.json", params=params)
        rows = result.get("orders") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient, order_id: int | str,
        *, fields: str = "",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if fields:
            params["fields"] = fields
        result = client.get(
            f"orders/{order_id}.json",
            params=params or None,
        )
        order = result.get("order")
        if not isinstance(order, dict):
            raise ShopifyAdminError(
                f"order {order_id} not returned",
                path=f"orders/{order_id}.json",
            )
        return order

    @staticmethod
    def count(
        client: ShopifyAdminClient,
        *,
        status: str = "any",
        financial_status: str = "",
    ) -> int:
        params: dict[str, Any] = {"status": status}
        if financial_status:
            params["financial_status"] = financial_status
        result = client.get(
            "orders/count.json", params=params,
        )
        return int(result.get("count") or 0)

    # ── State transitions ──────────────────────────────

    @staticmethod
    def cancel(
        client: ShopifyAdminClient,
        order_id: int | str,
        *,
        reason: str = "customer",
        email_customer: bool = True,
        restock: bool = False,
        refund_currency: str = "",
    ) -> dict[str, Any]:
        """Cancel an order. ``reason`` must be one of
        ``customer | fraud | inventory | declined | other``.
        ``restock=True`` bumps inventory back to stock (only
        meaningful if the order wasn't already fulfilled)."""
        if reason not in _VALID_CANCEL_REASONS:
            raise ValueError(
                f"reason must be one of "
                f"{sorted(_VALID_CANCEL_REASONS)} "
                f"(got {reason!r})",
            )
        body: dict[str, Any] = {
            "reason": reason,
            "email": bool(email_customer),
            "restock": bool(restock),
        }
        if refund_currency:
            body["currency"] = refund_currency
        result = client.post(
            f"orders/{order_id}/cancel.json", body,
        )
        order = result.get("order")
        if not isinstance(order, dict):
            raise ShopifyAdminError(
                "order not returned by cancel",
                path=f"orders/{order_id}/cancel.json",
                body=str(result),
            )
        return order

    @staticmethod
    def close(
        client: ShopifyAdminClient,
        order_id: int | str,
    ) -> dict[str, Any]:
        """Mark an order closed (archived) — doesn't cancel,
        doesn't refund. Used for "deal with this later" state."""
        result = client.post(
            f"orders/{order_id}/close.json", {},
        )
        order = result.get("order")
        if not isinstance(order, dict):
            raise ShopifyAdminError(
                "order not returned by close",
                path=f"orders/{order_id}/close.json",
            )
        return order

    @staticmethod
    def open(
        client: ShopifyAdminClient,
        order_id: int | str,
    ) -> dict[str, Any]:
        """Reopen a previously-closed order."""
        result = client.post(
            f"orders/{order_id}/open.json", {},
        )
        order = result.get("order")
        if not isinstance(order, dict):
            raise ShopifyAdminError(
                "order not returned by open",
                path=f"orders/{order_id}/open.json",
            )
        return order

    # ── Update ─────────────────────────────────────────

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        order_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Partial update — only pass fields you want to
        change. Shopify requires ``id`` on payload — helper
        injects. Writable fields include: email, phone,
        note, note_attributes, shipping_address, tags,
        customer (assign/reassign).
        """
        if not fields:
            raise ValueError("fields: non-empty dict required")
        body = {
            "order": {
                "id": int(order_id),
                **fields,
            },
        }
        result = client.put(
            f"orders/{order_id}.json", body,
        )
        updated = result.get("order")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "order not returned by update",
                path=f"orders/{order_id}.json",
            )
        return updated

    # ── Tag helpers ────────────────────────────────────

    @staticmethod
    def add_tags(
        client: ShopifyAdminClient,
        order_id: int | str,
        tags: list[str],
    ) -> dict[str, Any]:
        if not tags:
            raise ValueError("tags: non-empty list required")
        existing = Orders.get(client, order_id)
        current = _split_tags(existing.get("tags", ""))
        merged = sorted({
            *current, *(t.strip() for t in tags if t),
        })
        return Orders.update(
            client, order_id,
            fields={"tags": ", ".join(merged)},
        )

    @staticmethod
    def remove_tags(
        client: ShopifyAdminClient,
        order_id: int | str,
        tags: list[str],
    ) -> dict[str, Any]:
        if not tags:
            raise ValueError("tags: non-empty list required")
        drop = {t.strip().lower() for t in tags if t}
        existing = Orders.get(client, order_id)
        current = _split_tags(existing.get("tags", ""))
        kept = sorted(
            t for t in current
            if t.strip().lower() not in drop
        )
        return Orders.update(
            client, order_id,
            fields={"tags": ", ".join(kept)},
        )


class OrderRisks:
    """Per-order fraud / risk assessments.

    Shopify's own Fraud Protect app + third-party fraud
    services populate these. Owner-facing ``list`` +
    ``create`` (manual flag) + ``delete`` (clear a flag) —
    reading is how the order webhook pipeline decides
    whether to pause fulfillment on high-risk orders.
    """

    @staticmethod
    def list_risks(
        client: ShopifyAdminClient,
        order_id: int | str,
    ) -> list[dict[str, Any]]:
        result = client.get(
            f"orders/{order_id}/risks.json",
        )
        rows = result.get("risks") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        order_id: int | str,
        risk_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"orders/{order_id}/risks/{risk_id}.json",
        )
        risk = result.get("risk")
        if not isinstance(risk, dict):
            raise ShopifyAdminError(
                f"risk {risk_id} not returned",
                path=(
                    f"orders/{order_id}/risks/{risk_id}.json"
                ),
            )
        return risk

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        order_id: int | str,
        risk_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"orders/{order_id}/risks/{risk_id}.json",
            {"risk": {"id": int(risk_id), **fields}},
        )
        risk = result.get("risk")
        if not isinstance(risk, dict):
            raise ShopifyAdminError(
                "risk not returned by update",
                path=(
                    f"orders/{order_id}/risks/{risk_id}.json"
                ),
            )
        return risk

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        order_id: int | str,
        *,
        message: str,
        recommendation: str,
        score: float | None = None,
        source: str = "External",
        display: bool = True,
        cause_cancel: bool = False,
    ) -> dict[str, Any]:
        """``recommendation``: ``accept`` / ``investigate`` /
        ``cancel``. ``score``: 0.0 (low) → 1.0 (high risk)."""
        if not message or not recommendation:
            raise ValueError(
                "message + recommendation required",
            )
        body: dict[str, Any] = {
            "risk": {
                "message": message,
                "recommendation": recommendation,
                "source": source,
                "display": bool(display),
                "cause_cancel": bool(cause_cancel),
            },
        }
        if score is not None:
            body["risk"]["score"] = float(score)
        result = client.post(
            f"orders/{order_id}/risks.json", body,
        )
        risk = result.get("risk")
        if not isinstance(risk, dict):
            raise ShopifyAdminError(
                "risk not returned by create",
                path=f"orders/{order_id}/risks.json",
                body=str(result),
            )
        return risk

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        order_id: int | str,
        risk_id: int | str,
    ) -> None:
        client.delete(
            f"orders/{order_id}/risks/{risk_id}.json",
        )


def _split_tags(raw: Any) -> list[str]:
    """Parse Shopify's comma-joined tag string. Same helper
    used in ``customers.py`` — duplicated here to keep
    modules independent (caller can use either)."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    return [
        t.strip() for t in str(raw).split(",") if t.strip()
    ]
