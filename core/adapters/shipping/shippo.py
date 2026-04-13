"""ShippoAdapter — secondary shipping rate + label adapter.

Shippo sits just behind EasyPost in the router chain. We keep
it around because:

  * **Different carrier coverage** — Shippo has a few regional
    carriers (DPD, GLS) that EasyPost doesn't, useful when the
    merchant ships to Europe.
  * **Generous free tier for small volume** — 30 labels/month
    free on the "Starter" plan, plus unmetered rate quotes
    (you only pay for labels you actually buy).
  * **Redundancy** — if EasyPost is having an outage the
    router falls back here instead of going dark on shipping.

Auth: ``Authorization: ShippoToken {key}`` header (not Bearer!).

Reference: https://docs.goshippo.com/shippoapi/public-api/
"""
from __future__ import annotations

from typing import Any

from ..config import ENV_ALIASES
from ..errors import AdapterError
from ._base import ShippingBaseAdapter

ENV_ALIASES.setdefault("shippo", "SHIPPO_API_KEY")


class ShippoAdapter(ShippingBaseAdapter):
    name = "shippo"
    base_url = "https://api.goshippo.com"
    config_alias = "shippo"

    # Secondary — EasyPost's 120K free/year wins most
    # comparisons, but Shippo's rate quotes are unmetered and
    # its European carrier coverage is broader.
    priority = 85
    cost_per_call = 0.0
    free_tier_daily_limit = 0
    free_tier_monthly_limit = 30   # labels/month on Starter

    # ── URL hooks ─────────────────────────────────────────────

    def _rate_quote_url(self) -> str:
        return f"{self.base_url}/shipments/"

    def _buy_url(self, shipment_id: str | None) -> str:
        # Shippo buys labels at the /transactions/ endpoint
        # with the rate_id — no shipment_id needed on that path.
        return f"{self.base_url}/transactions/"

    # ── Auth ──────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"ShippoToken {self._api_key()}",
            "Content-Type": "application/json",
        }

    # ── Request body ──────────────────────────────────────────

    def _build_shipment(
        self,
        from_address: dict[str, Any],
        to_address: dict[str, Any],
        parcel: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "address_from": self._address_to_shippo(from_address),
            "address_to": self._address_to_shippo(to_address),
            "parcels": [{
                "length": str(parcel["length"]),
                "width": str(parcel["width"]),
                "height": str(parcel["height"]),
                "distance_unit": "in",
                "weight": str(parcel["weight"]),
                "mass_unit": "oz",
            }],
            "async": False,
        }

    @staticmethod
    def _address_to_shippo(address: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": address.get("name", "") or "",
            "street1": address["street1"],
            "street2": address.get("street2", "") or "",
            "city": address["city"],
            "state": address.get("state", "") or "",
            "zip": address["zip"],
            "country": address["country"],
            "phone": address.get("phone", "") or "",
            "email": address.get("email", "") or "",
        }

    # ── Response parsing ──────────────────────────────────────

    def _parse_rates(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, dict):
            return []
        rates = raw.get("rates") or []
        if not isinstance(rates, list):
            return []

        out: list[dict[str, Any]] = []
        for r in rates:
            if not isinstance(r, dict):
                continue
            provider = r.get("provider") or r.get("servicelevel", {}).get("provider", "")
            service = ""
            sl = r.get("servicelevel")
            if isinstance(sl, dict):
                service = sl.get("name", "") or sl.get("token", "") or ""
            out.append({
                "rate_id": str(r.get("object_id", "")),
                "carrier": str(provider or ""),
                "service": str(service),
                "rate": float(r.get("amount", 0) or 0),
                "currency": str(r.get("currency", "USD") or "USD"),
                "delivery_days": int(r.get("estimated_days") or 0),
                "delivery_date": "",
            })
        return out

    def _extract_shipment_id(self, raw: Any) -> str:
        if isinstance(raw, dict):
            return str(raw.get("object_id", ""))
        return ""

    # ── Buy label ─────────────────────────────────────────────

    def _build_buy_payload(
        self,
        rate_id: str,
        shipment_id: str | None,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "rate": rate_id,
            "label_file_type": params.get("label_format", "PDF"),
            "async": False,
        }

    def _parse_label(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name, "unexpected buy-label response shape",
            )
        return {
            "shipment_id": str(raw.get("object_id", "")),
            "tracking_code": str(raw.get("tracking_number", "") or ""),
            "tracking_url": str(raw.get("tracking_url_provider", "") or ""),
            "label_url": str(raw.get("label_url", "") or ""),
            "label_format": str(raw.get("label_file_type", "") or ""),
            "carrier": "",         # Shippo doesn't echo this on transaction
            "service": "",         #   but caller already knows it from the rate
            "rate": float(raw.get("rate", 0) or 0),
            "currency": "USD",
        }
