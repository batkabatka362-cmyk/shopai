"""Pin publishing helpers.

Two operator surfaces:
  - list_boards()  -> list of existing boards (id + name)
  - publish_pin()  -> publish single pin given board + image + title

Both record via Pattern Z so the autonomous loop's outcome
tracking picks up the pin activity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


_ENGINE = "pinterest_publisher"
_ACTION_PUBLISH = "publish_pin"


@dataclass
class BoardListResult:
    success: bool
    boards: list[dict] = field(default_factory=list)
    error: str = ""


@dataclass
class PublishResult:
    success: bool
    pin_id: str = ""
    title: str = ""
    board_id: str = ""
    link: str = ""
    pin_url: str = ""
    error: str = ""


def list_boards(limit: int = 25) -> BoardListResult:
    try:
        from core.adapters.router import get_router
        from core.adapters.base import Capability
        router = get_router()
        result = router.execute(
            Capability.SOCIAL_LIST_BOARDS, {"limit": limit},
        )
    except Exception as exc:  # noqa: BLE001
        return BoardListResult(
            success=False,
            error=f"router error: {type(exc).__name__}",
        )
    if not getattr(result, "ok", False):
        return BoardListResult(
            success=False,
            error=getattr(result, "error", "") or "list failed",
        )
    data = getattr(result, "data", None) or {}
    return BoardListResult(
        success=True,
        boards=list(data.get("boards") or []),
    )


def publish_pin(
    *,
    board_id: str,
    title: str,
    image_url: str,
    description: str = "",
    link: str = "",
    record_writeback: bool = True,
) -> PublishResult:
    if not board_id:
        return PublishResult(
            success=False, error="board_id is required",
        )
    if not title:
        return PublishResult(
            success=False, error="title is required",
        )
    if not image_url:
        return PublishResult(
            success=False, error="image_url is required",
        )
    if not (
        image_url.startswith("http://")
        or image_url.startswith("https://")
    ):
        return PublishResult(
            success=False,
            error="image_url must be a public HTTP(S) URL",
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

    params = {
        "board_id": board_id,
        "title": title,
        "image_url": image_url,
        "description": description,
        "link": link,
    }
    try:
        result = router.execute(
            Capability.SOCIAL_CREATE_PIN, params,
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
        )

    return PublishResult(
        success=True,
        pin_id=str(data.get("pin_id") or ""),
        title=title,
        board_id=board_id,
        link=link,
        pin_url=str(data.get("url") or link),
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
            capability="SOCIAL_CREATE_PIN",
            params={
                "board_id": params.get("board_id", ""),
                "title": params.get("title", ""),
            },
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "pinterest_publisher writeback raised: %s", exc,
        )
