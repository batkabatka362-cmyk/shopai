"""Shopify disputes (chargebacks + inquiries).

Shopify Payments reports buyer disputes on this endpoint —
charges the buyer has pushed back on with their card issuer.
Each dispute has a state machine:

    needs_response → under_review → (won | lost | charge_refunded)

Owner response goes through Shopify's dashboard
(evidence upload, additional_documents); the API is
read-only so we can observe + alert on new disputes,
compute dispute-rate telemetry for the brain, and flag
high-risk customers.

Resource: ``/shopify_payments/disputes.json`` (read-only).
Only available when the store uses Shopify Payments as its
primary processor; returns 404 on stores without it —
surfaced as ShopifyAdminError so the caller can skip this
adapter cleanly.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger(
    "shopai.shopify_admin.disputes",
)


# Shopify's canonical dispute-status enums (docs: admin API
# Shopify Payments section). Validating up-front beats
# letting Shopify return an opaque 422 later.
_DISPUTE_STATUSES = {
    "needs_response", "under_review",
    "charge_refunded", "accepted",
    "won", "lost",
}

_INITIATED_AT_QUERIES = {
    "initiated_at_min", "initiated_at_max",
}


class Disputes:
    """Read-only dispute + chargeback CRUD."""

    @staticmethod
    def list_disputes(
        client: ShopifyAdminClient,
        *,
        status: str | None = None,
        initiated_at_min: str | None = None,
        initiated_at_max: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List disputes. ``status`` filters to one of the
        documented enum values; ``initiated_at_*`` take
        ISO-8601 timestamps."""
        if status is not None and status not in _DISPUTE_STATUSES:
            raise ValueError(
                f"status must be one of "
                f"{sorted(_DISPUTE_STATUSES)}",
            )
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if status:
            params["status"] = status
        if initiated_at_min:
            params["initiated_at_min"] = str(initiated_at_min)
        if initiated_at_max:
            params["initiated_at_max"] = str(initiated_at_max)
        result = client.get(
            "shopify_payments/disputes.json", params=params,
        )
        rows = result.get("disputes") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        dispute_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"shopify_payments/disputes/{dispute_id}.json",
        )
        dispute = result.get("dispute")
        if not isinstance(dispute, dict):
            raise ShopifyAdminError(
                f"dispute {dispute_id} not returned",
                path=(
                    "shopify_payments/disputes/"
                    f"{dispute_id}.json"
                ),
            )
        return dispute

    @staticmethod
    def needs_response(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Convenience: disputes where the owner still has
        time to push back (``needs_response`` state).
        Owner-alert flow reads this on every cycle."""
        return Disputes.list_disputes(
            client, status="needs_response", limit=limit,
        )

    @staticmethod
    def loss_total_usd(
        client: ShopifyAdminClient,
        *,
        initiated_at_min: str,
    ) -> float:
        """Sum amounts from disputes in terminal loss states
        (lost + charge_refunded) since ``initiated_at_min``.
        Used for monthly dispute-rate KPI on the dashboard."""
        total = 0.0
        for status in ("lost", "charge_refunded"):
            rows = Disputes.list_disputes(
                client,
                status=status,
                initiated_at_min=initiated_at_min,
                limit=250,
            )
            for row in rows:
                try:
                    total += float(row.get("amount") or 0)
                except (TypeError, ValueError):
                    continue
        return round(total, 2)
