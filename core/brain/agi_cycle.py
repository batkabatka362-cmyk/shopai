"""AGI cycle — end-to-end integration of the brain's modules.

Individually: 80+ modules. Together, until now: nothing. The brain
has a world model, a hypothesis engine, an MCTS planner, working
memory, epistemic coverage, a surprise detector, a self-prompt
generator — but no cycle actually walked them. This module is
that cycle.

run_cycle(observation) does one pass:

  1. Working memory — push the incoming observation with scored
     salience; also surface related long-term rules.
  2. Epistemic update — record the observation's feature cells
     so coverage grows.
  3. Surprise check — flag z>=2 outliers + novel signatures.
  4. World-model update — fold the outcome into the causal model.
  5. Policy match — name any strategy that fits this context.
  6. Tree search — MCTS plan for the next action over the WM.
  7. Governed decision — hand the proposal to DecisionGovernor.
  8. Hypothesis — register a prediction attached to the decision.
  9. Inner monologue — emit a structured transcript of the above.
 10. Self-prompt — generate any questions the observation raised.

Output is ``CycleReport`` which the daemon persists. A caller can
disable individual stages via ``skip={"tree_search", ...}`` for
cheap cycles.

No LLM; every stage is deterministic. Each subsystem is imported
lazily so test environments can stub one without touching the
others. Failures in any single stage produce a skipped ``StageOutcome``
and never break the full cycle.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class StageOutcome:
    name: str
    status: str               # "ok" | "skipped" | "error"
    duration_ms: float = 0.0
    detail: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 3),
            "detail": self.detail,
        }


@dataclass
class CycleReport:
    started_at: float
    elapsed_ms: float
    observation: dict[str, Any]
    stages: list[StageOutcome] = field(default_factory=list)
    chosen_action: dict[str, Any] | None = None
    decision_status: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "observation": self.observation,
            "stages": [s.as_dict() for s in self.stages],
            "chosen_action": self.chosen_action,
            "decision_status": self.decision_status,
        }


# ── Cycle ───────────────────────────────────────────────────

def run_cycle(
    observation: dict[str, Any],
    *,
    candidate_action: dict[str, Any] | None = None,
    stakes: float = 0.3,
    confidence: float = 0.6,
    urgency: int = 0,
    skip: Iterable[str] = (),
    governor: Any | None = None,
) -> CycleReport:
    start = time.monotonic()
    started_at = time.time()
    skip_set = set(skip)
    observation = dict(observation)
    report = CycleReport(
        started_at=started_at, elapsed_ms=0.0,
        observation=observation,
    )

    def _run(name: str, fn):
        if name in skip_set:
            report.stages.append(StageOutcome(name=name, status="skipped"))
            return None
        t = time.monotonic()
        try:
            detail = fn()
            duration = (time.monotonic() - t) * 1000
            report.stages.append(StageOutcome(
                name=name, status="ok",
                duration_ms=duration, detail=detail,
            ))
            return detail
        except Exception as exc:
            duration = (time.monotonic() - t) * 1000
            report.stages.append(StageOutcome(
                name=name, status="error",
                duration_ms=duration,
                detail=f"{type(exc).__name__}: {exc}",
            ))
            return None

    # 1. Working memory
    def _push_wm():
        from core.brain.working_memory import working_memory
        wm = working_memory()
        wm.push(
            kind=str(observation.get("kind", "event")),
            content=observation,
            urgency=int(observation.get("urgency", urgency)),
            score=float(observation.get("score", 1.0)),
            owner_relevant=bool(observation.get("owner_relevant")),
        )
        return {"pushed": 1}
    _run("working_memory", _push_wm)

    # 2. Epistemic update
    def _ep():
        from core.brain.epistemic import coverage_engine
        features = {
            k: v for k, v in observation.items()
            if k in ("niche", "price_band", "margin_band",
                     "copy_tone", "action")
        }
        if not features:
            return {"skipped": "no matching dims"}
        return {"touched": coverage_engine().observe(features)}
    _run("epistemic", _ep)

    # 3. Surprise
    def _surprise():
        from core.brain.surprise import surprise_detector
        kind = observation.get("kind", "event")
        sig = f"{kind}:{observation.get('niche', '*')}"
        ev = surprise_detector().observe(
            signature=sig,
            observed=observation.get("observed"),
            expected_mean=observation.get("expected_mean"),
            expected_stdev=observation.get("expected_stdev"),
            narrative=f"cycle observation {kind}",
        )
        return ev.as_dict() if ev else {"surprise": None}
    _run("surprise", _surprise)

    # 4. World-model update
    def _wm_update():
        from core.brain.world_model import Context, world_model
        action = observation.get("action")
        kpi = observation.get("kpi")
        value = observation.get("value")
        if not action or not kpi or value is None:
            return {"skipped": "missing action/kpi/value"}
        ctx = Context(
            niche=observation.get("niche", "unknown"),
            price_band=observation.get("price_band", "mid"),
            margin_band=observation.get("margin_band", "mid"),
            copy_tone=observation.get("copy_tone", "friendly"),
        )
        world_model().update(ctx, str(action), str(kpi), float(value))
        return {"folded": 1}
    _run("world_model", _wm_update)

    # 5. Policy match
    def _policy():
        from core.brain.policy_library import PolicyLibrary
        lib = PolicyLibrary()
        matches = lib.propose(observation, top_k=3)
        return {"matches": [m.as_dict() for m in matches]}
    _run("policy_match", _policy)

    # 6. Tree search — only when an action decision is expected
    def _tree():
        if candidate_action is None:
            return {"skipped": "no candidate_action"}
        from core.brain.tree_search import MCTSPlanner, State
        planner = MCTSPlanner(seed=42, rollout_depth=2)
        state = State(
            open_launches=int(observation.get("open_launches", 1)),
            cash_band=observation.get("cash_band", "mid"),
            niche=observation.get("niche", "unknown"),
            price_band=observation.get("price_band", "mid"),
            margin_band=observation.get("margin_band", "mid"),
            copy_tone=observation.get("copy_tone", "friendly"),
        )
        trace = planner.plan(state, simulations=40, time_budget_s=0.5)
        return trace.as_dict()
    tree_detail = _run("tree_search", _tree)

    # 7. Decision governor
    def _govern():
        if candidate_action is None or governor is None:
            return {"skipped": "no candidate or governor"}
        decision = governor.govern(
            context=observation,
            candidate_action=candidate_action,
            stakes=stakes, confidence=confidence,
            urgency=urgency,
        )
        report.chosen_action = decision.action
        report.decision_status = decision.status
        return decision.as_dict()
    _run("decision", _govern)

    # 8. Hypothesis registration (if a decision fired)
    def _hypo():
        if report.chosen_action is None:
            return {"skipped": "no decision made"}
        from core.brain.hypothesis import hypothesise_from_decision
        baseline = float(observation.get("baseline_kpi", 1.0))
        kpi = str(observation.get("kpi", "revenue"))
        h = hypothesise_from_decision(
            decision={
                "verdict": report.chosen_action.get("kind", "?"),
                "subject": observation.get("subject", "?"),
                "rationale": "auto-registered by agi_cycle",
                "rationale_tag": report.decision_status or "auto",
            },
            expected_kpi=kpi,
            baseline=baseline,
            horizon_days=int(observation.get("horizon_days", 7)),
        )
        return {"hypothesis_id": h.id, "direction": h.direction}
    _run("hypothesis", _hypo)

    # 9. Inner monologue
    def _monologue():
        from core.brain.inner_monologue import monologue
        m = monologue()
        m.checkpoint(f"cycle_{int(started_at)}")
        for s in report.stages:
            m.say(f"stage:{s.name}",
                   f"{s.status} in {s.duration_ms:.1f}ms")
        return {"utterances": len(report.stages)}
    _run("monologue", _monologue)

    # 10. Self-prompt
    def _sp():
        from core.brain.self_prompt import (
            compose, Situation,
        )
        sit = Situation(
            kills_last_7d=int(observation.get("kills_last_7d", 0)),
            scales_last_7d=int(observation.get("scales_last_7d", 0)),
            calibration_hit_rate=float(
                observation.get("calibration_hit_rate", 0.7),
            ),
        )
        questions = compose(sit, top_k=3)
        return {"questions": [q.as_dict() for q in questions]}
    _run("self_prompt", _sp)

    report.elapsed_ms = (time.monotonic() - start) * 1000
    return report
