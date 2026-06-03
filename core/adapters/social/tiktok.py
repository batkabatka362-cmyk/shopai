"""TikTokAdapter — TikTok for Business Content Posting API (W963-12).

TikTok is the second-largest visual social platform after Pinterest
for product discovery in beauty / fashion / home niches. The
TikTok for Business Content Posting API supports:

  * **Authentication probe** — verify the access_token
    (SOCIAL_VERIFY_AUTH).
  * **Post listing** — recent posts on the business account
    (SOCIAL_LIST_POSTS).
  * **Post creation** — publish photo or video posts from
    public media URLs with caption + hashtags + product link
    (SOCIAL_CREATE_POST).

Authentication: OAuth 2.0 access_token tied to a TikTok
Business Center account. Operators generate the token via:
  https://business.tiktok.com -> Developer Center

Required scopes:
  - user.info.basic
  - video.upload
  - video.list
  - business.create

TikTok API rate limits:
  - 100 requests / hour for Content Posting API
  - Post upload async (poll status after upload)

The adapter's create_post does NOT block on async processing.
It returns the publish_id; callers poll separately (Phase 2)
or trust TikTok's eventual-consistency for content placement.
"""
from __future__ import annotations

import json
from typing import Any

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimited,
    AdapterValidationError,
)

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False


_TIKTOK_BASE = "https://business-api.tiktok.com/open_api/v1.3"
_DEFAULT_TIMEOUT = 30.0


