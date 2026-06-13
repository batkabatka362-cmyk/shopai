"""AI pre-vet for pending approval queue actions.

When operators scale to N stores, the approval queue grows
linearly. Reviewing each pending action by hand stops scaling
around 50 actions/day. Wave 49 adds an LLM-based pre-vet:
given a pending action's metadata + similar past outcomes,
the LLM recommends approve / reject / hold with a rationale.

Pre-vet is ADVISORY -- operator still has the final decision.
This is the AGI principle: AI as consultant, not authority.

## Decision context fed to the LLM

For each pending action:
  - Engine + action type
  - Capability + params (truncated)
  - Recent outcomes for this engine (positive_ratio, sample
    count)
  - Recent attribution for this engine (revenue, orders,
    trend) if attribution data exists
  - Risk class (additive / modification / destructive)

## Output shape

PrevetRecommendation:
  recommendation: "approve" | "reject" | "hold"
  confidence: 0.0-1.0
  rationale: short explanation
  flags: list of warnings (e.g. ["high_spend_action",
    "engine_recently_paused"])

## Env-var gate

  SHOPAI_AI_PREVET=1 -- enable. Default OFF. Without it, the
  prevet helper returns "hold" with rationale="prevet
  disabled".
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


_VALID_RECOMMENDATIONS = frozenset({"approve", "reject", "hold"})


@dataclass
class PrevetRecommendation:
    action_id: str
    recommendation: str  # approve / reject / hold
    confidence: float = 0.0
    rationale: str = ""
    flags: list[str] = field(default_factory=list)


def is_enabled() -> bool:
    return os.environ.get("SHOPAI_AI_PREVET") == "1"


def _gather_engine_context(engine_name: str) -> dict[str, Any]:
    """Pull recent outcomes + attribution for the engine."""
    ctx: dict[str, Any] = {
        "engine": engine_name,
        "recent_outcomes": None,
        "attribution_7d": None,
    }
    # Recent outcomes from the queue
    try:
        from core.approval.queue import get_approval_queue
        stats = (
            get_approval_queue().engine_outcome_stats(
                engine_name,
            ) or {}
        )
        ctx["recent_outcomes"] = {
            "positive_count": int(
                stats.get("positive_count", 0) or 0,
            ),
            "negative_count": int(
                stats.get("negative_count", 0) or 0,
            ),
            "neutral_count": int(
                stats.get("neutral_count", 0) or 0,
            ),
        }
    except Exception:  # noqa: BLE001
        pass
    # Per-engine attribution
    try:
        from engines._revenue_attribution import attribute_revenue
        report = attribute_revenue(window_hours=168.0)
        for e in report.per_engine:
            if e.engine == engine_name:
                ctx["attribution_7d"] = {
                    "revenue": round(e.attributed_revenue, 2),
                    "orders": e.attributed_orders,
                    "confidence": e.confidence,
                    "cluster": e.cluster,
                }
                break
    except Exception:  # noqa: BLE001
        pass
    return ctx


def _heuristic_recommendation(
    action: Any,
    engine_context: dict[str, Any],
) -> PrevetRecommendation:
    """Deterministic baseline when LLM is unavailable.

    Rule of thumb:
      - additive risk + positive outcomes -> approve
      - destructive risk -> hold (operator-only)
      - modification + negative outcomes -> reject
      - new engine (no history) -> hold
      - default -> hold

    The LLM REFINES this; deterministic ensures we always
    have an answer even without API connectivity.
    """
    flags: list[str] = []
    action_id = str(getattr(action, "id", "?"))
    risk = (
        getattr(action, "risk_class", None)
        or "unknown"
    )
    if risk == "destructive":
        flags.append("destructive_risk_class")
        return PrevetRecommendation(
            action_id=action_id,
            recommendation="hold",
            confidence=0.95,
            rationale=(
                "destructive risk class -- operator-only "
                "escalation"
            ),
            flags=flags,
        )

    outcomes = engine_context.get("recent_outcomes") or {}
    pos = int(outcomes.get("positive_count", 0))
    neg = int(outcomes.get("negative_count", 0))
    total_decided = pos + neg
    if total_decided == 0:
        return PrevetRecommendation(
            action_id=action_id,
            recommendation="hold",
            confidence=0.3,
            rationale=(
                "no outcome history yet -- operator decides"
            ),
            flags=["new_engine"],
        )

    pos_ratio = pos / total_decided
    if pos_ratio >= 0.8 and total_decided >= 3 and risk == "additive":
        return PrevetRecommendation(
            action_id=action_id,
            recommendation="approve",
            confidence=min(0.9, 0.5 + pos_ratio / 2),
            rationale=(
                f"additive + {pos}/{total_decided} positive "
                f"outcomes ({pos_ratio:.0%})"
            ),
            flags=flags,
        )
    if pos_ratio <= 0.3 and total_decided >= 3:
        flags.append("negative_outcome_trend")
        return PrevetRecommendation(
            action_id=action_id,
            recommendation="reject",
            confidence=0.7,
            rationale=(
                f"only {pos}/{total_decided} positive outcomes "
                f"({pos_ratio:.0%}) -- engine recently misfiring"
            ),
            flags=flags,
        )
    return PrevetRecommendation(
        action_id=action_id,
        recommendation="hold",
        confidence=0.4,
        rationale=(
            f"mixed history ({pos}/{total_decided} positive) "
            "-- operator judgement"
        ),
        flags=flags,
    )


def prevet_action(action: Any) -> PrevetRecommendation:
    """Build a PrevetRecommendation for a single pending action.

    LLM-consultant pattern: deterministic recommendation runs
    first as the baseline; LLM may REFINE if enabled.
    """
    engine_name = getattr(action, "engine", None) or "unknown"
    ctx = _gather_engine_context(engine_name)
    base = _heuristic_recommendation(action, ctx)

    if not is_enabled():
        return base

    # LLM consultation
    try:
        from engines._ai_strategies import _LLMClient
        llm = _LLMClient()
        if not llm.available:
            return base
    except Exception:  # noqa: BLE001
        return base

    system = (
        "You are an approval pre-vet for ShopAI, an autonomous "
        "Shopify merchant. Given a pending action + its "
        "engine's recent history + revenue attribution, "
        "recommend approve / reject / hold with confidence "
        "0.0-1.0 + a short rationale. Return JSON: "
        "{\"recommendation\": \"approve|reject|hold\", "
        "\"confidence\": 0.0-1.0, \"rationale\": \"...\"}. "
        "Defaults to 'hold' when uncertain. Reject only when "
        "the engine is clearly misfiring (negative outcome "
        "trend, falling revenue). Approve only when "
        "additive + strong positive history."
    )
    user = json.dumps({
        "action_id": str(getattr(action, "id", "")),
        "engine": engine_name,
        "action_type": getattr(action, "action_type", ""),
        "capability": getattr(action, "capability", ""),
        "risk_class": getattr(action, "risk_class", "unknown"),
        "params_summary": str(
            getattr(action, "params", "") or "",
        )[:200],
        "deterministic_baseline": {
            "recommendation": base.recommendation,
            "rationale": base.rationale,
        },
        "engine_context": ctx,
    })

    resp = llm.chat_json(system, user)
    if resp is None:
        return base

    rec = resp.get("recommendation")
    if rec not in _VALID_RECOMMENDATIONS:
        return base
    try:
        conf = float(resp.get("confidence", 0.5))
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = 0.5

    return PrevetRecommendation(
        action_id=base.action_id,
        recommendation=rec,
        confidence=conf,
        rationale=(
            f"[AI] {resp.get('rationale', 'no rationale')} "
            f"(baseline: {base.recommendation})"
        ),
        flags=base.flags,
    )


def prevet_batch(actions: list[Any]) -> list[PrevetRecommendation]:
    """Run prevet over a batch of pending actions."""
    return [prevet_action(a) for a in actions]
