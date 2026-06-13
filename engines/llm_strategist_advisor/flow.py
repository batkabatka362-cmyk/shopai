"""LLM Strategist Advisor — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .advisor import AdvisorReport, advise

logger = logging.getLogger(__name__)


class LlmStrategistAdvisorEngine:
    ENGINE_NAME = "llm_strategist_advisor"

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

        store_id = str(data.get("store_id") or "")
        signal = str(data.get("signal") or "")
        try:
            k = int(data.get("k", 10))
        except (TypeError, ValueError):
            k = 10

        report = advise(
            store_id=store_id, signal=signal, k=k,
        )
        return self._success(
            {
                "store_id": store_id,
                "signal_filter": signal,
                "k": k,
                "entries_scanned": report.entries_scanned,
                "recommendations": [
                    asdict(r) for r in report.recommendations
                ],
                "llm_used": report.llm_used,
                "llm_reason": report.llm_reason,
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


def _next_action(r: AdvisorReport) -> str:
    if r.entries_scanned == 0:
        return (
            "No strategist memory entries yet. Run a cycle "
            "first: shopai cycle run --yes."
        )
    if not r.recommendations:
        return (
            f"{r.entries_scanned} entries scanned but no "
            "signals had decided outcomes. Need more data."
        )
    top = r.recommendations[0]
    used = "with LLM insight" if r.llm_used else "deterministic"
    return (
        f"Top signal '{top.signal}' has "
        f"{top.positive_count} positive / "
        f"{top.negative_count} negative outcomes "
        f"({top.confidence}-confidence, {used})."
    )
