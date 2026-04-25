"""Coherence checker — flag reasoning that contradicts stored beliefs.

Large reasoning chains drift: a mid-chain claim can subtly contradict
a stored belief without the brain noticing. coherence_checker scans
every reasoning step against a registry of ``Belief`` statements and
returns a list of ``Contradiction`` findings.

A belief is:
  • predicate (e.g. "roas_above", "price_below")
  • subject   (e.g. "product_p1", "niche.pet")
  • polarity  ("asserts" | "denies")
  • evidence_score (0..1)

A reasoning step carries a predicate + subject claim. The checker
flags a contradiction when the *same* (predicate, subject) pair
appears with opposite polarity. Confidence weighting: a low-evidence
belief contradicting a high-confidence step is a weaker signal than
two equal-strength claims.

This module is used by decision_stack (post-deliberate stage) to
abort plans that mention "kill product X" when a stored belief says
"product X is winner". Pure stdlib, deterministic.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.coherence_checker")


Polarity = Literal["asserts", "denies"]


@dataclass
class Belief:
    id: str
    predicate: str
    subject: str
    polarity: Polarity
    evidence_score: float
    source: str = ""
    ts: float = 0.0

    def __post_init__(self) -> None:
        if self.polarity not in ("asserts", "denies"):
            raise ValueError(
                "polarity must be asserts|denies",
            )
        if not 0.0 <= self.evidence_score <= 1.0:
            raise ValueError(
                "evidence_score must be in [0, 1]",
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "predicate": self.predicate,
            "subject": self.subject,
            "polarity": self.polarity,
            "evidence_score": round(self.evidence_score, 4),
            "source": self.source,
            "ts": self.ts,
        }


@dataclass
class Claim:
    predicate: str
    subject: str
    polarity: Polarity
    confidence: float
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "predicate": self.predicate,
            "subject": self.subject,
            "polarity": self.polarity,
            "confidence": round(self.confidence, 4),
            "note": self.note,
        }


@dataclass
class Contradiction:
    belief: Belief
    claim: Claim
    severity: float               # 0..1
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "belief": self.belief.as_dict(),
            "claim": self.claim.as_dict(),
            "severity": round(self.severity, 4),
            "note": self.note,
        }


class CoherenceChecker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._beliefs: dict[str, Belief] = {}

    # ── Belief registry ──────────────────────────────────

    def assert_belief(
        self,
        *,
        predicate: str,
        subject: str,
        polarity: Polarity = "asserts",
        evidence_score: float = 0.6,
        source: str = "",
        ts: float | None = None,
    ) -> Belief:
        if not predicate:
            raise ValueError("predicate required")
        if not subject:
            raise ValueError("subject required")
        b = Belief(
            id=uuid.uuid4().hex,
            predicate=str(predicate),
            subject=str(subject),
            polarity=polarity,
            evidence_score=float(evidence_score),
            source=str(source or ""),
            ts=float(ts if ts is not None else time.time()),
        )
        with self._lock:
            # Collapse: single belief per (predicate, subject); new
            # write overwrites if evidence is at least as strong.
            existing = self._find_by_pair(b.predicate, b.subject)
            if existing is not None:
                if b.evidence_score >= existing.evidence_score:
                    del self._beliefs[existing.id]
                else:
                    return existing
            self._beliefs[b.id] = b
        return b

    def retract(self, belief_id: str) -> bool:
        with self._lock:
            return self._beliefs.pop(belief_id, None) is not None

    def _find_by_pair(
        self, predicate: str, subject: str,
    ) -> Belief | None:
        for b in self._beliefs.values():
            if (
                b.predicate == predicate
                and b.subject == subject
            ):
                return b
        return None

    # ── Checking ─────────────────────────────────────────

    def check(
        self, claims: Iterable[Claim],
    ) -> list[Contradiction]:
        out: list[Contradiction] = []
        with self._lock:
            beliefs = list(self._beliefs.values())
        for claim in claims:
            if not 0.0 <= claim.confidence <= 1.0:
                continue
            for belief in beliefs:
                if (
                    belief.predicate != claim.predicate
                    or belief.subject != claim.subject
                ):
                    continue
                if belief.polarity == claim.polarity:
                    continue
                severity = min(
                    belief.evidence_score, claim.confidence,
                )
                out.append(Contradiction(
                    belief=belief,
                    claim=claim,
                    severity=severity,
                    note=(
                        f"belief {belief.polarity} {belief.predicate}"
                        f"({belief.subject}) but claim "
                        f"{claim.polarity}"
                    ),
                ))
        out.sort(key=lambda c: -c.severity)
        return out

    def is_coherent(
        self, claims: Iterable[Claim],
        *,
        severity_floor: float = 0.3,
    ) -> bool:
        return not any(
            c.severity >= severity_floor for c in self.check(claims)
        )

    # ── Queries ──────────────────────────────────────────

    def beliefs(self) -> list[Belief]:
        with self._lock:
            return sorted(
                self._beliefs.values(),
                key=lambda b: (b.predicate, b.subject),
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_polarity: dict[str, int] = {}
            for b in self._beliefs.values():
                by_polarity[b.polarity] = (
                    by_polarity.get(b.polarity, 0) + 1
                )
            return {
                "beliefs": len(self._beliefs),
                "by_polarity": by_polarity,
                "predicates": sorted({
                    b.predicate for b in self._beliefs.values()
                }),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._beliefs)
            self._beliefs.clear()
        return n
