"""Plan + PlanStep dataclasses.

The planner emits a ``Plan`` -- a structured response that
Claude, the autonomous loop, or an operator can read at the
same level of detail.

Schema tenets (mirror the registry):
  - Optional fields default; planner can return a sparse
    plan with just the relevant capability list when chains
    can't be derived.
  - to_dict() for JSON serialisation -- the planner output
    is meant to be consumed by an LLM planner (future) or
    rendered as a digest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanStep:
    """One actionable step in a plan.

    Each step references a capability by name (resolvable
    via the registry) and carries the operator-runnable form
    when one exists.

    ``suggested_args`` is the capability's ``example_input``
    from the registry, copied in so consumers of the Plan
    (LLM, executor, operator) don't need a second registry
    lookup. Empty dict when the capability doesn't declare
    example_input.
    """

    capability_name: str
    role: str  # "generator" | "applier" | "orchestrator" |
               # "verification" | "enricher" | "audit" | ...
    description: str
    cli_command: str = ""  # e.g. "shopai launch <store_name>"
    closes_audits: list[str] = field(default_factory=list)
    composes_with_next: list[str] = field(default_factory=list)
    suggested_args: dict[str, Any] = field(
        default_factory=dict,
    )

    # Composition: when this step receives its primary
    # input from a PRIOR step in the plan, ``pipe_from``
    # names the prior step's capability_name, and
    # ``pipe_as`` names the kwarg this step expects.
    # The multi-step executor reads both at runtime and
    # replaces ``suggested_args[pipe_as]`` with the prior
    # step's result.data. Empty strings = no piping.
    pipe_from: str = ""
    pipe_as: str = ""

    # Historical observability: when plan_history has prior
    # invocations involving this capability, the planner
    # populates these so consumers (LLM, operator UI) see
    # the past-success signal alongside the recommendation.
    # ``history_sample_size`` is the count of executed past
    # plans that included this step; ``history_success_rate``
    # is the success / sample_size ratio. Both default to
    # 0 / 0.0 when no history exists.
    history_sample_size: int = 0
    history_success_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_name": self.capability_name,
            "role": self.role,
            "description": self.description,
            "cli_command": self.cli_command,
            "closes_audits": list(self.closes_audits),
            "composes_with_next": list(
                self.composes_with_next,
            ),
            "suggested_args": dict(self.suggested_args),
            "pipe_from": self.pipe_from,
            "pipe_as": self.pipe_as,
            "history_sample_size": self.history_sample_size,
            "history_success_rate": self.history_success_rate,
        }


@dataclass
class Plan:
    """The planner's structured response to a goal.

    Fields:
      - ``goal``: the input phrase (or synthesised goal for
        audit-gap plans).
      - ``relevant_capabilities``: registry hits before chain
        analysis -- the raw discovery output.
      - ``steps``: ordered execution sequence. Empty list
        means "nothing matched" (planner returns an empty
        Plan rather than raising).
      - ``audit_coverage``: union of audit_checks_closed
        across the steps -- "if you run this plan, these
        audits will pass".
      - ``cli_sequence``: deduplicated list of CLI commands,
        prioritising orchestrators (so the operator runs
        ``shopai launch`` once instead of 7 sub-commands).
      - ``notes``: human-readable lines explaining WHY the
        planner picked each step. Useful for debugging the
        planner + for LLM consumers reasoning about the plan.
    """

    goal: str
    relevant_capabilities: list[str] = field(
        default_factory=list,
    )
    steps: list[PlanStep] = field(default_factory=list)
    audit_coverage: list[str] = field(default_factory=list)
    cli_sequence: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.steps and not self.relevant_capabilities

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "relevant_capabilities": list(
                self.relevant_capabilities,
            ),
            "steps": [s.to_dict() for s in self.steps],
            "audit_coverage": list(self.audit_coverage),
            "cli_sequence": list(self.cli_sequence),
            "notes": list(self.notes),
        }
