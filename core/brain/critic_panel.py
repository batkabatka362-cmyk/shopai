"""Critic panel — grade a proposal from multiple vantages.

counter_argument (v19-D1) runs a flat probe battery. A proper
critic panel splits concerns across role-players: a Bull hunts
upside, a Bear hunts downside, an Accountant hunts margin, an
Ethicist hunts harm. Each returns a 0-5 grade + rationale.
Aggregate grade is the weighted mean; the lowest grade is the
most damaging critic's voice.

APIs:

  grade(proposal) → PanelReport(avg_grade, critic_grades,
                                 overall_verdict)
  register_critic(name, fn, weight)
  deregister(name)
  critics()

Each critic callable receives the proposal dict and returns
(grade 0-5, rationale str). Missing data → conservative 2.5
(neutral). Ships 4 default critics you can augment with domain-
specific ones.

Pure stdlib, deterministic, zero LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal


Verdict = Literal["approve", "revise", "reject"]


@dataclass
class CriticGrade:
    name: str
    grade: float             # 0..5
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "grade": round(self.grade, 2),
            "rationale": self.rationale,
        }


@dataclass
class PanelReport:
    avg_grade: float
    overall_verdict: Verdict
    min_grade: float
    critic_grades: list[CriticGrade] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "avg_grade": round(self.avg_grade, 2),
            "min_grade": round(self.min_grade, 2),
            "overall_verdict": self.overall_verdict,
            "critic_grades": [g.as_dict() for g in self.critic_grades],
        }


CriticFn = Callable[[dict[str, Any]], tuple[float, str]]


@dataclass
class Critic:
    name: str
    fn: CriticFn
    weight: float = 1.0


# ── Default critics ────────────────────────────────────────

def _bull(p: dict[str, Any]) -> tuple[float, str]:
    score = 2.5
    reasons = []
    roas = p.get("projected_roas")
    if roas and float(roas) >= 2.0:
        score += 1.5
        reasons.append(f"strong ROAS projection {float(roas):.2f}")
    if p.get("high_novelty"):
        score += 0.5
        reasons.append("novelty")
    margin = p.get("projected_margin_pct")
    if margin and float(margin) >= 0.35:
        score += 0.5
        reasons.append("healthy margin")
    score = min(5.0, score)
    return score, "; ".join(reasons) or "neutral"


def _bear(p: dict[str, Any]) -> tuple[float, str]:
    score = 2.5
    reasons = []
    if p.get("irreversible") and not p.get("rollback_plan"):
        score -= 1.5
        reasons.append("irreversible without rollback")
    if not (p.get("evidence") or []):
        score -= 1.0
        reasons.append("no evidence")
    roas = p.get("projected_roas")
    if roas is not None and float(roas) < 1.0:
        score -= 1.5
        reasons.append(f"ROAS {float(roas):.2f} under 1.0")
    score = max(0.0, score)
    return score, "; ".join(reasons) or "no major downside"


def _accountant(p: dict[str, Any]) -> tuple[float, str]:
    margin = p.get("projected_margin_pct")
    floor = p.get("min_margin_pct", 0.1)
    spend = float(p.get("spend_usd", 0) or 0)
    cap = p.get("daily_cap_usd")
    score = 2.5
    reasons = []
    if margin is not None:
        if float(margin) < float(floor):
            score -= 2.0
            reasons.append(
                f"margin {float(margin):.1%} below floor "
                f"{float(floor):.1%}",
            )
        elif float(margin) >= 0.4:
            score += 1.5
            reasons.append(f"margin {float(margin):.1%}")
    if spend > 100 and cap is None:
        score -= 1.0
        reasons.append(f"uncapped spend ${spend:.0f}")
    if spend <= 50 and (cap is None or float(cap) >= spend):
        score += 0.5
        reasons.append("modest, bounded spend")
    score = max(0.0, min(5.0, score))
    return score, "; ".join(reasons) or "neutral financial profile"


def _ethicist(p: dict[str, Any]) -> tuple[float, str]:
    score = 4.0
    reasons = []
    if p.get("deceptive_anchor"):
        score -= 3.0
        reasons.append("deceptive anchor price")
    if p.get("scarcity_exaggerated"):
        score -= 2.0
        reasons.append("scarcity claim exaggerates stock")
    if p.get("requires_human_pii_log"):
        score -= 1.0
        reasons.append("logs PII without consent")
    score = max(0.0, score)
    return score, "; ".join(reasons) or "no ethical concerns"


_DEFAULT_CRITICS: tuple[Critic, ...] = (
    Critic(name="bull", fn=_bull, weight=1.0),
    Critic(name="bear", fn=_bear, weight=1.0),
    Critic(name="accountant", fn=_accountant, weight=1.5),
    Critic(name="ethicist", fn=_ethicist, weight=1.5),
)


# ── Panel ──────────────────────────────────────────────────

class CriticPanel:
    def __init__(self) -> None:
        self._critics: list[Critic] = list(_DEFAULT_CRITICS)

    def register_critic(
        self, name: str, fn: CriticFn, weight: float = 1.0,
    ) -> None:
        if not name:
            raise ValueError("critic name required")
        if weight <= 0:
            raise ValueError("critic weight must be > 0")
        self._critics = [
            c for c in self._critics if c.name != name
        ] + [Critic(name=name, fn=fn, weight=float(weight))]

    def deregister(self, name: str) -> bool:
        before = len(self._critics)
        self._critics = [c for c in self._critics if c.name != name]
        return len(self._critics) < before

    def critics(self) -> list[str]:
        return [c.name for c in self._critics]

    def grade(self, proposal: dict[str, Any]) -> PanelReport:
        grades: list[CriticGrade] = []
        total_weight = 0.0
        weighted_sum = 0.0
        for c in self._critics:
            try:
                g, rationale = c.fn(proposal)
                g = max(0.0, min(5.0, float(g)))
                grades.append(CriticGrade(
                    name=c.name, grade=g, rationale=rationale,
                ))
                weighted_sum += g * c.weight
                total_weight += c.weight
            except Exception:
                continue
        avg = weighted_sum / total_weight if total_weight else 0.0
        min_grade = min((g.grade for g in grades), default=0.0)
        verdict: Verdict
        if avg >= 3.75 and min_grade >= 2.0:
            verdict = "approve"
        elif min_grade < 1.0 or avg < 2.0:
            verdict = "reject"
        else:
            verdict = "revise"
        return PanelReport(
            avg_grade=avg,
            min_grade=min_grade,
            overall_verdict=verdict,
            critic_grades=grades,
        )
