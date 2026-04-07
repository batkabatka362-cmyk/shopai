"""Content Agent evaluator — assess quality of content generation results.

Thin wrapper around ``agents.base.evaluator.evaluate_results_base``.
"""
from __future__ import annotations

from typing import Any

from agents.base.evaluator import ScoreComponent, evaluate_results_base


def evaluate_results(results: dict[str, Any], goal: str) -> dict[str, Any]:
    """Evaluate content quality."""
    return evaluate_results_base(
        results, goal,
        components=[
            ScoreComponent(
                name="copy_quality",
                scorer=lambda er, meta: _score_copy_quality(er),
                strong_text="Written content is compelling with strong product messaging",
                weak_text="Copy quality is low — descriptions lack detail or persuasion",
            ),
            ScoreComponent(
                name="seo_readiness",
                scorer=lambda er, meta: _score_seo_readiness(er),
                strong_text="Content is well-optimized for target keywords",
                weak_text="SEO optimization is missing or incomplete",
            ),
            ScoreComponent(
                name="visual_guidance",
                scorer=lambda er, meta: _score_visual_guidance(er),
                strong_text="Visual content specs are detailed and production-ready",
                weak_text="Visual content guidance is lacking",
            ),
            ScoreComponent(
                name="completeness",
                scorer=lambda er, meta: _score_completeness(er, meta["completed"], meta["total"]),
                strong_text="Content generation completeness is high with rich output",
                weak_text="Content generation is incomplete or sparse",
            ),
        ],
        recommendation_fn=_overall_recommendation,
    )


def _score_copy_quality(results: dict[str, Any]) -> float:
    """Score written content quality."""
    score = 0

    pd = results.get("product_description", {})
    if isinstance(pd, dict) and pd.get("status") == "success":
        pd_data = pd.get("data") or {}
        if pd_data.get("descriptions"):
            descs = pd_data["descriptions"]
            score += 8
            if isinstance(descs, list) and len(descs) > 0:
                score += 4
        if pd_data.get("bullet_points"):
            score += 5

    cg = results.get("content_generation", {})
    if isinstance(cg, dict) and cg.get("status") == "success":
        cg_data = cg.get("data") or {}
        if cg_data.get("blog_posts"):
            score += 5
        if cg_data.get("ad_copy"):
            score += 3

    return min(25, score)


def _score_seo_readiness(results: dict[str, Any]) -> float:
    """Score SEO optimization level."""
    score = 0

    seo = results.get("search_optimization", {})
    if isinstance(seo, dict) and seo.get("status") == "success":
        seo_data = seo.get("data") or {}
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

    img = results.get("image_optimization", {})
    if isinstance(img, dict) and img.get("status") == "success":
        img_data = img.get("data") or {}
        if img_data.get("image_specs"):
            score += 8
        if img_data.get("alt_text"):
            score += 5

    vid = results.get("video_marketing", {})
    if isinstance(vid, dict) and vid.get("status") == "success":
        vid_data = vid.get("data") or {}
        if vid_data.get("video_scripts"):
            score += 7
        if vid_data.get("storyboards"):
            score += 5

    return min(25, score)


def _score_completeness(results: dict[str, Any], completed: int, total: int) -> float:
    """Score overall content generation completeness with a richness bonus."""
    if total == 0:
        return 0

    # Base score from completion ratio
    base = round(completed / max(total, 1) * 15)

    # Bonus for data richness in completed engines
    bonus = 0
    for engine_name, result in results.items():
        if not isinstance(result, dict):
            continue
        if result.get("status") == "success":
            data = result.get("data") or {}
            if not isinstance(data, dict):
                continue
            non_empty = sum(1 for v in data.values() if v)
            if non_empty >= 2:
                bonus += 2

    return min(25, base + bonus)


def _overall_recommendation(score: int, results: dict[str, Any]) -> str:
    """Generate final recommendation text."""
    seo = results.get("search_optimization", {})
    has_seo = isinstance(seo, dict) and seo.get("status") == "success"
    img = results.get("image_optimization", {})
    vid = results.get("video_marketing", {})
    has_visuals = (
        (isinstance(img, dict) and img.get("status") == "success")
        or (isinstance(vid, dict) and vid.get("status") == "success")
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
