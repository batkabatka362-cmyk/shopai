"""Earn Readiness composer -- Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .composer import build_readiness

logger = logging.getLogger(__name__)


class EarnReadinessEngine:
    ENGINE_NAME = "earn_readiness"

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

        try:
            report = build_readiness()
        except Exception as exc:  # noqa: BLE001
            logger.debug("earn_readiness: build raised: %s", exc)
            return self._fail(f"build raised: {exc}", 0.0)

        out = {
            "overall_verdict": report.overall_verdict,
            "headline": report.headline,
            "next_action": report.next_action,
            "ok_count": report.ok_count,
            "warn_count": report.warn_count,
            "fail_count": report.fail_count,
            "ready_for_launch": (
                report.overall_verdict == "ready"
            ),
            "checks": [asdict(c) for c in report.checks],
            "top_blockers": [
                asdict(c) for c in report.top_blockers
            ],
        }
        return self._success(out, start)

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
