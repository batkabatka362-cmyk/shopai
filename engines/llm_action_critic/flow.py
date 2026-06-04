"""LLM Action Critic — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .critic import CritiqueReport, critique

logger = logging.getLogger(__name__)


class LlmActionCriticEngine:
    ENGINE_NAME = "llm_action_critic"

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
        report = critique(store_id=store_id)
        return self._success(
            {
                "store_id": store_id,
                "verdict": report.verdict,
                "critiques": [
                    asdict(c) for c in report.critiques
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


def _next_action(r: CritiqueReport) -> str:
    if not r.critiques:
        return "No critiques generated."
    crit_n = sum(
        1 for c in r.critiques if c.severity == "critical"
    )
    warn_n = sum(
        1 for c in r.critiques if c.severity == "warn"
    )
    if crit_n > 0:
        return (
            f"{crit_n} critical / {warn_n} warn. Re-read "
            "rank-1 counter-rationale before acting."
        )
    if warn_n > 0:
        return (
            f"{warn_n} warn(s). Acceptable but proceed "
            "with awareness of flagged risks."
        )
    return "No critical risks flagged."
