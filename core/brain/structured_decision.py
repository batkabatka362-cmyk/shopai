"""Five-pillar structured decision framework.

Owner specification (2026-04-21): every significant decision
ShopAI makes should pass through a structured "thinking"
pipeline rather than a flat rule+execute shortcut. The five
pillars are:

  1. **Outcome** — what useful result are we after? Why?
     How do we measure success?
  2. **Thinking directions** — generate MANY candidate
     directions, not just the obvious one. Deterministic by
     default; LLM optional for fuzzy divergence.
  3. **Constraints** — what do we HAVE to respect? Hard
     (money caps, legal, safety) vs soft (style, preference).
  4. **Refine + learn** — iterate. Score each direction
     against the outcome + constraints, refine the winner,
     record what worked for the next decision.
  5. **Self-awareness** — meta-check. Am I in a wrong loop?
     Plumbing vs capability ratio? Dollar distance? These
     are CLAUDE.md §4c.K questions expressed as data.

The module intentionally mirrors the discipline the owner
asked Claude (the agent) to apply on every commit this
session, so the same structure applies to ShopAI's runtime
decisions — the operator and the operated share a shape.

Design choices:

  * ONE module, FIVE dataclasses — readable + testable,
    callers don't have to chase imports.
  * Scorer is dependency-injected so the policy stays
    pluggable. Default scorer: linear combination of
    ``expected_value`` × ``confidence`` plus outcome bias,
    with hard-violation → score=-inf.
  * Pure stdlib. LLM-free by default. An optional
    ``scorer`` kwarg lets callers plug richer evaluators
    without touching this module.
  * Integrates with the existing rationale ledger via
    ``as_rationale_entries()`` so ``shopai explain``
    surfaces every pillar of the decision path without
    a separate store.

Nothing here deletes or replaces existing code. Callers
opt in by constructing a Deliberation before calling
their usual execute method.

Distinct from ``core/brain/deliberation.py`` (multi-agent
Bull/Bear/Judge debate) — that's about getting a better
answer to a single question; this is about structuring
the thinking pipeline around a decision.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


# ── Pillar 1 — Outcome ────────────────────────────────────


@dataclass
class OutcomeSpec:
    """What useful result do we want, and how do we know
    when we got it?

    Callers MUST fill ``what`` + ``why`` + ``measurable``.
    ``value_usd`` is an optional expected monetary impact
    used by the default scorer — zero means "not priced".
    """

    what: str
    why: str
    measurable: str
    value_usd: float = 0.0
    deadline_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.what.strip():
            raise ValueError("OutcomeSpec.what required")
        if not self.why.strip():
            raise ValueError("OutcomeSpec.why required")
        if not self.measurable.strip():
            raise ValueError(
                "OutcomeSpec.measurable required",
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "what": self.what,
            "why": self.why,
            "measurable": self.measurable,
            "value_usd": round(self.value_usd, 4),
            "deadline_s": round(self.deadline_s, 2),
        }


# ── Pillar 2 — Thinking directions ───────────────────────


@dataclass
class ThinkingDirection:
    """One candidate approach to the outcome. ``action`` is
    the concrete proposal; ``reasoning`` is the one-line
    explanation for why this direction is worth considering.
    """

    label: str
    action: dict[str, Any]
    reasoning: str
    expected_value: float = 0.0
    confidence: float = 0.5

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError(
                "ThinkingDirection.label required",
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be in [0, 1]",
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "action": dict(self.action),
            "reasoning": self.reasoning,
            "expected_value": round(
                self.expected_value, 4,
            ),
            "confidence": round(self.confidence, 4),
        }


# ── Pillar 3 — Constraints ───────────────────────────────


@dataclass
class Constraint:
    """Something we must respect. Hard violations disqualify
    a direction; soft violations penalise the score.

    ``evaluator`` is an optional function
    ``(direction) -> (satisfied, headroom, detail)``.
    Constraints without an evaluator are advisory (always
    satisfied with headroom=1.0) — useful for documenting
    intent without blocking.
    """

    name: str
    kind: str             # "hard" | "soft"
    reason: str
    evaluator: Any = None

    def __post_init__(self) -> None:
        if self.kind not in ("hard", "soft"):
            raise ValueError(
                "Constraint.kind must be hard or soft",
            )
        if not self.name.strip():
            raise ValueError("Constraint.name required")

    def evaluate(
        self, direction: "ThinkingDirection",
    ) -> tuple[bool, float, str]:
        fn = self.evaluator
        if fn is None:
            return (True, 1.0, "advisory")
        try:
            result = fn(direction)
        except Exception as exc:  # noqa: BLE001
            return (
                False, 0.0,
                f"evaluator raised: {exc}",
            )
        if (
            not isinstance(result, tuple)
            or len(result) != 3
        ):
            return (
                False, 0.0,
                "evaluator returned wrong shape",
            )
        satisfied, headroom, detail = result
        return (
            bool(satisfied),
            float(headroom),
            str(detail),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "reason": self.reason,
        }


# ── Pillar 4 — Refine step (scored iteration log) ────────


@dataclass
class RefineStep:
    """One iteration of the refine loop."""

    iteration: int
    direction_label: str
    score: float
    hard_violations: tuple[str, ...] = ()
    soft_penalties: float = 0.0
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "direction_label": self.direction_label,
            "score": (
                round(self.score, 4)
                if math.isfinite(self.score)
                else str(self.score)
            ),
            "hard_violations": list(
                self.hard_violations,
            ),
            "soft_penalties": round(
                self.soft_penalties, 4,
            ),
            "note": self.note,
        }


# ── Pillar 5 — Self-awareness ────────────────────────────


@dataclass
class SelfAwareness:
    """Meta-cognitive flags. CLAUDE.md §4c.K wrong-loop
    detector expressed as data so auditors can see whether
    the decision was strategically sound, not just locally
    optimal."""

    loop_check: str
    dollar_distance: int
    plumbing_vs_capability: str
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.loop_check not in (
            "aligned", "plumbing", "off-mission",
        ):
            raise ValueError(
                "loop_check must be aligned / "
                "plumbing / off-mission",
            )
        if self.plumbing_vs_capability not in (
            "plumbing", "capability", "balanced",
        ):
            raise ValueError(
                "plumbing_vs_capability must be "
                "plumbing / capability / balanced",
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "loop_check": self.loop_check,
            "dollar_distance": int(self.dollar_distance),
            "plumbing_vs_capability": (
                self.plumbing_vs_capability
            ),
            "notes": list(self.notes),
        }


# ── Aggregate — the Deliberation record ──────────────────


@dataclass
class Deliberation:
    """All five pillars for one decision, plus the chosen
    direction (or None if nothing scored above a viable
    threshold)."""

    outcome: OutcomeSpec
    directions: tuple[ThinkingDirection, ...]
    constraints: tuple[Constraint, ...]
    refines: tuple[RefineStep, ...]
    awareness: SelfAwareness
    decision: ThinkingDirection | None = None
    created_ts: float = 0.0
    # Audit + learn loop: caller links a decision_id so
    # observed outcomes (e.g. an order_paid webhook for
    # the launched product) can back-fill the actual
    # measured value via :func:`record_outcome_for_decision`.
    # The owner reads the predicted-vs-observed pair via
    # MCP ``recent_deliberations`` to spot drift.
    decision_id: str = ""
    observation: dict[str, Any] = field(
        default_factory=dict,
    )
    observed_ts: float = 0.0

    def best_direction(self) -> ThinkingDirection | None:
        if not self.refines:
            return None
        viable = [
            r for r in self.refines
            if not r.hard_violations
            and math.isfinite(r.score)
        ]
        if not viable:
            return None
        winner = max(viable, key=lambda r: r.score)
        for d in self.directions:
            if d.label == winner.direction_label:
                return d
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.as_dict(),
            "directions": [
                d.as_dict() for d in self.directions
            ],
            "constraints": [
                c.as_dict() for c in self.constraints
            ],
            "refines": [
                r.as_dict() for r in self.refines
            ],
            "awareness": self.awareness.as_dict(),
            "decision": (
                self.decision.as_dict()
                if self.decision else None
            ),
            "created_ts": self.created_ts,
            "decision_id": self.decision_id,
            "observation": dict(self.observation),
            "observed_ts": self.observed_ts,
        }

    def as_rationale_entries(self) -> list[dict[str, Any]]:
        """Shape for rationale_ledger.add() calls so every
        pillar is visible in ``shopai explain <id>``."""
        entries: list[dict[str, Any]] = []
        entries.append({
            "kind": "goal",
            "headline": (
                f"outcome: {self.outcome.what} "
                f"(target: {self.outcome.measurable})"
            ),
            "weight": 1.0,
        })
        for d in self.directions:
            entries.append({
                "kind": "option",
                "headline": (
                    f"direction[{d.label}]: "
                    f"{d.reasoning}"
                ),
                "weight": round(float(d.confidence), 2),
            })
        for c in self.constraints:
            entries.append({
                "kind": "constraint",
                "headline": (
                    f"{c.kind}:{c.name} — {c.reason}"
                ),
                "weight": 0.9 if c.kind == "hard" else 0.4,
            })
        if self.decision is not None:
            entries.append({
                "kind": "gate",
                "headline": (
                    f"chose {self.decision.label}"
                ),
                "weight": 1.0,
            })
        entries.append({
            "kind": "meta",
            "headline": (
                f"self-check: "
                f"loop={self.awareness.loop_check} "
                f"dollar_distance="
                f"{self.awareness.dollar_distance} "
                f"{self.awareness.plumbing_vs_capability}"
            ),
            "weight": 0.5,
        })
        return entries


# ── Default scorer ───────────────────────────────────────


def default_scorer(
    direction: ThinkingDirection,
    outcome: OutcomeSpec,
    constraints: tuple[Constraint, ...],
) -> tuple[float, tuple[str, ...], float]:
    """Linear scorer. Hard violation → -inf so it never
    wins. Soft violation subtracts its deficit from the
    score. ``outcome.value_usd`` biases toward high-$ goals.
    """
    hard_violations: list[str] = []
    soft_penalty = 0.0
    for c in constraints:
        satisfied, headroom, _ = c.evaluate(direction)
        if not satisfied:
            if c.kind == "hard":
                hard_violations.append(c.name)
            else:
                soft_penalty += max(
                    0.0, 1.0 - float(headroom),
                )
    if hard_violations:
        return (
            -math.inf,
            tuple(hard_violations),
            soft_penalty,
        )
    base = float(direction.expected_value) * float(
        direction.confidence,
    )
    bias = 0.1 * float(outcome.value_usd)
    return (base + bias - soft_penalty, (), soft_penalty)


# ── Public entry point ───────────────────────────────────


def deliberate(
    *,
    outcome: OutcomeSpec,
    directions: list[ThinkingDirection],
    constraints: list[Constraint] | None = None,
    awareness: SelfAwareness | None = None,
    scorer: Callable[
        [
            ThinkingDirection,
            OutcomeSpec,
            tuple[Constraint, ...],
        ],
        tuple[float, tuple[str, ...], float],
    ] | None = None,
    now_fn: Any = None,
) -> Deliberation:
    """Run the 5-pillar pipeline once. Returns a
    :class:`Deliberation` whose ``.decision`` is the chosen
    direction (or None if every candidate had a hard
    violation)."""
    if not directions:
        raise ValueError(
            "deliberate() needs ≥ 1 direction",
        )
    score_fn = scorer or default_scorer
    cx = tuple(constraints or ())
    refines: list[RefineStep] = []
    for i, d in enumerate(directions, start=1):
        score, hard, soft = score_fn(d, outcome, cx)
        note = (
            "blocked: " + ", ".join(hard)
            if hard else "ok"
        )
        refines.append(RefineStep(
            iteration=i,
            direction_label=d.label,
            score=score,
            hard_violations=tuple(hard),
            soft_penalties=soft,
            note=note,
        ))
    aw = awareness or SelfAwareness(
        loop_check="aligned",
        dollar_distance=2,
        plumbing_vs_capability="balanced",
    )
    d_obj = Deliberation(
        outcome=outcome,
        directions=tuple(directions),
        constraints=cx,
        refines=tuple(refines),
        awareness=aw,
        created_ts=float((now_fn or time.time)()),
    )
    d_obj.decision = d_obj.best_direction()
    return d_obj


# ── In-process recent log (for brain snapshot) ───────────

_LOCK = threading.Lock()
_RECENT: list[Deliberation] = []
_MAX_RECENT = 200


def record_deliberation(d: Deliberation) -> None:
    """Push into the in-process recent-log (bounded at 200)
    so ``shopai brain`` / MCP ``brain_snapshot`` can surface
    the latest thinking paths."""
    with _LOCK:
        _RECENT.append(d)
        if len(_RECENT) > _MAX_RECENT:
            del _RECENT[: len(_RECENT) - _MAX_RECENT]


def recent_deliberations(
    limit: int = 20,
) -> list[Deliberation]:
    with _LOCK:
        limit = max(1, min(int(limit), _MAX_RECENT))
        return list(_RECENT[-limit:])


def reset_recent_for_tests() -> None:
    with _LOCK:
        _RECENT.clear()


def record_outcome_for_decision(
    decision_id: str,
    observation: dict[str, Any],
    *,
    now_fn: Any = None,
) -> bool:
    """Back-fill the actual measured outcome onto the
    Deliberation that drove the decision. Closes the
    refine + learn loop (CLAUDE.md §4d pillar 4 / §4b/B
    closed-loop telemetry).

    Looked up by ``decision_id``. Returns True if a
    matching Deliberation was found and updated, False
    otherwise (caller decides whether to log).

    The most recent matching Deliberation wins — a
    re-decision under the same id (rare, but possible)
    overwrites earlier observations rather than silently
    dropping data.
    """
    if not decision_id:
        return False
    if not isinstance(observation, dict):
        return False
    now = float((now_fn or time.time)())
    with _LOCK:
        for d in reversed(_RECENT):
            if d.decision_id == decision_id:
                d.observation = dict(observation)
                d.observed_ts = now
                return True
    return False


def find_deliberation_by_decision_id(
    decision_id: str,
) -> Deliberation | None:
    """Lookup helper used by tests + future MCP tools."""
    if not decision_id:
        return None
    with _LOCK:
        for d in reversed(_RECENT):
            if d.decision_id == decision_id:
                return d
    return None
