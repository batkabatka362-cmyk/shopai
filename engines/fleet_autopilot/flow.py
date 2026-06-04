"""Fleet Autopilot Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .runner import FleetReport, run_fleet_autopilot

logger = logging.getLogger(__name__)


class FleetAutopilotEngine:
    ENGINE_NAME = "fleet_autopilot"

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
        only_store = data.get("only_store")
        skip_raw = data.get("skip_stores") or []
        skip_stores = (
            [str(s) for s in skip_raw if s]
            if isinstance(skip_raw, list) else []
        )

        report = run_fleet_autopilot(
            confirmed=confirmed,
            only_store=only_store,
            skip_stores=skip_stores,
        )

        return self._success(
            {
                "confirmed": confirmed,
                "only_store": only_store,
                "skipped_stores": report.skipped_stores,
                "total_stores": report.total_stores,
                "by_store": [
                    asdict(o) for o in report.by_store
                ],
                "overall_verdict": report.overall_verdict,
                "sent_count_total": report.sent_count_total,
                "errors_total": report.errors_total,
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


def _next_action(report: FleetReport) -> str:
    if report.total_stores == 0:
        return (
            "No stores in fleet. Wire one: "
            "shopai onboard ID URL --api-key K"
        )
    if not report.confirmed:
        return (
            f"Dry-run across {report.total_stores} store(s). "
            "Add --yes (+ SHOPAI_AUTOPILOT_WELCOME=1 / "
            "REVIEWS=1) to fire writers."
        )
    if report.errors_total > 0:
        return (
            f"{report.errors_total} store-stage error(s). "
            "Drill: shopai checkup --store STORE"
        )
    if report.sent_count_total == 0:
        return (
            "No emails dispatched. Check env gates: "
            "shopai autopilot --json (per-store)"
        )
    return (
        f"Dispatched {report.sent_count_total} email(s) "
        f"across {len(report.by_store)} store(s). "
        "Schedule: shopai cycle schedule"
    )
