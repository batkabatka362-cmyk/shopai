"""Multi-agent debate — 5-persona proposal arbitration.

Wave 2 #8 closes the "no self-critique / single-voice
decision" gap. Every pre-execution decision already runs
through :class:`core.judgment.judgment_advisor.JudgmentAdvisor`
which produces a risk score. When that score is either clearly
safe (< ``PROCEED_THRESHOLD``) or clearly dangerous (>=
``DELAY_THRESHOLD``) a single-voice verdict is fine — the
signal is unambiguous.

The interesting band is the middle: ``[PROCEED_THRESHOLD,
DELAY_THRESHOLD]``. That's where human teams would normally
pause, debate, and pick. Wave 2 #8 wires the same pause into
the brain by spinning up five light-weight personas, asking
each for a proposal dict, and scoring the proposals against
the operator's :class:`core.mentality.Values` to pick a
winner. No LLM calls, no network — the personas are plain
Python strategies that emit a dict describing their preferred
course of action.

The five personas
-----------------

* **Analyzer** — "what does the data say?" Emits a
  conservative proposal anchored in the supplied context
  facts.
* **Planner** — "what sequence of steps minimises surprise?"
  Builds a multi-step proposal with rollback fallbacks.
* **Executor** — "ship it" Bias toward action; favours speed
  over exhaustive analysis.
* **Critic** — "what could go wrong?" Emits a proposal that
  surfaces the biggest objection and proposes a mitigation.
* **MemoryManager** — "have we seen this before?" Pulls
  precedent from prior decisions via the UnifiedMemory
  retrieve path.

Each persona is a callable that receives a
:class:`DebateContext` and returns a :class:`Proposal`. The
:class:`DebateArbiter` runs every persona, scores their
proposals with :meth:`core.mentality.Values.score`, and picks
the highest-scoring proposal. In the event of a tie the
tiebreaker is persona priority (Critic > Analyzer > Planner >
Executor > MemoryManager) so safety-oriented voices win ties
by default.

Integration contract
--------------------

``JudgmentAdvisor`` stays untouched. A caller that wants to
use debate wraps an advisor verdict::

    advisor = JudgmentAdvisor(values=...)
    result = advisor.evaluate(decision, situation)
    if should_debate(result["risk_score"]):
        debate = DebateArbiter(values=advisor._values or Values())
        outcome = debate.run(DebateContext(
            decision=decision, situation=situation,
            advisor_result=result,
        ))
        chosen = outcome.winner

The ``should_debate`` helper encodes the advisor's existing
threshold constants so callers don't have to hard-code them.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from core.judgment.judgment_advisor import (
    DELAY_THRESHOLD,
    PROCEED_THRESHOLD,
)
from core.mentality import Values
from utils.logger import get_logger

logger = get_logger("brain.debate")


# ---------------------------------------------------------------------------
# Context / proposal / outcome
# ---------------------------------------------------------------------------


@dataclass
class DebateContext:
    """Everything a persona needs to form a proposal.

    ``advisor_result`` is the full dict from
    :meth:`JudgmentAdvisor.evaluate` so personas can use the
    check breakdown when shaping their argument; it's optional
    for tests that want to run debate without the advisor.
    """

    decision:         dict[str, Any]
    situation:        dict[str, Any] = field(default_factory=dict)
    advisor_result:   dict[str, Any] = field(default_factory=dict)
    memories:         list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Proposal:
    """A single persona's proposed course of action.

    Proposals carry a free-form ``action_patch`` (diff on top
    of the original decision) plus per-principle attribute
    scores in ``[0, 1]`` which the arbiter feeds into
    :meth:`Values.score`. Missing principle keys score zero
    for that dimension, so a persona that genuinely doesn't
    care about "speed" can safely omit it.
    """

    persona:       str
    summary:       str
    action_patch:  dict[str, Any] = field(default_factory=dict)
    principles:    dict[str, float] = field(default_factory=dict)
    confidence:    float = 0.5
    rationale:     str = ""

    def as_option(self) -> dict[str, Any]:
        """Return the principle dict for :meth:`Values.score`."""
        return dict(self.principles)


@dataclass
class DebateOutcome:
    """Result of running the five personas through the arbiter."""

    winner:       Proposal
    scored:       list[tuple[Proposal, float]]
    triggered:    bool  # whether debate ran (vs a short-circuit)
    risk_score:   float = 0.0
    proposals:    int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "winner_persona": self.winner.persona,
            "winner_summary": self.winner.summary,
            "scored":         [
                {
                    "persona":    p.persona,
                    "score":      s,
                    "confidence": p.confidence,
                }
                for p, s in self.scored
            ],
            "triggered":      self.triggered,
            "risk_score":     self.risk_score,
            "proposals":      self.proposals,
        }


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------


PersonaFn = Callable[[DebateContext], Proposal]


def analyzer(ctx: DebateContext) -> Proposal:
    """Conservative, data-driven voice."""
    signals = _count_signals(ctx.situation)
    return Proposal(
        persona="Analyzer",
        summary="anchor on observed data, shrink the action if signals are weak",
        action_patch={"mode": "measured"},
        principles={
            "safety":      0.8,
            "reliability": 0.85,
            "long_term":   0.7,
            "speed":       0.3,
            "short_term":  0.4,
        },
        confidence=min(1.0, 0.5 + signals * 0.1),
        rationale=f"observed {signals} signal(s) in situation context",
    )


def planner(ctx: DebateContext) -> Proposal:
    """Staged-rollout voice with fallback plans."""
    return Proposal(
        persona="Planner",
        summary="split the action into gated phases with rollback points",
        action_patch={
            "mode": "phased",
            "rollback_ready": True,
        },
        principles={
            "safety":      0.75,
            "reliability": 0.9,
            "long_term":   0.8,
            "automation":  0.7,
            "speed":       0.4,
        },
        confidence=0.7,
        rationale="phased rollout maximises reliability at the cost of speed",
    )


def executor(ctx: DebateContext) -> Proposal:
    """Bias-to-action voice."""
    return Proposal(
        persona="Executor",
        summary="ship the action now; learn from the outcome",
        action_patch={"mode": "ship"},
        principles={
            "safety":      0.4,
            "reliability": 0.5,
            "speed":       0.95,
            "short_term":  0.9,
            "automation":  0.8,
            "long_term":   0.3,
        },
        confidence=0.6,
        rationale="speed of iteration compounds; delay has opportunity cost",
    )


def critic(ctx: DebateContext) -> Proposal:
    """Find the biggest hole and propose a mitigation."""
    risk = float(ctx.advisor_result.get("risk_score", 0.0) or 0.0)
    top_concern = "general risk"
    checks = ctx.advisor_result.get("checks") or []
    if checks:
        # The highest-score check is the biggest concern.
        worst = max(checks, key=lambda c: c.get("score", 0))
        top_concern = worst.get("name", top_concern)
    return Proposal(
        persona="Critic",
        summary=f"escalate review of {top_concern} before any execution",
        action_patch={
            "mode": "review",
            "escalate": True,
            "concern": top_concern,
        },
        principles={
            "safety":      0.95,
            "reliability": 0.85,
            "long_term":   0.85,
            "short_term":  0.2,
            "speed":       0.1,
        },
        confidence=min(1.0, 0.5 + risk),
        rationale=f"advisor risk_score={risk:.2f}, concern={top_concern}",
    )


def memory_manager(ctx: DebateContext) -> Proposal:
    """Pattern-match on prior decisions."""
    n = len(ctx.memories or [])
    successes = sum(
        1 for m in (ctx.memories or [])
        if isinstance(m, dict) and m.get("success")
    )
    ratio = successes / n if n else 0.5
    return Proposal(
        persona="MemoryManager",
        summary=(
            f"prior cases: {successes}/{n} succeeded "
            f"({ratio:.0%})"
        ),
        action_patch={"mode": "precedent", "precedent_success_rate": ratio},
        principles={
            "safety":      0.6 + 0.2 * ratio,
            "reliability": 0.6 + 0.2 * ratio,
            "long_term":   0.7,
            "speed":       0.4,
            "automation":  0.7,
        },
        confidence=min(1.0, 0.3 + 0.1 * n),
        rationale=f"n={n} matching precedents, ratio={ratio:.2f}",
    )


# Persona priority for tie-breaking — lower index wins ties.
_PERSONA_PRIORITY = ["Critic", "Analyzer", "Planner", "MemoryManager", "Executor"]


def _count_signals(situation: dict[str, Any]) -> int:
    """Count non-empty top-level keys on the situation dict."""
    if not isinstance(situation, dict):
        return 0
    return sum(1 for v in situation.values() if v)


# ---------------------------------------------------------------------------
# Arbiter
# ---------------------------------------------------------------------------


_DEFAULT_PERSONAS: tuple[PersonaFn, ...] = (
    analyzer, planner, executor, critic, memory_manager,
)


def should_debate(
    risk_score: float,
    *,
    lower: float = PROCEED_THRESHOLD,
    upper: float = DELAY_THRESHOLD,
) -> bool:
    """Return True if the score sits in the debate band.

    ``risk_score`` here follows the advisor's convention
    (``0`` = safe, ``1`` = unsafe). The band
    ``[lower, upper]`` defaults to the existing advisor
    thresholds (0.70, 0.85). Edge values fall *inside* the
    band so a score exactly at lower or upper triggers debate —
    the safer default.
    """
    return lower <= float(risk_score) <= upper


class DebateArbiter:
    """Runs personas, scores their proposals, picks a winner.

    Thread-safe (a single lock guards the persona list and
    optional memory hook).

    Parameters
    ----------
    values :
        :class:`Values` instance used to score each proposal
        via :meth:`Values.score`. Required — the whole point
        of debate is to favour the operator's principles, so
        missing values defaults to neutral ``Values()``.
    personas :
        Override the default 5-persona lineup. Mostly for
        tests; production should use the defaults.
    """

    def __init__(
        self,
        *,
        values: Values | None = None,
        personas: Iterable[PersonaFn] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._values = values or Values()
        self._personas: list[PersonaFn] = (
            list(personas) if personas is not None else list(_DEFAULT_PERSONAS)
        )

    def add_persona(self, persona: PersonaFn) -> None:
        with self._lock:
            self._personas.append(persona)

    def personas(self) -> list[str]:
        with self._lock:
            return [getattr(p, "__name__", repr(p)) for p in self._personas]

    def run(
        self,
        context: DebateContext,
    ) -> DebateOutcome:
        """Run every persona and pick the best proposal.

        Personas that raise are logged and skipped so a buggy
        strategy can't sink the whole debate.
        """
        with self._lock:
            personas = list(self._personas)

        proposals: list[Proposal] = []
        for p in personas:
            try:
                proposal = p(context)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "debate: persona %s raised %s: %s",
                    getattr(p, "__name__", p), type(exc).__name__, exc,
                )
                continue
            if proposal is None:
                continue
            proposals.append(proposal)

        if not proposals:
            raise RuntimeError("DebateArbiter: no valid proposals produced")

        scored: list[tuple[Proposal, float]] = [
            (pr, self._values.score(pr.as_option()))
            for pr in proposals
        ]

        def _tiebreak_key(item: tuple[Proposal, float]) -> tuple[float, int]:
            pr, sc = item
            # Sort by score descending, then by priority ascending
            try:
                prio = _PERSONA_PRIORITY.index(pr.persona)
            except ValueError:
                prio = len(_PERSONA_PRIORITY)
            return (-sc, prio)

        scored.sort(key=_tiebreak_key)
        winner = scored[0][0]

        risk = float(context.advisor_result.get("risk_score", 0.0) or 0.0)
        return DebateOutcome(
            winner=winner,
            scored=scored,
            triggered=True,
            risk_score=risk,
            proposals=len(proposals),
        )


__all__ = [
    "DebateArbiter",
    "DebateContext",
    "DebateOutcome",
    "Proposal",
    "analyzer",
    "planner",
    "executor",
    "critic",
    "memory_manager",
    "should_debate",
]
