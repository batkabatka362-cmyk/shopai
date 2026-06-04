"""Compose a plan via W963-31, then enqueue each step as a
PENDING approval action tagged with a shared plan_id."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EnqueuedStep:
    plan_step_order: int
    plan_step_engine: str
    plan_step_action: str
    enqueued: bool = False
    action_id: str = ""
    skip_reason: str = ""


@dataclass
class PlanExecutionReport:
    plan_id: str
    goal: str
    store_id: str
    confirmed: bool
    template_matched: str = ""
    plan_step_count: int = 0
    enqueued_count: int = 0
    skipped_count: int = 0
    steps: list[EnqueuedStep] = field(default_factory=list)
    skip_reasons: dict[str, int] = field(default_factory=dict)


def _bump_skip(
    report: PlanExecutionReport, reason: str,
) -> None:
    report.skipped_count += 1
    report.skip_reasons[reason] = (
        report.skip_reasons.get(reason, 0) + 1
    )


def _generate_plan_id() -> str:
    """Time-based plan id with monotonic seq for testability."""
    ts_ns = time.time_ns()
    return f"plan_{ts_ns}"


def _compose(
    goal: str, *, store_id: str, max_steps: int,
) -> dict[str, Any]:
    """Call plan_composer and return the data envelope."""
    try:
        from engines.plan_composer import PlanComposerEngine
        result = PlanComposerEngine().run({
            "data": {
                "goal": goal,
                "store_id": store_id,
                "max_steps": max_steps,
            },
        })
        if result.get("status") != "success":
            return {}
        return result.get("data") or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "plan_executor: compose raised: %s", exc,
        )
        return {}


def _resolve_capability(engine_name: str) -> str:
    """Best-effort: look up the canonical capability the
    engine uses. Falls back to a synthetic key."""
    if not engine_name:
        return ""
    return f"PLAN_STEP_{engine_name.upper()}"


def execute_plan(
    *,
    goal: str,
    store_id: str = "",
    confirmed: bool = False,
    max_steps: int = 10,
) -> PlanExecutionReport:
    """Compose the plan + enqueue each step as PENDING."""
    plan_id = _generate_plan_id()
    report = PlanExecutionReport(
        plan_id=plan_id,
        goal=goal,
        store_id=store_id,
        confirmed=confirmed,
    )

    if not goal:
        return report

    plan_data = _compose(
        goal, store_id=store_id, max_steps=max_steps,
    )
    if not plan_data:
        return report

    report.template_matched = str(
        plan_data.get("template_matched") or "",
    )
    plan_steps = plan_data.get("steps") or []
    report.plan_step_count = len(plan_steps)
    if not plan_steps:
        return report

    if not confirmed:
        # Dry run: record the candidate steps but don't enqueue.
        for raw in plan_steps:
            step = EnqueuedStep(
                plan_step_order=int(raw.get("order", 0)),
                plan_step_engine=str(
                    raw.get("engine") or "",
                ),
                plan_step_action=str(
                    raw.get("action") or "",
                ),
                skip_reason="dry_run",
            )
            report.steps.append(step)
            _bump_skip(report, "dry_run")
        return report

    # Live: enqueue each step.
    try:
        from core.approval.queue import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "plan_executor: queue import raised: %s", exc,
        )
        for raw in plan_steps:
            step = EnqueuedStep(
                plan_step_order=int(raw.get("order", 0)),
                plan_step_engine=str(
                    raw.get("engine") or "",
                ),
                plan_step_action=str(
                    raw.get("action") or "",
                ),
                skip_reason="queue_unavailable",
            )
            report.steps.append(step)
            _bump_skip(report, "queue_unavailable")
        return report

    for raw in plan_steps:
        order = int(raw.get("order", 0))
        engine = str(raw.get("engine") or "")
        action = str(raw.get("action") or "")
        drill = str(raw.get("drill_command") or "")
        reasoning = str(raw.get("reasoning") or "")
        impact = str(raw.get("impact") or "medium")
        step = EnqueuedStep(
            plan_step_order=order,
            plan_step_engine=engine,
            plan_step_action=action,
        )
        if not engine:
            step.skip_reason = "no_engine"
            report.steps.append(step)
            _bump_skip(report, "no_engine")
            continue
        action_type = (
            f"plan_step_{order}_{engine}"
        )
        capability = _resolve_capability(engine)
        params = {
            "plan_id": plan_id,
            "plan_step_order": order,
            "plan_step_engine": engine,
            "plan_step_drill": drill,
            "plan_step_impact": impact,
        }
        narrative = (
            f"Plan {plan_id} step {order}: {action}. "
            f"Engine={engine}. Why: {reasoning[:120]}"
        )
        try:
            enqueued = queue.enqueue(
                engine=engine,
                action_type=action_type,
                capability=capability,
                params=params,
                narrative=narrative,
                store_id=store_id or None,
            )
            step.enqueued = True
            step.action_id = str(
                getattr(enqueued, "id", "") or "",
            )
            report.enqueued_count += 1
        except Exception as exc:  # noqa: BLE001
            step.skip_reason = (
                f"enqueue_failed: {type(exc).__name__}"
            )
            _bump_skip(report, "enqueue_failed")
        report.steps.append(step)

    return report
