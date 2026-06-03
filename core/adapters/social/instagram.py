"""InstagramAdapter — Instagram Graph API (W963-15).

Third visual social platform after Pinterest (W963-10) and TikTok
(W963-12). Closes the visual-social trifecta for e-commerce
discovery.

Instagram Graph API publish flow is a 2-step async dance:

  1. POST /{ig-user-id}/media     -> create media container,
                                      returns creation_id
  2. POST /{ig-user-id}/media_publish  -> publish container by id

This adapter wraps the dance into a single SOCIAL_CREATE_POST
call that performs both steps + returns the published media id.
For images this typically completes synchronously; for video the
container needs a few seconds to process before publish succeeds.

Authentication: OAuth bearer token tied to a Facebook Page that
manages an Instagram Business Account. Operators generate via:
  https://developers.facebook.com -> create app -> add
  Instagram Graph API product -> generate token with
  instagram_basic + instagram_content_publish permissions

Required permissions:
  - instagram_basic
  - instagram_content_publish
  - pages_show_list
  - pages_read_engagement

Rate limits: same as Meta Graph API generally — 200 calls per
hour per user. Publish endpoint is the bottleneck.
"""
from __future__ import annotations

import json
import time
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


_GRAPH_BASE = "https://graph.facebook.com/v21.0"
_DEFAULT_TIMEOUT = 30.0
# Time to wait between container create + publish for VIDEO
# media. Photo containers are ready instantly.
_VIDEO_CONTAINER_DELAY = 5.0


class InstagramAdapter(BaseAdapter):
    """Instagram Graph API v21.0 adapter."""

    name = "instagram"
    base_url = _GRAPH_BASE
    config_alias = "instagram"
    category = AdapterCategory.SOCIAL

    priority = 88  # Between Pinterest (90) and TikTok (85)
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
                self.name,
                "INSTAGRAM_ACCESS_TOKEN not set",
            )
        return str(key)

    def _account_id(self) -> str | None:
        return get_config().get("instagram_account_id")

    def _auth_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _token_param(self) -> dict[str, str]:
        """Instagram Graph API takes the token as a query
        parameter, not a header (older Facebook pattern)."""
        return {"access_token": self._api_key()}

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
        account_id = self._account_id()
        if not account_id:
            raise AdapterValidationError(
                self.name,
                "INSTAGRAM_ACCOUNT_ID required for auth verify",
            )
        raw = self._http_get(
            f"/{account_id}",
            query={
                "fields": "id,username,name,profile_picture_url",
            },
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "account_id": raw.get("id", ""),
                "username": raw.get("username", ""),
                "name": raw.get("name", ""),
                "profile_picture_url": raw.get(
                    "profile_picture_url", "",
                ),
            },
            raw=raw,
        )

    # ── List posts (media) ────────────────────────────────────

    def _list_posts(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        account_id = (
            str(params.get("account_id") or "")
            or self._account_id()
            or ""
        )
        if not account_id:
            raise AdapterValidationError(
                self.name,
                "INSTAGRAM_ACCOUNT_ID required",
            )
        limit = max(1, min(int(params.get("limit", 25)), 100))

        raw = self._http_get(
            f"/{account_id}/media",
            query={
                "fields": (
                    "id,caption,media_type,media_url,"
                    "permalink,timestamp,like_count,"
                    "comments_count"
                ),
                "limit": limit,
            },
        )
        items = raw.get("data", []) or []
        posts = []
        for m in items:
            if not isinstance(m, dict):
                continue
            posts.append({
                "id": m.get("id", ""),
                "caption": m.get("caption", ""),
                "media_type": m.get("media_type", ""),
                "media_url": m.get("media_url", ""),
                "permalink": m.get("permalink", ""),
                "timestamp": m.get("timestamp", ""),
                "like_count": m.get("like_count", 0),
                "comments_count": m.get("comments_count", 0),
            })
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"posts": posts, "count": len(posts)},
            raw=raw,
        )

    # ── Create post (2-step async dance) ──────────────────────

    def _create_post(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        account_id = (
            str(params.get("account_id") or "")
            or self._account_id()
            or ""
        )
        if not account_id:
            raise AdapterValidationError(
                self.name,
                "INSTAGRAM_ACCOUNT_ID required",
            )

        caption = str(params.get("caption") or "").strip()
        if len(caption) > 2200:  # IG caption limit
            caption = caption[:2200]

        media_url = str(params.get("media_url") or "").strip()
        if not media_url:
            raise AdapterValidationError(
                self.name,
                "'media_url' is required "
                "(public HTTPS image or video URL)",
            )
        if not (
            media_url.startswith("http://")
            or media_url.startswith("https://")
        ):
            raise AdapterValidationError(
                self.name,
                "'media_url' must be HTTP(S)",
            )

        media_type = str(
            params.get("media_type") or "IMAGE",
        ).upper()
        if media_type not in ("IMAGE", "VIDEO", "REELS"):
            media_type = "IMAGE"

        # Step 1: create media container.
        container_body: dict[str, Any] = {"caption": caption}
        if media_type == "IMAGE":
            container_body["image_url"] = media_url
        else:
            container_body["video_url"] = media_url
            container_body["media_type"] = (
                "REELS" if media_type == "REELS" else "VIDEO"
            )

        container_raw = self._http_post(
            f"/{account_id}/media", body=container_body,
        )
        creation_id = container_raw.get("id", "")
        if not creation_id:
            raise AdapterError(
                self.name,
                "container create returned no id: "
                f"{json.dumps(container_raw)[:200]}",
            )

        # Step 2: publish container.
        # Video containers need a few seconds to process.
        if media_type in ("VIDEO", "REELS"):
            time.sleep(_VIDEO_CONTAINER_DELAY)

        publish_raw = self._http_post(
            f"/{account_id}/media_publish",
            body={"creation_id": creation_id},
        )

        media_id = publish_raw.get("id", "")
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "post_id": media_id,
                "creation_id": creation_id,
                "account_id": account_id,
                "media_type": media_type,
            },
            raw={"container": container_raw, "publish": publish_raw},
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
        full_query = dict(self._token_param())
        if query:
            full_query.update(query)
        try:
            resp = _requests.request(
                method,
                url,
                headers=self._auth_headers(),
                data=json.dumps(body) if body else None,
                params=full_query,
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
                "Instagram rate limit hit (HTTP 429)",
            )
        if resp.status_code >= 400:
            raise AdapterError(
                self.name,
                f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {}
