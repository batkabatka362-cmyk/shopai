"""Self narrative — coherent 'who am I' summary for LLM prompts + reports.

LLMs perform much better with a stable self-description. Rather than
re-deriving it per call (expensive, inconsistent), we synthesise one
from what the brain already knows about itself:

  • competence_model   — strengths + weaknesses per task class
  • learning_curve     — whether we're improving or plateauing
  • owner_model        — the owner's preference mix
  • commitment_register— open promises
  • action_queue       — pending actions
  • memory stats       — size + health

Output is a structured Narrative with:

  • identity_line     — one-sentence self-description
  • strengths         — list of {task, win_rate}
  • weaknesses        — list of {task, win_rate}
  • owner_style       — a short style descriptor
  • pending_load      — (commitments, queued_actions)
  • markdown          — the whole thing as prompt-ready markdown
  • system_prompt     — minimal LLM-ready string

All inputs are dependency-injected callables so tests need no
singletons. Pure stdlib. Deterministic given inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("brain.self_narrative")


@dataclass
class Narrative:
    identity_line: str
    strengths: list[dict[str, Any]] = field(default_factory=list)
    weaknesses: list[dict[str, Any]] = field(default_factory=list)
    owner_style: str = ""
    pending_load: dict[str, int] = field(default_factory=dict)
    markdown: str = ""
    system_prompt: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "identity_line": self.identity_line,
            "strengths": list(self.strengths),
            "weaknesses": list(self.weaknesses),
            "owner_style": self.owner_style,
            "pending_load": dict(self.pending_load),
            "markdown": self.markdown,
            "system_prompt": self.system_prompt,
        }


# ── Owner-style descriptor ───────────────────────────────

def _style_from_weights(weights: dict[str, float] | None) -> str:
    if not weights:
        return "unknown"
    roas = float(weights.get("roas", 0.25))
    refund = float(weights.get("refund_rate", 0.25))
    cost = float(weights.get("cost", 0.25))
    stability = float(weights.get("stability", 0.25))
    dominant = max(
        (
            ("growth-first", roas),
            ("quality-first", refund),
            ("cost-averse", cost),
            ("stability-first", stability),
        ),
        key=lambda kv: kv[1],
    )
    return dominant[0]


# ── Compose ───────────────────────────────────────────────

def compose(
    *,
    task_strengths: list[dict[str, Any]] | None = None,
    task_weaknesses: list[dict[str, Any]] | None = None,
    owner_weights: dict[str, float] | None = None,
    learning_trends: list[dict[str, Any]] | None = None,
    pending_load: dict[str, int] | None = None,
    memory_size: int | None = None,
) -> Narrative:
    """Pure composition — never touches a singleton."""
    strengths = list(task_strengths or [])
    weaknesses = list(task_weaknesses or [])
    owner_style = _style_from_weights(owner_weights)
    load = dict(pending_load or {})

    identity_parts = ["ShopAI commerce executor"]
    if owner_style != "unknown":
        identity_parts.append(f"{owner_style} owner")
    if strengths:
        top = strengths[0]
        identity_parts.append(
            f"best at {top.get('task_class', '?')}",
        )
    if weaknesses:
        worst = weaknesses[0]
        identity_parts.append(
            f"weakest at {worst.get('task_class', '?')}",
        )
    identity_line = " · ".join(identity_parts)

    # Improvement signal
    trend_parts: list[str] = []
    improving = sum(
        1 for t in (learning_trends or [])
        if t.get("trend") == "improving"
    )
    regressing = sum(
        1 for t in (learning_trends or [])
        if t.get("trend") == "regressing"
    )
    if improving:
        trend_parts.append(f"{improving} metric(s) improving")
    if regressing:
        trend_parts.append(f"{regressing} metric(s) regressing")

    lines = [f"# {identity_line}", ""]

    if owner_style != "unknown":
        lines.append(f"**Owner style**: {owner_style}")

    if strengths:
        lines.append("\n## Strengths")
        for s in strengths[:5]:
            lines.append(
                f"- {s.get('task_class', '?')} "
                f"(win_rate {s.get('success_rate', 0):.2f}, "
                f"n={s.get('uses', 0)})"
            )
    if weaknesses:
        lines.append("\n## Weaknesses")
        for w in weaknesses[:5]:
            lines.append(
                f"- {w.get('task_class', '?')} "
                f"(win_rate {w.get('success_rate', 0):.2f}, "
                f"n={w.get('uses', 0)})"
            )
    if trend_parts:
        lines.append("\n## Trends")
        for t in trend_parts:
            lines.append(f"- {t}")
    if load:
        lines.append("\n## Pending load")
        for k, v in sorted(load.items()):
            lines.append(f"- {k}: {v}")
    if memory_size is not None:
        lines.append(f"\n**Memory size**: {memory_size} records")

    markdown = "\n".join(lines).strip()

    # System prompt — tighter, suitable for LLM call
    prompt_bits = [identity_line]
    if owner_style != "unknown":
        prompt_bits.append(f"Owner prefers {owner_style} decisions.")
    if strengths:
        top_strengths = ", ".join(
            s.get("task_class", "?") for s in strengths[:3]
        )
        prompt_bits.append(
            f"I'm proven at: {top_strengths}."
        )
    if weaknesses:
        weak = ", ".join(
            w.get("task_class", "?") for w in weaknesses[:3]
        )
        prompt_bits.append(
            f"I defer on: {weak}."
        )
    system_prompt = " ".join(prompt_bits).strip()

    return Narrative(
        identity_line=identity_line,
        strengths=strengths,
        weaknesses=weaknesses,
        owner_style=owner_style,
        pending_load=load,
        markdown=markdown,
        system_prompt=system_prompt,
    )


# ── Injectable synthesiser (testable) ────────────────────

class SelfNarrator:
    def __init__(
        self,
        *,
        competence_provider: Callable[[], dict[str, list[dict[str, Any]]]]
            | None = None,
        owner_weights_provider: Callable[[], dict[str, float]]
            | None = None,
        learning_provider: Callable[[], list[dict[str, Any]]]
            | None = None,
        load_provider: Callable[[], dict[str, int]]
            | None = None,
        memory_size_provider: Callable[[], int]
            | None = None,
    ) -> None:
        self._competence = competence_provider
        self._owner = owner_weights_provider
        self._learning = learning_provider
        self._load = load_provider
        self._memory_size = memory_size_provider

    def _safe(self, fn, default):
        if fn is None:
            return default
        try:
            return fn()
        except Exception as exc:
            logger.debug("self_narrative provider failed: %s", exc)
            return default

    def narrate(self) -> Narrative:
        sw = self._safe(self._competence, {})
        strengths = sw.get("strengths", []) if isinstance(sw, dict) else []
        weaknesses = sw.get("weaknesses", []) if isinstance(sw, dict) else []
        weights = self._safe(self._owner, {})
        trends = self._safe(self._learning, [])
        load = self._safe(self._load, {})
        size = self._safe(self._memory_size, None)
        return compose(
            task_strengths=strengths,
            task_weaknesses=weaknesses,
            owner_weights=weights,
            learning_trends=trends,
            pending_load=load,
            memory_size=size,
        )
