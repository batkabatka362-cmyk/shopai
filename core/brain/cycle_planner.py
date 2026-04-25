"""Local cycle planner — the deterministic coordinator.

Owner instruction: *"teriig zohitsuuldag local Ai baiwal daraachiin
ajil deeree umnuhuusuu ilvv sain hiine baih"* — a local AI that
coordinates, so the next cycle performs better than the previous.

This module is that coordinator — deterministic, offline, cheap. It
reads recent experience (cycles, decisions, outcomes, LLM calls) and
produces a ``CyclePlan`` for the next cycle:

  • focus_areas   — subsystems to prioritise (from attention signals)
  • avoid_areas   — subsystems with recent failures to de-emphasise
  • retry_items   — outstanding commitments / curiosity items
  • suggested_kpis — metrics to measure this cycle (drift triage)
  • budget_mode   — conservative / normal / aggressive based on
                     recent LLM cost + success
  • rationale     — human-readable explanation

Inputs come from:
  - experience_recorder.recent(…)
  - learning_curve.rank(…)
  - competence_model.rank(…)
  - concept_drift_detector.summary()
  - commitment_register.pending()
  - curiosity_engine.peek()

Zero LLM. Pure function over recent state. If any input is missing,
the planner returns a neutral plan (never raises).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.cycle_planner")


@dataclass
class CyclePlan:
    cycle_id: str
    focus_areas: list[str] = field(default_factory=list)
    avoid_areas: list[str] = field(default_factory=list)
    retry_items: list[dict[str, Any]] = field(default_factory=list)
    suggested_kpis: list[str] = field(default_factory=list)
    budget_mode: str = "normal"    # conservative | normal | aggressive
    rationale: list[str] = field(default_factory=list)
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "focus_areas": list(self.focus_areas),
            "avoid_areas": list(self.avoid_areas),
            "retry_items": list(self.retry_items),
            "suggested_kpis": list(self.suggested_kpis),
            "budget_mode": self.budget_mode,
            "rationale": list(self.rationale),
            "ts": self.ts,
        }


# ── Input gatherers (each one fail-soft) ──────────────────

def _recent_phase_errors(limit: int = 50) -> dict[str, int]:
    """Recent per-phase error counts. More errors → de-emphasise."""
    try:
        from core.brain.experience_recorder import recent
        rows = recent(kind="phase", limit=limit)
        counts: dict[str, int] = {}
        for r in rows:
            name = str(r.payload.get("name", ""))
            status = str(r.payload.get("status", ""))
            if status not in ("ok", "skipped") and name:
                counts[name] = counts.get(name, 0) + 1
        return counts
    except Exception as exc:
        logger.debug("recent phase errors unavailable: %s", exc)
        return {}


def _weak_subsystems() -> list[str]:
    """Task classes with observed low success rate."""
    try:
        from core.brain.brain_facade import _competence_model
        ranked = _competence_model().rank(min_support=3)
        return [
            c.task_class for c in ranked
            if c.uses >= 3 and c.success_rate < 0.5
        ]
    except Exception as exc:
        logger.debug("competence unavailable: %s", exc)
        return []


def _drifted_features() -> list[str]:
    try:
        from core.brain.brain_facade import _drift_detector
        summary = _drift_detector().summary()
        shifted = summary.get("shifted", [])
        return [s.get("feature", "") for s in shifted if s.get("feature")]
    except Exception as exc:
        logger.debug("drift unavailable: %s", exc)
        return []


def _pending_commitments(hours_ahead: float = 24.0) -> list[dict[str, Any]]:
    try:
        from core.brain.brain_facade import _commitment_register
        urgent = _commitment_register().urgent(hours_ahead=hours_ahead)
        return [c.as_dict() for c in urgent]
    except Exception as exc:
        logger.debug("commitments unavailable: %s", exc)
        return []


def _curiosity_topk(k: int = 3) -> list[dict[str, Any]]:
    try:
        from core.brain.brain_facade import _curiosity_engine
        return [i.as_dict() for i in _curiosity_engine().peek(k=k)]
    except Exception as exc:
        logger.debug("curiosity unavailable: %s", exc)
        return []


def _llm_spend() -> dict[str, Any]:
    try:
        from core import llm_gateway
        return llm_gateway.stats()
    except Exception as exc:
        logger.debug("llm_gateway stats unavailable: %s", exc)
        return {
            "total_calls": 0, "total_cost_usd": 0.0,
            "failures": 0,
        }


def _learning_trend() -> dict[str, Any]:
    try:
        from core.brain.brain_facade import _learning_tracker
        t = _learning_tracker()
        # Cycle-level phase_error_count trend
        curve = t.curve("cycle", "phase_error_count", window=20)
        return curve.as_dict()
    except Exception as exc:
        logger.debug("learning_curve unavailable: %s", exc)
        return {"trend": "insufficient", "slope": 0.0}


# ── Budget-mode heuristic ────────────────────────────────

def _decide_budget_mode(
    llm_stats: dict[str, Any],
    learning_trend: dict[str, Any],
    weak: list[str],
) -> tuple[str, list[str]]:
    rationale: list[str] = []
    # Conservative when recent LLM failures are high
    total = int(llm_stats.get("total_calls", 0))
    failures = int(llm_stats.get("failures", 0))
    if total >= 10 and failures / max(1, total) > 0.25:
        rationale.append(
            f"LLM failure rate {failures}/{total} → conservative",
        )
        return "conservative", rationale
    # Conservative when the cycle is regressing (error count growing)
    if learning_trend.get("trend") == "regressing":
        rationale.append(
            "cycle error trend regressing → conservative",
        )
        return "conservative", rationale
    # Aggressive when everything is improving and we have budget headroom
    if (
        learning_trend.get("trend") == "improving"
        and not weak
        and total < 1_000
    ):
        rationale.append(
            "cycle improving, no weak subsystems → aggressive",
        )
        return "aggressive", rationale
    return "normal", rationale


# ── Main entry point ─────────────────────────────────────

def plan_next_cycle(cycle_id: str = "") -> CyclePlan:
    """Produce a CyclePlan from the latest recorded experience."""
    phase_err = _recent_phase_errors()
    weak = _weak_subsystems()
    drifted = _drifted_features()
    urgent = _pending_commitments()
    curious = _curiosity_topk()
    llm_stats = _llm_spend()
    trend = _learning_trend()

    # Focus: drifted features + curiosity peaks
    focus: list[str] = []
    focus.extend(f"drift:{f}" for f in drifted[:3])
    focus.extend(
        f"curiosity:{c.get('id', '')}" for c in curious if c.get("id")
    )

    # Avoid: phases with ≥ 3 recent errors + weak competence classes
    avoid: list[str] = []
    for name, n in phase_err.items():
        if n >= 3:
            avoid.append(f"phase:{name}")
    for w in weak[:5]:
        avoid.append(f"weak:{w}")

    # Suggested KPIs — drifted features first, then standing ones
    kpis = list(drifted[:3])
    for standing in ("roas", "cvr", "phase_error_count"):
        if standing not in kpis:
            kpis.append(standing)

    # Retry items = urgent commitments + curiosity items
    retry: list[dict[str, Any]] = []
    for u in urgent:
        retry.append({"type": "commitment", "ref": u.get("id", "")})
    for c in curious:
        retry.append({"type": "curiosity", "ref": c.get("id", "")})

    budget_mode, reasons = _decide_budget_mode(llm_stats, trend, weak)
    rationale = list(reasons)
    if drifted:
        rationale.append(f"drifted features: {drifted[:3]}")
    if weak:
        rationale.append(f"weak task classes: {weak[:3]}")
    if phase_err:
        top = sorted(phase_err.items(), key=lambda p: -p[1])[:3]
        rationale.append(f"repeat phase errors: {top}")
    if urgent:
        rationale.append(f"{len(urgent)} urgent commitments")
    if curious:
        rationale.append(f"{len(curious)} curiosity items pending")

    plan = CyclePlan(
        cycle_id=cycle_id or f"plan-{int(time.time())}",
        focus_areas=focus, avoid_areas=avoid,
        retry_items=retry[:10],
        suggested_kpis=kpis,
        budget_mode=budget_mode,
        rationale=rationale,
        ts=time.time(),
    )
    _mirror_plan(plan)
    return plan


def _mirror_plan(plan: CyclePlan) -> None:
    """Mirror the plan to the experience ledger + Obsidian."""
    try:
        from core.brain.experience_recorder import _mirror_to_obsidian, _write
        _write(
            kind="cycle_plan",
            cycle_id=plan.cycle_id,
            payload=plan.as_dict(),
        )
        body = _render_plan_md(plan)
        _mirror_to_obsidian(
            title=f"Cycle plan {plan.cycle_id[:12]}",
            body=body,
            folder="Cycle Plans",
            frontmatter={
                "kind": "cycle_plan",
                "budget_mode": plan.budget_mode,
                "ts": plan.ts,
            },
        )
    except Exception as exc:
        logger.debug("cycle plan mirror failed: %s", exc)


def _render_plan_md(plan: CyclePlan) -> str:
    lines = [
        f"**Budget mode**: {plan.budget_mode}",
        "",
        "## Focus",
    ]
    lines.extend(f"- {f}" for f in plan.focus_areas) or lines.append("- (none)")
    if not plan.focus_areas:
        lines.append("- (none)")
    lines.append("\n## Avoid")
    if plan.avoid_areas:
        lines.extend(f"- {a}" for a in plan.avoid_areas)
    else:
        lines.append("- (none)")
    lines.append("\n## Retry items")
    if plan.retry_items:
        for r in plan.retry_items:
            lines.append(f"- {r.get('type')}: {r.get('ref')}")
    else:
        lines.append("- (none)")
    lines.append("\n## Suggested KPIs")
    lines.extend(f"- {k}" for k in plan.suggested_kpis)
    if plan.rationale:
        lines.append("\n## Rationale")
        lines.extend(f"- {r}" for r in plan.rationale)
    return "\n".join(lines)
