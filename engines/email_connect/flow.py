"""Email Connect Engine — Pattern Q envelope wrapper.

Three actions:
  - status: per-provider readiness diagnostic
  - send-test: fire a single transactional email
  - (connect lives in connect.py; called directly from CLI for
     CLI-style positional API)
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .sender import send_test_email
from .status import get_all_status

logger = logging.getLogger(__name__)


class EmailConnectEngine:
    ENGINE_NAME = "email_connect"

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
            return self._success(
                {
                    "action": "status",
                    "providers": {
                        p: asdict(s) for p, s in
                        get_all_status().items()
                    },
                    "next_action": _status_next_action(),
                },
                start,
            )

        if action == "send-test":
            to = data.get("to")
            if not to:
                return self._fail(
                    "send-test requires 'to' field",
                    time.monotonic() - start,
                )
            res = send_test_email(
                to=str(to),
                subject=str(
                    data.get("subject")
                    or "ShopAI test email",
                ),
                from_email=data.get("from_email"),
            )
            return self._success(
                {
                    "action": "send-test",
                    "sent": res.success,
                    "to": to,
                    "message_id": res.message_id,
                    "detail": res.detail,
                    "error": res.error or None,
                    "next_action": (
                        "Check your inbox. If received, your "
                        "ESP is wired correctly."
                    ) if res.success else (
                        f"Send failed: {res.detail}"
                    ),
                },
                start,
            )

        return self._fail(
            f"unknown action '{action}'. Use status / send-test.",
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


def _status_next_action() -> str:
    statuses = get_all_status()
    ready = [p for p, s in statuses.items() if s.ready]
    if ready:
        return (
            f"Provider(s) ready: {', '.join(ready)}. Test: "
            "shopai email send-test --to your@email.com"
        )
    return (
        "No provider configured. Connect one: shopai email "
        "connect brevo --api-key <KEY>  "
        "(Brevo + Resend are wired)"
    )
