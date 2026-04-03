"""Content Agent planner — decides which engines to use and in what order.

Planning logic:
  1. Product Description for listing copy
  2. Content Generation for blog and ad copy
  3. Search Optimization for SEO readiness
  4. Image Optimization for visual assets
  5. Video Marketing for video scripts
  6. Tag Management for product taxonomy

If goal is specific:
  - "write_descriptions" → Product Description only
  - "generate_blog" → Content Generation + Search Optimization
  - "optimize_seo" → Search Optimization + Content Generation
  - "create_visuals" → Image Optimization + Video Marketing
  - "full_content" → all content engines
"""
from __future__ import annotations

from typing import Any


# Engine capabilities mapping
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

# Goal → engine mapping
GOAL_ENGINE_MAP = {
    "write_descriptions": ["product_description"],
    "generate_blog": ["content_generation", "search_optimization"],
    "optimize_seo": ["search_optimization", "content_generation"],
    "create_visuals": ["image_optimization", "video_marketing"],
    "full_content": ["product_description", "content_generation", "search_optimization", "image_optimization", "video_marketing"],
}


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Content Agent.

    Returns list of engines to call, in order, with their inputs.
    """
    # Determine which engines to use
    goal_lower = goal.lower().replace(" ", "_")
    engines_needed = _select_engines(goal_lower, context)

    # Build engine input for each
    steps = []
    for engine_name in engines_needed:
        engine_input = _build_engine_input(engine_name, context, constraints)
        steps.append({
            "name": engine_name,
            "purpose": ENGINE_CAPABILITIES[engine_name]["provides"][0],
            "input": engine_input,
            "depends_on": _get_dependencies(engine_name, steps),
        })

    # Determine strategy
    strategy = _determine_strategy(goal_lower, context)

    return {
        "engines": steps,
        "strategy": strategy,
        "estimated_steps": len(steps),
        "goal": goal,
    }


def _select_engines(goal: str, context: dict[str, Any]) -> list[str]:
    """Select which engines to use based on goal."""
    # Check goal mapping
    for key, engines in GOAL_ENGINE_MAP.items():
        if key in goal:
            return engines

    # Default: descriptions + SEO
    return ["product_description", "search_optimization"]


def _build_engine_input(engine_name: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Build the input payload for a specific engine."""
    products = context.get("products", [])

    if engine_name == "product_description":
        return {
            "status": "success",
            "data": {
                "products": products,
                "tone": context.get("tone", "professional"),
                "keywords": context.get("keywords", []),
                "competitors": context.get("competitors", []),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "content_generation":
        return {
            "status": "success",
            "data": {
                "topics": context.get("topics", []),
                "tone": context.get("tone", "professional"),
                "audience": context.get("audience", ""),
                "word_count": context.get("word_count", 800),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "search_optimization":
        return {
            "status": "success",
            "data": {
                "content": context.get("content", ""),
                "target_keywords": context.get("target_keywords", []),
                "competitors": context.get("competitors", []),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "image_optimization":
        return {
            "status": "success",
            "data": {
                "products": products,
                "brand_guidelines": context.get("brand_guidelines", {}),
                "dimensions": context.get("dimensions", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "video_marketing":
        return {
            "status": "success",
            "data": {
                "products": products,
                "duration": context.get("duration", 60),
                "platform": context.get("platform", ""),
                "style": context.get("style", ""),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "tag_management":
        return {
            "status": "success",
            "data": {
                "products": products,
                "taxonomy": context.get("taxonomy", {}),
                "existing_tags": context.get("existing_tags", []),
            },
            "meta": {},
            "error": None,
        }

    return {"status": "success", "data": context, "meta": {}, "error": None}


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    # Search optimization can use product descriptions or generated content
    if engine_name == "search_optimization":
        if any(s["name"] == "product_description" for s in existing_steps):
            return ["product_description"]
        if any(s["name"] == "content_generation" for s in existing_steps):
            return ["content_generation"]
    # Video marketing can use product descriptions
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
