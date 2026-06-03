"""Autopilot Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .runner import AutopilotReport, run_autopilot

logger = logging.getLogger(__name__)


class AutopilotEngine:
    ENGINE_NAME = "autopilot"

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

        confirmed = bool(data.get("confirmed", False))
        store_id = data.get("store_id")

        report = run_autopilot(
            confirmed=confirmed, store_id=store_id,
        )

        return self._success(
            {
                "confirmed": confirmed,
                "store_id": store_id,
                "overall_verdict": report.overall_verdict,
                "stages": [
                    asdict(s) for s in report.stages
                ],
                "next_action": _next_action(report),
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


def _next_action(report: AutopilotReport) -> str:
    if not report.confirmed:
        return (
            "Dry-run preview. Add --yes + set "
            "SHOPAI_AUTOPILOT_WELCOME=1 (or REVIEWS=1) to "
            "fire writers."
        )
    err_stages = [
        s for s in report.stages if s.verdict == "error"
    ]
    if err_stages:
        names = ",".join(s.name for s in err_stages)
        return (
            f"Stage(s) errored: {names}. Check "
            "shopai checkup for substrate health."
        )
    fired = [s for s in report.stages if s.fired]
    if not fired:
        return (
            "All write stages env-disabled. Set "
            "SHOPAI_AUTOPILOT_WELCOME=1 + SHOPAI_AUTOPILOT_"
            "REVIEWS=1 to enable."
        )
    return (
        f"{len(fired)} stage(s) fired clean. Schedule: "
        "shopai cycle schedule"
    )
