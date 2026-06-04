"""Fleet Intervention Alerts — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .alerter import (
    InterventionReport,
    collect_interventions,
)

logger = logging.getLogger(__name__)


class FleetInterventionAlertsEngine:
    ENGINE_NAME = "fleet_intervention_alerts"

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

        try:
            top = int(data.get("top", 0))
        except (TypeError, ValueError):
            top = 0
        top = max(0, top)

        report = collect_interventions()
        alerts = report.alerts
        if top > 0:
            alerts = alerts[:top]

        return self._success(
            {
                "total_signals_scanned":
                    report.total_signals_scanned,
                "critical_count": report.critical_count,
                "high_count": report.high_count,
                "medium_count": report.medium_count,
                "alerts": [asdict(a) for a in alerts],
                "stores_with_alerts": list(
                    report.by_store.keys(),
                ),
                "next_action": _next_action(
                    report, len(alerts),
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
    report: InterventionReport,
    surfaced: int,
) -> str:
    if surfaced == 0:
        return (
            "No interventions surfaced. Fleet is quiet."
        )
    top = report.alerts[0]
    return (
        f"Top: store {top.store_id} -- {top.headline}. "
        f"Drill: {top.drill_command}"
    )
