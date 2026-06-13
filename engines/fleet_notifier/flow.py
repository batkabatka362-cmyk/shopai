"""Fleet Notifier — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import os
import time
from dataclasses import asdict
from typing import Any

from .notifier import (
    NotifyReport,
    default_cooldowns,
    kind_severity,
    run_notifier,
)
from . import state as state_mod

logger = logging.getLogger(__name__)


_ENV_GATE = "SHOPAI_FLEET_NOTIFIER_ENABLED"


def _env_enabled() -> bool:
    raw = os.environ.get(_ENV_GATE, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


class FleetNotifierEngine:
    ENGINE_NAME = "fleet_notifier"

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

        operator_yes = bool(data.get("confirmed", False))
        env_enabled = _env_enabled()
        confirmed = operator_yes and env_enabled

        kind_filter = str(data.get("kind") or "")
        reset = bool(data.get("reset", False))

        reset_result = ""
        if reset:
            if state_mod.clear_all():
                reset_result = "cleared"
            else:
                reset_result = "skipped_test_env"

        webhook_url = os.environ.get(
            "SHOPAI_NOTIFY_WEBHOOK_URL", "",
        ).strip()

        report = run_notifier(
            confirmed=confirmed,
            kind_filter=kind_filter,
        )

        return self._success(
            {
                "operator_confirmed": operator_yes,
                "env_gate_set": env_enabled,
                "confirmed": confirmed,
                "webhook_url_set": bool(webhook_url),
                "reset_result": reset_result,
                "kind_filter": kind_filter,
                "candidates_scanned":
                    report.candidates_scanned,
                "eligible_count": report.eligible_count,
                "sent_count": report.sent_count,
                "skip_count": report.skip_count,
                "skip_reasons": dict(report.skip_reasons),
                "dispatches": [
                    asdict(d) for d in report.dispatches
                ],
                "default_cooldowns": default_cooldowns(),
                "kind_severity": kind_severity(),
                "next_action": _next_action(
                    report, operator_yes, env_enabled,
                    bool(webhook_url),
                ),
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


def _next_action(
    report: NotifyReport,
    operator_yes: bool,
    env_enabled: bool,
    webhook_url_set: bool,
) -> str:
    if report.candidates_scanned == 0:
        return (
            "No critical events. Fleet stable."
        )
    if not webhook_url_set:
        return (
            "SHOPAI_NOTIFY_WEBHOOK_URL not set. Wire a "
            "webhook (Slack incoming-webhook URL, etc.) to "
            "enable push notifications."
        )
    if not env_enabled:
        return (
            f"Env gate OFF. Enable: export "
            f"{_ENV_GATE}=1 (and re-run with --yes)."
        )
    if not operator_yes:
        return (
            f"{report.eligible_count} event(s) ready to "
            "dispatch. Add --yes to send."
        )
    if report.sent_count == 0:
        return (
            "Confirmed but 0 sent. Check skip_reasons "
            "(likely cooldowns or webhook failures)."
        )
    return (
        f"Dispatched {report.sent_count} notification(s). "
        "Cooldown active for these kinds."
    )
