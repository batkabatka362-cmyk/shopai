"""Fleet Strategist Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .ranker import (
    FleetStrategistReport,
    overall_verdict,
    rank_fleet,
)

logger = logging.getLogger(__name__)


class FleetStrategistEngine:
    ENGINE_NAME = "fleet_strategist"

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

        verdict_filter = str(data.get("verdict") or "")
        try:
            top = int(data.get("top", 0))
        except (TypeError, ValueError):
            top = 0
        top = max(0, top)

        report = rank_fleet(
            verdict_filter=verdict_filter, top=top,
        )
        fleet_verdict = overall_verdict(report)

        return self._success(
            {
                "fleet_verdict": fleet_verdict,
                "total_stores": report.total_stores,
                "stores_with_data": report.stores_with_data,
                "verdict_filter": verdict_filter,
                "top_filter": top,
                "rankings": [
                    asdict(r) for r in report.all_rankings
                ],
                "by_bucket": {
                    name: [asdict(r) for r in lst]
                    for name, lst in report.by_bucket.items()
                },
                "next_action": _next_action(
                    report, fleet_verdict,
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
    report: FleetStrategistReport,
    fleet_verdict: str,
) -> str:
    if report.total_stores == 0:
        return (
            "No stores in fleet. Wire one: "
            "shopai onboard ID URL --api-key K"
        )
    if report.stores_with_data == 0:
        return (
            f"{report.total_stores} stores but strategist "
            "couldn't read data for any. Run: "
            "shopai checkup --store STORE"
        )
    if fleet_verdict == "intervention_needed":
        intervene = report.by_bucket.get("intervene_now", [])
        top = intervene[0] if intervene else None
        if top:
            return (
                f"Focus on store {top.store_id}: "
                f"{top.top_action}. Drill: {top.top_drill}"
            )
    if fleet_verdict == "cold_start_fleet":
        return (
            "Fleet in cold_start. Run: "
            "shopai fleet-autopilot --yes (after wiring ESP "
            "+ ads)."
        )
    if fleet_verdict == "earning_fleet":
        return (
            "Fleet earning. Schedule recurring cycle: "
            "shopai cycle schedule"
        )
    return "Fleet quiet. Wait for more data or seed traffic."
