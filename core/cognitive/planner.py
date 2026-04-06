"""Planner — decomposes goals into executable plans.

Where GoalManager says "I want to achieve X", Planner answers
"and here are the concrete steps to do it". A plan is a tree of
nodes:

    Goal "Improve engine.pricing"
      ├── Step 1: collect last 30 days of pricing decisions
      ├── Step 2: identify the most common failure mode
      ├── Step 3: propose 3 alternative tactics
      └── Step 4: dry-run each tactic in simulation

Two backends share the same Planner interface:

    LLMPlanBackend       Uses the existing LLMAdapter to ask Mistral
                          / Qwen / LLaMA to decompose a goal into
                          structured JSON steps. Used when an LLM is
                          actually available.

    HeuristicPlanBackend  Pattern-matches the goal text against a set
                          of templates ("improve X", "explore Y",
                          "fix Z") and produces a deterministic plan.
                          Used when no LLM is configured, or as a
                          safety net when LLM output is malformed.

The Planner public API picks LLM first, falls back to heuristic on
any failure (timeout, parse error, no providers). Plans are stored
in the same goals database as their parent goals via parent_id, so
the existing GoalManager API can navigate them with .children().

Plans are revisable: when a step fails or returns unexpected
results, replan() can re-decompose the failing step in light of
new evidence — backtracking without restarting from scratch.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("cognitive.planner")


@dataclass
class PlanStep:
    """One step in a plan tree."""
    description: str
    rationale: str = ""
    expected_outcome: str = ""
    estimated_cost: float = 0.5      # 0..1
    estimated_impact: float = 0.5    # 0..1
    confidence: float = 0.5          # how sure we are this step is right
    sub_steps: list["PlanStep"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "rationale": self.rationale,
            "expected_outcome": self.expected_outcome,
            "estimated_cost": self.estimated_cost,
            "estimated_impact": self.estimated_impact,
            "confidence": self.confidence,
            "sub_steps": [s.to_dict() for s in self.sub_steps],
        }


@dataclass
class Plan:
    """A plan for one goal — root node + flat step list + metadata."""
    goal_id: str
    goal_what: str
    steps: list[PlanStep] = field(default_factory=list)
    backend: str = ""                # "llm" or "heuristic"
    raw_response: str = ""           # for debugging
    confidence: float = 0.5          # avg of step confidences

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "goal_what": self.goal_what,
            "steps": [s.to_dict() for s in self.steps],
            "backend": self.backend,
            "confidence": self.confidence,
            "step_count": len(self.steps),
        }

    def is_empty(self) -> bool:
        return not self.steps

    def step_count(self) -> int:
        return len(self.steps)


# ── Backend protocol ──────────────────────────────────────────


class PlanBackend:
    """Protocol: anything with `decompose(goal_what, context) -> Plan`."""

    name: str = ""

    def decompose(
        self, goal_what: str, *, context: Optional[dict] = None,
    ) -> Plan:
        raise NotImplementedError


# ── LLM backend ───────────────────────────────────────────────


_LLM_SYSTEM_PROMPT = (
    "You are a planning assistant for an autonomous e-commerce AI. "
    "Given a goal, decompose it into 3-6 concrete, executable steps. "
    "Return ONLY a JSON object of the form:\n"
    '{"steps": ['
    '{"description": "...", "rationale": "...", '
    '"expected_outcome": "...", "estimated_cost": 0.0-1.0, '
    '"estimated_impact": 0.0-1.0, "confidence": 0.0-1.0}, ...]}\n'
    "Each step should be small enough to attempt in isolation. "
    "Cost is the effort to execute. Impact is the expected progress "
    "toward the goal. Confidence is how sure you are this step is "
    "the right thing to do."
)


class LLMPlanBackend(PlanBackend):
    """Plan via the existing LLMAdapter (Ollama / OpenAI / Anthropic)."""

    name = "llm"

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm  # injected for testability; auto-loaded if None

    def _get_llm(self) -> Any:
        if self._llm is None:
            from core.system.llm_adapter import get_llm
            self._llm = get_llm()
        return self._llm

    def decompose(
        self, goal_what: str, *, context: Optional[dict] = None,
    ) -> Plan:
        plan = Plan(goal_id="", goal_what=goal_what, backend=self.name)

        try:
            llm = self._get_llm()
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLMPlanBackend: cannot load LLM (%s)", exc)
            return plan

        prompt = (
            f"Goal: {goal_what}\n"
            "Decompose this into 3-6 concrete steps. Return JSON only."
        )
        try:
            response = llm.ask(
                role="analyzer",
                prompt=prompt,
                context=context or {},
                system_prompt=_LLM_SYSTEM_PROMPT,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLMPlanBackend: ask() failed: %s", exc)
            return plan

        if not getattr(response, "success", False):
            logger.info(
                "LLMPlanBackend: model returned no success (%s)",
                getattr(response, "error", "unknown"),
            )
            return plan

        plan.raw_response = getattr(response, "text", "") or ""
        steps = self._parse_steps(plan.raw_response)
        if not steps:
            logger.info("LLMPlanBackend: no parseable steps in response")
            return plan

        plan.steps = steps
        plan.confidence = (
            sum(s.confidence for s in steps) / len(steps)
            if steps else 0.0
        )
        return plan

    @staticmethod
    def _parse_steps(text: str) -> list[PlanStep]:
        """Pull a JSON object out of a model response and convert to steps.

        Tolerant of:
        - Markdown code fences (```json ... ```)
        - Leading/trailing chatter
        - Missing optional fields
        """
        if not text:
            return []

        # Strip code fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned, flags=re.MULTILINE)

        # Find the first {...} block
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return []

        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []

        if not isinstance(payload, dict):
            return []
        raw_steps = payload.get("steps") or []
        if not isinstance(raw_steps, list):
            return []

        steps: list[PlanStep] = []
        for raw in raw_steps[:10]:  # cap at 10 steps
            if not isinstance(raw, dict):
                continue
            desc = str(raw.get("description") or "").strip()
            if not desc:
                continue
            steps.append(PlanStep(
                description=desc,
                rationale=str(raw.get("rationale") or "").strip(),
                expected_outcome=str(raw.get("expected_outcome") or "").strip(),
                estimated_cost=_clamp01(raw.get("estimated_cost"), default=0.5),
                estimated_impact=_clamp01(raw.get("estimated_impact"), default=0.5),
                confidence=_clamp01(raw.get("confidence"), default=0.5),
            ))
        return steps


# ── Heuristic backend ─────────────────────────────────────────


# Patterns the heuristic backend recognizes — ordered, first match wins
_HEURISTIC_PATTERNS: list[tuple[str, list[str]]] = [
    (
        # "Improve weak capability X" / "fix X" / "optimize X"
        r"(?:improve|fix|optimi[sz]e|repair)\s+(?:weak\s+)?(?:capability\s+)?'?(.+?)'?$",
        [
            "Audit recent failures of {target} from memory",
            "Identify the most common failure mode",
            "Propose 2-3 alternative tactics",
            "Dry-run each tactic in simulation",
            "Apply the highest-confidence tactic and observe",
            "Update SelfModel with the outcome",
        ],
    ),
    (
        # "Explore unknown capability X" / "explore X" / "learn about X"
        r"(?:explore|learn\s+about|investigate|research)\s+(?:unknown\s+)?(?:capability\s+)?'?(.+?)'?$",
        [
            "Survey existing data about {target}",
            "Run {target} once with default inputs and capture the result",
            "Vary one input dimension and re-run",
            "Compare outcomes and form an initial hypothesis",
            "Record findings in memory and update SelfModel confidence",
        ],
    ),
    (
        # "Recover X" / "restore X"
        r"(?:recover|restore)\s+'?(.+?)'?$",
        [
            "Identify the last known-good state of {target}",
            "Diagnose what changed",
            "Roll back to known-good and verify",
            "Document the regression to prevent recurrence",
        ],
    ),
    (
        # "Increase X" / "grow X" / "boost X"
        r"(?:increase|grow|boost|maximi[sz]e)\s+'?(.+?)'?$",
        [
            "Measure current {target} baseline",
            "Identify the top 3 contributors to {target}",
            "Pick the highest-leverage contributor",
            "Run an A/B experiment optimizing it",
            "Apply the winning variant if significant",
        ],
    ),
    (
        # "Decrease X" / "reduce X" / "minimize X"
        r"(?:decrease|reduce|minimi[sz]e|cut)\s+'?(.+?)'?$",
        [
            "Measure current {target} baseline",
            "Identify the top 3 sources of {target}",
            "Pick the largest source to attack first",
            "Implement a mitigation and re-measure",
        ],
    ),
]

_DEFAULT_HEURISTIC_STEPS = [
    "Gather context on '{target}'",
    "Identify the most relevant evidence in memory",
    "Choose an action and dry-run it",
    "Apply the action and record the outcome",
    "Reflect on what was learned",
]


class HeuristicPlanBackend(PlanBackend):
    """Pattern-matched plan templates. Deterministic, fast, no LLM."""

    name = "heuristic"

    def decompose(
        self, goal_what: str, *, context: Optional[dict] = None,
    ) -> Plan:
        plan = Plan(goal_id="", goal_what=goal_what, backend=self.name)
        target, template = self._match(goal_what)
        steps = [
            PlanStep(
                description=tpl.format(target=target),
                rationale=f"heuristic template '{tpl[:30]}…'",
                confidence=0.6,  # fixed mid-confidence for templates
                estimated_cost=0.4,
                estimated_impact=0.5,
            )
            for tpl in template
        ]
        plan.steps = steps
        plan.confidence = 0.6 if steps else 0.0
        return plan

    @staticmethod
    def _match(goal_what: str) -> tuple[str, list[str]]:
        text = goal_what.strip()
        for pattern, template in _HEURISTIC_PATTERNS:
            m = re.match(pattern, text, flags=re.IGNORECASE)
            if m:
                return m.group(1).strip(), template
        # No pattern matched — generic plan with the whole goal as target
        return text, _DEFAULT_HEURISTIC_STEPS


# ── Top-level Planner ─────────────────────────────────────────


class Planner:
    """Picks the best available backend and decomposes goals into plans.

    The default backend order is [LLMPlanBackend, HeuristicPlanBackend].
    Override via `backends=` for tests or to plug in alternatives.

    Each `plan(goal)` call:
      1. Tries the first backend
      2. If it returns an empty plan, falls back to the next
      3. Stamps the chosen backend onto the result
      4. Optionally persists the plan as child goals via store_plan()

    The result is a Plan object — callers can convert to a dict or
    feed straight into GoalManager.propose() with parent_id set to
    the original goal.
    """

    def __init__(
        self,
        backends: Optional[list[PlanBackend]] = None,
    ) -> None:
        self._backends: list[PlanBackend] = (
            backends if backends is not None else self._default_backends()
        )

    @staticmethod
    def _default_backends() -> list[PlanBackend]:
        return [LLMPlanBackend(), HeuristicPlanBackend()]

    # ── Core API ───────────────────────────────────────────────

    def plan(
        self,
        goal: dict[str, Any] | str,
        *,
        context: Optional[dict] = None,
    ) -> Plan:
        """Decompose a goal into a Plan.

        Accepts either a string ("improve X") or a goal dict from
        GoalManager (must contain at least "what"; "id" is copied to
        the resulting plan when present).
        """
        if isinstance(goal, dict):
            goal_what = str(goal.get("what") or "").strip()
            goal_id = str(goal.get("id") or "")
        else:
            goal_what = str(goal).strip()
            goal_id = ""

        if not goal_what:
            return Plan(goal_id=goal_id, goal_what="", backend="empty")

        for backend in self._backends:
            try:
                plan = backend.decompose(goal_what, context=context)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Planner backend %s raised %s; falling back",
                    backend.name, exc,
                )
                continue
            if plan and not plan.is_empty():
                plan.goal_id = goal_id
                logger.info(
                    "Planner: %d steps from backend=%s for goal '%s'",
                    plan.step_count(), backend.name, goal_what[:60],
                )
                return plan

        # No backend produced a plan — return an empty marker
        empty = Plan(goal_id=goal_id, goal_what=goal_what, backend="none")
        return empty

    def replan(
        self,
        plan: Plan,
        failed_step_index: int,
        *,
        evidence: str = "",
    ) -> Plan:
        """Re-decompose just the failing step in light of new evidence.

        Returns a new Plan whose steps are: original steps before the
        failure + the freshly re-planned alternatives + original steps
        after the failure. Useful for backtracking without losing
        already-completed progress.
        """
        if not plan.steps or failed_step_index < 0 or failed_step_index >= len(plan.steps):
            return plan

        failed = plan.steps[failed_step_index]
        new_goal = (
            f"{failed.description} (re-plan: previous attempt failed"
            f"{', evidence: ' + evidence if evidence else ''})"
        )
        sub_plan = self.plan(new_goal)
        merged = Plan(
            goal_id=plan.goal_id,
            goal_what=plan.goal_what,
            backend=f"{plan.backend}+{sub_plan.backend}-replan",
        )
        merged.steps = (
            plan.steps[:failed_step_index]
            + sub_plan.steps
            + plan.steps[failed_step_index + 1:]
        )
        if merged.steps:
            merged.confidence = (
                sum(s.confidence for s in merged.steps) / len(merged.steps)
            )
        return merged

    # ── Persistence helper ─────────────────────────────────────

    def store_plan(
        self,
        plan: Plan,
        goal_manager: Any,
    ) -> list[str]:
        """Persist a Plan as child goals under its parent goal.

        Each step becomes a sub-goal with parent_id = plan.goal_id.
        Returns the list of created child goal IDs.
        """
        if not plan or not plan.steps or not goal_manager:
            return []
        if not plan.goal_id:
            logger.warning("store_plan: plan has no goal_id; cannot persist")
            return []

        ids: list[str] = []
        for i, step in enumerate(plan.steps):
            try:
                gid = goal_manager.propose(
                    what=step.description,
                    why=step.rationale or f"Step {i+1} of plan for {plan.goal_what}",
                    source=f"planner.{plan.backend}",
                    parent_id=plan.goal_id,
                    impact=step.estimated_impact,
                    cost=step.estimated_cost,
                    confidence=step.confidence,
                )
                ids.append(gid)
            except Exception as exc:  # noqa: BLE001
                logger.warning("store_plan: propose failed for step %d: %s", i, exc)
        return ids


# ── Helpers ───────────────────────────────────────────────────


def _clamp01(value: Any, *, default: float = 0.5) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v))


# ── Singleton accessor ────────────────────────────────────────


_instance: Optional[Planner] = None


def get_planner() -> Planner:
    global _instance
    if _instance is None:
        _instance = Planner()
    return _instance
