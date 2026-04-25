"""Counter-argument — red-team any proposed decision.

debate (v4) runs bull/bear/judge roleplay over a topic. counter_
argument is a cheaper, deterministic cousin: given a concrete
proposal, emit a ranked list of objections that a thoughtful
sceptic would raise. No LLM, no multi-agent setup — just a
structured set of rule-based probes that every good e-commerce
decision should survive.

Probes ship with defaults; register_probe lets you add domain-
specific objectors. Each probe inspects the proposal and returns
zero or more Objections with severity + suggested_test.

APIs:

  critique(proposal) → CritiqueReport(objections, overall_risk)
  register_probe(name, fn)
  deregister(name)
  probes()

A proposal that survives every probe earns overall_risk ∈ [0, 0.1];
one that flunks three or more earns ≥ 0.7. The governor / debate
module consumes this before green-lighting anything money-moving.

Pure stdlib; deterministic; zero LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


Severity = str   # "low" | "medium" | "high"


@dataclass
class Objection:
    probe: str
    severity: Severity
    reason: str
    suggested_test: str = ""

    def weight(self) -> float:
        return {"low": 0.2, "medium": 0.5, "high": 1.0}.get(
            self.severity, 0.3,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "probe": self.probe,
            "severity": self.severity,
            "reason": self.reason,
            "suggested_test": self.suggested_test,
        }


@dataclass
class CritiqueReport:
    overall_risk: float
    objections: list[Objection] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall_risk": round(self.overall_risk, 3),
            "objection_count": len(self.objections),
            "objections": [o.as_dict() for o in self.objections],
        }


Probe = Callable[[dict[str, Any]], Iterable[Objection]]


# ── Default probes ──────────────────────────────────────────

def _thin_evidence(p: dict[str, Any]) -> Iterable[Objection]:
    evidence = p.get("evidence") or []
    if len(evidence) < 3:
        yield Objection(
            probe="thin_evidence",
            severity="medium",
            reason=f"only {len(evidence)} supporting data point(s)",
            suggested_test=(
                "gather ≥3 independent observations before acting"
            ),
        )


def _high_spend_without_cap(p: dict[str, Any]) -> Iterable[Objection]:
    spend = float(p.get("spend_usd", 0) or 0)
    cap = p.get("daily_cap_usd")
    if spend > 100 and cap is None:
        yield Objection(
            probe="high_spend_without_cap",
            severity="high",
            reason=(f"${spend:.0f} spend with no daily cap declared"),
            suggested_test="set an explicit daily_cap_usd first",
        )


def _novelty_without_canary(p: dict[str, Any]) -> Iterable[Objection]:
    if p.get("novel") and not p.get("canary_pct"):
        yield Objection(
            probe="novelty_without_canary",
            severity="medium",
            reason="new/unproven action without a canary slice",
            suggested_test=(
                "start at canary_pct=5 and ramp via rollout_manager"
            ),
        )


def _margin_floor_breach(p: dict[str, Any]) -> Iterable[Objection]:
    margin = p.get("projected_margin_pct")
    floor = p.get("min_margin_pct", 0.1)
    if margin is not None and float(margin) < float(floor):
        yield Objection(
            probe="margin_floor_breach",
            severity="high",
            reason=(f"projected margin {margin:.1%} "
                    f"< floor {floor:.1%}"),
            suggested_test="re-price or cut variable costs first",
        )


def _assumption_untested(p: dict[str, Any]) -> Iterable[Objection]:
    tested = p.get("assumptions_tested") or []
    stated = p.get("assumptions") or []
    untested = [a for a in stated if a not in tested]
    if untested:
        yield Objection(
            probe="assumption_untested",
            severity="medium",
            reason=(f"{len(untested)} stated assumption(s) "
                    f"have no test: {untested[:3]}"),
            suggested_test=(
                "register a hypothesis for each untested assumption"
            ),
        )


def _reversibility_missing(p: dict[str, Any]) -> Iterable[Objection]:
    if p.get("irreversible") and not p.get("rollback_plan"):
        yield Objection(
            probe="reversibility_missing",
            severity="high",
            reason="irreversible action with no rollback plan",
            suggested_test="draft a reversal path or require human approve",
        )


def _counterfactual_absent(p: dict[str, Any]) -> Iterable[Objection]:
    if p.get("stakes_band") == "high" and not p.get("counterfactual"):
        yield Objection(
            probe="counterfactual_absent",
            severity="medium",
            reason=(
                "high-stakes decision without a counterfactual baseline"
            ),
            suggested_test="run offline_sandbox on the alternative",
        )


_DEFAULT_PROBES: tuple[tuple[str, Probe], ...] = (
    ("thin_evidence", _thin_evidence),
    ("high_spend_without_cap", _high_spend_without_cap),
    ("novelty_without_canary", _novelty_without_canary),
    ("margin_floor_breach", _margin_floor_breach),
    ("assumption_untested", _assumption_untested),
    ("reversibility_missing", _reversibility_missing),
    ("counterfactual_absent", _counterfactual_absent),
)


# ── Engine ─────────────────────────────────────────────────

class CounterArgumentEngine:
    def __init__(self) -> None:
        self._probes: dict[str, Probe] = dict(_DEFAULT_PROBES)

    def register_probe(self, name: str, fn: Probe) -> None:
        if not name:
            raise ValueError("probe name required")
        self._probes[name] = fn

    def deregister(self, name: str) -> bool:
        return self._probes.pop(name, None) is not None

    def probes(self) -> list[str]:
        return sorted(self._probes.keys())

    def critique(
        self, proposal: dict[str, Any],
    ) -> CritiqueReport:
        objections: list[Objection] = []
        for name, probe in self._probes.items():
            try:
                for obj in probe(proposal) or []:
                    objections.append(obj)
            except Exception:
                continue
        objections.sort(key=lambda o: -o.weight())
        # Risk: sum of weights, capped at 1.0 via logistic-ish shape.
        raw = sum(o.weight() for o in objections)
        risk = min(1.0, raw / (raw + 1.0) * 2.0) if raw > 0 else 0.0
        return CritiqueReport(
            overall_risk=risk, objections=objections,
        )
