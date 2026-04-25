"""Conflict resolver — pick between contradictory rules.

consolidation (v5) detects that two rules *are* contradictory. It
doesn't say which one wins at decision time. Without a tie-breaker
the brain either fires both (logically inconsistent) or falls back
to whichever the iteration found first (arbitrary).

ConflictResolver ranks contradictory rules and returns a signed
verdict. Six signals, each producing a score; the highest sum
wins:

  • success_rate     — fires × wins → Beta posterior mean
  • recency          — newer evidence beats older stale evidence
  • owner_feedback   — net up-votes − down-votes
  • evidence_count   — more source events = more trust
  • height_preference — specific rules beat abstract ones on
                         direct applicability, abstract beat
                         specific when the specific's coverage is
                         thin (uses epistemic map)
  • provenance       — rules derived from owner demonstrations
                         (imitation) beat purely-mined rules

Returns a ``Resolution`` with the winner id, the loser id, the
margin (winner_score − loser_score), and per-signal breakdown so
the decision is auditable. When the margin < 0.1, status =
``"tie"`` and the caller is instructed to abstain.

Pure stdlib; no LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class Signal:
    name: str
    winner_score: float
    loser_score: float

    @property
    def delta(self) -> float:
        return self.winner_score - self.loser_score

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "winner_score": round(self.winner_score, 3),
            "loser_score": round(self.loser_score, 3),
            "delta": round(self.delta, 3),
        }


@dataclass
class Resolution:
    status: str                     # "resolved" | "tie"
    winner_id: str | None
    loser_id: str | None
    margin: float
    signals: list[Signal] = field(default_factory=list)
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "winner_id": self.winner_id,
            "loser_id": self.loser_id,
            "margin": round(self.margin, 3),
            "rationale": self.rationale,
            "signals": [s.as_dict() for s in self.signals],
        }


# ── Signal computations ─────────────────────────────────────

def _success_rate(rule: dict[str, Any]) -> float:
    fires = int(rule.get("fires", 0))
    wins = int(rule.get("wins", rule.get("successes", 0)))
    # Beta(1+wins, 1+fires-wins) mean
    alpha = 1.0 + wins
    beta = 1.0 + max(0, fires - wins)
    return alpha / (alpha + beta)


def _recency(rule: dict[str, Any], now_ref: float) -> float:
    last = float(rule.get("last_seen", rule.get("updated_at", 0)))
    if last <= 0:
        return 0.0
    age_days = max(0.0, (now_ref - last) / 86_400)
    # Simple decay: 1 at 0 days, 0.5 at 30d, ~0.1 at 100d
    import math
    return math.exp(-age_days / 45.0)


def _owner_feedback(rule: dict[str, Any]) -> float:
    ups = int(rule.get("up_votes", 0))
    downs = int(rule.get("down_votes", 0))
    total = ups + downs
    if total == 0:
        return 0.5
    return ups / total


def _evidence_count(rule: dict[str, Any]) -> float:
    n = int(rule.get("source_count", rule.get("fires", 0)))
    # saturating curve: 0 → 0, 5 → 0.5, 20+ → 1
    return min(1.0, n / 20.0)


def _height_preference(
    rule: dict[str, Any], opponent: dict[str, Any],
    context_coverage: float,
) -> float:
    """Specific rules (lower height) win when we have confident
    coverage; abstract rules win when coverage is thin."""
    height = int(rule.get("height", 0))
    opp_height = int(opponent.get("height", 0))
    if height == opp_height:
        return 0.5
    # context_coverage: 1 = hot, 0 = cold
    if height < opp_height:
        # I am more specific; I win iff coverage is high
        return 0.5 + 0.5 * context_coverage
    return 0.5 + 0.5 * (1 - context_coverage)


def _provenance(rule: dict[str, Any]) -> float:
    prov = str(rule.get("provenance", "mined")).lower()
    # owner_demo > hypothesis_confirmed > mined > heuristic
    return {
        "owner_demo": 1.0,
        "imitation": 1.0,
        "hypothesis_confirmed": 0.8,
        "mined": 0.5,
        "heuristic": 0.3,
    }.get(prov, 0.5)


# ── Resolver ───────────────────────────────────────────────

def resolve(
    rule_a: dict[str, Any],
    rule_b: dict[str, Any],
    *,
    context_coverage: float = 0.5,
    now_ref: float | None = None,
    weights: dict[str, float] | None = None,
) -> Resolution:
    import time
    now_ref = float(now_ref) if now_ref is not None else time.time()
    weights = weights or {
        "success_rate": 2.5,
        "recency": 1.0,
        "owner_feedback": 2.0,
        "evidence_count": 1.0,
        "height_preference": 0.8,
        "provenance": 1.5,
    }
    signals: list[Signal] = []
    a_total = 0.0
    b_total = 0.0
    pairs = (
        ("success_rate", _success_rate(rule_a), _success_rate(rule_b)),
        ("recency",
         _recency(rule_a, now_ref),
         _recency(rule_b, now_ref)),
        ("owner_feedback",
         _owner_feedback(rule_a), _owner_feedback(rule_b)),
        ("evidence_count",
         _evidence_count(rule_a), _evidence_count(rule_b)),
        ("height_preference",
         _height_preference(rule_a, rule_b, context_coverage),
         _height_preference(rule_b, rule_a, context_coverage)),
        ("provenance", _provenance(rule_a), _provenance(rule_b)),
    )
    for name, sa, sb in pairs:
        w = weights.get(name, 1.0)
        signals.append(Signal(name=name,
                               winner_score=sa * w,
                               loser_score=sb * w))
        a_total += sa * w
        b_total += sb * w
    margin = abs(a_total - b_total)
    if margin < 0.1:
        return Resolution(
            status="tie",
            winner_id=None,
            loser_id=None,
            margin=margin,
            signals=signals,
            rationale="signals too close — abstain",
        )
    winner, loser = (
        (rule_a, rule_b) if a_total > b_total else (rule_b, rule_a)
    )
    # Repopulate signals so winner_score/loser_score reflect the
    # actual winner rule, not just the A/B argument order.
    final_signals: list[Signal] = []
    if a_total > b_total:
        final_signals = signals
    else:
        for s in signals:
            final_signals.append(Signal(
                name=s.name,
                winner_score=s.loser_score,
                loser_score=s.winner_score,
            ))
    top_signal = max(final_signals, key=lambda s: s.delta)
    return Resolution(
        status="resolved",
        winner_id=str(winner.get("id")),
        loser_id=str(loser.get("id")),
        margin=margin,
        signals=final_signals,
        rationale=(f"{top_signal.name} favoured winner "
                   f"({top_signal.delta:+.2f})"),
    )


def batch_resolve(
    contradiction_pairs: Iterable[tuple[dict[str, Any], dict[str, Any]]],
    *, context_coverage: float = 0.5,
) -> list[Resolution]:
    return [
        resolve(a, b, context_coverage=context_coverage)
        for a, b in contradiction_pairs
    ]
