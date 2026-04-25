"""Shopify marketing events — external campaign reporting.

When Deguar launches a campaign outside Shopify (Meta Ads,
TikTok Ads, Klaviyo email blast, blog post, influencer push)
the event is invisible to Shopify's native analytics unless
we report it. A marketing event is a Shopify-owned record
that ties external spend / reach → orders attributed to it.

Why owner needs this:

  * Shopify's Sales by marketing report + the new Analytics
    attribution model both pull from the marketing_events
    table. Without events the "Sources" column on the
    dashboard shows ``direct`` for every organic click.
  * When we later ship Marketing Activities (app-scoped,
    richer attribution) the activities depend on an
    underlying marketing_event record — events are the
    foundation.

REST surface (``marketing_events.json``, API 2024-10+):

  * GET    /marketing_events.json                 — list
  * GET    /marketing_events/count.json           — count
  * GET    /marketing_events/{id}.json            — get
  * POST   /marketing_events.json                 — create
  * PUT    /marketing_events/{id}.json            — update
  * DELETE /marketing_events/{id}.json            — delete
  * POST   /marketing_events/{id}/engagements.json
                                                  — push engagement metrics

Creating an event takes a normalised enum triplet:

  * ``event_type``    — one of Shopify's fixed values
                        (``ad``, ``post``, ``message``,
                        ``retargeting``, ``transactional``,
                        ``affiliate``, ``loyalty``,
                        ``newsletter``, ``abandoned_cart``)
  * ``marketing_channel`` — ``search``, ``display``,
                        ``social``, ``email``, ``sms``,
                        ``referral``, ``other``
  * ``referring_domain`` — domain the click/impression came
                        from (``facebook.com``,
                        ``tiktok.com``, etc.)
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger(
    "shopai.shopify_admin.marketing_events",
)


_EVENT_TYPES = {
    "ad", "post", "message", "retargeting",
    "transactional", "affiliate", "loyalty",
    "newsletter", "abandoned_cart",
}

_MARKETING_CHANNELS = {
    "search", "display", "social", "email", "sms",
    "referral", "other",
}


def _iso(value: str | _dt.datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        # Shopify wants ISO-8601 with timezone.
        if value.tzinfo is None:
            value = value.replace(tzinfo=_dt.timezone.utc)
        return value.isoformat()
    return str(value)


class MarketingEvents:
    """Stateless CRUD for Shopify marketing events."""

    @staticmethod
    def list_events(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        result = client.get(
            "marketing_events.json",
            params={"limit": max(1, min(int(limit), 250))},
        )
        rows = result.get("marketing_events") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        event_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"marketing_events/{event_id}.json",
        )
        event = result.get("marketing_event")
        if not isinstance(event, dict):
            raise ShopifyAdminError(
                f"marketing_event {event_id} not returned",
                path=f"marketing_events/{event_id}.json",
            )
        return event

    @staticmethod
    def count(client: ShopifyAdminClient) -> int:
        result = client.get("marketing_events/count.json")
        try:
            return int(result.get("count") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        event_type: str,
        marketing_channel: str,
        referring_domain: str,
        started_at: str | _dt.datetime,
        ended_at: str | _dt.datetime | None = None,
        description: str | None = None,
        budget: float | None = None,
        currency: str | None = None,
        manage_url: str | None = None,
        preview_url: str | None = None,
        utm_campaign: str | None = None,
        utm_source: str | None = None,
        utm_medium: str | None = None,
        marketed_resources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a marketing event.

        ``event_type`` + ``marketing_channel`` are validated
        against Shopify's fixed enums — unknown values raise
        ``ValueError`` up-front rather than getting rejected
        by Shopify with an opaque 422.

        ``marketed_resources`` — optional list of
        ``{type, id}`` dicts pointing at product / collection
        records the campaign features. Shopify uses this for
        per-SKU attribution. Example:

            [{"type": "product", "id": 12345}]
        """
        et = event_type.lower().strip()
        if et not in _EVENT_TYPES:
            raise ValueError(
                f"event_type must be one of "
                f"{sorted(_EVENT_TYPES)}",
            )
        mc = marketing_channel.lower().strip()
        if mc not in _MARKETING_CHANNELS:
            raise ValueError(
                f"marketing_channel must be one of "
                f"{sorted(_MARKETING_CHANNELS)}",
            )
        if not referring_domain:
            raise ValueError("referring_domain: required")

        event: dict[str, Any] = {
            "event_type": et,
            "marketing_channel": mc,
            "referring_domain": str(referring_domain).strip(),
            "started_at": _iso(started_at),
        }
        if ended_at is not None:
            event["ended_at"] = _iso(ended_at)
        if description:
            event["description"] = str(description)
        if budget is not None:
            try:
                event["budget"] = f"{float(budget):.2f}"
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"budget must be numeric (got {budget!r})",
                ) from exc
        if currency:
            event["currency"] = str(currency).upper()
        if manage_url:
            event["manage_url"] = str(manage_url)
        if preview_url:
            event["preview_url"] = str(preview_url)
        if utm_campaign:
            event["utm_campaign"] = str(utm_campaign)
        if utm_source:
            event["utm_source"] = str(utm_source)
        if utm_medium:
            event["utm_medium"] = str(utm_medium)
        if marketed_resources:
            event["marketed_resources"] = [
                {"type": str(r["type"]), "id": int(r["id"])}
                for r in marketed_resources
                if isinstance(r, dict)
                and r.get("type") and r.get("id") is not None
            ]

        result = client.post(
            "marketing_events.json",
            {"marketing_event": event},
        )
        created = result.get("marketing_event")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "marketing_event not returned by create",
                path="marketing_events.json",
                body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        event_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        # Re-validate enums if they're being changed.
        if "event_type" in fields:
            et = str(fields["event_type"]).lower().strip()
            if et not in _EVENT_TYPES:
                raise ValueError(
                    f"event_type must be one of "
                    f"{sorted(_EVENT_TYPES)}",
                )
            fields = {**fields, "event_type": et}
        if "marketing_channel" in fields:
            mc = str(fields["marketing_channel"]).lower().strip()
            if mc not in _MARKETING_CHANNELS:
                raise ValueError(
                    f"marketing_channel must be one of "
                    f"{sorted(_MARKETING_CHANNELS)}",
                )
            fields = {**fields, "marketing_channel": mc}
        result = client.put(
            f"marketing_events/{event_id}.json",
            {"marketing_event": {
                "id": int(event_id), **fields,
            }},
        )
        updated = result.get("marketing_event")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "marketing_event not returned by update",
                path=f"marketing_events/{event_id}.json",
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        event_id: int | str,
    ) -> None:
        client.delete(f"marketing_events/{event_id}.json")

    @staticmethod
    def report_engagement(
        client: ShopifyAdminClient,
        event_id: int | str,
        *,
        occurred_on: str,
        impressions_count: int | None = None,
        clicks_count: int | None = None,
        views_count: int | None = None,
        shares_count: int | None = None,
        favorites_count: int | None = None,
        comments_count: int | None = None,
        unsubscribes_count: int | None = None,
        complaints_count: int | None = None,
        fails_count: int | None = None,
        sends_count: int | None = None,
        unique_views_count: int | None = None,
        unique_clicks_count: int | None = None,
        ad_spend: float | None = None,
        currency_code: str | None = None,
        is_cumulative: bool = False,
    ) -> dict[str, Any]:
        """Push daily engagement metrics for the event.
        ``occurred_on`` — ``YYYY-MM-DD``. ``is_cumulative``
        True = values are totals since start (overwrite);
        False = delta for this day (accumulate)."""
        engagement: dict[str, Any] = {
            "occurred_on": str(occurred_on),
            "is_cumulative": bool(is_cumulative),
        }
        for key, value in (
            ("impressions_count", impressions_count),
            ("clicks_count", clicks_count),
            ("views_count", views_count),
            ("shares_count", shares_count),
            ("favorites_count", favorites_count),
            ("comments_count", comments_count),
            ("unsubscribes_count", unsubscribes_count),
            ("complaints_count", complaints_count),
            ("fails_count", fails_count),
            ("sends_count", sends_count),
            ("unique_views_count", unique_views_count),
            ("unique_clicks_count", unique_clicks_count),
        ):
            if value is not None:
                engagement[key] = int(value)
        if ad_spend is not None:
            try:
                engagement["ad_spend"] = (
                    f"{float(ad_spend):.2f}"
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"ad_spend must be numeric "
                    f"(got {ad_spend!r})",
                ) from exc
        if currency_code:
            engagement["currency_code"] = (
                str(currency_code).upper()
            )
        result = client.post(
            f"marketing_events/{event_id}/engagements.json",
            {"engagements": [engagement]},
        )
        return result
