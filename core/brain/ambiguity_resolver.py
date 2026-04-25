"""Ambiguity resolver — pick the best candidate interpretation.

When a signal is unclear (owner says "kill it", dialog_memory flags
an open pronoun; monitor fires but which sibling invariant is the
real cause?), callers can submit multiple candidate interpretations
and a set of evaluators. The resolver scores each candidate and
returns a ranked list with:

  • consistency      — does this interpretation agree with recent
                        context?
  • prior_likelihood — caller-supplied prior weight
  • evidence_support — sum of positive evaluator scores
  • cost_of_error    — penalty if this interpretation is wrong

The resolver is evaluator-agnostic: each evaluator is a callable
``(candidate) → float`` in [-1, 1]. The sign matters: -1 = strong
evidence *against*. Pure stdlib, deterministic, no LLM.

Typical use from dialog_memory open_intent:

    resolver.resolve([
        Candidate(key="kill_recent_audio_ads",
                  explanation="refers to ad_batch_42",
                  prior=0.6),
        Candidate(key="kill_the_winner",
                  explanation="owner may have meant the hero product",
                  prior=0.2),
    ], evaluators=[recent_context_evaluator, hot_topic_evaluator])
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.ambiguity_resolver")


@dataclass
class Candidate:
    key: str
    explanation: str = ""
    prior: float = 0.5
    cost_of_error: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("Candidate.key required")
        if not 0 <= self.prior <= 1:
            raise ValueError("prior must be 0..1")
        if self.cost_of_error < 0:
            raise ValueError("cost_of_error must be ≥ 0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "explanation": self.explanation,
            "prior": round(self.prior, 4),
            "cost_of_error": round(self.cost_of_error, 4),
            "metadata": dict(self.metadata),
        }


@dataclass
class ResolutionEntry:
    candidate: Candidate
    score: float
    prior_component: float
    evidence_component: float
    cost_penalty: float
    evaluator_notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.as_dict(),
            "score": round(self.score, 4),
            "prior_component": round(self.prior_component, 4),
            "evidence_component": round(self.evidence_component, 4),
            "cost_penalty": round(self.cost_penalty, 4),
            "evaluator_notes": list(self.evaluator_notes),
        }


@dataclass
class ResolutionReport:
    best: ResolutionEntry | None
    alternatives: list[ResolutionEntry] = field(default_factory=list)
    confident: bool = False
    explain: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "best": self.best.as_dict() if self.best else None,
            "alternatives": [e.as_dict() for e in self.alternatives],
            "confident": self.confident,
            "explain": self.explain,
        }


Evaluator = Callable[[Candidate], float]


class AmbiguityResolver:
    def __init__(
        self,
        *,
        prior_weight: float = 0.4,
        evidence_weight: float = 0.6,
        cost_weight: float = 0.1,
        confident_margin: float = 0.25,
    ) -> None:
        if prior_weight < 0 or evidence_weight < 0:
            raise ValueError("weights must be non-negative")
        if cost_weight < 0:
            raise ValueError("cost_weight must be non-negative")
        if confident_margin < 0:
            raise ValueError("confident_margin must be non-negative")
        self._prior_w = float(prior_weight)
        self._evidence_w = float(evidence_weight)
        self._cost_w = float(cost_weight)
        self._confident_margin = float(confident_margin)

    # ── Resolve ──────────────────────────────────────────

    def _evaluate(
        self,
        candidate: Candidate,
        evaluators: Iterable[Evaluator] | Iterable[tuple[str, Evaluator]],
    ) -> tuple[float, list[str]]:
        """Return (summed_evidence, notes) clipped to [-1, 1] per
        evaluator. Evaluators that raise contribute 0 with a note."""
        total = 0.0
        notes: list[str] = []
        for ev in evaluators:
            if isinstance(ev, tuple):
                name, fn = ev
            else:
                name, fn = getattr(ev, "__name__", "evaluator"), ev
            try:
                score = float(fn(candidate))
                score = max(-1.0, min(1.0, score))
            except Exception as exc:
                logger.debug(
                    "evaluator %s raised for %s: %s",
                    name, candidate.key, exc,
                )
                score = 0.0
                notes.append(f"{name}:error")
                total += score
                continue
            total += score
            notes.append(f"{name}:{score:+.3f}")
        return total, notes

    def resolve(
        self,
        candidates: Iterable[Candidate],
        *,
        evaluators: Iterable[Evaluator] | Iterable[tuple[str, Evaluator]] = (),
    ) -> ResolutionReport:
        cand_list = list(candidates)
        if not cand_list:
            return ResolutionReport(best=None, explain="no candidates")
        evaluator_list = list(evaluators or [])

        entries: list[ResolutionEntry] = []
        for c in cand_list:
            evidence_total, notes = self._evaluate(c, evaluator_list)
            prior_comp = self._prior_w * c.prior
            evidence_comp = self._evidence_w * evidence_total
            cost_pen = self._cost_w * c.cost_of_error
            score = prior_comp + evidence_comp - cost_pen
            entries.append(ResolutionEntry(
                candidate=c,
                score=score,
                prior_component=prior_comp,
                evidence_component=evidence_comp,
                cost_penalty=cost_pen,
                evaluator_notes=notes,
            ))

        entries.sort(key=lambda e: -e.score)
        best = entries[0]
        alternatives = entries[1:]
        confident = False
        explain_bits: list[str] = []
        if len(entries) == 1:
            confident = True
            explain_bits.append("sole candidate")
        else:
            runner_up = entries[1]
            margin = best.score - runner_up.score
            explain_bits.append(
                f"margin over runner-up: {margin:+.3f}",
            )
            confident = margin >= self._confident_margin
            if not confident:
                explain_bits.append(
                    "confidence below margin threshold — "
                    "ambiguity remains",
                )
        return ResolutionReport(
            best=best,
            alternatives=alternatives,
            confident=confident,
            explain="; ".join(explain_bits),
        )

    # ── Stats ────────────────────────────────────────────

    def config(self) -> dict[str, Any]:
        return {
            "prior_weight": self._prior_w,
            "evidence_weight": self._evidence_w,
            "cost_weight": self._cost_w,
            "confident_margin": self._confident_margin,
        }
