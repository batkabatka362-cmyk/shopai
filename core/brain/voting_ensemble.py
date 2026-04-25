"""Voting ensemble — multiple policies vote on one decision.

One policy is a point estimate; several policies disagree and
that disagreement carries information. voting_ensemble runs N
independent policy callables over the same context and emits a
weighted verdict plus a confidence that accounts for agreement.

Supports three voting schemes:

  • plurality       — simple majority across raw votes
  • weighted        — weight × confidence per voter
  • borda_count     — ranked choice over multiple alternatives
  • unanimous       — all voters must agree or abstain

When voters disagree, the returned ``confidence`` drops
proportionally. Ties under plurality break on highest total
weight, then lexicographic voter name for determinism.

APIs:

  register(name, fn, weight=1.0)
  vote(context, scheme="weighted") → Verdict
  verdict_margin(verdict)           → gap between 1st and 2nd

Each policy fn returns a Ballot dict:
  {"choice": str, "confidence": float, "rationale": str}

Pure stdlib. Deterministic under a fixed voter order. Zero LLM.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal


Scheme = Literal["plurality", "weighted", "borda_count", "unanimous"]


@dataclass
class Ballot:
    voter: str
    choice: str
    confidence: float = 1.0
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "voter": self.voter,
            "choice": self.choice,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
        }


@dataclass
class Verdict:
    scheme: Scheme
    winner: str | None
    confidence: float
    tallies: dict[str, float] = field(default_factory=dict)
    ballots: list[Ballot] = field(default_factory=list)
    unanimous: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme,
            "winner": self.winner,
            "confidence": round(self.confidence, 3),
            "unanimous": self.unanimous,
            "tallies": {k: round(v, 3) for k, v in self.tallies.items()},
            "ballots": [b.as_dict() for b in self.ballots],
        }


PolicyFn = Callable[[dict[str, Any]], Any]


@dataclass
class Voter:
    name: str
    fn: PolicyFn
    weight: float = 1.0


# ── Ensemble ────────────────────────────────────────────────

class VotingEnsemble:
    def __init__(self) -> None:
        self._voters: list[Voter] = []

    def register(
        self, name: str, fn: PolicyFn, weight: float = 1.0,
    ) -> None:
        name = name.strip()
        if not name:
            raise ValueError("voter name required")
        if weight <= 0:
            raise ValueError("voter weight must be > 0")
        self._voters = [
            v for v in self._voters if v.name != name
        ] + [Voter(name=name, fn=fn, weight=float(weight))]

    def deregister(self, name: str) -> bool:
        before = len(self._voters)
        self._voters = [v for v in self._voters if v.name != name]
        return len(self._voters) < before

    def voters(self) -> list[str]:
        return [v.name for v in self._voters]

    # ── Vote ───────────────────────────────────────────────

    def vote(
        self, context: dict[str, Any],
        scheme: Scheme = "weighted",
    ) -> Verdict:
        if scheme not in (
            "plurality", "weighted", "borda_count", "unanimous",
        ):
            raise ValueError(f"unknown scheme {scheme!r}")
        ballots = self._cast_ballots(context)
        if not ballots:
            return Verdict(
                scheme=scheme, winner=None, confidence=0.0,
                ballots=[], tallies={},
            )
        if scheme == "plurality":
            return self._plurality(ballots, scheme)
        if scheme == "weighted":
            return self._weighted(ballots, scheme)
        if scheme == "unanimous":
            return self._unanimous(ballots, scheme)
        return self._borda(ballots, scheme, context)

    # ── Ballot casting ────────────────────────────────────

    def _cast_ballots(
        self, context: dict[str, Any],
    ) -> list[Ballot]:
        out: list[Ballot] = []
        # Preserve registration order for determinism
        for voter in self._voters:
            try:
                result = voter.fn(context) or {}
            except Exception:
                continue
            if isinstance(result, str):
                out.append(Ballot(
                    voter=voter.name, choice=result,
                    confidence=1.0,
                ))
            elif isinstance(result, dict):
                choice = result.get("choice")
                if not choice:
                    # Borda-only voters return {'ranking': [...]}.
                    # Treat the top-ranked option as the ballot's
                    # choice so the plurality path still sees a
                    # vote and the ensemble doesn't early-exit.
                    ranking = result.get("ranking") or []
                    choice = ranking[0] if ranking else None
                if not choice:
                    continue
                out.append(Ballot(
                    voter=voter.name,
                    choice=str(choice),
                    confidence=float(result.get("confidence", 1.0)),
                    rationale=str(result.get("rationale", "")),
                ))
            else:
                continue
        return out

    # ── Scheme implementations ────────────────────────────

    def _plurality(
        self, ballots: list[Ballot], scheme: Scheme,
    ) -> Verdict:
        counts: dict[str, int] = defaultdict(int)
        weights: dict[str, float] = defaultdict(float)
        voter_weights = {v.name: v.weight for v in self._voters}
        for b in ballots:
            counts[b.choice] += 1
            weights[b.choice] += voter_weights.get(b.voter, 1.0)
        total = sum(counts.values())
        # Sort by count desc, then weight desc, then name asc
        ordered = sorted(
            counts.keys(),
            key=lambda k: (-counts[k], -weights[k], k),
        )
        winner = ordered[0]
        confidence = counts[winner] / total if total else 0.0
        unanimous = counts[winner] == total
        return Verdict(
            scheme=scheme, winner=winner, confidence=confidence,
            tallies={k: float(v) for k, v in counts.items()},
            ballots=ballots, unanimous=unanimous,
        )

    def _weighted(
        self, ballots: list[Ballot], scheme: Scheme,
    ) -> Verdict:
        tallies: dict[str, float] = defaultdict(float)
        voter_weights = {v.name: v.weight for v in self._voters}
        for b in ballots:
            w = voter_weights.get(b.voter, 1.0) * b.confidence
            tallies[b.choice] += w
        if not tallies:
            return Verdict(
                scheme=scheme, winner=None, confidence=0.0,
                tallies={}, ballots=ballots,
            )
        total = sum(tallies.values())
        ordered = sorted(
            tallies.keys(),
            key=lambda k: (-tallies[k], k),
        )
        winner = ordered[0]
        confidence = tallies[winner] / total if total else 0.0
        unanimous = all(b.choice == winner for b in ballots)
        return Verdict(
            scheme=scheme, winner=winner, confidence=confidence,
            tallies=dict(tallies), ballots=ballots,
            unanimous=unanimous,
        )

    def _unanimous(
        self, ballots: list[Ballot], scheme: Scheme,
    ) -> Verdict:
        choices = {b.choice for b in ballots}
        if len(choices) != 1 or len(ballots) < len(self._voters):
            return Verdict(
                scheme=scheme, winner=None, confidence=0.0,
                tallies={c: sum(1 for b in ballots if b.choice == c)
                          for c in choices},
                ballots=ballots, unanimous=False,
            )
        winner = next(iter(choices))
        return Verdict(
            scheme=scheme, winner=winner, confidence=1.0,
            tallies={winner: float(len(ballots))},
            ballots=ballots, unanimous=True,
        )

    def _borda(
        self, ballots: list[Ballot], scheme: Scheme,
        context: dict[str, Any],
    ) -> Verdict:
        """Borda Count — voters must return ranked lists via
        {'ranking': [...]} in their ballot (fall back to choice).

        Each voter's k-th-ranked candidate receives (N − k − 1)
        points, weighted by voter weight × confidence."""
        # Collect rankings; if absent, treat choice as only-ranked.
        voter_weights = {v.name: v.weight for v in self._voters}
        # Re-cast to capture ranking field
        raw_ballots: dict[str, tuple[list[str], float]] = {}
        for voter in self._voters:
            try:
                result = voter.fn(context)
            except Exception:
                continue
            ranking: list[str] = []
            weight_conf = voter_weights.get(voter.name, 1.0)
            if isinstance(result, dict):
                r = result.get("ranking")
                if isinstance(r, list) and r:
                    ranking = [str(x) for x in r]
                elif result.get("choice"):
                    ranking = [str(result["choice"])]
                weight_conf *= float(result.get("confidence", 1.0))
            elif isinstance(result, str):
                ranking = [result]
            if ranking:
                raw_ballots[voter.name] = (ranking, weight_conf)
        all_candidates = sorted({
            c for ranking, _ in raw_ballots.values() for c in ranking
        })
        if not all_candidates:
            return Verdict(
                scheme=scheme, winner=None, confidence=0.0,
                tallies={}, ballots=ballots,
            )
        N = len(all_candidates)
        tallies: dict[str, float] = defaultdict(float)
        for ranking, w in raw_ballots.values():
            for k, c in enumerate(ranking):
                tallies[c] += (N - k - 1) * w
        ordered = sorted(
            tallies.keys(), key=lambda k: (-tallies[k], k),
        )
        winner = ordered[0]
        total = sum(tallies.values())
        confidence = tallies[winner] / total if total > 0 else 0.0
        return Verdict(
            scheme=scheme, winner=winner,
            confidence=confidence, tallies=dict(tallies),
            ballots=ballots, unanimous=False,
        )


def verdict_margin(verdict: Verdict) -> float:
    """Gap between winner and runner-up (0 if only one candidate)."""
    if not verdict.tallies or verdict.winner is None:
        return 0.0
    sorted_vals = sorted(verdict.tallies.values(), reverse=True)
    if len(sorted_vals) < 2:
        return 0.0
    return float(sorted_vals[0] - sorted_vals[1])
