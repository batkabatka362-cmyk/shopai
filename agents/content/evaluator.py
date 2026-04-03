"""Content Agent evaluator — assess quality of content generation results.

Evaluates:
  - Copy quality (is the written content compelling and accurate?)
  - SEO readiness (is content optimized for search engines?)
  - Visual guidance (are image/video specs actionable?)
  - Completeness (did all requested content get generated?)
"""
from __future__ import annotations

from typing import Any


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate content quality.

    Returns score 0-100 with detailed breakdown.
    """
    engine_results = results.get("engine_results", {})
    completed = results.get("completed_steps", 0)
    total = results.get("total_steps", 1)

    scores: dict[str, float] = {}
    issues: list[str] = []
    strengths: list[str] = []

    # 1. Copy quality (0-25): Is the written content good?
    copy_quality = _score_copy_quality(engine_results)
    scores["copy_quality"] = copy_quality
    if copy_quality >= 20:
        strengths.append("Written content is compelling with strong product messaging")
    elif copy_quality < 10:
        issues.append("Copy quality is low — descriptions lack detail or persuasion")

    # 2. SEO readiness (0-25): Is content search-optimized?
    seo_readiness = _score_seo_readiness(engine_results)
    scores["seo_readiness"] = seo_readiness
    if seo_readiness >= 20:
        strengths.append("Content is well-optimized for target keywords")
    elif seo_readiness < 10:
        issues.append("SEO optimization is missing or incomplete")

    # 3. Visual guidance (0-25): Are visual specs actionable?
    visual_guidance = _score_visual_guidance(engine_results)
    scores["visual_guidance"] = visual_guidance
    if visual_guidance >= 20:
        strengths.append("Visual content specs are detailed and production-ready")
    elif visual_guidance < 10:
        issues.append("Visual content guidance is lacking")

    # 4. Completeness (0-25): Did we generate everything needed?
    completeness = _score_completeness(engine_results, completed, total)
    scores["completeness"] = completeness
    if completeness >= 20:
        strengths.append(f"All {total} content engines completed successfully")
    elif completeness < 10:
        issues.append(f"{total - completed}/{total} content engines failed")

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


def _score_copy_quality(results: dict[str, Any]) -> float:
    """Score written content quality."""
    score = 0

    # Product descriptions
    pd = results.get("product_description", {})
    if pd.get("status") == "success":
        pd_data = pd.get("data", {})
        if pd_data.get("descriptions"):
            descs = pd_data["descriptions"]
            score += 8
            if isinstance(descs, list) and len(descs) > 0:
                score += 4
        if pd_data.get("bullet_points"):
            score += 5

    # Blog / ad copy
    cg = results.get("content_generation", {})
    if cg.get("status") == "success":
        cg_data = cg.get("data", {})
        if cg_data.get("blog_posts"):
            score += 5
        if cg_data.get("ad_copy"):
            score += 3

    return min(25, score)


def _score_seo_readiness(results: dict[str, Any]) -> float:
    """Score SEO optimization level."""
    score = 0

    seo = results.get("search_optimization", {})
    if seo.get("status") == "success":
        seo_data = seo.get("data", {})
        if seo_data.get("seo_analysis"):
            score += 10
            analysis = seo_data["seo_analysis"]
            if isinstance(analysis, dict):
                if analysis.get("title_tags"):
                    score += 3
                if analysis.get("meta_descriptions"):
                    score += 3
                if analysis.get("keyword_density"):
                    score += 3
        if seo_data.get("keywords"):
            keywords = seo_data["keywords"]
            score += 6
            if isinstance(keywords, list) and len(keywords) >= 10:
                score += 3

    return min(25, score)


def _score_visual_guidance(results: dict[str, Any]) -> float:
    """Score visual content specs."""
    score = 0

    # Image optimization
    img = results.get("image_optimization", {})
    if img.get("status") == "success":
        img_data = img.get("data", {})
        if img_data.get("image_specs"):
            score += 8
        if img_data.get("alt_text"):
            score += 5

    # Video marketing
    vid = results.get("video_marketing", {})
    if vid.get("status") == "success":
        vid_data = vid.get("data", {})
        if vid_data.get("video_scripts"):
            score += 7
        if vid_data.get("storyboards"):
            score += 5

    return min(25, score)


def _score_completeness(results: dict[str, Any], completed: int, total: int) -> float:
    """Score overall content generation completeness."""
    if total == 0:
        return 0

    # Base score from completion ratio
    base = round(completed / max(total, 1) * 15)

    # Bonus for data richness in completed engines
    bonus = 0
    for engine_name, result in results.items():
        if result.get("status") == "success":
            data = result.get("data", {})
            non_empty = sum(1 for v in data.values() if v)
            if non_empty >= 2:
                bonus += 2

    return min(25, base + bonus)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    has_seo = results.get("search_optimization", {}).get("status") == "success"
    has_visuals = (
        results.get("image_optimization", {}).get("status") == "success"
        or results.get("video_marketing", {}).get("status") == "success"
    )

    if score >= 70:
        if has_seo and has_visuals:
            return "Content is publication-ready with strong SEO and visual assets."
        if has_seo:
            return "Written content is strong and SEO-ready. Consider adding visual assets."
        return "Content quality is high. Add SEO optimization before publishing."

    if score >= 40:
        return "Content is partially ready. Revise weak areas and optimize for SEO before publishing."

    return "Content needs significant work. Rewrite copy, add SEO keywords, and create visual assets."
