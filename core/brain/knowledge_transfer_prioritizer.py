"""Knowledge transfer prioritizer — which learnings to push first.

multi_store federation can share rules/patterns/playbooks across
stores. Pushing *every* learning floods the channel. This module
ranks candidate learnings by expected value-if-adopted:

  • evidence_strength — how much evidence backs the learning
  • portability       — how generalisable (tied to niche vs universal)
  • novelty_to_peer   — how new it is at the target store
  • expected_lift     — predicted KPI improvement if adopted
  • source_trust      — trust of the emitting store

Output: ranked ``TransferCandidate`` list. Callers push the top-N to
the federation bus. Complements skill_transfer (which translates a
skill across domains) by answering *which skills to attempt first*.

Pure stdlib, deterministic.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.knowledge_transfer_prioritizer")


@dataclass
class TransferCandidate:
    id: str
    subject: str             # rule / pattern / playbook name
    source_store: str
    target_store: str
    evidence_strength: float  # 0..1
    portability: float        # 0..1
    novelty_to_peer: float    # 0..1
    expected_lift: float      # 0..1
    source_trust: float = 0.5

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "source_store": self.source_store,
            "target_store": self.target_store,
            "evidence_strength": round(
                self.evidence_strength, 4,
            ),
            "portability": round(self.portability, 4),
            "novelty_to_peer": round(self.novelty_to_peer, 4),
            "expected_lift": round(self.expected_lift, 4),
            "source_trust": round(self.source_trust, 4),
        }


@dataclass
class RankedCandidate:
    candidate: TransferCandidate
    score: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.as_dict(),
            "score": round(self.score, 4),
            "reason": self.reason,
        }


@dataclass
class TransferWeights:
    evidence: float = 0.30
    portability: float = 0.20
    novelty: float = 0.15
    lift: float = 0.25
    trust: float = 0.10

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence,
            "portability": self.portability,
            "novelty": self.novelty,
            "lift": self.lift,
            "trust": self.trust,
        }


def _validate(candidate: TransferCandidate) -> None:
    for name, val in (
        ("evidence_strength", candidate.evidence_strength),
        ("portability", candidate.portability),
        ("novelty_to_peer", candidate.novelty_to_peer),
        ("expected_lift", candidate.expected_lift),
        ("source_trust", candidate.source_trust),
    ):
        if not 0.0 <= val <= 1.0:
            raise ValueError(
                f"{name} must be in [0, 1]",
            )
    if not candidate.subject:
        raise ValueError("subject required")
    if not candidate.target_store:
        raise ValueError("target_store required")


class KnowledgeTransferPrioritizer:
    def __init__(
        self,
        *,
        weights: TransferWeights | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._weights = weights or TransferWeights()
        self._history: list[RankedCandidate] = []

    def weights(self) -> TransferWeights:
        with self._lock:
            return self._weights

    def set_weights(self, weights: TransferWeights) -> None:
        with self._lock:
            self._weights = weights

    # ── Rank ─────────────────────────────────────────────

    def rank(
        self,
        candidates: Iterable[TransferCandidate],
        *,
        top_k: int | None = None,
        min_score: float = 0.0,
    ) -> list[RankedCandidate]:
        weights = self.weights()
        ranked: list[RankedCandidate] = []
        for c in candidates:
            _validate(c)
            score = (
                weights.evidence * c.evidence_strength
                + weights.portability * c.portability
                + weights.novelty * c.novelty_to_peer
                + weights.lift * c.expected_lift
                + weights.trust * c.source_trust
            )
            if score < min_score:
                continue
            # Build reason from the two highest contributors
            contribs = [
                ("evidence",
                 weights.evidence * c.evidence_strength),
                ("portability",
                 weights.portability * c.portability),
                ("novelty",
                 weights.novelty * c.novelty_to_peer),
                ("lift",
                 weights.lift * c.expected_lift),
                ("trust",
                 weights.trust * c.source_trust),
            ]
            contribs.sort(key=lambda kv: -kv[1])
            reason = (
                f"top drivers: "
                f"{contribs[0][0]}({contribs[0][1]:.2f}), "
                f"{contribs[1][0]}({contribs[1][1]:.2f})"
            )
            ranked.append(RankedCandidate(
                candidate=c,
                score=score,
                reason=reason,
            ))
        ranked.sort(key=lambda r: -r.score)
        if top_k is not None:
            ranked = ranked[: max(1, int(top_k))]
        with self._lock:
            self._history.extend(ranked)
            if len(self._history) > 500:
                del self._history[
                    : len(self._history) - 500
                ]
        return ranked

    # ── Queries ──────────────────────────────────────────

    def recent(
        self, *, limit: int = 20,
    ) -> list[RankedCandidate]:
        with self._lock:
            return list(
                self._history[-max(1, int(limit)):],
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ranked_total": len(self._history),
                "weights": self._weights.as_dict(),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._history)
            self._history.clear()
        return n
