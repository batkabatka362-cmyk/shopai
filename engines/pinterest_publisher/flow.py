"""Pinterest Publisher Engine — Pattern Q envelope.

Three actions:
  - status: readiness check (adapter + creds + optional live probe)
  - list-boards: existing board inventory
  - publish-pin: single pin write
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .publisher import list_boards, publish_pin
from .status import get_status

logger = logging.getLogger(__name__)


class PinterestPublisherEngine:
    ENGINE_NAME = "pinterest_publisher"

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

        if action == "list-boards":
            limit = int(data.get("limit", 25))
            res = list_boards(limit=limit)
            return self._success(
                {
                    "action": "list-boards",
                    "success": res.success,
                    "boards": res.boards,
                    "count": len(res.boards),
                    "error": res.error or None,
                    "next_action": (
                        "Publish: shopai pinterest publish-pin "
                        "--board-id <id> --title T "
                        "--image-url U"
                    ) if res.success else (
                        f"List failed: {res.error}. "
                        "Run shopai pinterest status."
                    ),
                },
                start,
            )

        if action == "publish-pin":
            res = publish_pin(
                board_id=str(data.get("board_id") or ""),
                title=str(data.get("title") or ""),
                image_url=str(data.get("image_url") or ""),
                description=str(data.get("description") or ""),
                link=str(data.get("link") or ""),
            )
            return self._success(
                {
                    "action": "publish-pin",
                    "published": res.success,
                    "pin_id": res.pin_id,
                    "title": res.title,
                    "board_id": res.board_id,
                    "link": res.link,
                    "pin_url": res.pin_url,
                    "error": res.error or None,
                    "next_action": (
                        f"Pin live at {res.pin_url}. Track "
                        "engagement via Pinterest Analytics."
                    ) if res.success else (
                        f"Publish failed: {res.error}"
                    ),
                },
                start,
            )

        return self._fail(
            f"unknown action '{action}'. Use status / "
            "list-boards / publish-pin.",
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
            f"Pinterest ready (user={s.username}). "
            "List boards: shopai pinterest boards"
        )
    if s.ready:
        return (
            "Credentials present. Verify with: "
            "shopai pinterest status (will run live probe)"
        )
    if not s.credentials_present:
        return (
            "Connect: shopai pinterest connect "
            "--token <PINTEREST_ACCESS_TOKEN>"
        )
    return (
        f"State: {s.detail}. See "
        "https://developers.pinterest.com/apps "
        "to generate a new token."
    )
