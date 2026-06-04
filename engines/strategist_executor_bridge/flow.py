"""Strategist Executor Bridge — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import os
import time
from dataclasses import asdict
from typing import Any

from .bridge import (
    BridgeReport,
    run_bridge,
    signal_template_map,
)

logger = logging.getLogger(__name__)


_ENV_GATE = "SHOPAI_STRATEGIST_EXECUTOR_BRIDGE"


def _env_enabled() -> bool:
    raw = os.environ.get(_ENV_GATE, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


class StrategistExecutorBridgeEngine:
    ENGINE_NAME = "strategist_executor_bridge"

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

        operator_yes = bool(data.get("confirmed", False))
        env_enabled = _env_enabled()
        # Triple-gate at the bridge level. Plan_executor will
        # ALSO check its own env gate, so live enqueue requires
        # both env vars + --yes.
        confirmed = operator_yes and env_enabled

        try:
            floor = float(data.get("confidence_floor", 0.6))
        except (TypeError, ValueError):
            floor = 0.6
        store_filter = str(data.get("store_id") or "")

        report = run_bridge(
            confirmed=confirmed,
            confidence_floor=floor,
            store_filter=store_filter,
        )

        return self._success(
            {
                "operator_confirmed": operator_yes,
                "env_gate_set": env_enabled,
                "confirmed": confirmed,
                "confidence_floor": report.confidence_floor,
                "store_filter": store_filter,
                "total_stores_scanned":
                    report.total_stores_scanned,
                "composed_only": report.composed_only,
                "enqueued_total": report.enqueued_total,
                "skip_count": report.skip_count,
                "skip_reasons": dict(report.skip_reasons),
                "decisions": [
                    asdict(d) for d in report.decisions
                ],
                "signal_template_map":
                    signal_template_map(),
                "next_action": _next_action(
                    report, operator_yes, env_enabled,
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
    report: BridgeReport,
    operator_yes: bool,
    env_enabled: bool,
) -> str:
    if report.total_stores_scanned == 0:
        return (
            "No stores in fleet. Wire one: "
            "shopai onboard ID URL --api-key K"
        )
    if not env_enabled:
        return (
            f"Env gate OFF. Enable: export "
            f"{_ENV_GATE}=1 (and add --yes)."
        )
    if not operator_yes:
        return (
            f"Dry-run across {report.total_stores_scanned} "
            f"store(s). composed_only="
            f"{report.composed_only}. Add --yes to enqueue."
        )
    if report.enqueued_total == 0:
        return (
            "Bridge confirmed but 0 enqueued. Check "
            "skip_reasons (also requires "
            "SHOPAI_PLAN_EXECUTOR_ENABLED=1)."
        )
    return (
        f"Enqueued {report.enqueued_total} step(s) across "
        f"{report.total_stores_scanned} store(s). "
        "Review: shopai approvals pending --sort priority"
    )
