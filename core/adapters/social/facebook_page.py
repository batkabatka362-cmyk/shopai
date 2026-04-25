"""FacebookPageAdapter — organic Facebook Page posting.

Same Meta Graph API family as Instagram but simpler: FB
Pages allow direct text + link + optional photo posts via
``POST /<page-id>/feed`` (text + link) or
``POST /<page-id>/photos`` (image).
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


class FacebookPageAdapter(SocialBaseAdapter):
    """Facebook Page organic posting adapter."""

    name = "facebook_page"
    config_alias = "meta_page_access_token"

    capabilities = {
        Capability.SOCIAL_PUBLISH_POST,
        Capability.SOCIAL_SCHEDULE_POST,
        Capability.SOCIAL_GET_INSIGHTS,
        Capability.SOCIAL_LIST_POSTS,
        Capability.SOCIAL_DELETE_POST,
    }

    priority = 70

    @property
    def base_url(self) -> str:
        return (
            f"https://graph.facebook.com/"
            f"{_resolved_version()}"
        )

    def is_configured(self) -> bool:
        if not super().is_configured():
            return False
        return bool(get_config().get("meta_page_id"))

    def _page_id(self) -> str:
        pid = get_config().get("meta_page_id")
        if not pid:
            raise AdapterValidationError(
                self.name,
                "'META_PAGE_ID' not configured",
            )
        return str(pid)

    # ── Capabilities ──────────────────────────────────

    def _do_publish_post(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_publish(params)
        caption = self._compose_caption(params)
        image = str(params.get("image_url") or "").strip()
        link = str(params.get("link_url") or "").strip()
        query: dict[str, Any] = {
            "access_token": self._api_key(),
        }
        if image:
            # Photos endpoint takes caption in ``caption`` field.
            query["url"] = image
            if caption:
                query["caption"] = caption
            url = (
                f"{self.base_url}/{self._page_id()}/photos"
            )
        else:
            # Text-only or link post via /feed.
            if caption:
                query["message"] = caption
            if link:
                query["link"] = link
            url = f"{self.base_url}/{self._page_id()}/feed"
        raw = self._http_request("POST", url, params=query)
        post_id = str(
            raw.get("id") or raw.get("post_id") or "",
        )
        if not post_id:
            raise AdapterError(
                self.name, "FB publish returned no id",
            )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "post_id": post_id,
                "permalink": "",
                "platform": "facebook_page",
            },
            raw=raw,
        )

    def _do_schedule_post(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_publish(params)
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
                "'publish_at_unix' must be > 0",
            )
        caption = self._compose_caption(params)
        link = str(params.get("link_url") or "").strip()
        query: dict[str, Any] = {
            "access_token": self._api_key(),
            "published": "false",
            "scheduled_publish_time": scheduled_ts,
        }
        if caption:
            query["message"] = caption
        if link:
            query["link"] = link
        raw = self._http_request(
            "POST",
            f"{self.base_url}/{self._page_id()}/feed",
            params=query,
        )
        post_id = str(raw.get("id") or "")
        if not post_id:
            raise AdapterError(
                self.name, "FB schedule returned no id",
            )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "post_id": post_id,
                "scheduled_at_unix": scheduled_ts,
                "platform": "facebook_page",
            },
            raw=raw,
        )

    def _do_get_insights(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_post_id(params)
        pid = str(params["post_id"])
        metrics = (
            "post_impressions,post_impressions_unique,"
            "post_reactions_like_total,post_clicks"
        )
        raw = self._http_request(
            "GET",
            f"{self.base_url}/{pid}/insights",
            params={
                "metric": metrics,
                "access_token": self._api_key(),
            },
        )
        values = {
            "impressions": 0, "reach": 0, "likes": 0,
            "comments": 0, "shares": 0, "saves": 0,
        }
        mapping = {
            "post_impressions": "impressions",
            "post_impressions_unique": "reach",
            "post_reactions_like_total": "likes",
        }
        rows = raw.get("data") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = mapping.get(str(row.get("name") or ""))
            if not key:
                continue
            vals = row.get("values") or []
            if not vals:
                continue
            try:
                values[key] = int(
                    (vals[0] or {}).get("value") or 0,
                )
            except (TypeError, ValueError):
                values[key] = 0
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
            f"{self.base_url}/{self._page_id()}/posts",
            params={
                "limit": limit,
                "fields": (
                    "id,message,created_time,permalink_url"
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
                "message": str(row.get("message") or ""),
                "permalink":
                    str(row.get("permalink_url") or ""),
                "timestamp":
                    str(row.get("created_time") or ""),
            })
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "platform": "facebook_page",
                "posts": posts,
                "total": len(posts),
            },
            raw=raw,
        )

    def _do_delete_post(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_post_id(params)
        pid = str(params["post_id"])
        raw = self._http_request(
            "DELETE",
            f"{self.base_url}/{pid}",
            params={"access_token": self._api_key()},
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "post_id": pid,
                "deleted": bool(raw.get("success", True)),
            },
            raw=raw,
        )
