"""Marketing Agent evaluator — assess quality of marketing campaign results.

Thin wrapper around ``agents.base.evaluator.evaluate_results_base``.
"""
from __future__ import annotations

from typing import Any

from agents.base.evaluator import ScoreComponent, evaluate_results_base


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate marketing campaign quality."""
    return evaluate_results_base(
        results, goal,
        components=[
            ScoreComponent(
                name="content_quality",
                scorer=lambda er, meta: _score_content_quality(er),
                strong_text="High-quality marketing and ad copy generated",
                weak_text="Content quality is low — copy may not convert",
            ),
            ScoreComponent(
                name="channel_coverage",
                scorer=lambda er, meta: _score_channel_coverage(er, meta["completed"], meta["total"]),
                strong_text="Strong multi-channel coverage across platforms",
                weak_text="Limited channel coverage — missing key platforms",
            ),
            ScoreComponent(
                name="audience_alignment",
                scorer=lambda er, meta: _score_audience_alignment(er),
                strong_text="Content well-aligned with target audience segments",
                weak_text="Poor audience targeting — content may miss the mark",
            ),
            ScoreComponent(
                name="test_readiness",
                scorer=lambda er, meta: _score_test_readiness(er),
                strong_text="A/B tests and performance metrics are properly configured",
                weak_text="No testing plan — unable to optimize campaigns",
            ),
        ],
        recommendation_fn=_overall_recommendation,
    )


def _score_content_quality(results: dict[str, Any]) -> float:
    """Score the quality of generated content."""
    score = 0

    cg = results.get("content_generation", {})
    if isinstance(cg, dict) and cg.get("status") == "success":
        cg_data = cg.get("data") or {}
        if cg_data.get("marketing_copy"):
            score += 7
        if cg_data.get("ad_copy"):
            score += 6
        if cg_data.get("headlines"):
            score += 3

    vm = results.get("video_marketing", {})
    if isinstance(vm, dict) and vm.get("status") == "success":
        vm_data = vm.get("data") or {}
        if vm_data.get("video_scripts"):
            score += 5

    lp = results.get("landing_page", {})
    if isinstance(lp, dict) and lp.get("status") == "success":
        lp_data = lp.get("data") or {}
        if lp_data.get("landing_pages"):
            score += 4

    return min(25, score)


def _score_channel_coverage(results: dict[str, Any], completed: int, total: int) -> float:
    """Score how well channels are covered."""
    score = 0

    # Base score from engine completion rate
    score += round(completed / max(total, 1) * 10)

    em = results.get("email_marketing", {})
    if isinstance(em, dict) and em.get("status") == "success":
        em_data = em.get("data") or {}
        if em_data.get("email_campaigns"):
            score += 5

    sm = results.get("social_media", {})
    if isinstance(sm, dict) and sm.get("status") == "success":
        sm_data = sm.get("data") or {}
        if sm_data.get("social_posts"):
            score += 5

    inf = results.get("influencer", {})
    if isinstance(inf, dict) and inf.get("status") == "success":
        score += 3

    aff = results.get("affiliate", {})
    if isinstance(aff, dict) and aff.get("status") == "success":
        score += 2

    return min(25, score)


def _score_audience_alignment(results: dict[str, Any]) -> float:
    """Score how well content aligns with target audience."""
    score = 0

    em = results.get("email_marketing", {})
    if isinstance(em, dict) and em.get("status") == "success":
        em_data = em.get("data") or {}
        if em_data.get("email_campaigns"):
            score += 5
        if em_data.get("audience_segments"):
            score += 5

    inf = results.get("influencer", {})
    if isinstance(inf, dict) and inf.get("status") == "success":
        inf_data = inf.get("data") or {}
        if inf_data.get("influencer_plan"):
            score += 5
        if inf_data.get("audience_match_score"):
            score += 5

    cg = results.get("content_generation", {})
    if isinstance(cg, dict) and cg.get("status") == "success":
        cg_data = cg.get("data") or {}
        if cg_data.get("marketing_copy"):
            score += 3
        if cg_data.get("audience_personas"):
            score += 2

    return min(25, score)


def _score_test_readiness(results: dict[str, Any]) -> float:
    """Score whether testing and optimization is set up."""
    score = 0

    ab = results.get("ab_testing", {})
    if isinstance(ab, dict) and ab.get("status") == "success":
        ab_data = ab.get("data") or {}
        if ab_data.get("test_plans"):
            score += 10
        if ab_data.get("success_metrics"):
            score += 5
        if ab_data.get("test_variants"):
            score += 3

    lp = results.get("landing_page", {})
    if isinstance(lp, dict) and lp.get("status") == "success":
        lp_data = lp.get("data") or {}
        if lp_data.get("landing_pages"):
            score += 4

    # Any engine with metrics defined
    for engine_name, engine_result in results.items():
        if not isinstance(engine_result, dict):
            continue
        if engine_result.get("status") == "success":
            if (engine_result.get("data") or {}).get("kpis"):
                score += 3
                break

    return min(25, score)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    content = results.get("content_generation", {})
    has_content = isinstance(content, dict) and content.get("status") == "success"

    ab = results.get("ab_testing", {})
    has_testing = isinstance(ab, dict) and ab.get("status") == "success"

    if score >= 70:
        if has_content and has_testing:
            return "Campaign is ready to launch with testing in place. Go live."
        return "Campaign quality is strong. Set up A/B tests before full launch."

    if score >= 40:
        return "Campaign shows potential but needs content or targeting improvements."

    return "Campaign is not ready. Improve content quality and expand channel coverage."
