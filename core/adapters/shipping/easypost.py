"""EasyPostAdapter — primary shipping rate + label adapter.

Why EasyPost is the default shipping adapter:

  * **120,000 shipments/year FREE** (developer tier) — the most
    generous free tier in the space. Covers bulk of small-to-
    mid Shopify stores entirely.
  * **Multi-carrier** — USPS, UPS, FedEx, DHL, and 100+ more
    carriers behind a single API. No need to wire each carrier
    individually.
  * **Stable schema** — EasyPost's ``/shipments`` endpoint
    returns a rates array with consistent fields across
    carriers, so downstream code doesn't branch on carrier
    name.

Auth: HTTP Basic auth with the API key as the username and
an empty password. We encode the ``{key}:`` pair once per
call — that's what the ``Authorization`` header ends up as.

Reference: https://docs.easypost.com/docs/shipments
"""
from __future__ import annotations

import base64
from typing import Any

from ..errors import AdapterError
from ._base import ShippingBaseAdapter

# Dedicated env alias so operators can rotate EasyPost
# independently of Shippo. See ``core.adapters.config.ENV_ALIASES``
# for the canonical registry — we extend it below so the base
# class's ``_api_key`` helper picks the value up without any
# adapter-specific code path.
from ..config import ENV_ALIASES
ENV_ALIASES.setdefault("easypost", "EASYPOST_API_KEY")


class EasyPostAdapter(ShippingBaseAdapter):
    name = "easypost"
    base_url = "https://api.easypost.com/v2"
    config_alias = "easypost"

    # Highest shipping priority — 120K free/year beats
    # everything else. Router picks EasyPost first whenever it's
    # configured.
    priority = 95
    cost_per_call = 0.0
    free_tier_daily_limit = 0
    free_tier_monthly_limit = 10_000   # 120K/yr averages ~10K/mo

    # ── URL hooks ─────────────────────────────────────────────

    def _rate_quote_url(self) -> str:
        return f"{self.base_url}/shipments"

    def _buy_url(self, shipment_id: str | None) -> str:
        if not shipment_id:
            raise AdapterError(
                self.name,
                "EasyPost buy-label requires a shipment_id from a "
                "prior rate-quote call",
            )
        return f"{self.base_url}/shipments/{shipment_id}/buy"

    # ── Auth ──────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        # EasyPost uses HTTP Basic with the API key as the username
        # and an empty password. Encode once per call; there's no
        # session token to cache.
        token = base64.b64encode(
            f"{self._api_key()}:".encode(),
        ).decode()
        return {
            "Authorization": f"Basic {token}",
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
            "shipment": {
                "to_address": self._address_to_easypost(to_address),
                "from_address": self._address_to_easypost(from_address),
                "parcel": {
                    "length": float(parcel["length"]),
                    "width": float(parcel["width"]),
                    "height": float(parcel["height"]),
                    "weight": float(parcel["weight"]),  # ounces
                },
            },
        }

    @staticmethod
    def _address_to_easypost(address: dict[str, Any]) -> dict[str, Any]:
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
            out.append({
                "rate_id": str(r.get("id", "")),
                "carrier": str(r.get("carrier", "")),
                "service": str(r.get("service", "")),
                "rate": float(r.get("rate", 0) or 0),
                "currency": str(r.get("currency", "USD") or "USD"),
                "delivery_days": int(r.get("delivery_days") or 0),
                "delivery_date": str(r.get("delivery_date", "") or ""),
            })
        return out

    def _extract_shipment_id(self, raw: Any) -> str:
        if isinstance(raw, dict):
            return str(raw.get("id", ""))
        return ""

    # ── Buy label ─────────────────────────────────────────────

    def _build_buy_payload(
        self,
        rate_id: str,
        shipment_id: str | None,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "rate": {"id": rate_id},
        }

    def _parse_label(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name, "unexpected buy-label response shape",
            )
        tracking_code = str(raw.get("tracking_code", "") or "")
        postage_label = raw.get("postage_label") or {}
        selected_rate = raw.get("selected_rate") or {}
        return {
            "shipment_id": str(raw.get("id", "")),
            "tracking_code": tracking_code,
            "tracking_url": str(raw.get("tracker", {}).get("public_url", "") or ""),
            "label_url": str(postage_label.get("label_url", "") or ""),
            "label_format": str(postage_label.get("label_file_type", "") or ""),
            "carrier": str(selected_rate.get("carrier", "") or ""),
            "service": str(selected_rate.get("service", "") or ""),
            "rate": float(selected_rate.get("rate", 0) or 0),
            "currency": str(selected_rate.get("currency", "USD") or "USD"),
        }
