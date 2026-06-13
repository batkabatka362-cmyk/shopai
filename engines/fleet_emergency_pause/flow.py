"""Fleet Emergency Pause Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from .state import (
    clear_paused,
    get_state,
    is_paused,
    set_paused,
)

logger = logging.getLogger(__name__)


class FleetEmergencyPauseEngine:
    ENGINE_NAME = "fleet_emergency_pause"

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
        confirmed = bool(data.get("confirmed", False))
        reason = str(data.get("reason") or "")
        by = str(data.get("by") or "operator")

        # Action: status (no gate, no write)
        if action == "status":
            return self._emit_status(start)

        # Action: pause (needs --yes)
        if action == "pause":
            if not confirmed:
                return self._success_with_status(
                    {
                        "action": "pause",
                        "fired": False,
                        "skip_reason": "dry_run",
                        "next_action": (
                            "Dry-run. Add confirmed=True "
                            "(CLI: --yes) to set the fleet "
                            "pause marker."
                        ),
                    },
                    start,
                )
            wrote = set_paused(reason=reason, by=by)
            return self._success_with_status(
                {
                    "action": "pause",
                    "fired": wrote,
                    "skip_reason": (
                        "" if wrote else "test_env_or_io"
                    ),
                    "next_action": (
                        (
                            "Fleet PAUSED. Disable any cron + "
                            "review event that triggered the "
                            "pause. Resume: "
                            "shopai fleet-emergency --resume --yes"
                        )
                        if wrote
                        else (
                            "Marker NOT written (test env or "
                            "I/O error)."
                        )
                    ),
                },
                start,
            )

        # Action: resume (needs --yes)
        if action == "resume":
            if not confirmed:
                return self._success_with_status(
                    {
                        "action": "resume",
                        "fired": False,
                        "skip_reason": "dry_run",
                        "next_action": (
                            "Dry-run. Add confirmed=True "
                            "(CLI: --yes) to clear the marker."
                        ),
                    },
                    start,
                )
            wrote = clear_paused()
            return self._success_with_status(
                {
                    "action": "resume",
                    "fired": wrote,
                    "skip_reason": (
                        "" if wrote else "test_env_or_io"
                    ),
                    "next_action": (
                        (
                            "Fleet RESUMED. Re-enable cron + "
                            "run a fresh cycle to verify."
                        )
                        if wrote
                        else (
                            "Marker NOT cleared (test env or "
                            "I/O error)."
                        )
                    ),
                },
                start,
            )

        return self._fail(
            f"unknown action {action!r}. Use status / pause "
            "/ resume.",
            time.monotonic() - start,
        )

    def _emit_status(self, start: float) -> dict[str, Any]:
        state = get_state()
        return self._success_with_status(
            {
                "action": "status",
                "fired": False,
                "next_action": _status_next_action(state),
            },
            start,
        )

    def _success_with_status(
        self, extra: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        state = get_state()
        return self._success(
            {
                "paused": bool(state.get("paused")),
                "paused_at": state.get("paused_at", ""),
                "paused_by": state.get("paused_by", ""),
                "reason": state.get("reason", ""),
                **extra,
            },
            start,
        )

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


def _status_next_action(state: dict[str, Any]) -> str:
    if state.get("paused"):
        return (
            f"PAUSED at {state.get('paused_at', '?')} by "
            f"{state.get('paused_by', '?')}. Reason: "
            f"{state.get('reason', '(none)') or '(none)'}. "
            "Resume: shopai fleet-emergency --resume --yes"
        )
    return (
        "Fleet ACTIVE. Emergency-pause: "
        "shopai fleet-emergency --pause --yes --reason X"
    )
