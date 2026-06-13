"""Plan Composer Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .composer import (
    Plan,
    available_templates,
    compose_plan,
)

logger = logging.getLogger(__name__)


class PlanComposerEngine:
    ENGINE_NAME = "plan_composer"

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
        try:
            max_steps = int(data.get("max_steps", 10))
        except (TypeError, ValueError):
            max_steps = 10

        if not goal:
            return self._success(
                {
                    "goal": "",
                    "store_id": store_id,
                    "template_matched": "",
                    "confidence": 0.0,
                    "step_count": 0,
                    "steps": [],
                    "available_templates": available_templates(),
                    "next_action": (
                        "Pass a goal phrase. Try: "
                        + ", ".join(available_templates())
                    ),
                },
                start,
            )

        plan = compose_plan(
            goal=goal,
            store_id=store_id,
            max_steps=max_steps,
        )

        return self._success(
            {
                "goal": plan.goal,
                "store_id": plan.store_id,
                "template_matched": plan.template_matched,
                "confidence": round(plan.confidence, 3),
                "step_count": len(plan.steps),
                "steps": [asdict(s) for s in plan.steps],
                "notes": list(plan.notes),
                "available_templates": available_templates(),
                "next_action": _next_action(plan),
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


def _next_action(plan: Plan) -> str:
    if not plan.steps:
        return (
            f"No plan generated for {plan.goal!r}. "
            "Try a canonical template."
        )
    if plan.template_matched:
        return (
            f"Template {plan.template_matched!r} matched. "
            f"Step 1: {plan.steps[0].drill_command}"
        )
    return (
        f"Custom plan composed ({len(plan.steps)} steps). "
        f"Step 1: {plan.steps[0].drill_command}"
    )
