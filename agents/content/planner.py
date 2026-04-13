"""Content Agent planner — decides which engines to use and in what order.

Thin wrapper around ``agents.base.planner.create_plan_base``.
"""
from __future__ import annotations

from typing import Any

from agents.base.planner import create_plan_base, wrap_engine_input


ENGINE_CAPABILITIES = {
    "product_description": {
        "provides": ["descriptions", "bullet_points"],
        "requires": ["products"],
        "optional": ["tone", "keywords", "competitors"],
    },
    "content_generation": {
        "provides": ["blog_posts", "ad_copy"],
        "requires": ["topics"],
        "optional": ["tone", "audience", "word_count"],
    },
    "search_optimization": {
        "provides": ["seo_analysis", "keywords"],
        "requires": ["content"],
        "optional": ["target_keywords", "competitors"],
    },
    "image_optimization": {
        "provides": ["image_specs", "alt_text"],
        "requires": ["products"],
        "optional": ["brand_guidelines", "dimensions"],
    },
    "video_marketing": {
        "provides": ["video_scripts", "storyboards"],
        "requires": ["products"],
        "optional": ["duration", "platform", "style"],
    },
    "tag_management": {
        "provides": ["product_tags"],
        "requires": ["products"],
        "optional": ["taxonomy", "existing_tags"],
    },
}

GOAL_ENGINE_MAP = {
    "write_descriptions": ["product_description"],
    "generate_blog": ["content_generation", "search_optimization"],
    "optimize_seo": ["search_optimization", "content_generation"],
    "create_visuals": ["image_optimization", "video_marketing"],
    "full_content": ["product_description", "content_generation", "search_optimization", "image_optimization", "video_marketing"],
}

DEFAULT_ENGINES = ["product_description", "search_optimization"]


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Content Agent."""
    return create_plan_base(
        goal, context, constraints,
        engine_capabilities=ENGINE_CAPABILITIES,
        goal_engine_map=GOAL_ENGINE_MAP,
        default_engines=DEFAULT_ENGINES,
        build_engine_input=_build_engine_input,
        get_dependencies=_get_dependencies,
        determine_strategy=_determine_strategy,
    )


def _build_engine_input(engine_name: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Build the input payload for a specific engine."""
    products = context.get("products", [])

    if engine_name == "product_description":
        return wrap_engine_input({
            "products": products,
            "tone": context.get("tone", "professional"),
            "keywords": context.get("keywords", []),
            "competitors": context.get("competitors", []),
        })

    if engine_name == "content_generation":
        return wrap_engine_input({
            "topics": context.get("topics", []),
            "tone": context.get("tone", "professional"),
            "audience": context.get("audience", ""),
            "word_count": context.get("word_count", 800),
        })

    if engine_name == "search_optimization":
        return wrap_engine_input({
            "content": context.get("content", ""),
            "target_keywords": context.get("target_keywords", []),
            "competitors": context.get("competitors", []),
        })

    if engine_name == "image_optimization":
        return wrap_engine_input({
            "products": products,
            "brand_guidelines": context.get("brand_guidelines", {}),
            "dimensions": context.get("dimensions", {}),
        })

    if engine_name == "video_marketing":
        return wrap_engine_input({
            "products": products,
            "duration": context.get("duration", 60),
            "platform": context.get("platform", ""),
            "style": context.get("style", ""),
        })

    if engine_name == "tag_management":
        return wrap_engine_input({
            "products": products,
            "taxonomy": context.get("taxonomy", {}),
            "existing_tags": context.get("existing_tags", []),
        })

    # Defensive fallback: never leak context. Pass 35.
    return wrap_engine_input({})


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    if engine_name == "search_optimization":
        if any(s["name"] == "product_description" for s in existing_steps):
            return ["product_description"]
        if any(s["name"] == "content_generation" for s in existing_steps):
            return ["content_generation"]
    if engine_name == "video_marketing" and any(s["name"] == "product_description" for s in existing_steps):
        return ["product_description"]
    return []


def _determine_strategy(goal: str, context: dict[str, Any]) -> str:
    """Determine content strategy."""
    if "quick" in goal or "fast" in goal:
        return "quick_draft"
    if "full" in goal or "thorough" in goal:
        return "full_content"
    if "seo" in goal or "search" in goal:
        return "seo_focused"
    if "blog" in goal or "article" in goal:
        return "editorial_focused"
    if "visual" in goal or "image" in goal or "video" in goal:
        return "visual_focused"
    if "description" in goal or "product" in goal:
        return "product_focused"
    return "balanced"
