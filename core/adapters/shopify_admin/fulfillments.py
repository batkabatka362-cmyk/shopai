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


class FulfillmentServices:
    """Third-party fulfillment provider registration.

    A fulfillment service is an app that Shopify hands
    orders to when they're placed — Shopify calls the
    service's registered callback URL, the service ships the
    order, Shopify marks the order fulfilled. Owner-facing:
    register a custom 3PL, list active services, decommission
    one.

    Endpoint: ``/fulfillment_services.json`` (REST).
    """

    @staticmethod
    def list_services(
        client: ShopifyAdminClient,
        *,
        scope: str = "current_client",
    ) -> list[dict[str, Any]]:
        """``scope`` filters to services visible to the
        current app. ``all`` returns every service on the
        store."""
        if scope not in ("current_client", "all"):
            raise ValueError(
                "scope must be 'current_client' or 'all'",
            )
        result = client.get(
            "fulfillment_services.json",
            params={"scope": scope},
        )
        rows = result.get("fulfillment_services") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        service_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"fulfillment_services/{service_id}.json",
        )
        svc = result.get("fulfillment_service")
        if not isinstance(svc, dict):
            raise ShopifyAdminError(
                f"fulfillment_service {service_id} "
                "not returned",
                path=(
                    f"fulfillment_services/{service_id}.json"
                ),
            )
        return svc

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        name: str,
        callback_url: str,
        inventory_management: bool = True,
        tracking_support: bool = True,
        requires_shipping_method: bool = True,
        fulfillment_orders_opt_in: bool = True,
    ) -> dict[str, Any]:
        """Register a new fulfillment service. ``callback_url``
        receives Shopify's POST on each new order; must be
        https."""
        if not name or not callback_url:
            raise ValueError(
                "name + callback_url required",
            )
        if not callback_url.startswith("https://"):
            raise ValueError(
                "callback_url must be https://",
            )
        body = {
            "fulfillment_service": {
                "name": name,
                "callback_url": callback_url,
                "inventory_management": bool(
                    inventory_management,
                ),
                "tracking_support": bool(tracking_support),
                "requires_shipping_method": bool(
                    requires_shipping_method,
                ),
                "fulfillment_orders_opt_in": bool(
                    fulfillment_orders_opt_in,
                ),
                "format": "json",
            },
        }
        result = client.post(
            "fulfillment_services.json", body,
        )
        svc = result.get("fulfillment_service")
        if not isinstance(svc, dict):
            raise ShopifyAdminError(
                "fulfillment_service not returned by create",
                path="fulfillment_services.json",
                body=str(result),
            )
        return svc

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        service_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"fulfillment_services/{service_id}.json",
            {"fulfillment_service": {
                "id": int(service_id), **fields,
            }},
        )
        svc = result.get("fulfillment_service")
        if not isinstance(svc, dict):
            raise ShopifyAdminError(
                "fulfillment_service not returned by update",
                path=(
                    f"fulfillment_services/{service_id}.json"
                ),
            )
        return svc

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        service_id: int | str,
    ) -> None:
        client.delete(
            f"fulfillment_services/{service_id}.json",
        )


class FulfillmentEvents:
    """Per-fulfillment status events — "label_printed",
    "in_transit", "delivered", etc. Shopify pushes these
    to the storefront's order-status page so buyers see
    real-time progress.

    Endpoint: ``orders/{order_id}/fulfillments/{fulfillment_id}/events.json``.
    """

    _STATUSES = {
        "label_printed", "label_purchased", "attempted_delivery",
        "ready_for_pickup", "confirmed", "in_transit",
        "out_for_delivery", "delivered", "failure",
    }

    @staticmethod
    def list_events(
        client: ShopifyAdminClient,
        *,
        order_id: int | str,
        fulfillment_id: int | str,
    ) -> list[dict[str, Any]]:
        result = client.get(
            f"orders/{order_id}/fulfillments/"
            f"{fulfillment_id}/events.json",
        )
        rows = result.get("fulfillment_events") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        order_id: int | str,
        fulfillment_id: int | str,
        status: str,
        message: str = "",
        city: str = "",
        province: str = "",
        country: str = "",
        zip_code: str = "",
        happened_at: str | None = None,
    ) -> dict[str, Any]:
        if status not in FulfillmentEvents._STATUSES:
            raise ValueError(
                f"status must be one of "
                f"{sorted(FulfillmentEvents._STATUSES)}",
            )
        event: dict[str, Any] = {"status": status}
        if message:
            event["message"] = message
        if city:
            event["city"] = city
        if province:
            event["province"] = province
        if country:
            event["country"] = country
        if zip_code:
            event["zip"] = zip_code
        if happened_at:
            event["happened_at"] = happened_at
        result = client.post(
            f"orders/{order_id}/fulfillments/"
            f"{fulfillment_id}/events.json",
            {"event": event},
        )
        created = result.get("fulfillment_event")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "fulfillment_event not returned by create",
                path=(
                    f"orders/{order_id}/fulfillments/"
                    f"{fulfillment_id}/events.json"
                ),
                body=str(result),
            )
        return created

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        *,
        order_id: int | str,
        fulfillment_id: int | str,
        event_id: int | str,
    ) -> None:
        client.delete(
            f"orders/{order_id}/fulfillments/"
            f"{fulfillment_id}/events/{event_id}.json",
        )
