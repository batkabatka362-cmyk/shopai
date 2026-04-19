"""Decision governor — unify dual-process, ethics, safety, policies.

Four separate modules made decisions feasible but ungoverned:

  • dual_process     chose fast vs slow thinking
  • ethics_gate      blocked outbound harm
  • safety_envelope  bounded the action space upfront
  • policy_library   ranked named strategies by track record

Nothing wired them together. A caller had to manually call each
and sequence them — which meant many call sites just didn't, and
shipped decisions that bypassed one or another check.

DecisionGovernor is the single entry point. Every candidate
decision runs the full pipeline:

  1. Envelope clamp   — project the candidate into the safety
                          envelope's bounds.
  2. Ethics pre-check — reject anything that hits a hard-block.
  3. Policy match     — propose strategies from policy_library.
  4. Dual-process     — system-1 fast path vs system-2 deliberation
                          based on stakes + confidence + urgency.
  5. Ethics post-check — the chosen answer is re-checked against
                          ethics in case the slow path produced a
                          different action.

Returns GovernedDecision with status (allowed | clamped |
blocked), the final action, the route taken, contributing
policies, and violations if any. Decision is *always* explainable:
``trace`` lists every pipeline stage.

Pure orchestrator — dependencies are injected so tests can
stub each component. No LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from core.brain.ethics_gate import check as ethics_check
from core.brain.safety_envelope import Envelope, envelope_for
from core.brain.dual_process import DualProcessArbiter, Decision
from core.brain.policy_library import PolicyLibrary, PolicyMatch


Status = Literal["allowed", "clamped", "blocked"]


@dataclass
class TraceStep:
    stage: str
    status: str                    # "ok" | "modified" | "blocked"
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class GovernedDecision:
    status: Status
    action: dict[str, Any] | None
    route: str = ""                # system1 / system2 / n/a
    policies: list[PolicyMatch] = field(default_factory=list)
    ethics_violations: list[dict[str, Any]] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "action": self.action,
            "route": self.route,
            "policies": [p.as_dict() for p in self.policies],
            "ethics_violations": self.ethics_violations,
            "trace": [t.as_dict() for t in self.trace],
            "rationale": self.rationale,
        }


# ── Governor ────────────────────────────────────────────────

class DecisionGovernor:
    def __init__(
        self,
        arbiter: DualProcessArbiter,
        policy_library: PolicyLibrary | None = None,
        envelope_builder: Callable[[dict[str, Any]], Envelope] | None = None,
    ) -> None:
        self._arbiter = arbiter
        self._policies = policy_library
        self._envelope_builder = envelope_builder or envelope_for

    # ── Pipeline ────────────────────────────────────────────

    def govern(
        self,
        *,
        context: dict[str, Any],
        candidate_action: dict[str, Any],
        stakes: float = 0.5,
        confidence: float = 0.5,
        urgency: int = 0,
        fast_args: tuple = (),
        fast_kwargs: dict[str, Any] | None = None,
        slow_args: tuple = (),
        slow_kwargs: dict[str, Any] | None = None,
    ) -> GovernedDecision:
        trace: list[TraceStep] = []
        fast_kwargs = fast_kwargs or {}
        slow_kwargs = slow_kwargs or {}

        # 1 — envelope clamp
        envelope = self._envelope_builder(context)
        before = dict(candidate_action)
        clamped = envelope.project(candidate_action)
        if clamped != before:
            trace.append(TraceStep(
                stage="envelope",
                status="modified",
                detail=f"projected into envelope ({envelope.description})",
            ))
            status: Status = "clamped"
        else:
            trace.append(TraceStep(
                stage="envelope", status="ok",
                detail=envelope.description,
            ))
            status = "allowed"

        # 2 — ethics pre-check
        pre_verdict = ethics_check(clamped)
        if pre_verdict.status == "hard_block":
            trace.append(TraceStep(
                stage="ethics_pre", status="blocked",
                detail=", ".join(
                    v.rule for v in pre_verdict.violations
                ),
            ))
            return GovernedDecision(
                status="blocked",
                action=None,
                policies=[],
                ethics_violations=[v.as_dict() for v in pre_verdict.violations],
                trace=trace,
                rationale="ethics pre-check hard-blocked candidate",
            )
        if pre_verdict.violations:
            trace.append(TraceStep(
                stage="ethics_pre", status="modified",
                detail=f"soft violations: "
                       f"{', '.join(v.rule for v in pre_verdict.violations)}",
            ))
        else:
            trace.append(TraceStep(stage="ethics_pre", status="ok"))

        # 3 — policy match (informational — never blocks)
        matches: list[PolicyMatch] = []
        if self._policies is not None:
            matches = self._policies.propose(context, top_k=3)
            trace.append(TraceStep(
                stage="policy_match", status="ok",
                detail=(f"{len(matches)} policy match(es)"
                         if matches else "no policy match"),
            ))

        # 4 — dual-process decision. Default: pass the clamped action
        # as the single positional argument so the arms always have
        # something to work on even when the caller didn't specify
        # fast_args/slow_args explicitly.
        call_args = slow_args or fast_args or (clamped,)
        call_kwargs = slow_kwargs or fast_kwargs
        dp_result: Decision = self._arbiter.decide(
            *call_args,
            stakes=stakes, confidence=confidence, urgency=urgency,
            **call_kwargs,
        )
        trace.append(TraceStep(
            stage="dual_process",
            status="ok",
            detail=f"route={dp_result.route}, "
                   f"latency={dp_result.latency_s:.3f}s",
        ))

        # The arbiter's answer might be a refinement of the candidate.
        chosen = dp_result.answer if isinstance(
            dp_result.answer, dict,
        ) else clamped

        # Re-apply envelope projection to whatever the arm produced
        chosen = envelope.project(chosen)

        # 5 — ethics post-check on final action
        post_verdict = ethics_check(chosen)
        if post_verdict.status == "hard_block":
            trace.append(TraceStep(
                stage="ethics_post", status="blocked",
                detail=", ".join(
                    v.rule for v in post_verdict.violations
                ),
            ))
            return GovernedDecision(
                status="blocked",
                action=None,
                route=dp_result.route,
                policies=matches,
                ethics_violations=[
                    v.as_dict() for v in post_verdict.violations
                ],
                trace=trace,
                rationale="ethics post-check hard-blocked arm output",
            )
        if post_verdict.violations:
            trace.append(TraceStep(
                stage="ethics_post", status="modified",
                detail=f"soft violations: "
                       f"{', '.join(v.rule for v in post_verdict.violations)}",
            ))
        else:
            trace.append(TraceStep(stage="ethics_post", status="ok"))

        rationale = self._rationale(
            status, dp_result, matches, post_verdict.violations,
        )
        return GovernedDecision(
            status=status,
            action=chosen,
            route=dp_result.route,
            policies=matches,
            ethics_violations=[
                v.as_dict() for v in post_verdict.violations
            ],
            trace=trace,
            rationale=rationale,
        )

    @staticmethod
    def _rationale(
        status: str,
        dp: Decision,
        policies: list[PolicyMatch],
        soft_violations: list[Any],
    ) -> str:
        bits = [f"route={dp.route}"]
        if status == "clamped":
            bits.append("clamped to envelope")
        if policies:
            top = policies[0]
            bits.append(f"policy {top.policy.name} fits {top.fit:.2f}")
        if soft_violations:
            bits.append(f"{len(soft_violations)} soft ethics flag(s)")
        return "; ".join(bits)
