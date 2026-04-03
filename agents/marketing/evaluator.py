"""Marketing Agent evaluator — assess quality of marketing campaign results.

Evaluates:
  - Content quality (is the copy compelling and on-brand?)
  - Channel coverage (are all target channels covered?)
  - Audience alignment (does content match target audience?)
  - Test readiness (are A/B tests and metrics set up?)
"""
from __future__ import annotations

from typing import Any


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate marketing campaign quality.

    Returns score 0-100 with detailed breakdown.
    """
    engine_results = results.get("engine_results", {})
    completed = results.get("completed_steps", 0)
    total = results.get("total_steps", 1)

    scores: dict[str, float] = {}
    issues: list[str] = []
    strengths: list[str] = []

    # 1. Content quality (0-25): Is the copy good?
    content_quality = _score_content_quality(engine_results)
    scores["content_quality"] = content_quality
    if content_quality >= 20:
        strengths.append("High-quality marketing and ad copy generated")
    elif content_quality < 10:
        issues.append("Content quality is low — copy may not convert")

    # 2. Channel coverage (0-25): Are channels covered?
    channel_coverage = _score_channel_coverage(engine_results, completed, total)
    scores["channel_coverage"] = channel_coverage
    if channel_coverage >= 20:
        strengths.append("Strong multi-channel coverage across platforms")
    elif channel_coverage < 10:
        issues.append("Limited channel coverage — missing key platforms")

    # 3. Audience alignment (0-25): Does content match audience?
    audience_alignment = _score_audience_alignment(engine_results)
    scores["audience_alignment"] = audience_alignment
    if audience_alignment >= 20:
        strengths.append("Content well-aligned with target audience segments")
    elif audience_alignment < 10:
        issues.append("Poor audience targeting — content may miss the mark")

    # 4. Test readiness (0-25): Are tests set up?
    test_readiness = _score_test_readiness(engine_results)
    scores["test_readiness"] = test_readiness
    if test_readiness >= 20:
        strengths.append("A/B tests and performance metrics are properly configured")
    elif test_readiness < 10:
        issues.append("No testing plan — unable to optimize campaigns")

    total_score = sum(scores.values())
    total_score = max(0, min(100, round(total_score)))

    quality = "high" if total_score >= 70 else "medium" if total_score >= 40 else "low"

    return {
        "score": total_score,
        "quality": quality,
        "scores": scores,
        "issues": issues,
        "strengths": strengths,
        "recommendation": _overall_recommendation(total_score, engine_results),
    }


def _score_content_quality(results: dict[str, Any]) -> float:
    """Score the quality of generated content."""
    score = 0

    # Content generation results
    cg = results.get("content_generation", {})
    if cg.get("status") == "success":
        cg_data = cg.get("data", {})
        if cg_data.get("marketing_copy"):
            score += 7
        if cg_data.get("ad_copy"):
            score += 6
        if cg_data.get("headlines"):
            score += 3

    # Video marketing content
    vm = results.get("video_marketing", {})
    if vm.get("status") == "success":
        vm_data = vm.get("data", {})
        if vm_data.get("video_scripts"):
            score += 5

    # Landing page content
    lp = results.get("landing_page", {})
    if lp.get("status") == "success":
        lp_data = lp.get("data", {})
        if lp_data.get("landing_pages"):
            score += 4

    return min(25, score)


def _score_channel_coverage(results: dict[str, Any], completed: int, total: int) -> float:
    """Score how well channels are covered."""
    score = 0

    # Base score from engine completion rate
    score += round(completed / max(total, 1) * 10)

    # Email marketing
    em = results.get("email_marketing", {})
    if em.get("status") == "success":
        em_data = em.get("data", {})
        if em_data.get("email_campaigns"):
            score += 5

    # Social media
    sm = results.get("social_media", {})
    if sm.get("status") == "success":
        sm_data = sm.get("data", {})
        if sm_data.get("social_posts"):
            score += 5

    # Influencer
    inf = results.get("influencer", {})
    if inf.get("status") == "success":
        score += 3

    # Affiliate
    aff = results.get("affiliate", {})
    if aff.get("status") == "success":
        score += 2

    return min(25, score)


def _score_audience_alignment(results: dict[str, Any]) -> float:
    """Score how well content aligns with target audience."""
    score = 0

    # Email marketing audience segmentation
    em = results.get("email_marketing", {})
    if em.get("status") == "success":
        em_data = em.get("data", {})
        if em_data.get("email_campaigns"):
            score += 5
        if em_data.get("audience_segments"):
            score += 5

    # Influencer audience match
    inf = results.get("influencer", {})
    if inf.get("status") == "success":
        inf_data = inf.get("data", {})
        if inf_data.get("influencer_plan"):
            score += 5
        if inf_data.get("audience_match_score"):
            score += 5

    # Content generation with audience context
    cg = results.get("content_generation", {})
    if cg.get("status") == "success":
        cg_data = cg.get("data", {})
        if cg_data.get("marketing_copy"):
            score += 3
        if cg_data.get("audience_personas"):
            score += 2

    return min(25, score)


def _score_test_readiness(results: dict[str, Any]) -> float:
    """Score whether testing and optimization is set up."""
    score = 0

    # A/B testing plan
    ab = results.get("ab_testing", {})
    if ab.get("status") == "success":
        ab_data = ab.get("data", {})
        if ab_data.get("test_plans"):
            score += 10
        if ab_data.get("success_metrics"):
            score += 5
        if ab_data.get("test_variants"):
            score += 3

    # Landing page variants for testing
    lp = results.get("landing_page", {})
    if lp.get("status") == "success":
        lp_data = lp.get("data", {})
        if lp_data.get("landing_pages"):
            score += 4

    # Any engine with metrics defined
    for engine_name, engine_result in results.items():
        if engine_result.get("status") == "success":
            if engine_result.get("data", {}).get("kpis"):
                score += 3
                break

    return min(25, score)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    content = results.get("content_generation", {})
    has_content = content.get("status") == "success"

    ab = results.get("ab_testing", {})
    has_testing = ab.get("status") == "success"

    if score >= 70:
        if has_content and has_testing:
            return "Campaign is ready to launch with testing in place. Go live."
        return "Campaign quality is strong. Set up A/B tests before full launch."

    if score >= 40:
        return "Campaign shows potential but needs content or targeting improvements."

    return "Campaign is not ready. Improve content quality and expand channel coverage."
