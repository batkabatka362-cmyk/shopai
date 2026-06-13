"""Fleet Chaos Test Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .runner import (
    ChaosReport,
    available_suites,
    run_chaos_tests,
)

logger = logging.getLogger(__name__)


class FleetChaosTestEngine:
    ENGINE_NAME = "fleet_chaos_test"

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

        suite_filter = str(data.get("suite") or "")
        report = run_chaos_tests(suite_filter=suite_filter)

        verdict = (
            "resilient" if report.failed == 0
            else "fragile" if report.failed >= report.passed
            else "degraded"
        )
        return self._success(
            {
                "suite_filter": report.suite_filter,
                "verdict": verdict,
                "total": report.total,
                "passed": report.passed,
                "failed": report.failed,
                "results": [
                    asdict(r) for r in report.results
                ],
                "available_suites": available_suites(),
                "next_action": _next_action(report, verdict),
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


def _next_action(report: ChaosReport, verdict: str) -> str:
    if report.total == 0:
        return (
            f"No tests in suite "
            f"{report.suite_filter!r}. Try without --suite."
        )
    if verdict == "resilient":
        return (
            f"All {report.total} chaos tests passed. Empire "
            "degrades gracefully under substrate failure."
        )
    failures = [
        r for r in report.results if not r.passed
    ]
    if failures:
        first = failures[0]
        return (
            f"{report.failed}/{report.total} failed. First: "
            f"{first.suite}.{first.name} -- "
            f"{first.detail}"
        )
    return f"{report.failed}/{report.total} failed."
