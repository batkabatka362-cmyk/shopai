"""Plan repair — when a workflow step fails, patch the rest.

workflow_dag (v17) handles retries and skip-downstream semantics, but
it doesn't *replan*. When the ``publish`` step fails because the
Shopify API returned a validation error, the rest of the DAG (ads,
notify) is skipped silently — nobody substitutes an alternative path.

plan_repair takes the failure report and the remaining DAG and
decides among three strategies:

  • **retry** — same step, back-off schedule
  • **substitute** — swap the failed step for a declared alternative
  • **skip-with-side-effects** — emit a compensating action then move on
  • **abort** — no repair possible, escalate to owner

Registration looks like:

    repairer.register(FailureRecipe(
        step="publish",
        cause_match=lambda exc: "validation" in str(exc).lower(),
        strategy="substitute",
        substitute="publish_via_graphql",
    ))
    repairer.register(FailureRecipe(
        step="ads_launch",
        cause_match=lambda exc: "rate limit" in str(exc).lower(),
        strategy="retry",
        retry_schedule_s=(5, 30, 120),
    ))

Then the DAG runner calls ``decide(step, exc, remaining_steps)`` and
applies the returned RepairAction.

Pure stdlib. Deterministic. No LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal


Strategy = Literal["retry", "substitute", "skip", "abort"]
MatchFn = Callable[[BaseException], bool]


@dataclass
class FailureRecipe:
    step: str
    cause_match: MatchFn                     # exc → should this recipe apply?
    strategy: Strategy
    substitute: str = ""                     # only for substitute
    compensation: str = ""                   # only for skip — a side-effect step
    retry_schedule_s: tuple[float, ...] = ()  # only for retry
    description: str = ""

    def __post_init__(self) -> None:
        if not self.step:
            raise ValueError("FailureRecipe.step required")
        valid = ("retry", "substitute", "skip", "abort")
        if self.strategy not in valid:
            raise ValueError(f"strategy must be one of {valid}")
        if self.strategy == "substitute" and not self.substitute:
            raise ValueError("substitute strategy needs 'substitute' step")
        if self.strategy == "retry" and not self.retry_schedule_s:
            raise ValueError("retry strategy needs retry_schedule_s")

    def matches(self, exc: BaseException) -> bool:
        try:
            return bool(self.cause_match(exc))
        except Exception:
            return False


@dataclass
class RepairAction:
    strategy: Strategy
    next_step: str = ""                      # step to execute next
    delay_s: float = 0.0                      # for retry
    compensation: str = ""                    # for skip
    reason: str = ""
    escalate: bool = False                    # abort → true

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "next_step": self.next_step,
            "delay_s": self.delay_s,
            "compensation": self.compensation,
            "reason": self.reason,
            "escalate": self.escalate,
        }


class PlanRepairer:
    def __init__(self) -> None:
        self._recipes: list[FailureRecipe] = []
        self._retry_state: dict[str, int] = {}   # step → attempt count

    def register(self, recipe: FailureRecipe) -> None:
        self._recipes.append(recipe)

    def unregister_step(self, step: str) -> int:
        before = len(self._recipes)
        self._recipes = [r for r in self._recipes if r.step != step]
        self._retry_state.pop(step, None)
        return before - len(self._recipes)

    def recipes_for(self, step: str) -> list[FailureRecipe]:
        return [r for r in self._recipes if r.step == step]

    def reset_state(self) -> None:
        self._retry_state.clear()

    # ── Decide ────────────────────────────────────────────

    def decide(
        self,
        step: str,
        exc: BaseException,
        remaining_steps: Iterable[str] = (),
    ) -> RepairAction:
        """Pick a repair for a failed step."""
        remaining = list(remaining_steps)
        for recipe in self.recipes_for(step):
            if not recipe.matches(exc):
                continue
            if recipe.strategy == "retry":
                return self._handle_retry(step, recipe, exc)
            if recipe.strategy == "substitute":
                return RepairAction(
                    strategy="substitute",
                    next_step=recipe.substitute,
                    reason=(
                        f"swap {step} → {recipe.substitute} "
                        f"({recipe.description or 'matched recipe'})"
                    ),
                )
            if recipe.strategy == "skip":
                return RepairAction(
                    strategy="skip",
                    compensation=recipe.compensation,
                    next_step=remaining[0] if remaining else "",
                    reason=(
                        f"skip {step} with compensation "
                        f"'{recipe.compensation}'"
                    ),
                )
            if recipe.strategy == "abort":
                return RepairAction(
                    strategy="abort", escalate=True,
                    reason=recipe.description or f"abort on {step}",
                )
        # No matching recipe — default: abort + escalate
        return RepairAction(
            strategy="abort", escalate=True,
            reason=f"no repair recipe for {step}: {exc}",
        )

    def _handle_retry(
        self,
        step: str,
        recipe: FailureRecipe,
        exc: BaseException,
    ) -> RepairAction:
        attempt = self._retry_state.get(step, 0)
        schedule = recipe.retry_schedule_s
        if attempt >= len(schedule):
            return RepairAction(
                strategy="abort", escalate=True,
                reason=(
                    f"retry budget exhausted after "
                    f"{len(schedule)} attempts on {step}"
                ),
            )
        delay = schedule[attempt]
        self._retry_state[step] = attempt + 1
        return RepairAction(
            strategy="retry", next_step=step,
            delay_s=float(delay),
            reason=f"retry {step} (attempt {attempt + 1}) after {delay}s",
        )

    def stats(self) -> dict[str, Any]:
        return {
            "recipes": len(self._recipes),
            "steps_with_retries": dict(self._retry_state),
        }
