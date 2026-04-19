"""Decision audit trail — walk a decision back through every contributor.

When the brain decides "kill ad 12345" the owner reasonably asks
"WHY?". Today we have explanation_aggregator (one-shot prose), but
no machine-checkable trail showing exactly which signals + rules +
prior cases contributed. The audit trail does that.

Inputs (any combination, all optional):

  • the decision Experience itself (kind=decision, payload includes
    context + chosen + reasoning + timestamps)
  • surrounding LLM calls within the same cycle
  • surrounding outcomes / phase events sharing the cycle_id
  • credit_assigner credits for that decision id

Outputs are a structured ``AuditTrail`` with:

  • decision      — the original payload
  • contributors  — list of (kind, ts, summary) sorted by recency
  • metrics       — per-source contribution: counts + LLM cost
  • verdict       — "complete" | "partial" | "unknown"

Pure stdlib. Inputs come from experience_recorder.recent (default) or
caller-injected, so tests can mock cleanly.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.decision_audit_trail")


@dataclass
class Contributor:
    kind: str
    ts: float
    summary: str
    ref_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ts": self.ts,
            "summary": self.summary,
            "ref_id": self.ref_id,
            "payload": dict(self.payload),
        }


@dataclass
class AuditTrail:
    decision_id: str
    cycle_id: str
    decision: dict[str, Any] = field(default_factory=dict)
    contributors: list[Contributor] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    verdict: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "cycle_id": self.cycle_id,
            "decision": dict(self.decision),
            "contributors": [c.as_dict() for c in self.contributors],
            "metrics": dict(self.metrics),
            "verdict": self.verdict,
        }


# ── Helpers ───────────────────────────────────────────────

def _payload(event: Any) -> dict[str, Any]:
    p = getattr(event, "payload", None)
    if p is None and isinstance(event, dict):
        p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _kind(event: Any) -> str:
    return str(
        getattr(event, "kind", None)
        or (event.get("kind") if isinstance(event, dict) else "")
    )


def _id(event: Any) -> str:
    return str(
        getattr(event, "id", None)
        or (event.get("id") if isinstance(event, dict) else "")
    )


def _ts(event: Any) -> float:
    return float(
        getattr(event, "ts", None)
        or (event.get("ts") if isinstance(event, dict) else 0.0)
        or 0.0
    )


def _cycle_id(event: Any) -> str:
    return str(
        getattr(event, "cycle_id", None)
        or (event.get("cycle_id") if isinstance(event, dict) else "")
        or ""
    )


# ── Builder ───────────────────────────────────────────────

class DecisionAuditor:
    def __init__(
        self,
        recent_fn: Callable[..., list[Any]] | None = None,
        credit_lookup_fn: Callable[[str], dict[str, float]] | None = None,
    ) -> None:
        self._recent_fn = recent_fn
        self._credit_lookup = credit_lookup_fn

    def _recent(self, **kwargs: Any) -> list[Any]:
        if self._recent_fn is not None:
            try:
                return list(self._recent_fn(**kwargs))
            except Exception as exc:
                logger.debug("injected recent_fn failed: %s", exc)
                return []
        try:
            from core.brain.experience_recorder import recent
            return list(recent(**kwargs))
        except Exception as exc:
            logger.debug("default recent failed: %s", exc)
            return []

    def _credits(self, decision_id: str) -> dict[str, float]:
        if self._credit_lookup is not None:
            try:
                return dict(self._credit_lookup(decision_id))
            except Exception as exc:
                logger.debug("credit_lookup failed: %s", exc)
                return {}
        try:
            from core.brain.brain_facade import _credit_assigner
            ca = _credit_assigner()
            total = ca.total_credit(decision_id)
            return {"total_credit": float(total)}
        except Exception as exc:
            logger.debug("credit_assigner unavailable: %s", exc)
            return {}

    # ── Build ────────────────────────────────────────────

    def build(self, decision_id: str) -> AuditTrail:
        if not decision_id:
            return AuditTrail(decision_id="", cycle_id="", verdict="unknown")
        events = self._recent(limit=1000)
        # Find the decision event
        decision_event: Any = None
        for ev in events:
            if _kind(ev) == "decision" and _id(ev) == decision_id:
                decision_event = ev
                break
        if decision_event is None:
            return AuditTrail(
                decision_id=decision_id,
                cycle_id="",
                verdict="unknown",
            )
        decision_payload = _payload(decision_event)
        cycle_id = _cycle_id(decision_event)
        decision_ts = _ts(decision_event)

        # Gather contributors: events sharing cycle_id, sorted by ts
        siblings: list[Any] = []
        for ev in events:
            if _id(ev) == decision_id:
                continue
            if cycle_id and _cycle_id(ev) != cycle_id:
                continue
            siblings.append(ev)
        siblings.sort(key=_ts)

        contributors: list[Contributor] = []
        llm_cost = 0.0
        per_kind: dict[str, int] = {}
        for ev in siblings:
            k = _kind(ev)
            per_kind[k] = per_kind.get(k, 0) + 1
            payload = _payload(ev)
            summary = _summarise(k, payload)
            ref_id = _id(ev)
            contributors.append(Contributor(
                kind=k, ts=_ts(ev),
                summary=summary,
                ref_id=ref_id,
                payload=payload,
            ))
            if k == "llm_call":
                try:
                    llm_cost += float(payload.get("cost_usd", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue

        credit_info = self._credits(decision_id)

        # Verdict: complete if we have at least one outcome AND one
        # context-aware contributor (phase / llm).
        has_outcome = any(c.kind == "outcome" for c in contributors)
        has_context = any(
            c.kind in ("phase", "llm_call") for c in contributors
        )
        if has_outcome and has_context:
            verdict = "complete"
        elif contributors:
            verdict = "partial"
        else:
            verdict = "unknown"

        metrics = {
            "n_contributors": len(contributors),
            "by_kind": per_kind,
            "llm_cost_usd": round(llm_cost, 6),
            "credits": credit_info,
            "decision_ts": decision_ts,
        }
        return AuditTrail(
            decision_id=decision_id,
            cycle_id=cycle_id,
            decision=decision_payload,
            contributors=contributors,
            metrics=metrics,
            verdict=verdict,
        )

    def chain_text(self, trail: AuditTrail) -> str:
        """Render an AuditTrail as readable markdown for owners."""
        if trail.verdict == "unknown":
            return f"# Decision {trail.decision_id} — no trail found"
        chosen = (trail.decision.get("chosen") or {})
        action = chosen.get("action") or chosen.get("kind") or "?"
        lines = [
            f"# Decision {trail.decision_id} — {action}",
            "",
            f"**Cycle**: {trail.cycle_id or '(none)'}",
            f"**Verdict**: {trail.verdict}",
            f"**Contributors**: {trail.metrics.get('n_contributors', 0)}",
        ]
        if trail.metrics.get("llm_cost_usd"):
            lines.append(
                f"**LLM cost**: ${trail.metrics['llm_cost_usd']:.4f}",
            )
        if trail.contributors:
            lines.append("\n## Trail")
            for c in trail.contributors:
                lines.append(f"- {c.kind}: {c.summary}")
        if trail.metrics.get("credits"):
            lines.append("\n## Credit")
            for k, v in trail.metrics["credits"].items():
                lines.append(f"- {k}: {v}")
        return "\n".join(lines)


def _summarise(kind: str, payload: dict[str, Any]) -> str:
    if kind == "phase":
        return (
            f"phase {payload.get('name', '?')} "
            f"= {payload.get('status', '?')}"
        )
    if kind == "outcome":
        return (
            f"outcome {payload.get('kpi', '?')} "
            f"= {payload.get('value', '?')}"
        )
    if kind == "llm_call":
        return (
            f"llm_call adapter={payload.get('adapter', '?')} "
            f"ok={payload.get('ok', False)}"
        )
    if kind == "assessment":
        return f"assessment health={payload.get('health_score', '?')}"
    return f"{kind} payload_keys={sorted(list(payload.keys()))[:5]}"
