"""Instagram Publisher Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .publisher import list_posts, publish_post
from .status import get_status

logger = logging.getLogger(__name__)


class InstagramPublisherEngine:
    ENGINE_NAME = "instagram_publisher"

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

        action = str(data.get("action") or "status").lower()

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
            res = list_posts(
                limit=int(data.get("limit", 25)),
                account_id=data.get("account_id"),
            )
            return self._success(
                {
                    "action": "list-posts",
                    "success": res.success,
                    "posts": res.posts,
                    "count": len(res.posts),
                    "error": res.error or None,
                    "next_action": (
                        "Publish: shopai instagram "
                        "publish-post --caption C "
                        "--media-url U"
                    ) if res.success else (
                        f"List failed: {res.error}. "
                        "Run shopai instagram status."
                    ),
                },
                start,
            )

        if action == "publish-post":
            res = publish_post(
                caption=str(data.get("caption") or ""),
                media_url=str(data.get("media_url") or ""),
                media_type=str(
                    data.get("media_type") or "IMAGE",
                ),
                account_id=data.get("account_id"),
            )
            return self._success(
                {
                    "action": "publish-post",
                    "published": res.success,
                    "post_id": res.post_id,
                    "creation_id": res.creation_id,
                    "media_type": res.media_type,
                    "error": res.error or None,
                    "next_action": (
                        f"Post live on Instagram. "
                        f"post_id={res.post_id or '(unknown)'}"
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
            f"Instagram ready (user={s.username}). "
            "List posts: shopai instagram posts"
        )
    if s.ready:
        return (
            "Credentials present. Verify with: "
            "shopai instagram status (live probe)"
        )
    return (
        "Connect: shopai instagram connect --token X "
        "--account-id Y. Setup: "
        "https://developers.facebook.com -> Instagram Graph API"
    )
