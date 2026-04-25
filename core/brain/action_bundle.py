"""Action bundle — transactional all-or-nothing action group.

Some decisions require multiple actions that *must* all succeed:
create product → publish → launch ad. If the ad launch fails, you
don't want an orphan published product sitting there. action_bundle
is the transactional wrapper:

  1. Register a bundle with an ordered list of ``BundleAction``
     records, each with an ``execute`` callable and a matching
     ``compensate`` callable.
  2. ``run()`` executes them in order. If any step fails, every
     already-executed step's compensator runs in REVERSE order.
  3. Returns a ``BundleReport`` with per-step status + rollback trail.

This is NOT a distributed transaction — compensation is best-effort.
It IS enough for a Shopify / Meta setup where each step has an
obvious undo (delete_product / pause_ad / refund_charge). Pure
stdlib, deterministic, zero external dependencies.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.action_bundle")


ActionFn = Callable[[dict[str, Any]], dict[str, Any]]
CompensateFn = Callable[[dict[str, Any]], None]

Status = Literal[
    "pending", "ok", "failed", "compensated", "skipped",
]


@dataclass
class BundleAction:
    name: str
    execute: ActionFn
    compensate: CompensateFn | None = None
    optional: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("BundleAction.name required")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "optional": self.optional,
            "has_compensate": self.compensate is not None,
            "payload_keys": sorted(self.payload.keys()),
        }


@dataclass
class StepResult:
    name: str
    status: Status
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    elapsed_ms: float = 0.0
    compensated_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "output": dict(self.output),
            "error": self.error,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "compensated_at": self.compensated_at,
        }


@dataclass
class BundleReport:
    bundle_name: str
    success: bool
    rolled_back: bool
    steps: list[StepResult] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle_name": self.bundle_name,
            "success": self.success,
            "rolled_back": self.rolled_back,
            "steps": [s.as_dict() for s in self.steps],
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


# ── Engine ────────────────────────────────────────────────

class ActionBundle:
    def __init__(
        self, name: str,
        *,
        actions: Iterable[BundleAction] = (),
    ) -> None:
        if not name:
            raise ValueError("bundle name required")
        self.name = name
        self._actions: list[BundleAction] = list(actions)

    def add(self, action: BundleAction) -> None:
        self._actions.append(action)

    def actions(self) -> list[BundleAction]:
        return list(self._actions)

    # ── Run ──────────────────────────────────────────────

    def run(
        self,
        context: dict[str, Any] | None = None,
    ) -> BundleReport:
        started = time.monotonic()
        ctx = dict(context or {})
        results: list[StepResult] = []
        success = True
        fail_index = -1
        for idx, action in enumerate(self._actions):
            step_start = time.monotonic()
            try:
                payload = action.execute(
                    {"context": ctx, "payload": dict(action.payload)},
                )
                if not isinstance(payload, dict):
                    payload = {"result": payload}
                results.append(StepResult(
                    name=action.name,
                    status="ok",
                    output=dict(payload),
                    elapsed_ms=(
                        time.monotonic() - step_start
                    ) * 1000.0,
                ))
                ctx.update(payload)
            except Exception as exc:
                logger.debug(
                    "bundle step %s raised: %s", action.name, exc,
                )
                results.append(StepResult(
                    name=action.name,
                    status="failed",
                    error=str(exc),
                    elapsed_ms=(
                        time.monotonic() - step_start
                    ) * 1000.0,
                ))
                if action.optional:
                    # Optional step failure does NOT trigger rollback.
                    continue
                success = False
                fail_index = idx
                break

        # Mark remaining (un-executed) steps as skipped
        for idx in range(len(results), len(self._actions)):
            results.append(StepResult(
                name=self._actions[idx].name,
                status="skipped",
            ))

        rolled_back = False
        if not success:
            # Walk BACK through already-ok steps and compensate.
            for i in range(fail_index - 1, -1, -1):
                step = results[i]
                action = self._actions[i]
                if step.status != "ok" or action.compensate is None:
                    continue
                try:
                    action.compensate(
                        {"context": ctx, "output": step.output},
                    )
                    step.status = "compensated"
                    step.compensated_at = time.time()
                    rolled_back = True
                except Exception as exc:
                    logger.debug(
                        "compensate %s raised: %s",
                        action.name, exc,
                    )
                    # Leave step as ok + record error so operators
                    # can see that rollback partially failed.
                    step.error = f"compensate_failed: {exc}"

        return BundleReport(
            bundle_name=self.name,
            success=success,
            rolled_back=rolled_back,
            steps=results,
            elapsed_ms=(time.monotonic() - started) * 1000.0,
        )

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "step_count": len(self._actions),
            "steps_with_compensate": sum(
                1 for a in self._actions if a.compensate is not None
            ),
            "optional_steps": sum(
                1 for a in self._actions if a.optional
            ),
        }
