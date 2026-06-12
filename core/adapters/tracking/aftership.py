"""AfterShipAdapter -- AfterShip Tracking API (v4).

API docs: https://developers.aftership.com/reference

Endpoints used:
  - POST /v4/trackings -- register a new shipment
  - GET  /v4/trackings/{slug}/{tracking_number} -- lookup
  - GET  /v4/trackings -- list recent

Auth: header `aftership-api-key: <key>`.

Status code normalisation maps AfterShip's tags
(Pending/InfoReceived/InTransit/...) to the
TrackingBaseAdapter's normalised constants.

Per-store routing: SHOPAI_STORE_<SID>_AFTERSHIP_API_KEY
takes precedence over fleet AFTERSHIP_API_KEY.

Pre-fix the customer support team manually answered
'where is my order?' by copy-pasting tracking numbers
into the carrier's site. This adapter unlocks:
  - Auto-resolve via TRACKING_LOOKUP
  - delivery_feedback engine consumes status changes
  - customer_support_autonomy can auto-reply to
    'where's my order' tickets with current status
"""
from __future__ import annotations

from typing import Any

from ._base import (
    STATUS_AVAILABLE_FOR_PICKUP,
    STATUS_DELIVERED,
    STATUS_EXCEPTION,
    STATUS_EXPIRED,
    STATUS_INFO_RECEIVED,
    STATUS_IN_TRANSIT,
    STATUS_OUT_FOR_DELIVERY,
    STATUS_PENDING,
    STATUS_UNKNOWN,
    TrackingBaseAdapter,
)


# AfterShip 'tag' -> normalised status
_AFTERSHIP_TAG_MAP = {
    "Pending": STATUS_PENDING,
    "InfoReceived": STATUS_INFO_RECEIVED,
    "InTransit": STATUS_IN_TRANSIT,
    "OutForDelivery": STATUS_OUT_FOR_DELIVERY,
    "AttemptFail": STATUS_EXCEPTION,
    "Delivered": STATUS_DELIVERED,
    "AvailableForPickup": STATUS_AVAILABLE_FOR_PICKUP,
    "Exception": STATUS_EXCEPTION,
    "Expired": STATUS_EXPIRED,
}


class AfterShipAdapter(TrackingBaseAdapter):
    """AfterShip Tracking aggregator (~1000 carriers)."""

    name = "aftership"
    base_url = "https://api.aftership.com"
    config_alias = "aftership_api_key"
    cost_per_call = 0.0   # bundled cost in plan; we
                          # don't itemise per call

    # ── Auth ──────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        return {
            "aftership-api-key": self._api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Paths ─────────────────────────────────────────────────

    def _register_path(self) -> str:
        return "/v4/trackings"

    def _lookup_path(
        self, *, tracking_number: str, carrier: str,
    ) -> str:
        # AfterShip uses 'slug' for carrier
        return (
            f"/v4/trackings/{carrier}/{tracking_number}"
        )

    def _list_path(self, *, limit: int) -> str:
        return (
            f"/v4/trackings?limit={max(1, min(limit, 200))}"
        )

    # ── Payload + response shapes ─────────────────────────────

    def _register_payload(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        tracking: dict[str, Any] = {
            "tracking_number": kwargs["tracking_number"],
            "slug": kwargs["carrier"],
        }
        if kwargs.get("title"):
            tracking["title"] = kwargs["title"]
        if kwargs.get("customer_email"):
            tracking["emails"] = [
                kwargs["customer_email"],
            ]
        if kwargs.get("customer_phone"):
            tracking["smses"] = [
                kwargs["customer_phone"],
            ]
        if kwargs.get("order_id"):
            tracking["order_id"] = str(
                kwargs["order_id"],
            )
        return {"tracking": tracking}

    def _parse_register_response(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        data = raw.get("data") or {}
        inner = data.get("tracking") or {}
        return {
            "registered": True,
            "tracking_id": inner.get("id", ""),
            "tracking_number": inner.get(
                "tracking_number", "",
            ),
            "carrier": inner.get("slug", ""),
            "status": _AFTERSHIP_TAG_MAP.get(
                inner.get("tag", ""), STATUS_UNKNOWN,
            ),
        }

    def _parse_lookup_response(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        data = raw.get("data") or {}
        inner = data.get("tracking") or {}
        events_raw = inner.get("checkpoints") or []
        events: list[dict[str, Any]] = []
        for ev in events_raw:
            if not isinstance(ev, dict):
                continue
            events.append({
                "timestamp": ev.get(
                    "checkpoint_time", "",
                ),
                "location": _format_location(ev),
                "message": ev.get("message", ""),
                "status_normalised": (
                    _AFTERSHIP_TAG_MAP.get(
                        ev.get("tag", ""),
                        STATUS_UNKNOWN,
                    )
                ),
            })
        return {
            "tracking_number": inner.get(
                "tracking_number", "",
            ),
            "carrier": inner.get("slug", ""),
            "status": _AFTERSHIP_TAG_MAP.get(
                inner.get("tag", ""), STATUS_UNKNOWN,
            ),
            "status_detail": inner.get(
                "subtag_message", "",
            ),
            "expected_delivery": inner.get(
                "expected_delivery", "",
            ),
            "events": events,
            "last_updated": inner.get("updated_at", ""),
            "order_id": inner.get("order_id", ""),
            "title": inner.get("title", ""),
        }

    def _parse_list_response(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        data = raw.get("data") or {}
        rows = data.get("trackings") or []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append({
                "tracking_number": row.get(
                    "tracking_number", "",
                ),
                "carrier": row.get("slug", ""),
                "status": _AFTERSHIP_TAG_MAP.get(
                    row.get("tag", ""), STATUS_UNKNOWN,
                ),
                "last_updated": row.get(
                    "updated_at", "",
                ),
                "order_id": row.get("order_id", ""),
            })
        return {
            "count": len(out),
            "trackings": out,
        }


def _format_location(checkpoint: dict[str, Any]) -> str:
    """Build 'City, Region, Country' from a checkpoint."""
    parts = [
        str(checkpoint.get(k, ""))
        for k in ("city", "state", "country_name")
    ]
    return ", ".join(p for p in parts if p)
