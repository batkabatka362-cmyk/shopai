"""Explanation aggregator — compose a single 'why' answer.

The brain leaves explanation trails in at least five places:

  • decision_trace    — evidence + verdict + confidence
  • inner_monologue   — step-by-step thought stream
  • policy_library    — which policy was matched, fit + track record
  • reward_model      — per-feature contribution to the chosen reward
  • ethics/envelope   — any clamps / blocks applied

Asking "why did you do that?" used to require pulling each by
hand and composing prose manually. ExplanationAggregator is the
single entry point:

  aggregate(decision_id=..., context=..., chosen_action=...,
            policies=[...], reward_contributions=[...])
    → Explanation(summary, highlights, sections[])

The output is serialisable (dashboard) AND renderable (owner
digest). The summary is one sentence, the highlights are the top
3 evidence items across modules, and the sections enumerate each
source's contribution in order.

Pure Python. No LLM. An optional ``polisher`` callable can wrap
the summary through an LLM for prose smoothing, but the baseline
output is already coherent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass
class Highlight:
    source: str                      # "policy" / "reward" / "trace" / ...
    text: str
    weight: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "text": self.text,
            "weight": round(self.weight, 3),
        }


@dataclass
class Section:
    title: str
    body: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "body": list(self.body)}


@dataclass
class Explanation:
    decision_id: str
    summary: str
    highlights: list[Highlight] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "summary": self.summary,
            "highlights": [h.as_dict() for h in self.highlights],
            "sections": [s.as_dict() for s in self.sections],
        }

    def to_markdown(self) -> str:
        lines = [f"## Why: {self.summary}", ""]
        if self.highlights:
            lines.append("**Highlights**")
            for h in self.highlights:
                lines.append(
                    f"- ({h.source}, weight {h.weight:.2f}) {h.text}",
                )
            lines.append("")
        for s in self.sections:
            lines.append(f"### {s.title}")
            if s.body:
                for line in s.body:
                    lines.append(f"- {line}")
            else:
                lines.append("  _(no data)_")
            lines.append("")
        return "\n".join(lines).strip()


# ── Aggregator ──────────────────────────────────────────────

def aggregate(
    *,
    decision_id: str,
    context: dict[str, Any] | None = None,
    chosen_action: dict[str, Any] | None = None,
    verdict: str = "",
    confidence: float = 0.0,
    evidence: Iterable[dict[str, Any]] | None = None,
    monologue_excerpts: Iterable[str] | None = None,
    policies: Iterable[dict[str, Any]] | None = None,
    reward_contributions: Iterable[dict[str, Any]] | None = None,
    violations: Iterable[dict[str, Any]] | None = None,
    envelope_clamps: Iterable[str] | None = None,
    polisher: Callable[[str], str] | None = None,
) -> Explanation:
    sections: list[Section] = []

    # Context section
    ctx = Section(title="Context")
    if context:
        for k, v in sorted(context.items()):
            ctx.body.append(f"{k}: {v}")
    sections.append(ctx)

    # Action + verdict
    outcome = Section(title="Decision")
    if verdict:
        outcome.body.append(f"verdict: {verdict}")
    if chosen_action:
        for k, v in sorted(chosen_action.items()):
            outcome.body.append(f"action.{k}: {v}")
    if confidence:
        outcome.body.append(f"confidence: {confidence:.2f}")
    sections.append(outcome)

    # Evidence from decision_trace
    ev_section = Section(title="Evidence")
    highlights: list[Highlight] = []
    if evidence:
        for item in evidence:
            kind = item.get("kind", "fact")
            weight = float(item.get("weight", 0))
            note = item.get("note", "")
            ev_section.body.append(f"[{kind}, w={weight:.2f}] {note}")
            highlights.append(Highlight(
                source=f"trace:{kind}",
                text=note or str(item.get("ref_id", "?")),
                weight=weight,
            ))
    sections.append(ev_section)

    # Policies
    pol_section = Section(title="Policies")
    if policies:
        for p in policies:
            name = p.get("name", "?")
            fit = float(p.get("fit", 0))
            score = float(p.get("score", 0))
            pol_section.body.append(
                f"{name}: fit {fit:.2f}, score {score:.2f}",
            )
            highlights.append(Highlight(
                source="policy",
                text=f"{name} (fit {fit:.2f})",
                weight=score,
            ))
    sections.append(pol_section)

    # Reward model contributions
    rew_section = Section(title="Reward model")
    if reward_contributions:
        for c in reward_contributions:
            feat = c.get("feature", "?")
            val = c.get("value", "?")
            llr = float(c.get("llr", 0))
            rew_section.body.append(
                f"{feat}={val} llr {llr:+.2f}",
            )
            highlights.append(Highlight(
                source="reward",
                text=f"{feat}={val}",
                weight=llr,
            ))
    sections.append(rew_section)

    # Ethics + envelope
    ethics_section = Section(title="Safety")
    if envelope_clamps:
        for clamp in envelope_clamps:
            ethics_section.body.append(f"clamp: {clamp}")
    if violations:
        for v in violations:
            ethics_section.body.append(
                f"violation: {v.get('rule')} "
                f"({v.get('severity')}) — {v.get('reason')}",
            )
            highlights.append(Highlight(
                source=f"ethics:{v.get('severity', '?')}",
                text=str(v.get("rule", "?")),
                weight=-1.0 if v.get("severity") == "hard" else -0.5,
            ))
    sections.append(ethics_section)

    # Monologue excerpts
    if monologue_excerpts:
        mono = Section(title="Inner thought")
        for excerpt in monologue_excerpts:
            mono.body.append(excerpt)
        sections.append(mono)

    # Top highlights: sort by absolute weight
    highlights.sort(key=lambda h: -abs(h.weight))
    top = highlights[:3]

    # Summary: first verdict + top highlight
    summary = _summary(verdict, confidence, top, violations or [])
    if polisher:
        try:
            polished = polisher(summary)
            if polished:
                summary = polished
        except Exception:
            pass

    return Explanation(
        decision_id=decision_id,
        summary=summary,
        highlights=top,
        sections=sections,
    )


def _summary(
    verdict: str, confidence: float,
    highlights: list[Highlight],
    violations: Iterable[dict[str, Any]],
) -> str:
    if verdict:
        root = f"{verdict}"
    else:
        root = "decision made"
    if confidence:
        root = f"{root} (confidence {confidence:.2f})"
    if highlights:
        bits = ", ".join(
            f"{h.source}:{h.text[:30]}" for h in highlights
        )
        root = f"{root} — because {bits}"
    vlist = list(violations)
    if any(v.get("severity") == "hard" for v in vlist):
        root = f"{root}; blocked by ethics"
    return root
