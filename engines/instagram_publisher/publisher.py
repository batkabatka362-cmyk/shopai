"""Instagram publishing helpers — list_posts + publish_post."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


_ENGINE = "instagram_publisher"
_ACTION_PUBLISH = "publish_post"


@dataclass
class PostListResult:
    success: bool
    posts: list[dict] = field(default_factory=list)
    error: str = ""


@dataclass
class PublishResult:
    success: bool
    post_id: str = ""
    creation_id: str = ""
    media_type: str = ""
    error: str = ""


def list_posts(
    *, limit: int = 25, account_id: str | None = None,
) -> PostListResult:
    try:
        from core.adapters.router import get_router
        from core.adapters.base import Capability
        router = get_router()
        params: dict = {"limit": limit}
        if account_id:
            params["account_id"] = account_id
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
    media_type: str = "IMAGE",
    account_id: str | None = None,
    record_writeback: bool = True,
) -> PublishResult:
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
    media_type = (media_type or "IMAGE").upper()
    if media_type not in ("IMAGE", "VIDEO", "REELS"):
        return PublishResult(
            success=False,
            error="media_type must be IMAGE / VIDEO / REELS",
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
    }
    if account_id:
        params["account_id"] = account_id

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
            media_type=media_type,
        )

    return PublishResult(
        success=True,
        post_id=str(data.get("post_id") or ""),
        creation_id=str(data.get("creation_id") or ""),
        media_type=str(data.get("media_type") or media_type),
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
            "instagram_publisher writeback raised: %s", exc,
        )
