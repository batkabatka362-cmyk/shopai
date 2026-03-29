"""ContentDistributor — distributes content to multiple channels concurrently.

Uses only the Python standard library.  Channel-specific publishing is
delegated to ContentPublisher; this class coordinates fan-out across
multiple channels and aggregates results.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
from typing import Any


class ContentDistributor:
    """Fan-out a piece of content to multiple channels in parallel."""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def distribute(
        self,
        content: dict[str, Any],
        channels: list[str],
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Publish *content* to every channel in *channels*.

        Args:
            content:     Generic content dict with at minimum ``title`` or
                         ``body`` / ``body_html``.
            channels:    List of channel names: ``"shopify"``, ``"facebook"``,
                         ``"instagram"``, ``"twitter"``, ``"linkedin"``,
                         ``"tiktok"``.
            credentials: Dict keyed by channel name, each value is the
                         credentials dict expected by ContentPublisher.

        Returns:
            ``{"status": "ok"|"partial"|"error",
               "results": {channel: result_dict},
               "succeeded": [channels], "failed": [channels],
               "total_channels": int, "distributed_at": str}``
        """
        results: dict[str, Any] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(channels), 10)
        ) as pool:
            future_to_channel = {
                pool.submit(
                    self._distribute_to_channel,
                    channel,
                    content,
                    credentials,
                ): channel
                for channel in channels
            }
            for future in concurrent.futures.as_completed(future_to_channel):
                channel = future_to_channel[future]
                try:
                    results[channel] = future.result()
                except Exception as exc:
                    results[channel] = {
                        "status": "error",
                        "channel": channel,
                        "error": str(exc),
                    }

        succeeded = [c for c, r in results.items() if r.get("status") == "published"]
        failed = [c for c, r in results.items() if r.get("status") != "published"]

        overall = (
            "ok" if not failed else ("partial" if succeeded else "error")
        )
        return {
            "status": overall,
            "results": results,
            "succeeded": succeeded,
            "failed": failed,
            "total_channels": len(channels),
            "distributed_at": datetime.now(timezone.utc).isoformat(),
        }

    def distribute_product_launch(
        self,
        product: dict[str, Any],
        channels: list[str],
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Announce a new product across all requested channels.

        Converts a product dict into a marketing-ready content dict then
        calls :meth:`distribute`.

        Args:
            product:  Dict with ``title``, ``description``/``body_html``,
                      ``price``, optional ``image_url``, ``url``, ``tags``.

        Returns:
            Same envelope as :meth:`distribute`.
        """
        content = self._build_product_launch_content(product)
        return self.distribute(content, channels, credentials)

    def distribute_campaign(
        self,
        campaign: dict[str, Any],
        channels: list[str],
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Distribute a marketing campaign message across channels.

        Args:
            campaign: Dict with ``name``, ``headline``, ``description``,
                      optional ``cta``, ``image_url``, ``link``.

        Returns:
            Same envelope as :meth:`distribute`.
        """
        content = self._build_campaign_content(campaign)
        return self.distribute(content, channels, credentials)

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _distribute_to_channel(
        self,
        channel: str,
        content: dict[str, Any],
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Publish *content* to a single *channel*.

        Delegates to :class:`~execution.content.publisher.ContentPublisher`.
        """
        from execution.content.publisher import ContentPublisher

        publisher = ContentPublisher()
        channel_content = self._format_for_channel(channel, content)
        channel_credentials = credentials.get(channel, credentials)

        if channel == "shopify":
            shop_url = channel_credentials.get("shop_url", "")
            api_key = channel_credentials.get("api_key", "")
            result = publisher.publish_to_shopify(shop_url, api_key, channel_content)
        else:
            result = publisher.publish_to_social(
                channel, channel_credentials, channel_content
            )

        # Ensure status is always present
        result.setdefault("channel", channel)
        return result

    def _format_for_channel(
        self, channel: str, content: dict[str, Any]
    ) -> dict[str, Any]:
        """Adapt a generic content dict for a specific channel's conventions."""
        base = dict(content)

        if channel == "shopify":
            base.setdefault("type", "article")
            base.setdefault("body_html", base.pop("body", base.get("body_html", "")))
            return base

        if channel == "twitter":
            # Twitter has a 280-char limit — build a compact tweet
            title = base.get("title", "")
            link = base.get("link", base.get("url", ""))
            tweet = title
            if link:
                tweet = f"{title} {link}"
            base["tweet"] = str(tweet)[:280]
            return base

        if channel == "instagram":
            caption_parts = [base.get("title", ""), base.get("body", "")]
            tags = base.get("tags", "")
            if isinstance(tags, list):
                tags = " ".join(f"#{t.strip()}" for t in tags)
            if tags:
                caption_parts.append(tags)
            base["caption"] = " — ".join(p for p in caption_parts if p)
            return base

        if channel == "facebook":
            body = base.get("body", base.get("description", base.get("title", "")))
            base["caption"] = body
            return base

        if channel == "linkedin":
            base.setdefault("body", base.get("description", base.get("title", "")))
            return base

        if channel == "tiktok":
            caption = base.get("title", base.get("description", ""))
            base["caption"] = caption
            return base

        return base

    # ------------------------------------------------------------------ #
    # Content builders                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_product_launch_content(product: dict[str, Any]) -> dict[str, Any]:
        title = product.get("title", "New Product Launch")
        description = product.get("description", product.get("body_html", ""))
        price = product.get("price")
        price_str = f" — ${price}" if price is not None else ""
        url = product.get("url", product.get("link", ""))
        tags = product.get("tags", [])
        image_url = product.get("image_url", "")

        body = f"{description}{price_str}"
        if url:
            body += f"\n{url}"

        return {
            "title": f"Introducing: {title}",
            "body": body.strip(),
            "body_html": f"<p>{body.strip()}</p>",
            "description": description,
            "link": url,
            "image_url": image_url,
            "tags": tags,
            "price": price,
            "content_type": "product_launch",
        }

    @staticmethod
    def _build_campaign_content(campaign: dict[str, Any]) -> dict[str, Any]:
        headline = campaign.get("headline", campaign.get("name", "New Campaign"))
        description = campaign.get("description", "")
        cta = campaign.get("cta", "")
        link = campaign.get("link", campaign.get("url", ""))
        image_url = campaign.get("image_url", "")

        body_parts = [description]
        if cta:
            body_parts.append(cta)
        if link:
            body_parts.append(link)
        body = "\n".join(p for p in body_parts if p)

        return {
            "title": headline,
            "body": body,
            "body_html": f"<p>{body}</p>",
            "description": description,
            "cta": cta,
            "link": link,
            "image_url": image_url,
            "content_type": "campaign",
        }
