"""W963-152: Loox vendor handler.

Loox webhook docs:
  https://help.loox.com/article/376-loox-webhooks

Loox is the dominant photo-review app for Shopify stores.
Unlike Judge.me (basic text + star rating), Loox is built
around customer-submitted photos + videos as social proof.
This handler feeds the photo-review feedback loop into
ShopAI's reviews_management + customer_outreach engines.

Auth: HMAC-SHA256 + base64. Header
'X-Loox-Hmac-Sha256'.

Topics ShopAI listens to:

  review.created   -> reviews_management (intake +
                      quality scoring) + customer_outreach
                      (thank-you flow)
  review.published -> reviews_management (live signal --
                      conversion contribution starts)
  review.declined  -> customer_support (operator may
                      want to follow up)
  review.media_added -> reviews_management (photo /
                      video boost -- higher trust score)

Store identifier: Loox events include `shop_domain`
field at the top level (e.g. 'store-a.myshopify.com').
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from typing import Any

from ..handler import VendorHandler

logger = logging.getLogger(__name__)


class LooxVendorHandler(VendorHandler):
    name = "loox"

    def __init__(
        self,
        secret_env: str = "LOOX_WEBHOOK_SECRET",
    ) -> None:
        self._secret_env = secret_env

    def _secret(self) -> str:
        return os.environ.get(self._secret_env, "")

    def verify_hmac(
        self, raw_body: bytes, signature: str,
    ) -> bool:
        secret = self._secret()
        if not secret:
            return True
        if not signature:
            return False
        expected = base64.b64encode(
            hmac.new(
                secret.encode("utf-8"),
                raw_body, hashlib.sha256,
            ).digest(),
        ).decode("ascii")
        return hmac.compare_digest(expected, signature)

    def extract_topic(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        # Loox sends event in 'event' field at the top
        # level, e.g. 'review.created'.
        topic = str(payload.get("event") or "").strip()
        if not topic:
            return "unknown"
        return topic

    def extract_store_identifier(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        # Loox always carries shop_domain at top level.
        # Also accept shopai_store_id for non-Shopify
        # multi-tenant cases.
        shop = (
            payload.get("shop_domain")
            or payload.get("shopify_domain")
            or payload.get("shopai_store_id")
            or ""
        )
        if isinstance(shop, str):
            return shop
        return ""

    def normalise_payload(
        self, topic: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Surface the review object as the engine-facing
        payload, with normalised score + media info.

        Loox review payload shape (typical):
          {
            "event": "review.created",
            "shop_domain": "store-a.myshopify.com",
            "review": {
              "id": 12345,
              "product_id": "...",
              "rating": 5,
              "title": "Great!",
              "body": "...",
              "reviewer_name": "...",
              "reviewer_email": "...",
              "photos": [{"url": "..."}],
              "videos": [],
              "is_published": true,
              "created_at": "...",
            }
          }
        """
        review = payload.get("review")
        if not isinstance(review, dict):
            return payload

        # Normalise media count
        photos = review.get("photos") or []
        videos = review.get("videos") or []
        photo_count = (
            len(photos) if isinstance(photos, list)
            else 0
        )
        video_count = (
            len(videos) if isinstance(videos, list)
            else 0
        )
        has_media = (photo_count + video_count) > 0

        rating = 0
        try:
            rating = int(review.get("rating") or 0)
        except (TypeError, ValueError):
            rating = 0

        # Flat shape consumed by engines
        out: dict[str, Any] = {
            "review_id": str(review.get("id", "")),
            "product_id": str(
                review.get("product_id", ""),
            ),
            "rating": max(0, min(5, rating)),
            "title": str(review.get("title", "")),
            "body": str(review.get("body", "")),
            "reviewer_name": str(
                review.get("reviewer_name", ""),
            ),
            "reviewer_email": str(
                review.get("reviewer_email", ""),
            ),
            "photo_count": photo_count,
            "video_count": video_count,
            "has_media": has_media,
            "is_published": bool(
                review.get("is_published", False),
            ),
            "created_at": str(
                review.get("created_at", ""),
            ),
            "_loox_event": topic,
        }
        return out
