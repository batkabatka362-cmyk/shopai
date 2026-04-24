"""InstagramAdapter — organic posting via IG Graph API.

Instagram Business / Creator accounts connected to a Meta
Page can be posted to via the Graph API. Two-step publish:

  1. POST ``/<ig-account-id>/media`` → returns a container id
  2. POST ``/<ig-account-id>/media_publish`` with the
     container id → returns the real post id

This adapter wraps both steps so callers see a single
``publish_post`` call. Schedule_post uses the native
``scheduled_publish_time`` field Instagram added in 2024.

Auth: long-lived page-scoped access token obtained through
the Meta Ads OAuth flow (the same token can read ad
insights AND post to the linked IG account).
"""
from __future__ import annotations

import os
from typing import Any

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import AdapterError, AdapterValidationError
from ._base import SocialBaseAdapter


_DEFAULT_API_VERSION = "v21.0"


def _resolved_version() -> str:
    override = os.environ.get(
        "SHOPAI_META_API_VERSION", "",
    ).strip()
    return override or _DEFAULT_API_VERSION


class InstagramAdapter(SocialBaseAdapter):
    """Instagram Business organic posting adapter."""

    name = "instagram"
    config_alias = "meta_page_access_token"

    capabilities = {
        Capability.SOCIAL_PUBLISH_POST,
        Capability.SOCIAL_SCHEDULE_POST,
        Capability.SOCIAL_GET_INSIGHTS,
        Capability.SOCIAL_LIST_POSTS,
    }
    # Instagram forbids post deletion via Graph API — only the
    # native app can remove posts. SOCIAL_DELETE_POST stays
    # off the capability set so the router skips IG for it.

    priority = 75

    @property
    def base_url(self) -> str:
        return (
            f"https://graph.facebook.com/"
            f"{_resolved_version()}"
        )

    def is_configured(self) -> bool:
        if not super().is_configured():
            return False
        return bool(
            get_config().get("instagram_business_account_id"),
        )

    def _ig_account_id(self) -> str:
        aid = get_config().get("instagram_business_account_id")
        if not aid:
            raise AdapterValidationError(
                self.name,
                "'INSTAGRAM_BUSINESS_ACCOUNT_ID' not configured",
            )
        return str(aid)

    # ── Capabilities ──────────────────────────────────

    def _do_publish_post(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_publish(params)
        image = str(params.get("image_url") or "").strip()
        video = str(params.get("video_url") or "").strip()
        if not image and not video:
            raise AdapterValidationError(
                self.name,
                "Instagram posts require image_url or video_url",
            )
        caption = self._compose_caption(params)
        # 1) Create media container
        container = self._create_media_container(
            image=image, video=video, caption=caption,
        )
        # 2) Publish container
        published = self._http_request(
            "POST",
            (
                f"{self.base_url}/{self._ig_account_id()}/"
                f"media_publish"
            ),
            params={
                "creation_id": container,
                "access_token": self._api_key(),
            },
        )
        post_id = str(published.get("id") or "")
        if not post_id:
            raise AdapterError(
                self.name,
                "Instagram media_publish returned no id",
            )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "post_id": post_id,
                "permalink": "",
                "platform": "instagram",
            },
            raw=published,
        )

    def _do_schedule_post(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_publish(params)
        image = str(params.get("image_url") or "").strip()
        video = str(params.get("video_url") or "").strip()
        if not image and not video:
            raise AdapterValidationError(
                self.name,
                "Instagram posts require image_url or video_url",
            )
        try:
            scheduled_ts = int(params.get("publish_at_unix", 0))
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name,
                "'publish_at_unix' must be int UNIX seconds",
            ) from exc
        if scheduled_ts <= 0:
            raise AdapterValidationError(
                self.name,
                "'publish_at_unix' must be a future UNIX "
                "timestamp",
            )
        caption = self._compose_caption(params)
        container = self._create_media_container(
            image=image,
            video=video,
            caption=caption,
            scheduled_ts=scheduled_ts,
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "container_id": container,
                "scheduled_at_unix": scheduled_ts,
                "platform": "instagram",
            },
        )

    def _do_get_insights(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_post_id(params)
        pid = str(params["post_id"])
        # IG insights metric set — "reach" + "impressions"
        # deprecated on some flavours; the base set covers
        # both image + reel posts.
        metrics = "impressions,reach,likes,comments,saved,shares"
        raw = self._http_request(
            "GET",
            f"{self.base_url}/{pid}/insights",
            params={
                "metric": metrics,
                "access_token": self._api_key(),
            },
        )
        values: dict[str, int] = {
            k: 0 for k in (
                "impressions", "reach", "likes",
                "comments", "shares", "saves",
            )
        }
        rows = raw.get("data") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "")
            lookup = "saves" if name == "saved" else name
            if lookup not in values:
                continue
            vals = row.get("values") or []
            if not vals:
                continue
            try:
                values[lookup] = int(
                    (vals[0] or {}).get("value") or 0,
                )
            except (TypeError, ValueError):
                values[lookup] = 0
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"post_id": pid, **values},
            raw=raw,
        )

    def _do_list_posts(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        limit = max(1, min(int(params.get("limit", 25)), 100))
        raw = self._http_request(
            "GET",
            f"{self.base_url}/{self._ig_account_id()}/media",
            params={
                "limit": limit,
                "fields": (
                    "id,caption,permalink,media_type,"
                    "timestamp,media_url"
                ),
                "access_token": self._api_key(),
            },
        )
        rows = raw.get("data") or []
        posts: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            posts.append({
                "post_id": str(row.get("id") or ""),
                "caption": str(row.get("caption") or ""),
                "permalink": str(row.get("permalink") or ""),
                "media_type": str(row.get("media_type") or ""),
                "media_url": str(row.get("media_url") or ""),
                "timestamp": str(row.get("timestamp") or ""),
            })
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "platform": "instagram",
                "posts": posts,
                "total": len(posts),
            },
            raw=raw,
        )

    # ── Internals ─────────────────────────────────────

    def _create_media_container(
        self,
        *,
        image: str = "",
        video: str = "",
        caption: str = "",
        scheduled_ts: int = 0,
    ) -> str:
        query: dict[str, Any] = {
            "access_token": self._api_key(),
        }
        if image:
            query["image_url"] = image
        if video:
            query["video_url"] = video
            # IG requires explicit media_type for video.
            query["media_type"] = "REELS"
        if caption:
            query["caption"] = caption
        if scheduled_ts:
            query["scheduled_publish_time"] = scheduled_ts
        raw = self._http_request(
            "POST",
            f"{self.base_url}/{self._ig_account_id()}/media",
            params=query,
        )
        cid = str(raw.get("id") or "")
        if not cid:
            raise AdapterError(
                self.name,
                "Instagram media create returned no id",
            )
        return cid
