"""GA4 vendor handler (placeholder).

GA4 Measurement Protocol is push-OUT only. Google does
not currently send incoming webhooks for purchase
events. This handler is scaffolding for the future when
Google adds Measurement Protocol callbacks or for
operators who wire GA4 Tag Manager to call ShopAI.
"""
from __future__ import annotations

from typing import Any

from ..handler import VendorHandler


class GA4VendorHandler(VendorHandler):
    name = "ga4"

    def extract_topic(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        return str(payload.get("event_name") or "unknown")

    def extract_store_identifier(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        # GTM-relayed events should include a
        # shopai_store_id custom param
        return str(
            payload.get("shopai_store_id") or "",
        )

    def normalise_payload(
        self, topic: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return payload