class TikTokAdapter(BaseAdapter):
    """TikTok for Business v1.3 adapter."""

    name = "tiktok"
    base_url = _TIKTOK_BASE
    config_alias = "tiktok"
    category = AdapterCategory.SOCIAL

    priority = 85  # below Pinterest (90) -- Pinterest > TikTok ROI
    cost_per_call = 0.0

    required_scopes: tuple[str, ...] = ()

    capabilities = frozenset({
        Capability.SOCIAL_VERIFY_AUTH,
        Capability.SOCIAL_LIST_POSTS,
        Capability.SOCIAL_CREATE_POST,
    })

    # ── Configuration ─────────────────────────────────────────

    def is_configured(self) -> bool:
        return bool(get_config().get(self.config_alias))

    def _api_key(self) -> str:
        key = get_config().get(self.config_alias)
        if not key:
            raise AdapterAuthError(
                self.name, "TIKTOK_ACCESS_TOKEN not set",
            )
        return str(key)

    def _business_id(self) -> str | None:
        return get_config().get("tiktok_business_id")

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Access-Token": self._api_key(),
            "Content-Type": "application/json",
        }

    # ── Dispatch ──────────────────────────────────────────────

    def _execute(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        if not _REQUESTS_AVAILABLE:
            raise AdapterError(
                self.name,
                "requests library not available",
            )

        if capability == Capability.SOCIAL_VERIFY_AUTH:
            return self._verify_auth(capability)
        if capability == Capability.SOCIAL_LIST_POSTS:
            return self._list_posts(capability, params)
        if capability == Capability.SOCIAL_CREATE_POST:
            return self._create_post(capability, params)
        raise AdapterValidationError(
            self.name,
            f"unsupported capability: {capability.value}",
        )

    # ── Verify auth ───────────────────────────────────────────

    def _verify_auth(
        self, capability: Capability,
    ) -> AdapterResult:
        raw = self._http_get("/user/info/")
        data = raw.get("data", {}) or {}
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "username": data.get("display_name", ""),
                "business_id": data.get("business_id", ""),
                "account_type": data.get("account_type", ""),
            },
            raw=raw,
        )

    # ── List posts ────────────────────────────────────────────

    def _list_posts(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        page_size = int(params.get("limit", 25))
        page_size = max(1, min(page_size, 100))
        biz = (
            str(params.get("business_id") or "")
            or self._business_id()
            or ""
        )
        if not biz:
            raise AdapterValidationError(
                self.name,
                "business_id required (set TIKTOK_BUSINESS_ID "
                "env or pass --business-id)",
            )
        raw = self._http_get(
            "/business/video/list/",
            query={
                "business_id": biz,
                "page_size": page_size,
            },
        )
        items = (raw.get("data") or {}).get("videos", []) or []
        posts = []
        for v in items:
            if not isinstance(v, dict):
                continue
            posts.append({
                "id": v.get("item_id", ""),
                "caption": v.get("caption", ""),
                "create_time": v.get("create_time", 0),
                "share_url": v.get("share_url", ""),
                "view_count": v.get("view_count", 0),
                "like_count": v.get("like_count", 0),
                "comment_count": v.get("comment_count", 0),
            })
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "posts": posts,
                "count": len(posts),
            },
            raw=raw,
        )

    # ── Create post ───────────────────────────────────────────

    def _create_post(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        # Required: business_id + caption + media_url
        biz = (
            str(params.get("business_id") or "")
            or self._business_id()
            or ""
        )
        if not biz:
            raise AdapterValidationError(
                self.name,
                "business_id required (set TIKTOK_BUSINESS_ID "
                "env or pass via params)",
            )

        caption = str(params.get("caption") or "").strip()
        if not caption:
            raise AdapterValidationError(
                self.name,
                "'caption' is required",
            )
        if len(caption) > 2200:  # TikTok limit
            caption = caption[:2200]

        media_url = str(params.get("media_url") or "").strip()
        if not media_url:
            raise AdapterValidationError(
                self.name,
                "'media_url' is required "
                "(public HTTPS image/video URL)",
            )
        if not (
            media_url.startswith("http://")
            or media_url.startswith("https://")
        ):
            raise AdapterValidationError(
                self.name,
                "'media_url' must be HTTP(S)",
            )

        # Optional fields.
        media_type = str(
            params.get("media_type") or "PHOTO",
        ).upper()
        if media_type not in ("PHOTO", "VIDEO"):
            media_type = "PHOTO"

        # privacy_level defaults to PUBLIC_TO_EVERYONE for
        # business accounts. Operators wanting drafts pass
        # SELF_ONLY.
        privacy = str(
            params.get("privacy") or "PUBLIC_TO_EVERYONE",
        ).upper()
        if privacy not in (
            "PUBLIC_TO_EVERYONE",
            "MUTUAL_FOLLOW_FRIENDS",
            "SELF_ONLY",
        ):
            privacy = "PUBLIC_TO_EVERYONE"

        body: dict[str, Any] = {
            "business_id": biz,
            "post_info": {
                "caption": caption,
                "privacy_level": privacy,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "media_type": media_type,
                "video_url" if media_type == "VIDEO"
                else "photo_url": media_url,
            },
        }

        raw = self._http_post(
            "/business/post/publish/", body=body,
        )
        data_block = raw.get("data") or {}
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "publish_id": data_block.get("publish_id", ""),
                "share_url": data_block.get("share_url", ""),
                "status": data_block.get(
                    "status", "PROCESSING",
                ),
            },
            raw=raw,
        )

    # ── HTTP plumbing ─────────────────────────────────────────

    def _http_get(
        self, path: str, *, query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._http_request("GET", path, query=query)

    def _http_post(
        self, path: str, *, body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._http_request("POST", path, body=body)

    def _http_request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = _requests.request(
                method,
                url,
                headers=self._auth_headers(),
                data=json.dumps(body) if body else None,
                params=query,
                timeout=_DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"network error: {type(exc).__name__}",
            ) from exc

        if resp.status_code in (401, 403):
            raise AdapterAuthError(
                self.name,
                f"auth failed (HTTP {resp.status_code}): "
                f"{resp.text[:200]}",
            )
        if resp.status_code == 429:
            raise AdapterRateLimited(
                self.name,
                "TikTok rate limit hit (HTTP 429)",
            )
        if resp.status_code >= 400:
            raise AdapterError(
                self.name,
                f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            return {}

        # TikTok wraps real errors in success-shaped responses.
        # Per their API: code 0 = success; any non-zero is fail.
        code = payload.get("code")
        if isinstance(code, int) and code != 0:
            raise AdapterError(
                self.name,
                f"TikTok error code={code}: "
                f"{payload.get('message', '')[:150]}",
            )
        return payload
