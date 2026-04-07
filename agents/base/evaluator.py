"""Shared evaluator primitives for domain agents.

Audit pass 37 — extracted from the 7 near-identical
``evaluate_results`` bodies that existed in
``agents/{product,marketing,content,finance,operations,
customer,research}/evaluator.py``.

Each domain evaluator had the same six-step shape:

  1. Defensive coercion of ``results`` / ``goal`` /
     ``engine_results`` / ``completed`` / ``total``
     (added in pass 36).
  2. Append a universal "All N engines completed"
     strength or "K/N failed" issue.
  3. Call 3–4 agent-specific scorer helpers, each returning
     a float in ``[0, 25]``.
  4. Apply the universal ``>= 20`` / ``< 10`` thresholds to
     decide which of the agent-supplied text snippets to
     append to strengths / issues.
  5. Sum the component scores, clamp to ``[0, 100]``, pick a
     ``"high" / "medium" / "low"`` quality band on ``>= 70``
     / ``>= 40``.
  6. Call an agent-specific ``_overall_recommendation`` to
     produce the final advice text.

Only the **domain knowledge** (how each agent scores its own
engine results and how it phrases its recommendations) was
actually agent-specific. Everything else was duplicated 7
times which made every defensive bug fix in passes 30-36 a
7-file copy/paste exercise.

This module gives the agents two entry points:

  * ``evaluate_results_base(results, goal, *, components,
    recommendation_fn)`` — the full evaluator contract. Each
    domain evaluator passes its own list of
    :class:`ScoreComponent` instances plus a recommendation
    function, and the base handles argument coercion, the
    universal completeness signal, threshold application,
    total scoring, quality banding, and the return shape.

  * ``ScoreComponent`` dataclass — describes one scorable
    dimension (name, scorer callable, strong/weak text,
    thresholds).

  * ``completeness_component(...)`` — convenience factory for
    the "round(completed/total * 25)" component used by
    product / content / research.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


ScorerFn = Callable[[dict[str, Any], dict[str, Any]], float]
RecommendationFn = Callable[[int, dict[str, Any]], str]


@dataclass(frozen=True)
class ScoreComponent:
    """One scorable dimension of an evaluator's quality report.

    Attributes:
        name: Key under which this score appears in the
            ``scores`` dict of the final report.
        scorer: ``(engine_results, meta) -> float`` callable.
            ``meta`` carries the audit context
            ``{"completed", "total", "goal"}`` — scorers that
            don't need it can ignore it.
        strong_text: Appended to ``strengths`` if the scorer
            returned a value ``>= strong_threshold``. Empty
            string disables this branch.
        weak_text: Appended to ``issues`` if the scorer
            returned a value ``< weak_threshold``. Empty
            string disables this branch.
        strong_threshold: Default 20.0 — matches every
            original evaluator's ``>= 20`` pattern.
        weak_threshold: Default 10.0 — matches every original
            evaluator's ``< 10`` pattern.
    """
    name: str
    scorer: ScorerFn
    strong_text: str = ""
    weak_text: str = ""
    strong_threshold: float = 20.0
    weak_threshold: float = 10.0


def completeness_component(
    strong_text: str = "",
    weak_text: str = "",
) -> ScoreComponent:
    """Standard ``round(completed/total * 25)`` completeness scorer.

    Used by product / content / research evaluators which
    include "completeness" as one of their 4 score dimensions.
    Agents whose score dimensions don't include completeness
    (marketing / finance / operations / customer) can omit
    this component; the universal completeness *signal*
    (the "All N engines completed" / "K/N failed" strength /
    issue) is still appended by :func:`evaluate_results_base`
    regardless.
    """
    def _scorer(engine_results: dict[str, Any], meta: dict[str, Any]) -> float:
        completed = meta.get("completed", 0) or 0
        total = meta.get("total", 1) or 1
        return round(completed / max(total, 1) * 25)

    return ScoreComponent(
        name="completeness",
        scorer=_scorer,
        strong_text=strong_text,
        weak_text=weak_text,
    )


def _coerce_entry(
    results: Any,
    goal: Any,
) -> tuple[dict[str, Any], str, dict[str, Any], int, int]:
    """Defensive coercion shared by every domain evaluator.

    Returns ``(results_dict, goal_str, engine_results_dict,
    completed_num, total_num)`` — the exact set of locals the
    original bodies used. ``total`` is floored at 1 to prevent
    divide-by-zero in downstream math.
    """
    results_dict = results if isinstance(results, dict) else {}
    goal_str = goal if isinstance(goal, str) else ""

    engine_results = results_dict.get("engine_results") or {}
    if not isinstance(engine_results, dict):
        engine_results = {}

    # ``.get(k, default)`` only returns the default when k is
    # MISSING; present-but-None crashed the int math in every
    # original evaluator. Audit pass 36 fix, now shared.
    completed = results_dict.get("completed_steps") or 0
    total = results_dict.get("total_steps") or 1
    if not isinstance(completed, (int, float)):
        completed = 0
    if not isinstance(total, (int, float)) or total <= 0:
        total = 1

    return results_dict, goal_str, engine_results, completed, total


def evaluate_results_base(
    results: dict[str, Any],
    goal: str,
    *,
    components: list[ScoreComponent],
    recommendation_fn: RecommendationFn,
) -> dict[str, Any]:
    """Run the full evaluator contract, delegating domain scoring.

    Args:
        results: ``{"engine_results": {...}, "completed_steps":
            int, "total_steps": int}`` dict as produced by an
            executor. Coerced to ``{}`` on non-dict.
        goal: free-text goal the plan was aiming at. Coerced
            to ``""`` on non-string.
        components: ordered list of :class:`ScoreComponent`
            instances describing the agent's score dimensions.
            Each scorer returns a float in ``[0, 25]``; the
            base sums them, clamps to ``[0, 100]``, and bands
            the total into ``"high"``/``"medium"``/``"low"``.
            A buggy scorer is caught and counted as 0.
        recommendation_fn: ``(total_score, engine_results) ->
            str`` callback. A buggy recommendation function is
            caught and replaced with ``""``.

    Returns:
        The standard evaluator envelope::

            {
                "score": int,         # 0-100
                "quality": str,       # "high"/"medium"/"low"
                "scores": {name: float, ...},
                "issues": [...],
                "strengths": [...],
                "recommendation": str,
            }
    """
    _, goal_str, engine_results, completed, total = _coerce_entry(results, goal)
    meta = {"completed": completed, "total": total, "goal": goal_str}

    scores: dict[str, float] = {}
    strengths: list[str] = []
    issues: list[str] = []

    # Universal completeness signal — every original evaluator
    # emitted one of these two lines regardless of whether
    # "completeness" was a scored dimension.
    if completed == total:
        strengths.append(f"All {total} engines completed successfully")
    else:
        missing = total - completed
        if missing > 0:
            issues.append(f"{missing}/{total} engines failed")

    for comp in components:
        try:
            value = comp.scorer(engine_results, meta)
        except Exception:  # noqa: BLE001
            # A buggy scorer must not take down the evaluator.
            value = 0.0
        if not isinstance(value, (int, float)):
            value = 0.0
        scores[comp.name] = value

        if comp.strong_text and value >= comp.strong_threshold:
            strengths.append(comp.strong_text)
        elif comp.weak_text and value < comp.weak_threshold:
            issues.append(comp.weak_text)

    total_score = sum(scores.values())
    total_score = max(0, min(100, round(total_score)))
    quality = (
        "high" if total_score >= 70
        else "medium" if total_score >= 40
        else "low"
    )

    try:
        recommendation = recommendation_fn(total_score, engine_results)
    except Exception:  # noqa: BLE001
        recommendation = ""
    if not isinstance(recommendation, str):
        recommendation = ""

    return {
        "score": total_score,
        "quality": quality,
        "scores": scores,
        "issues": issues,
        "strengths": strengths,
        "recommendation": recommendation,
    }
