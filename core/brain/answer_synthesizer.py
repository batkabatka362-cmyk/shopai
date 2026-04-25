"""Answer synthesizer — compose owner-facing answers from sources.

Owners ask 'should I scale this audio launch?'. Good answers
weave together: policy library matches, recent reward-model
signal, relevant search hits, and any caveats from the ethics
gate or drift detector. explanation_aggregator (v12-D6) composes
the post-decision rationale. answer_synthesizer handles the
*pre-decision* question: owner asked, synthesise the evidence.

Pure stdlib. No LLM. Accepts already-prepared evidence bundles
so the caller wires in search_index, policy_library, reward_model,
etc. themselves; this layer is pure composition.

APIs:

  synthesize(question, bundle) → Answer
  bundle_builder()             → helper to populate a fresh Bundle

Answer carries:
  summary              — 1-2 sentence owner-facing line
  confidence           — 0-1 how well-supported the answer is
  supporting_points    — ordered list of Fact evidence items
  caveats              — warnings the owner should read
  suggested_follow_ups — questions the synthesizer raised but
                         couldn't fully resolve

Pure stdlib, deterministic; zero LLM (optional polisher hook).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass
class Fact:
    source: str                # policy | reward | search | rule | ontology
    text: str
    weight: float = 0.5        # 0..1 — how much this fact matters

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "text": self.text,
            "weight": round(self.weight, 3),
        }


@dataclass
class Bundle:
    facts: list[Fact] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    def add(
        self, source: str, text: str, weight: float = 0.5,
    ) -> None:
        if not text:
            return
        self.facts.append(Fact(
            source=source, text=text,
            weight=max(0.0, min(1.0, float(weight))),
        ))

    def caveat(self, text: str) -> None:
        if text:
            self.caveats.append(text)


@dataclass
class Answer:
    question: str
    summary: str
    confidence: float                  # 0..1
    supporting_points: list[Fact] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    suggested_follow_ups: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "summary": self.summary,
            "confidence": round(self.confidence, 3),
            "supporting_points": [
                f.as_dict() for f in self.supporting_points
            ],
            "caveats": list(self.caveats),
            "suggested_follow_ups": list(self.suggested_follow_ups),
        }


# ── Synthesizer ────────────────────────────────────────────

def bundle_builder() -> Bundle:
    return Bundle()


def synthesize(
    question: str,
    bundle: Bundle,
    *,
    top_facts: int = 3,
    polisher: Callable[[str], str] | None = None,
) -> Answer:
    question = (question or "").strip()
    if not question:
        return Answer(question="", summary="empty question",
                       confidence=0.0)
    facts = sorted(bundle.facts, key=lambda f: -f.weight)
    top = facts[:top_facts]
    summary = _summary(question, top, bundle.caveats)
    if polisher:
        try:
            polished = polisher(summary)
            if polished:
                summary = polished
        except Exception as exc:
            # Polisher is a best-effort wrap; fall back to the
            # plain summary if it raises.
            _ = exc
    follow_ups = _suggested_follow_ups(bundle)
    # Confidence: weighted mean of top facts discounted by caveats.
    if top:
        base = sum(f.weight for f in top) / len(top)
    else:
        base = 0.0
    caveat_penalty = min(0.4, 0.1 * len(bundle.caveats))
    confidence = max(0.0, min(1.0, base - caveat_penalty))
    return Answer(
        question=question,
        summary=summary,
        confidence=confidence,
        supporting_points=top,
        caveats=list(bundle.caveats),
        suggested_follow_ups=follow_ups,
    )


# ── Helpers ────────────────────────────────────────────────

def _summary(
    question: str, top: list[Fact], caveats: list[str],
) -> str:
    if not top:
        return f"No strong evidence found for: {question!r}"
    lead = ", ".join(
        f"{f.source}: {f.text[:60]}{'…' if len(f.text) > 60 else ''}"
        for f in top
    )
    tail = f"; caveats: {caveats[0]}" if caveats else ""
    return f"{question} — {lead}{tail}"


def _suggested_follow_ups(bundle: Bundle) -> list[str]:
    out: list[str] = []
    if not bundle.facts:
        out.append("Gather at least 3 supporting data points.")
    elif len(bundle.facts) < 3:
        out.append("Strengthen the case with more evidence.")
    sources = {f.source for f in bundle.facts}
    if "policy" not in sources:
        out.append("Check policy_library for matching strategies.")
    if "reward" not in sources:
        out.append("Query reward_model for owner-preference signal.")
    if bundle.caveats:
        out.append(
            "Address the flagged caveats before acting.",
        )
    return out[:5]
