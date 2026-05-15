"""Engine recommender — given current goal + learned effectiveness,
rank which engines to run next.

This is the first concrete piece of the orchestration-brain layer.
``GoalManager`` already knows the current goal and tracks per-goal
effectiveness EMA (PR #89). ``ENGINE_GOAL_MAP`` declares which
engines optimize for which goal. The recommender joins those two:

  1. Resolve the current goal (caller passes ``goal=...`` or the
     manager's ``get_current_goal()`` is consulted).
  2. List every engine whose primary goal matches.
  3. Rank by ``priority = alignment * (0.5 + 0.5 * effectiveness)``
     so a proven-effective goal lifts all its aligned engines.
  4. Return ``EngineRecommendation`` rows the API / CLI can render.

The output is a structured list, not free text — caller decides how
to present (chat UI, /api/recommendations response, dashboard
widget). Each row carries enough metadata for the merchant to
understand WHY this engine was picked: the goal it serves, the
goal's learned effectiveness, and the alignment score.

Goal-mismatch behaviour
-----------------------
Engines whose primary goal differs from the active goal get an
``alignment=0`` row in the alternatives list, NOT the primary
result list. The primary list contains only goal-aligned engines.
This keeps the recommendation honest — when the active goal is
``survive_crisis``, the recommender won't suggest a growth
engine in the primary slot.

Wiring
------
Pure functional + state-aware: takes a ``GoalManager`` instance
(or uses the default singleton from ``goal_feedback._default_manager``).
No side effects, no DB writes — recommendations are advisory.
A follow-up PR can wire this into an API endpoint and a CLI
``shopai suggest`` command.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from core.goals.engine_goal_map import (
    ENGINE_GOAL_MAP,
    engines_for_goal,
    goal_for_engine,
)
from utils.logger import get_logger

logger = get_logger("core.brain.engine_recommender")


# Alignment scores. Primary match = 1.0 (engine's main goal IS
# the active goal). Cross-aligned engines get 0.5 (used when
# extending to a multi-goal map; absent in v1). Mismatched = 0.0.
_ALIGNMENT_PRIMARY = 1.0
_ALIGNMENT_MISMATCH = 0.0

# Effectiveness baseline used when an engine's goal has no
# recorded outcomes yet. Same neutral value GoalManager uses.
_EFFECTIVENESS_NEUTRAL = 0.5

# Default cap on the primary recommendation list. Most callers
# want a short list to render; the alternatives slot picks up the
# overflow.
_DEFAULT_LIMIT = 10

# Maximum per-engine priority adjustment driven by direct outcome
# data. A score of 1.0 (every recorded outcome positive) bumps
# priority by +cap; 0.0 (every outcome a refund/cancel) by -cap.
# Capped at 0.10 so a hot engine moves above its goal cluster but
# can't override the goal alignment signal (which swings ±0.5).
_OUTCOME_ADJUSTMENT_MAX = 0.10


@dataclass
class EngineRecommendation:
    """One engine the recommender suggests running.

    Attributes:
        engine: Canonical engine name (matches registry keys).
        goal: The primary goal this engine optimizes for.
        alignment: 0.0–1.0 — how well the engine aligns with the
            currently active goal. 1.0 for primary match, 0.0
            for mismatch (alternative-bucket only).
        effectiveness: 0.0–1.0 EMA from ``GoalManager`` for the
            engine's primary goal. ``_EFFECTIVENESS_NEUTRAL`` (0.5)
            when no outcomes recorded yet.
        priority: ``alignment * (0.5 + 0.5 * effectiveness)``.
            Higher = better next pick. Range [0.0, 1.0].
        reason: One-line operator-facing explanation.
    """

    engine: str
    goal: str
    alignment: float
    effectiveness: float
    priority: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "goal": self.goal,
            "alignment": round(self.alignment, 3),
            "effectiveness": round(self.effectiveness, 3),
            "priority": round(self.priority, 3),
            "reason": self.reason,
        }


@dataclass
class RecommendationResult:
    """Full recommender response.

    ``primary`` carries goal-aligned suggestions ranked by priority.
    ``alternatives`` carries adjacent engines (non-primary alignment)
    in case the merchant wants to override the goal-driven default.
    """

    active_goal: str
    primary: list[EngineRecommendation] = field(default_factory=list)
    alternatives: list[EngineRecommendation] = field(default_factory=list)
    source: str = "rules"
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_goal": self.active_goal,
            "primary": [r.to_dict() for r in self.primary],
            "alternatives": [r.to_dict() for r in self.alternatives],
            "source": self.source,
            "explanation": self.explanation,
        }


def recommend_engines(
    *,
    goal: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    manager: Any | None = None,
    include_alternatives: bool = True,
    available_engines: set[str] | None = None,
    outcome_scores: dict[str, float | None] | None = None,
) -> RecommendationResult:
    """Rank engines for the current goal.

    Args:
        goal: Active goal name. When ``None``, the recommender
            asks the ``GoalManager`` for the current goal. When
            ``manager`` is also ``None`` and the singleton lookup
            fails, falls back to ``"maximize_profit"`` (the
            ``GoalManager`` default).
        limit: Max length of the primary list.
        manager: Optional ``GoalManager`` instance. Defaults to
            the module singleton used by ``goal_feedback``.
        include_alternatives: When ``True`` (default), engines
            mapped to OTHER goals are returned in
            ``alternatives`` so the merchant can override the
            goal-driven default. Set ``False`` to keep the
            response compact (API list endpoint, for example).
        available_engines: Optional whitelist — only engines in
            this set are considered. Useful for callers that have
            already filtered by capability / scope.

    Returns:
        :class:`RecommendationResult`. Always returns — never
        raises. When no engines match (extremely unusual — would
        mean every goal bucket is empty), the result carries
        empty lists and a descriptive ``explanation``.
    """
    resolved_goal = _resolve_goal(goal, manager)
    resolved_manager = manager or _resolve_default_manager()
    effective_limit = max(1, int(limit) if limit is not None else _DEFAULT_LIMIT)

    primary_engines = engines_for_goal(resolved_goal)
    if available_engines is not None:
        primary_engines = [
            e for e in primary_engines if e in available_engines
        ]

    # If no outcome_scores override provided, fetch from the
    # approval queue (best-effort — queue unavailable → skip).
    resolved_scores = outcome_scores
    if resolved_scores is None:
        resolved_scores = _resolve_outcome_scores()

    primary_rows = _build_rows(
        primary_engines,
        active_goal=resolved_goal,
        manager=resolved_manager,
        alignment=_ALIGNMENT_PRIMARY,
        outcome_scores=resolved_scores,
    )
    primary_rows.sort(key=lambda r: r.priority, reverse=True)
    primary_rows = primary_rows[:effective_limit]

    alternative_rows: list[EngineRecommendation] = []
    if include_alternatives:
        # Engines whose primary goal differs from the active goal.
        # Limited to the same effective_limit so the response stays
        # bounded.
        other_engines = [
            engine for engine in ENGINE_GOAL_MAP.keys()
            if goal_for_engine(engine) != resolved_goal
            and (
                available_engines is None
                or engine in available_engines
            )
        ]
        alternative_rows = _build_rows(
            other_engines,
            active_goal=resolved_goal,
            manager=resolved_manager,
            alignment=_ALIGNMENT_MISMATCH,
            outcome_scores=resolved_scores,
        )
        # Rank alternatives by effectiveness within their own goal
        # (since alignment is identical 0.0 for all of them).
        alternative_rows.sort(
            key=lambda r: r.effectiveness, reverse=True,
        )
        alternative_rows = alternative_rows[:effective_limit]

    if not primary_rows and not alternative_rows:
        explanation = (
            f"no engines available for goal {resolved_goal!r}"
        )
    elif not primary_rows:
        explanation = (
            f"no engines map to goal {resolved_goal!r}; showing "
            f"alternatives from other goal buckets"
        )
    else:
        top = primary_rows[0]
        explanation = (
            f"top pick: {top.engine} "
            f"(priority={top.priority:.2f}, "
            f"effectiveness={top.effectiveness:.2f}) "
            f"for goal={resolved_goal!r}"
        )

    return RecommendationResult(
        active_goal=resolved_goal,
        primary=primary_rows,
        alternatives=alternative_rows,
        source="rules",
        explanation=explanation,
    )


# ── Internal helpers ──────────────────────────────────────────


def _build_rows(
    engines: list[str],
    *,
    active_goal: str,
    manager: Any | None,
    alignment: float,
    outcome_scores: dict[str, float | None] | None = None,
) -> list[EngineRecommendation]:
    """Per-engine: resolve goal + effectiveness, compute priority.

    Engines absent from ``ENGINE_GOAL_MAP`` (shouldn't happen given
    callers source from that map, but defensive) are skipped.

    When ``outcome_scores`` is provided, the per-engine outcome
    score (positive / (positive + negative) over the action_outcomes
    table) shifts priority by up to ±``_OUTCOME_ADJUSTMENT_MAX``.
    Goal-level EMA is the primary signal; the per-engine bump
    differentiates engines within a goal cluster without dominating.
    """
    scores = outcome_scores or {}
    rows: list[EngineRecommendation] = []
    for engine in engines:
        primary_goal = goal_for_engine(engine)
        if primary_goal == "unmapped":
            continue
        effectiveness = _effectiveness_for(primary_goal, manager)
        base = alignment * (0.5 + 0.5 * effectiveness)
        # Per-engine outcome adjustment: score is None when the
        # engine has no polarised history yet (no positive AND no
        # negative outcomes). In that case the adjustment is zero —
        # the recommender doesn't punish untested engines.
        outcome_score = scores.get(engine)
        if outcome_score is None:
            adjustment = 0.0
            score_str = "no outcomes yet"
        else:
            # Center at 0.5 (neutral) and scale to the cap.
            # score=1.0 → +cap; score=0.0 → -cap; score=0.5 → 0.
            adjustment = (
                _OUTCOME_ADJUSTMENT_MAX * 2.0 * (outcome_score - 0.5)
            )
            score_str = (
                f"outcome score {outcome_score:.2f} "
                f"({'+' if adjustment >= 0 else ''}{adjustment:.2f})"
            )
        priority = base + adjustment
        if alignment >= _ALIGNMENT_PRIMARY:
            reason = (
                f"primary engine for {active_goal!r}; "
                f"effectiveness {effectiveness:.2f}; "
                f"{score_str}"
            )
        else:
            reason = (
                f"primary goal {primary_goal!r} differs from "
                f"active {active_goal!r}; effectiveness "
                f"{effectiveness:.2f}; {score_str}"
            )
        rows.append(EngineRecommendation(
            engine=engine,
            goal=primary_goal,
            alignment=alignment,
            effectiveness=effectiveness,
            priority=priority,
            reason=reason,
        ))
    return rows


def _resolve_outcome_scores() -> dict[str, float | None]:
    """Best-effort: fetch per-engine outcome scores from the
    approval queue. Returns an empty dict if the queue is
    unavailable — the recommender simply skips the per-engine
    adjustment in that case.

    Pattern J — short-circuits under pytest so tests that don't
    explicitly pass ``outcome_scores`` don't accidentally read
    production state from ``data/approval_queue.db``. Tests that
    DO want to exercise the auto-fetch path either patch
    ``PYTEST_CURRENT_TEST`` away or supply ``outcome_scores``
    directly to ``recommend_engines``.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {}
    try:
        from core.approval import get_approval_queue
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return {}
    try:
        stats = get_approval_queue().all_engine_outcome_stats()
    except Exception as exc:  # noqa: BLE001
        logger.debug("engine outcome stats lookup failed: %s", exc)
        return {}
    return {
        engine: entry.get("outcome_score")
        for engine, entry in stats.items()
    }


