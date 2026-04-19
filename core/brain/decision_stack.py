"""Decision stack — unified chain from observation to commit.

v20-v31 shipped 84+ subsystems. Today each caller wires them
ad-hoc: some call attention_filter, some call deliberation_loop,
some call action_safety_guard. No single entry point handles the
canonical path.

decision_stack is that entry point. Given:

  • observation      — a dict describing the event / query
  • candidate_action — the brain's first guess (optional)
  • stakes            — 0..1 how much money/SLA is on the line

it walks the canonical pipeline:

  1. Attention filter — is this worth attending to?
  2. Evidence sufficiency — do we have enough to decide?
  3. Deliberation loop — think → critique → revise
  4. Safety guard — bright lines + blast + rollback
  5. Feasibility gate — constraint satisfaction
  6. Utility blender — multi-objective score

Each stage returns a verdict; the chain short-circuits when
anything blocks. Results land in a ``DecisionStackReport`` carrying:

  • final_action (or None if blocked)
  • stage_verdicts list
  • block_reason (when blocked)
  • trace (for audit / reasoning_trace)

All stages are DEPENDENCY-INJECTED via callables so tests don't
touch real singletons and production can override any stage. Pure
stdlib. Deterministic.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("brain.decision_stack")


StageFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class StageVerdict:
    stage: str
    status: str                 # "ok" | "blocked" | "skipped" | "error"
    note: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "note": self.note,
            "payload": dict(self.payload),
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


@dataclass
class DecisionStackReport:
    observation: dict[str, Any]
    candidate_action: dict[str, Any] | None
    final_action: dict[str, Any] | None
    stage_verdicts: list[StageVerdict] = field(default_factory=list)
    block_reason: str = ""
    stakes: float = 0.0
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "observation": dict(self.observation),
            "candidate_action": (
                dict(self.candidate_action)
                if self.candidate_action else None
            ),
            "final_action": (
                dict(self.final_action)
                if self.final_action else None
            ),
            "stage_verdicts": [
                v.as_dict() for v in self.stage_verdicts
            ],
            "block_reason": self.block_reason,
            "stakes": round(self.stakes, 4),
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


# ── Default stage builders (all callable or None) ─────────

@dataclass
class StageCallables:
    """Each stage function accepts (ctx) and returns a dict with:
        status: "ok" | "blocked" | "skipped"
        note: str (optional)
        payload: dict (arbitrary output)
    The stage is skipped entirely if the callable is None.
    """
    attention: StageFn | None = None
    evidence: StageFn | None = None
    deliberate: StageFn | None = None
    safety: StageFn | None = None
    feasibility: StageFn | None = None
    utility: StageFn | None = None


# ── Engine ────────────────────────────────────────────────

class DecisionStack:
    """Runs the canonical 6-stage decision pipeline."""

    STAGES: tuple[str, ...] = (
        "attention", "evidence", "deliberate",
        "safety", "feasibility", "utility",
    )

    def __init__(self, stages: StageCallables | None = None) -> None:
        self._stages = stages or StageCallables()

    # ── Stage dispatch ───────────────────────────────────

    def _run_stage(
        self,
        name: str,
        fn: StageFn | None,
        ctx: dict[str, Any],
    ) -> StageVerdict:
        if fn is None:
            return StageVerdict(
                stage=name, status="skipped",
                note="no handler registered",
            )
        start = time.monotonic()
        try:
            out = fn(dict(ctx))
        except Exception as exc:
            logger.debug("stage %s raised: %s", name, exc)
            return StageVerdict(
                stage=name, status="error",
                note=f"raised: {exc}",
                elapsed_ms=(time.monotonic() - start) * 1000.0,
            )
        if not isinstance(out, dict):
            return StageVerdict(
                stage=name, status="error",
                note="stage did not return dict",
                elapsed_ms=(time.monotonic() - start) * 1000.0,
            )
        status = str(out.get("status", "ok"))
        if status not in ("ok", "blocked", "skipped"):
            status = "error"
        return StageVerdict(
            stage=name,
            status=status,
            note=str(out.get("note", "")),
            payload=dict(out.get("payload", {}) or {}),
            elapsed_ms=(time.monotonic() - start) * 1000.0,
        )

    # ── Decide ───────────────────────────────────────────

    def decide(
        self,
        *,
        observation: dict[str, Any],
        candidate_action: dict[str, Any] | None = None,
        stakes: float = 0.3,
    ) -> DecisionStackReport:
        started = time.monotonic()
        ctx = {
            "observation": dict(observation or {}),
            "candidate_action": (
                dict(candidate_action)
                if candidate_action else None
            ),
            "stakes": max(0.0, min(1.0, float(stakes))),
        }
        report = DecisionStackReport(
            observation=ctx["observation"],
            candidate_action=ctx["candidate_action"],
            final_action=None,
            stakes=ctx["stakes"],
        )

        stage_map = {
            "attention": self._stages.attention,
            "evidence": self._stages.evidence,
            "deliberate": self._stages.deliberate,
            "safety": self._stages.safety,
            "feasibility": self._stages.feasibility,
            "utility": self._stages.utility,
        }

        chosen = ctx["candidate_action"]
        for name in self.STAGES:
            verdict = self._run_stage(name, stage_map[name], ctx)
            report.stage_verdicts.append(verdict)
            # If deliberation proposes a candidate, let it override
            if (
                name == "deliberate"
                and verdict.status == "ok"
                and "candidate" in verdict.payload
            ):
                chosen = dict(verdict.payload["candidate"])
                ctx["candidate_action"] = chosen
            if verdict.status == "blocked":
                report.block_reason = (
                    f"{name}:{verdict.note}" if verdict.note
                    else f"blocked at {name}"
                )
                report.final_action = None
                report.elapsed_ms = (
                    time.monotonic() - started
                ) * 1000.0
                return report
            if verdict.status == "error":
                report.block_reason = (
                    f"{name} error: {verdict.note}"
                )
                report.final_action = None
                report.elapsed_ms = (
                    time.monotonic() - started
                ) * 1000.0
                return report

        report.final_action = chosen
        report.elapsed_ms = (time.monotonic() - started) * 1000.0
        return report

    # ── Introspection ────────────────────────────────────

    def registered_stages(self) -> list[str]:
        return [
            name for name in self.STAGES
            if getattr(self._stages, name) is not None
        ]

    def stats(self) -> dict[str, Any]:
        return {
            "stages_total": len(self.STAGES),
            "stages_registered": len(self.registered_stages()),
            "registered": self.registered_stages(),
        }
