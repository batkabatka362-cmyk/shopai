"""AutonomyGateEngine -- Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from .threshold import check_autonomy_gate

logger = logging.getLogger(__name__)


class AutonomyGateEngine:
    ENGINE_NAME = "autonomy_gate"

    def run(
        self,
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start = time.monotonic()
        payload = self._safe_copy(input_payload)
        if payload is None:
            return self._fail("Input copy failed", 0.0)
        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(
                payload.get(
                    "error", "Upstream failure",
                ), 0.0,
            )
        try:
            report = check_autonomy_gate()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "check_autonomy_gate raised: %s", exc,
            )
            return self._fail(
                f"gate check raised: {exc}", 0.0,
            )

        data = {
            "unlocked": report.unlocked,
            "required_stores": report.required_stores,
            "proof_window_days": (
                report.proof_window_days
            ),
            "min_cycles_per_store": (
                report.min_cycles_per_store
            ),
            "stable_count": report.stable_count,
            "progress_pct": round(
                report.progress_pct, 1,
            ),
            "blockers": list(report.blockers),
            "stores": [
                {
                    "store_id": s.store_id,
                    "cycle_count": s.cycle_count,
                    "total_incidents": (
                        s.total_incidents
                    ),
                    "is_stable": s.is_stable,
                    "cycle_errors": s.cycle_errors,
                    "autopause_fires": (
                        s.autopause_fires
                    ),
                    "rejected_actions": (
                        s.rejected_actions
                    ),
                }
                for s in report.stores
            ],
        }
        return self._success(data, start)

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
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(),
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
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(),
                ),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
