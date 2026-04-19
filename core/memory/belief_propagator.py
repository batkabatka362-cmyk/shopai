"""Belief propagator — Bayesian merge of conflicting claims.

knowledge_validator flags conflicts; trust_calibrator ranks sources.
belief_propagator is the consumer that *fuses* a contested fact into
a single probabilistic belief.

Given claims on the same (subject, predicate) from multiple sources:

    [
      Claim(subject="p1", predicate="price", value=29.99,
            source="shopify", confidence=0.9),
      Claim(subject="p1", predicate="price", value=30.49,
            source="autods",  confidence=0.7),
      Claim(subject="p1", predicate="price", value=29.99,
            source="manual",  confidence=0.8),
    ]

Returns a ``Belief`` with:

  • value       — the most-supported value
  • probability — posterior weight of that value vs alternatives
  • support     — list of (value, total_weight, sources) per candidate
  • verdict     — "confident" | "ambiguous" | "conflicted" | "unknown"

Weights combine: source ``confidence`` × optional ``trust(source)``
lookup (inject any callable: typically trust_calibrator.trust).

Pure stdlib. Deterministic. Zero external dependencies.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("memory.belief_propagator")


Verdict = Literal["confident", "ambiguous", "conflicted", "unknown"]


@dataclass
class Claim:
    subject: str
    predicate: str
    value: Any
    source: str
    confidence: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "value": self.value,
            "source": self.source,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class Belief:
    subject: str
    predicate: str
    value: Any
    probability: float
    verdict: Verdict
    support: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "value": self.value,
            "probability": round(self.probability, 4),
            "verdict": self.verdict,
            "support": list(self.support),
        }


def _value_key(value: Any) -> str:
    """Canonical key so floats with tiny drift land in same bucket."""
    if isinstance(value, float):
        return f"{round(value, 6)}"
    if isinstance(value, (list, tuple)):
        return str(tuple(_value_key(v) for v in value))
    if isinstance(value, dict):
        return str(sorted((k, _value_key(v)) for k, v in value.items()))
    return str(value)


# ── Engine ────────────────────────────────────────────────

class BeliefPropagator:
    """Stateless merge function — fresh per call so callers can tune
    the trust lookup independently."""

    def __init__(
        self,
        *,
        confident_threshold: float = 0.75,
        ambiguous_threshold: float = 0.55,
    ) -> None:
        if not 0 < ambiguous_threshold <= confident_threshold <= 1:
            raise ValueError(
                "thresholds must satisfy "
                "0 < ambiguous ≤ confident ≤ 1",
            )
        self._confident_threshold = float(confident_threshold)
        self._ambiguous_threshold = float(ambiguous_threshold)

    # ── Merge ────────────────────────────────────────────

    def merge(
        self,
        claims: Iterable[Claim | dict[str, Any]],
        *,
        trust_fn: Callable[[str], float] | None = None,
    ) -> Belief | None:
        coerced: list[Claim] = []
        for c in claims:
            if isinstance(c, Claim):
                coerced.append(c)
            elif isinstance(c, dict):
                try:
                    coerced.append(Claim(
                        subject=str(c["subject"]),
                        predicate=str(c["predicate"]),
                        value=c["value"],
                        source=str(c.get("source", "unknown")),
                        confidence=float(c.get("confidence", 1.0)),
                    ))
                except (KeyError, TypeError, ValueError) as exc:
                    logger.debug(
                        "claim coerce skipped: %s", exc,
                    )
                    continue
        if not coerced:
            return None

        subject = coerced[0].subject
        predicate = coerced[0].predicate
        # Enforce same subject/predicate per merge call.
        for c in coerced:
            if c.subject != subject or c.predicate != predicate:
                raise ValueError(
                    "all claims must share subject+predicate",
                )

        # Weight each claim and bucket by canonicalised value.
        buckets: dict[str, list[Claim]] = defaultdict(list)
        weights: dict[str, float] = defaultdict(float)
        values: dict[str, Any] = {}
        for c in coerced:
            key = _value_key(c.value)
            buckets[key].append(c)
            values[key] = c.value
            conf = max(0.0, min(1.0, float(c.confidence)))
            trust = 1.0
            if trust_fn is not None:
                try:
                    trust = max(0.0, min(1.0, float(trust_fn(c.source))))
                except Exception as exc:
                    logger.debug(
                        "trust_fn raised for %s: %s",
                        c.source, exc,
                    )
                    trust = 1.0
            weights[key] += conf * trust

        total = sum(weights.values())
        if total <= 0:
            return Belief(
                subject=subject, predicate=predicate,
                value=None, probability=0.0,
                verdict="unknown",
            )

        # Rank candidate values by weight.
        ranked = sorted(
            weights.items(), key=lambda kv: -kv[1],
        )
        top_key, top_w = ranked[0]
        top_value = values[top_key]
        probability = top_w / total

        # Support breakdown for transparency.
        support: list[dict[str, Any]] = []
        for key, w in ranked:
            support.append({
                "value": values[key],
                "weight": round(w, 4),
                "sources": sorted(
                    {c.source for c in buckets[key]},
                ),
                "n": len(buckets[key]),
            })

        if probability >= self._confident_threshold:
            verdict: Verdict = "confident"
        elif probability >= self._ambiguous_threshold:
            verdict = "ambiguous"
        elif len(ranked) > 1:
            verdict = "conflicted"
        else:
            verdict = "unknown"

        return Belief(
            subject=subject,
            predicate=predicate,
            value=top_value,
            probability=probability,
            verdict=verdict,
            support=support,
        )

    # ── Batch ────────────────────────────────────────────

    def merge_batch(
        self,
        claims: Iterable[Claim | dict[str, Any]],
        *,
        trust_fn: Callable[[str], float] | None = None,
    ) -> list[Belief]:
        """Group claims by (subject, predicate) and merge each group."""
        by_sp: dict[tuple[str, str], list[Claim]] = defaultdict(list)
        for c in claims:
            if isinstance(c, Claim):
                by_sp[(c.subject, c.predicate)].append(c)
            elif isinstance(c, dict):
                try:
                    by_sp[(
                        str(c["subject"]), str(c["predicate"]),
                    )].append(Claim(
                        subject=str(c["subject"]),
                        predicate=str(c["predicate"]),
                        value=c["value"],
                        source=str(c.get("source", "unknown")),
                        confidence=float(c.get("confidence", 1.0)),
                    ))
                except (KeyError, TypeError, ValueError) as exc:
                    logger.debug(
                        "claim coerce skipped in batch: %s", exc,
                    )
                    continue
        out: list[Belief] = []
        for group in by_sp.values():
            belief = self.merge(group, trust_fn=trust_fn)
            if belief is not None:
                out.append(belief)
        return out
