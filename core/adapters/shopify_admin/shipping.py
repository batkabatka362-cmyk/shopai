"""Shopify shipping zones + rates + carrier services.

Shopify's shipping model:

  * **ShippingZone** — a set of countries/provinces where
    shipping is offered. A store can have many zones (US,
    EU, ROW…). Each zone has countries + rate sets.
  * **Price-based rates** — "Free over $50, $6 under $50".
    Per-zone; simplest kind.
  * **Weight-based rates** — "$0–500g = $4, 500g–2kg = $8".
  * **Carrier services** — live rates from USPS, UPS, DHL,
    etc. Requires app-provider integration.

Shipping zones themselves are READ-ONLY via REST API in 2024+
(Shopify Admin UI / GraphQL only for zone mutations). We expose
``list_zones`` + ``get_zone`` for observability plus the three
**rate** CRUDs per zone — those ARE REST-writable.

``CarrierServices`` handles the ``carrier_services.json``
resource — custom shipping rate providers an app registers.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger(
    "shopai.shopify_admin.shipping",
)


class ShippingZones:
    """Read-only zone access + per-zone rate CRUD."""

    @staticmethod
    def list_zones(
        client: ShopifyAdminClient,
    ) -> list[dict[str, Any]]:
        """Every zone on the store. Each entry includes
        ``countries`` (list) + ``price_based_shipping_rates``
        + ``weight_based_shipping_rates`` +
        ``carrier_shipping_rate_providers``."""
        result = client.get("shipping_zones.json")
        rows = result.get("shipping_zones") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def list_zone_countries(
        client: ShopifyAdminClient,
        zone_id: int | str,
    ) -> list[dict[str, Any]]:
        """Countries served by this zone — for verifying a
        target market is covered before launching ads to it."""
        for zone in ShippingZones.list_zones(client):
            if str(zone.get("id")) == str(zone_id):
                return [
                    c for c in (zone.get("countries") or [])
                    if isinstance(c, dict)
                ]
        return []

    @staticmethod
    def covers_country(
        client: ShopifyAdminClient,
        country_code: str,
    ) -> bool:
        """True if ANY zone includes the given ISO-alpha-2
        country code. Quick pre-ad-launch check."""
        if not country_code:
            return False
        target = country_code.strip().upper()
        for zone in ShippingZones.list_zones(client):
            for c in (zone.get("countries") or []):
                if not isinstance(c, dict):
                    continue
                code = str(c.get("code") or "").upper()
                if code == target:
                    return True
                # 'Rest of World' wildcard
                if code == "*":
                    return True
        return False


class ShippingRates:
    """CRUD for per-zone price-based + weight-based rates."""

    # ── Price-based rates ──────────────────────────────

    @staticmethod
    def list_price_based(
        client: ShopifyAdminClient,
        zone_id: int | str,
    ) -> list[dict[str, Any]]:
        result = client.get(
            f"shipping_zones/{zone_id}/"
            "price_based_shipping_rates.json",
        )
        rows = (
            result.get("price_based_shipping_rates") or []
        )
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def create_price_based(
        client: ShopifyAdminClient,
        zone_id: int | str,
        *,
        name: str,
        price: float | str,
        min_order_subtotal: float | str | None = None,
        max_order_subtotal: float | str | None = None,
    ) -> dict[str, Any]:
        """Create a price-based rate.

        Example — "Free shipping over $50":
            min_order_subtotal=50.00, price=0.00

        Example — "$6 flat, no minimum":
            price=6.00 (no min/max)
        """
        if not name:
            raise ValueError("name: required")
        body: dict[str, Any] = {
            "price_based_shipping_rate": {
                "name": name,
                "price": (
                    f"{float(price):.2f}"
                    if not isinstance(price, str) else price
                ),
            },
        }
        rate = body["price_based_shipping_rate"]
        if min_order_subtotal is not None:
            rate["min_order_subtotal"] = (
                f"{float(min_order_subtotal):.2f}"
                if not isinstance(min_order_subtotal, str)
                else min_order_subtotal
            )
        if max_order_subtotal is not None:
            rate["max_order_subtotal"] = (
                f"{float(max_order_subtotal):.2f}"
                if not isinstance(max_order_subtotal, str)
                else max_order_subtotal
            )
        result = client.post(
            f"shipping_zones/{zone_id}/"
            "price_based_shipping_rates.json",
            body,
        )
        created = result.get("price_based_shipping_rate")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "price_based_shipping_rate not returned by "
                "create",
                path=(
                    f"shipping_zones/{zone_id}/"
                    "price_based_shipping_rates.json"
                ),
                body=str(result),
            )
        return created

    @staticmethod
    def update_price_based(
        client: ShopifyAdminClient,
        zone_id: int | str,
        rate_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"shipping_zones/{zone_id}/"
            f"price_based_shipping_rates/{rate_id}.json",
            {"price_based_shipping_rate": {
                "id": int(rate_id), **fields,
            }},
        )
        updated = result.get("price_based_shipping_rate")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "price_based_shipping_rate not returned",
                path=(
                    f"shipping_zones/{zone_id}/"
                    f"price_based_shipping_rates/"
                    f"{rate_id}.json"
                ),
            )
        return updated

    @staticmethod
    def delete_price_based(
        client: ShopifyAdminClient,
        zone_id: int | str,
        rate_id: int | str,
    ) -> None:
        client.delete(
            f"shipping_zones/{zone_id}/"
            f"price_based_shipping_rates/{rate_id}.json",
        )

    # ── Weight-based rates ─────────────────────────────

    @staticmethod
    def list_weight_based(
        client: ShopifyAdminClient,
        zone_id: int | str,
    ) -> list[dict[str, Any]]:
        result = client.get(
            f"shipping_zones/{zone_id}/"
            "weight_based_shipping_rates.json",
        )
        rows = (
            result.get("weight_based_shipping_rates") or []
        )
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def create_weight_based(
        client: ShopifyAdminClient,
        zone_id: int | str,
        *,
        name: str,
        price: float | str,
        weight_low_kg: float,
        weight_high_kg: float,
    ) -> dict[str, Any]:
        """Shopify stores weight in grams under the hood —
        caller passes kg for readability, helper converts."""
        if not name:
            raise ValueError("name: required")
        if weight_low_kg < 0 or weight_high_kg <= weight_low_kg:
            raise ValueError(
                "weight_high_kg must be > weight_low_kg "
                "and both >= 0",
            )
        body: dict[str, Any] = {
            "weight_based_shipping_rate": {
                "name": name,
                "price": (
                    f"{float(price):.2f}"
                    if not isinstance(price, str) else price
                ),
                "weight_low": f"{float(weight_low_kg):.3f}",
                "weight_high": f"{float(weight_high_kg):.3f}",
            },
        }
        result = client.post(
            f"shipping_zones/{zone_id}/"
            "weight_based_shipping_rates.json",
            body,
        )
        created = result.get("weight_based_shipping_rate")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "weight_based_shipping_rate not returned",
                path=(
                    f"shipping_zones/{zone_id}/"
                    "weight_based_shipping_rates.json"
                ),
                body=str(result),
            )
        return created

    @staticmethod
    def update_weight_based(
        client: ShopifyAdminClient,
        zone_id: int | str,
        rate_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"shipping_zones/{zone_id}/"
            f"weight_based_shipping_rates/{rate_id}.json",
            {"weight_based_shipping_rate": {
                "id": int(rate_id), **fields,
            }},
        )
        updated = result.get("weight_based_shipping_rate")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "weight_based_shipping_rate not returned",
                path=(
                    f"shipping_zones/{zone_id}/"
                    f"weight_based_shipping_rates/"
                    f"{rate_id}.json"
                ),
            )
        return updated

    @staticmethod
    def delete_weight_based(
        client: ShopifyAdminClient,
        zone_id: int | str,
        rate_id: int | str,
    ) -> None:
        client.delete(
            f"shipping_zones/{zone_id}/"
            f"weight_based_shipping_rates/{rate_id}.json",
        )


class CarrierServices:
    """Third-party live-rate providers (USPS, UPS, DHL via
    app integrations). Most stores don't need these — flat
    + weight-based rates cover Deguar-scale dropshipping.
    Included for completeness so the resource map is
    fully covered.
    """

    @staticmethod
    def list_services(
        client: ShopifyAdminClient,
    ) -> list[dict[str, Any]]:
        result = client.get("carrier_services.json")
        rows = result.get("carrier_services") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        service_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"carrier_services/{service_id}.json",
        )
        svc = result.get("carrier_service")
        if not isinstance(svc, dict):
            raise ShopifyAdminError(
                f"carrier_service {service_id} not returned",
                path=f"carrier_services/{service_id}.json",
            )
        return svc

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        name: str,
        callback_url: str,
        service_discovery: bool = True,
    ) -> dict[str, Any]:
        """Register a custom rate provider. ``callback_url``
        must accept POSTs with cart + address, respond with
        JSON rate array. Rarely used by us — included for
        coverage."""
        if not name or not callback_url:
            raise ValueError(
                "name + callback_url required",
            )
        body = {
            "carrier_service": {
                "name": name,
                "callback_url": callback_url,
                "service_discovery": bool(service_discovery),
            },
        }
        result = client.post("carrier_services.json", body)
        created = result.get("carrier_service")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "carrier_service not returned",
                path="carrier_services.json",
                body=str(result),
            )
        return created

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        service_id: int | str,
    ) -> None:
        client.delete(f"carrier_services/{service_id}.json")
