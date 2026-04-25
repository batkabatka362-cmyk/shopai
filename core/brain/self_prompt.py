"""Self-prompt generator — the brain asks itself proactive questions.

Reactive brains only respond. Proactive brains notice "why did I
kill three launches this week but scale none?" and ask themselves
*before* the owner does. That's the question-generation layer.

SelfPromptGenerator walks the store's current situation and emits
a ranked list of open questions the brain should answer this
cycle. Each question carries:

  • text            — the question itself
  • trigger          — which observation spawned it
  • priority         — 0-1 salience score
  • suggested_tool   — hint at which subsystem (debate / retrospect /
                       counterfactual / hypothesis / oracle)
  • context          — metadata the tool needs

Generators (pure functions, each takes a ``Situation`` snapshot):

  gen_kill_spike        — N killed launches in M days, none scaled
  gen_confidence_drop   — calibration hit-rate slipped under threshold
  gen_stagnant_goal     — a goal with no progress for >K days
  gen_unresolved_surprise — high-magnitude surprise still pending
  gen_idle_skill        — skill registered but never used
  gen_hypothesis_overdue — pending prediction past its horizon

The generator functions are composable and return ``Question``
dataclasses. ``compose()`` runs them all and returns the top-K
by priority.

No LLM — this is a structured question engine. An optional
``writer`` callable can polish phrasing with an LLM if configured.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Situation:
    """Minimal context the generators need. Caller populates what
    it has; missing fields default to safe zeros."""
    kills_last_7d: int = 0
    scales_last_7d: int = 0
    calibration_hit_rate: float = 0.7
    stagnant_goals: list[dict[str, Any]] = field(default_factory=list)
    unresolved_surprises: list[dict[str, Any]] = field(
        default_factory=list,
    )
    idle_skills: list[dict[str, Any]] = field(default_factory=list)
    overdue_hypotheses: list[dict[str, Any]] = field(
        default_factory=list,
    )


@dataclass
class Question:
    text: str
    trigger: str
    priority: float                # 0-1
    suggested_tool: str
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "trigger": self.trigger,
            "priority": round(self.priority, 3),
            "suggested_tool": self.suggested_tool,
            "context": self.context,
        }


# ── Generators ──────────────────────────────────────────────

def gen_kill_spike(sit: Situation) -> list[Question]:
    if sit.kills_last_7d < 3:
        return []
    # Priority scales with how lopsided the week was
    skew = sit.kills_last_7d / max(1, sit.kills_last_7d + sit.scales_last_7d)
    priority = min(1.0, 0.4 + 0.6 * skew)
    return [Question(
        text=(f"We killed {sit.kills_last_7d} launches this week but "
              f"scaled {sit.scales_last_7d}. What's the common failure "
              "pattern?"),
        trigger="kill_spike",
        priority=priority,
        suggested_tool="counterfactual",
        context={"kills": sit.kills_last_7d,
                 "scales": sit.scales_last_7d},
    )]


def gen_confidence_drop(sit: Situation) -> list[Question]:
    if sit.calibration_hit_rate >= 0.55:
        return []
    # Under 55% hit-rate: the brain's predictions are barely
    # beating a coin-flip.
    priority = min(1.0, 0.5 + (0.55 - sit.calibration_hit_rate) * 2)
    return [Question(
        text=(f"My prediction hit-rate is {sit.calibration_hit_rate:.0%}. "
              "Which rationale tags are over-confident?"),
        trigger="low_calibration",
        priority=priority,
        suggested_tool="metacognition",
        context={"hit_rate": sit.calibration_hit_rate},
    )]


def gen_stagnant_goal(sit: Situation) -> list[Question]:
    out: list[Question] = []
    for g in sit.stagnant_goals:
        days = float(g.get("days_idle", 0))
        if days < 3:
            continue
        priority = min(1.0, 0.3 + days / 30.0)
        out.append(Question(
            text=(f"Goal '{g.get('title', '?')}' has been idle "
                  f"{int(days)} days. Is it blocked, obsolete, or "
                  "needs a fresh plan?"),
            trigger="stagnant_goal",
            priority=priority,
            suggested_tool="hierarchical_planner",
            context={"goal_id": g.get("id")},
        ))
    return out


def gen_unresolved_surprise(sit: Situation) -> list[Question]:
    out: list[Question] = []
    for s in sit.unresolved_surprises:
        mag = float(s.get("magnitude", 0))
        if mag < 0.4:
            continue
        priority = min(1.0, 0.5 + mag * 0.5)
        out.append(Question(
            text=(f"Surprise '{s.get('signature', '?')}' still pending "
                  f"(magnitude {mag:.2f}). What changed?"),
            trigger="unresolved_surprise",
            priority=priority,
            suggested_tool="debate",
            context={"surprise_id": s.get("id")},
        ))
    return out


def gen_idle_skill(sit: Situation) -> list[Question]:
    out: list[Question] = []
    for sk in sit.idle_skills:
        days = float(sk.get("days_since_use", 0))
        if days < 14:
            continue
        priority = min(0.6, 0.2 + days / 60.0)
        out.append(Question(
            text=(f"Skill '{sk.get('name', '?')}' hasn't been used in "
                  f"{int(days)} days. Should we exercise it or deprecate?"),
            trigger="idle_skill",
            priority=priority,
            suggested_tool="skills",
            context={"skill": sk.get("name")},
        ))
    return out


def gen_hypothesis_overdue(sit: Situation) -> list[Question]:
    out: list[Question] = []
    for h in sit.overdue_hypotheses:
        days = float(h.get("days_overdue", 0))
        priority = min(0.9, 0.4 + days / 14.0)
        out.append(Question(
            text=(f"Hypothesis '{h.get('subject', '?')}' is "
                  f"{int(days)}d overdue. Resolve or mark stale?"),
            trigger="hypothesis_overdue",
            priority=priority,
            suggested_tool="hypothesis",
            context={"hypothesis_id": h.get("id")},
        ))
    return out


_GENERATORS: tuple[Callable[[Situation], list[Question]], ...] = (
    gen_kill_spike, gen_confidence_drop, gen_stagnant_goal,
    gen_unresolved_surprise, gen_idle_skill, gen_hypothesis_overdue,
)


# ── Composer ────────────────────────────────────────────────

def compose(
    situation: Situation,
    top_k: int = 5,
    writer: Callable[[Question], str] | None = None,
) -> list[Question]:
    """Run every generator and return the top ``k`` questions by
    priority. Optional ``writer`` callable can polish each question's
    text (LLM wrap) in place."""
    pool: list[Question] = []
    for g in _GENERATORS:
        pool.extend(g(situation))
    pool.sort(key=lambda q: -q.priority)
    top = pool[:top_k]
    if writer:
        for q in top:
            polished = writer(q)
            if polished:
                q.text = polished
    return top
