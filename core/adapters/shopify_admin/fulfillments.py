"""Shopify fulfillments — fulfillment_orders + fulfillments +
tracking.

Shopify's fulfillment model moved to a two-tier design:

  * **FulfillmentOrder** — Shopify's view of what still needs
    to ship for a given (order × location × service) triple.
    One Order can have multiple FulfillmentOrders (multi-ware-
    house, partial ship). We read them + accept / reject /
    move between services.
  * **Fulfillment** — the actual shipment event a merchant
    records against one or more FulfillmentOrders. Carries
    tracking number + carrier. Created once; ``update_tracking``
    amends carrier info after the fact.

Methods take a ``ShopifyAdminClient`` + stay stateless.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger(
    "shopai.shopify_admin.fulfillments",
)


class FulfillmentOrders:
    """Read + manage the fulfillment_order state machine."""

    @staticmethod
    def list_for_order(
        client: ShopifyAdminClient, order_id: int | str,
    ) -> list[dict[str, Any]]:
        result = client.get(
            f"orders/{order_id}/fulfillment_orders.json",
        )
        rows = result.get("fulfillment_orders") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        fulfillment_order_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"fulfillment_orders/{fulfillment_order_id}.json",
        )
        fo = result.get("fulfillment_order")
        if not isinstance(fo, dict):
            raise ShopifyAdminError(
                f"fulfillment_order {fulfillment_order_id} "
                "not returned",
                path=(
                    f"fulfillment_orders/"
                    f"{fulfillment_order_id}.json"
                ),
            )
        return fo

    @staticmethod
    def cancel(
        client: ShopifyAdminClient,
        fulfillment_order_id: int | str,
    ) -> dict[str, Any]:
        """Cancel a fulfillment order — puts line items back
        in ``open`` state. Used when the supplier can't
        deliver + we need to refund or retry a different
        service."""
        result = client.post(
            f"fulfillment_orders/"
            f"{fulfillment_order_id}/cancel.json",
            {},
        )
        return result.get("fulfillment_order") or {}

    @staticmethod
    def close(
        client: ShopifyAdminClient,
        fulfillment_order_id: int | str,
        *,
        message: str = "",
    ) -> dict[str, Any]:
        """Mark closed without creating a shipment (used when
        an order is cancelled before fulfillment)."""
        body: dict[str, Any] = {}
        if message:
            body = {"message": str(message)}
        result = client.post(
            f"fulfillment_orders/"
            f"{fulfillment_order_id}/close.json",
            body,
        )
        return result.get("fulfillment_order") or {}

    @staticmethod
    def move(
        client: ShopifyAdminClient,
        fulfillment_order_id: int | str,
        *,
        new_location_id: int | str,
    ) -> dict[str, Any]:
        """Reassign to a different location (multi-warehouse
        routing). Useful when primary runs out of stock."""
        result = client.post(
            f"fulfillment_orders/"
            f"{fulfillment_order_id}/move.json",
            {
                "fulfillment_order": {
                    "new_location_id": int(new_location_id),
                },
            },
        )
        # Response shape includes both old + new FO records
        return result


class Fulfillments:
    """Record shipments against fulfillment_orders."""

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        line_items_by_fulfillment_order: list[dict[str, Any]],
        tracking_number: str = "",
        tracking_url: str = "",
        tracking_company: str = "",
        notify_customer: bool = True,
    ) -> dict[str, Any]:
        """Create a shipment.

        ``line_items_by_fulfillment_order`` is a list of
        ``{"fulfillment_order_id": N, "fulfillment_order_
        line_items": [{"id": X, "quantity": Y}, ...]}`` — if
        ``fulfillment_order_line_items`` is omitted Shopify
        fulfills the entire FO.

        Tracking fields optional — missing ones leave the
        shipment in "unknown" state (customer still gets an
        email via ``notify_customer``).
        """
        if not line_items_by_fulfillment_order:
            raise ValueError(
                "line_items_by_fulfillment_order: "
                "non-empty list required",
            )

        body: dict[str, Any] = {
            "fulfillment": {
                "line_items_by_fulfillment_order": (
                    line_items_by_fulfillment_order
                ),
                "notify_customer": bool(notify_customer),
            },
        }
        if any((
            tracking_number, tracking_url, tracking_company,
        )):
            body["fulfillment"]["tracking_info"] = {
                "number": tracking_number or None,
                "url": tracking_url or None,
                "company": tracking_company or None,
            }
        result = client.post("fulfillments.json", body)
        fulfillment = result.get("fulfillment")
        if not isinstance(fulfillment, dict):
            raise ShopifyAdminError(
                "fulfillment not returned by create",
                path="fulfillments.json", body=str(result),
            )
        return fulfillment

    @staticmethod
    def update_tracking(
        client: ShopifyAdminClient,
        fulfillment_id: int | str,
        *,
        tracking_number: str = "",
        tracking_url: str = "",
        tracking_company: str = "",
        notify_customer: bool = True,
    ) -> dict[str, Any]:
        """Amend tracking info after the shipment was
        recorded. Typical flow: fulfillment created with
        empty tracking → supplier ACK returns a tracking
        number later → we update."""
        body: dict[str, Any] = {
            "fulfillment": {
                "notify_customer": bool(notify_customer),
                "tracking_info": {
                    "number": tracking_number or None,
                    "url": tracking_url or None,
                    "company": tracking_company or None,
                },
            },
        }
        result = client.post(
            f"fulfillments/"
            f"{fulfillment_id}/update_tracking.json",
            body,
        )
        fulfillment = result.get("fulfillment")
        if not isinstance(fulfillment, dict):
            raise ShopifyAdminError(
                "fulfillment not returned by "
                "update_tracking",
                path=(
                    f"fulfillments/"
                    f"{fulfillment_id}/update_tracking.json"
                ),
                body=str(result),
            )
        return fulfillment

    @staticmethod
    def cancel(
        client: ShopifyAdminClient,
        fulfillment_id: int | str,
    ) -> dict[str, Any]:
        """Cancel a shipment (e.g. label voided)."""
        result = client.post(
            f"fulfillments/{fulfillment_id}/cancel.json",
            {},
        )
        return result.get("fulfillment") or {}

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        fulfillment_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"fulfillments/{fulfillment_id}.json",
        )
        fulfillment = result.get("fulfillment")
        if not isinstance(fulfillment, dict):
            raise ShopifyAdminError(
                f"fulfillment {fulfillment_id} not returned",
                path=f"fulfillments/{fulfillment_id}.json",
            )
        return fulfillment

    @staticmethod
    def list_for_order(
        client: ShopifyAdminClient, order_id: int | str,
    ) -> list[dict[str, Any]]:
        """Every shipment against a given order."""
        result = client.get(
            f"orders/{order_id}/fulfillments.json",
        )
        rows = result.get("fulfillments") or []
        return [r for r in rows if isinstance(r, dict)]