def _resolve_goal(goal: str | None, manager: Any | None) -> str:
    """Pick the active goal: explicit > manager > fallback."""
    if isinstance(goal, str) and goal.strip():
        return goal.strip()
    resolved_manager = manager or _resolve_default_manager()
    if resolved_manager is not None:
        try:
            current = resolved_manager.get_current_goal()
            if isinstance(current, str) and current:
                return current
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "manager.get_current_goal raised: %s", exc,
            )
    return "maximize_profit"


def _effectiveness_for(goal: str, manager: Any | None) -> float:
    """Pull learned effectiveness from the manager. Defaults to
    neutral when the manager is unavailable or has no entry yet.
    """
    if manager is None:
        return _EFFECTIVENESS_NEUTRAL
    try:
        raw = manager.get_effectiveness(goal)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "manager.get_effectiveness(%s) raised: %s", goal, exc,
        )
        return _EFFECTIVENESS_NEUTRAL
    try:
        return float(raw)
    except (TypeError, ValueError):
        return _EFFECTIVENESS_NEUTRAL


def _resolve_default_manager() -> Any | None:
    """Lazy import of the goal-feedback singleton.

    Kept in its own helper so a missing goal_feedback module
    can't break the recommender (degrades to neutral
    effectiveness + ``maximize_profit`` fallback).
    """
    try:
        from core.goals.goal_feedback import _default_manager
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "goal_feedback singleton unavailable: %s", exc,
        )
        return None
    try:
        return _default_manager()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "_default_manager() raised: %s", exc,
        )
        return None
