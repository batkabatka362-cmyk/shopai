"""Proposal arbiter — decide which pending revision to promote.

self_revision_journal piles up proposed edits to rules/skills/knobs/
narrative. A target can accumulate multiple proposals (each with its
own reason + evidence score). Left unchecked the journal grows; the
brain needs a single winner to *apply*.

Conflict_resolver already scores contradictory *rules*. Proposal
arbiter operates on *pending proposals vs the current live value*:

  • ``arbitrate(target, proposals, current_value)`` picks the best
  • Criteria: evidence_score, recency, new-value conservatism
    (prefer small deltas to large jumps), proposer reputation
  • Returns a ``ArbitrationOutcome`` with winner_id, verdict
    (accept | reject_all | defer), reason, and the *deltas* each
    proposal implies from the live value

Callers feed the winner to ``SelfRevisionJournal.accept(id)`` and
mark the remainder as ``reject``ed with a note. Defer means "not
enough evidence gap — wait another cycle".

Pure stdlib, deterministic, LLM-free.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.proposal_arbiter")


Verdict = Literal["accept", "reject_all", "defer"]


@dataclass
class Proposal:
    id: str
    target: str
    new_value: Any
    evidence_score: float     # 0..1
    proposer: str = ""        # "learning_loop" / "owner" / ...
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target": self.target,
            "new_value": self.new_value,
            "evidence_score": round(self.evidence_score, 4),
            "proposer": self.proposer,
            "ts": self.ts,
        }


@dataclass
class ArbitrationOutcome:
    target: str
    verdict: Verdict
    winner_id: str
    reason: str
    losers: list[str]
    scores: dict[str, float]
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "verdict": self.verdict,
            "winner_id": self.winner_id,
            "reason": self.reason,
            "losers": list(self.losers),
            "scores": {
                k: round(v, 4) for k, v in self.scores.items()
            },
            "ts": self.ts,
        }


@dataclass
class ArbiterWeights:
    evidence: float = 0.5
    recency: float = 0.2
    conservatism: float = 0.2
    reputation: float = 0.1

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence,
            "recency": self.recency,
            "conservatism": self.conservatism,
            "reputation": self.reputation,
        }


_DEFAULT_WEIGHTS = ArbiterWeights()
_DEFER_MARGIN = 0.05
_MIN_EVIDENCE_TO_ACCEPT = 0.3


def _conservatism_score(
    proposal: Proposal, current_value: Any,
) -> float:
    """1.0 = tiny delta; 0.0 = large delta.

    Only numeric deltas measured; for non-numeric we return 0.5
    (neutral).
    """
    try:
        a = float(current_value)
        b = float(proposal.new_value)
    except (TypeError, ValueError):
        return 0.5
    if a == 0 and b == 0:
        return 1.0
    denom = max(abs(a), abs(b), 1e-9)
    delta = abs(b - a) / denom
    return max(0.0, 1.0 - min(1.0, delta))


class ProposalArbiter:
    def __init__(
        self,
        *,
        weights: ArbiterWeights | None = None,
        reputations: dict[str, float] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._weights = weights or _DEFAULT_WEIGHTS
        self._reputations: dict[str, float] = dict(reputations or {})
        self._history: list[ArbitrationOutcome] = []

    def set_reputation(self, proposer: str, score: float) -> None:
        if not proposer:
            raise ValueError("proposer required")
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be in [0, 1]")
        with self._lock:
            self._reputations[proposer] = float(score)

    def reputation(self, proposer: str) -> float:
        with self._lock:
            return self._reputations.get(proposer, 0.5)

    # ── Arbitrate ────────────────────────────────────────

    def arbitrate(
        self,
        target: str,
        proposals: Iterable[Proposal],
        *,
        current_value: Any = None,
        now: float | None = None,
    ) -> ArbitrationOutcome:
        if not target:
            raise ValueError("target required")
        plist = [p for p in proposals if p.target == target]
        ts_now = float(now if now is not None else time.time())
        if not plist:
            out = ArbitrationOutcome(
                target=target,
                verdict="reject_all",
                winner_id="",
                reason="no proposals",
                losers=[],
                scores={},
                ts=ts_now,
            )
            with self._lock:
                self._history.append(out)
            return out
        weights = self._weights
        times = [p.ts for p in plist]
        newest = max(times) if times else ts_now
        oldest = min(times) if times else ts_now
        span = max(newest - oldest, 1.0)
        scores: dict[str, float] = {}
        for p in plist:
            recency = (
                (p.ts - oldest) / span if span > 0 else 1.0
            )
            conservatism = _conservatism_score(p, current_value)
            reputation = self.reputation(p.proposer)
            score = (
                weights.evidence * p.evidence_score
                + weights.recency * recency
                + weights.conservatism * conservatism
                + weights.reputation * reputation
            )
            scores[p.id] = score
        ranked = sorted(
            plist, key=lambda p: -scores[p.id],
        )
        winner = ranked[0]
        runner = ranked[1] if len(ranked) > 1 else None
        margin = (
            scores[winner.id] - scores[runner.id]
            if runner is not None else 1.0
        )
        if winner.evidence_score < _MIN_EVIDENCE_TO_ACCEPT:
            verdict: Verdict = "reject_all"
            reason = (
                f"all evidence_scores below "
                f"{_MIN_EVIDENCE_TO_ACCEPT}"
            )
            winner_id = ""
            losers = [p.id for p in plist]
        elif margin < _DEFER_MARGIN:
            verdict = "defer"
            reason = (
                f"top two within {_DEFER_MARGIN} — "
                f"need more evidence"
            )
            winner_id = ""
            losers = []
        else:
            verdict = "accept"
            reason = (
                f"winner margin={margin:.3f}; "
                f"evidence={winner.evidence_score:.2f}"
            )
            winner_id = winner.id
            losers = [p.id for p in plist if p.id != winner.id]
        outcome = ArbitrationOutcome(
            target=target,
            verdict=verdict,
            winner_id=winner_id,
            reason=reason,
            losers=losers,
            scores=scores,
            ts=ts_now,
        )
        with self._lock:
            self._history.append(outcome)
            if len(self._history) > 200:
                del self._history[: len(self._history) - 200]
        return outcome

    def recent(self, *, limit: int = 20) -> list[ArbitrationOutcome]:
        with self._lock:
            return list(self._history[-max(1, int(limit)):])

    def stats(self) -> dict[str, Any]:
        with self._lock:
            verdict_counts: dict[str, int] = {}
            for o in self._history:
                verdict_counts[o.verdict] = (
                    verdict_counts.get(o.verdict, 0) + 1
                )
            return {
                "arbitrations": len(self._history),
                "by_verdict": verdict_counts,
                "reputations": dict(self._reputations),
                "weights": self._weights.as_dict(),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._history)
            self._history.clear()
        return n
