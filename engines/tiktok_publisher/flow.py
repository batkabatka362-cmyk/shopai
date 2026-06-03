"""TikTok Publisher Engine — Pattern Q envelope.

Three actions: status / list-posts / publish-post. Same shape
as engines.pinterest_publisher.flow.
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .publisher import list_posts, publish_post
from .status import get_status

logger = logging.getLogger(__name__)


class TikTokPublisherEngine:
    ENGINE_NAME = "tiktok_publisher"

    def run(
        self, input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start = time.monotonic()
        payload = self._safe_copy(input_payload)
        if payload is None:
            return self._fail("Input copy failed", 0.0)
        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        action = (data.get("action") or "status").lower()

        if action == "status":
            skip_live = bool(data.get("skip_live", False))
            s = get_status(skip_live=skip_live)
            return self._success(
                {
                    "action": "status",
                    "status": asdict(s),
                    "ready": s.ready,
                    "next_action": _status_next_action(s),
                },
                start,
            )

        if action == "list-posts":
            limit = int(data.get("limit", 25))
            business_id = data.get("business_id")
            res = list_posts(
                limit=limit, business_id=business_id,
            )
            return self._success(
                {
                    "action": "list-posts",
                    "success": res.success,
                    "posts": res.posts,
                    "count": len(res.posts),
                    "error": res.error or None,
                    "next_action": (
                        "Publish: shopai tiktok publish-post "
                        "--caption C --media-url U "
                        "--type PHOTO"
                    ) if res.success else (
                        f"List failed: {res.error}. "
                        "Run shopai tiktok status."
                    ),
                },
                start,
            )

        if action == "publish-post":
            res = publish_post(
                caption=str(data.get("caption") or ""),
                media_url=str(data.get("media_url") or ""),
                media_type=str(
                    data.get("media_type") or "PHOTO",
                ),
                business_id=data.get("business_id"),
                privacy=str(
                    data.get("privacy") or "PUBLIC_TO_EVERYONE",
                ),
            )
            return self._success(
                {
                    "action": "publish-post",
                    "published": res.success,
                    "publish_id": res.publish_id,
                    "caption": res.caption,
                    "media_type": res.media_type,
                    "share_url": res.share_url,
                    "status": res.status,
                    "error": res.error or None,
                    "next_action": (
                        f"Post processing. status="
                        f"{res.status}. share_url="
                        f"{res.share_url or '(pending)'}"
                    ) if res.success else (
                        f"Publish failed: {res.error}"
                    ),
                },
                start,
            )

        return self._fail(
            f"unknown action '{action}'. Use status / "
            "list-posts / publish-post.",
            time.monotonic() - start,
        )

    # ── Internal ──────────────────────────────────────────

    @staticmethod
    def _safe_copy(payload: Any) -> Any:
        if payload is None:
            return {}
        try:
            return copy.deepcopy(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("input copy raised: %s", exc)
            return None

    def _success(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "data": data,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(
                    time.monotonic() - start, 3,
                ),
            },
            "error": None,
        }

    def _fail(
        self, reason: str, elapsed: float,
    ) -> dict[str, Any]:
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }


def _status_next_action(s) -> str:
    if s.ready and s.auth_verified:
        return (
            f"TikTok ready (user={s.username}). "
            "List posts: shopai tiktok posts"
        )
    if s.ready:
        return (
            "Credentials present. Verify with: "
            "shopai tiktok status (live probe)"
        )
    return (
        "Connect: shopai tiktok connect --token X "
        "--business-id Y. Setup: "
        "https://business.tiktok.com -> Developer Center"
    )
