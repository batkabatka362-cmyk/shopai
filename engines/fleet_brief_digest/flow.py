"""Fleet Brief Digest — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .digest import DigestReport, assemble_digest

logger = logging.getLogger(__name__)


class FleetBriefDigestEngine:
    ENGINE_NAME = "fleet_brief_digest"

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

        report = assemble_digest()

        return self._success(
            {
                "fleet_verdict": report.fleet_verdict,
                "fleet_size": report.fleet_size,
                "fleet_revenue_7d": report.fleet_revenue_7d,
                "earning_count": report.earning_count,
                "intervene_count": report.intervene_count,
                "critical_interventions":
                    report.critical_interventions,
                "emergency_active": report.emergency_active,
                "sections": [
                    asdict(s) for s in report.sections
                ],
                "top_actions": list(report.top_actions),
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


def _next_action(report: DigestReport) -> str:
    if report.emergency_active:
        return (
            "EMERGENCY ACTIVE. Resume: shopai "
            "fleet-emergency --resume --yes"
        )
    if report.top_actions:
        return report.top_actions[0]
    return "Brief generated. Fleet stable."
