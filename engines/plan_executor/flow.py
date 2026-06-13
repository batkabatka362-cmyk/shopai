"""Plan Executor Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import os
import time
from dataclasses import asdict
from typing import Any

from .executor import (
    PlanExecutionReport,
    execute_plan,
)

logger = logging.getLogger(__name__)


_ENV_GATE = "SHOPAI_PLAN_EXECUTOR_ENABLED"


def _env_enabled() -> bool:
    raw = os.environ.get(_ENV_GATE, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


class PlanExecutorEngine:
    ENGINE_NAME = "plan_executor"

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

        goal = str(data.get("goal") or "")
        store_id = str(data.get("store_id") or "")
        operator_yes = bool(data.get("confirmed", False))
        env_enabled = _env_enabled()
        # Triple gate (same pattern as fleet_transfer_auto +
        # confidence_auto_approver).
        confirmed = operator_yes and env_enabled
        try:
            max_steps = int(data.get("max_steps", 10))
        except (TypeError, ValueError):
            max_steps = 10

        report = execute_plan(
            goal=goal,
            store_id=store_id,
            confirmed=confirmed,
            max_steps=max(1, max_steps),
        )

        return self._success(
            {
                "plan_id": report.plan_id,
                "goal": report.goal,
                "store_id": report.store_id,
                "operator_confirmed": operator_yes,
                "env_gate_set": env_enabled,
                "confirmed": confirmed,
                "template_matched": report.template_matched,
                "plan_step_count": report.plan_step_count,
                "enqueued_count": report.enqueued_count,
                "skipped_count": report.skipped_count,
                "skip_reasons": dict(report.skip_reasons),
                "steps": [asdict(s) for s in report.steps],
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
    report: PlanExecutionReport,
    operator_yes: bool,
    env_enabled: bool,
) -> str:
    if not report.goal:
        return (
            "Pass a goal phrase. Templates: cold_start, "
            "increase_conversion, increase_traffic, "
            "retain_customers, diagnose."
        )
    if report.plan_step_count == 0:
        return (
            f"No plan generated for {report.goal!r}. "
            "Try shopai plan-compose to debug."
        )
    if not env_enabled:
        return (
            f"Env gate OFF. Enable: export "
            f"{_ENV_GATE}=1 (and re-run with --yes)."
        )
    if not operator_yes:
        return (
            f"Dry-run. {report.plan_step_count} step(s) "
            "would enqueue. Add --yes to commit."
        )
    if report.enqueued_count == 0:
        return (
            "Plan composed but 0 enqueued. Check skip_reasons."
        )
    return (
        f"Enqueued {report.enqueued_count} step(s) under "
        f"plan_id={report.plan_id}. Review: "
        "shopai approvals pending --sort priority"
    )
