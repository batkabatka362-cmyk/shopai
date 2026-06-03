"""TikTok publishing helpers — list_posts + publish_post."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


_ENGINE = "tiktok_publisher"
_ACTION_PUBLISH = "publish_post"


@dataclass
class PostListResult:
    success: bool
    posts: list[dict] = field(default_factory=list)
    error: str = ""


@dataclass
class PublishResult:
    success: bool
    publish_id: str = ""
    caption: str = ""
    media_type: str = ""
    share_url: str = ""
    status: str = ""
    error: str = ""


def list_posts(
    *, limit: int = 25, business_id: str | None = None,
) -> PostListResult:
    try:
        from core.adapters.router import get_router
        from core.adapters.base import Capability
        router = get_router()
        params: dict = {"limit": limit}
        if business_id:
            params["business_id"] = business_id
        result = router.execute(
            Capability.SOCIAL_LIST_POSTS, params,
        )
    except Exception as exc:  # noqa: BLE001
        return PostListResult(
            success=False,
            error=f"router error: {type(exc).__name__}",
        )
    if not getattr(result, "ok", False):
        return PostListResult(
            success=False,
            error=getattr(result, "error", "") or "list failed",
        )
    data = getattr(result, "data", None) or {}
    return PostListResult(
        success=True,
        posts=list(data.get("posts") or []),
    )


def publish_post(
    *,
    caption: str,
    media_url: str,
    media_type: str = "PHOTO",
    business_id: str | None = None,
    privacy: str = "PUBLIC_TO_EVERYONE",
    record_writeback: bool = True,
) -> PublishResult:
    if not caption:
        return PublishResult(
            success=False, error="caption is required",
        )
    if not media_url:
        return PublishResult(
            success=False, error="media_url is required",
        )
    if not (
        media_url.startswith("http://")
        or media_url.startswith("https://")
    ):
        return PublishResult(
            success=False,
            error="media_url must be a public HTTP(S) URL",
        )
    media_type = (media_type or "PHOTO").upper()
    if media_type not in ("PHOTO", "VIDEO"):
        return PublishResult(
            success=False,
            error="media_type must be PHOTO or VIDEO",
        )

    try:
        from core.adapters.router import get_router
        from core.adapters.base import Capability
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        return PublishResult(
            success=False,
            error=f"router unavailable: {type(exc).__name__}",
        )

    params: dict = {
        "caption": caption,
        "media_url": media_url,
        "media_type": media_type,
        "privacy": privacy,
    }
    if business_id:
        params["business_id"] = business_id

    try:
        result = router.execute(
            Capability.SOCIAL_CREATE_POST, params,
        )
    except Exception as exc:  # noqa: BLE001
        if record_writeback:
            _record(params, success=False, error=str(exc))
        return PublishResult(
            success=False,
            error=f"adapter raised: {type(exc).__name__}",
        )

    ok = bool(getattr(result, "ok", False))
    err = getattr(result, "error", "") or ""
    data = getattr(result, "data", None) or {}

    if record_writeback:
        _record(
            params, success=ok,
            error=None if ok else err,
        )

    if not ok:
        return PublishResult(
            success=False,
            error=err or "publish failed",
            caption=caption,
            media_type=media_type,
        )

    return PublishResult(
        success=True,
        publish_id=str(data.get("publish_id") or ""),
        caption=caption,
        media_type=media_type,
        share_url=str(data.get("share_url") or ""),
        status=str(data.get("status") or "PROCESSING"),
    )


def _record(
    params: dict, *, success: bool, error: str | None,
) -> None:
    try:
        from engines._writeback_recorder import (
            record_writeback,
        )
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_PUBLISH,
            capability="SOCIAL_CREATE_POST",
            params={
                "media_type": params.get("media_type", ""),
                "caption": params.get("caption", "")[:80],
            },
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "tiktok_publisher writeback raised: %s", exc,
        )
