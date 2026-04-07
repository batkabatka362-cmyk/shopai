"""Marketing Agent planner — decides which engines to use and in what order.

Thin wrapper around ``agents.base.planner.create_plan_base``.
"""
from __future__ import annotations

from typing import Any

from agents.base.planner import create_plan_base, wrap_engine_input


ENGINE_CAPABILITIES = {
    "content_generation": {
        "provides": ["marketing_copy", "ad_copy"],
        "requires": ["products"],
        "optional": ["brand_voice", "target_audience"],
    },
    "email_marketing": {
        "provides": ["email_campaigns"],
        "requires": ["content", "audiences"],
        "optional": ["send_schedule", "segmentation"],
    },
    "social_media": {
        "provides": ["social_posts"],
        "requires": ["content"],
        "optional": ["platforms", "hashtags", "schedule"],
    },
    "ab_testing": {
        "provides": ["test_plans"],
        "requires": ["campaign_data"],
        "optional": ["test_duration", "metrics"],
    },
    "influencer": {
        "provides": ["influencer_plan"],
        "requires": ["products", "audience"],
        "optional": ["budget", "platforms"],
    },
    "affiliate": {
        "provides": ["affiliate_plan"],
        "requires": ["products"],
        "optional": ["commission_rates", "partners"],
    },
    "landing_page": {
        "provides": ["landing_pages"],
        "requires": ["content", "products"],
        "optional": ["templates", "cta_variants"],
    },
    "video_marketing": {
        "provides": ["video_scripts"],
        "requires": ["products"],
        "optional": ["style", "duration", "platforms"],
    },
}

GOAL_ENGINE_MAP = {
    "launch_campaign": ["content_generation", "email_marketing", "social_media", "ab_testing"],
    "email_campaign": ["content_generation", "email_marketing"],
    "social_campaign": ["content_generation", "social_media", "video_marketing"],
    "influencer_campaign": ["influencer", "content_generation", "social_media"],
    "full_marketing": [
        "content_generation", "email_marketing", "social_media", "ab_testing",
        "influencer", "affiliate", "landing_page", "video_marketing",
    ],
}

DEFAULT_ENGINES = ["content_generation", "email_marketing", "social_media"]


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Marketing Agent."""
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
    audiences = context.get("audiences", [])
    content = context.get("content", {})

    if engine_name == "content_generation":
        return wrap_engine_input({
            "products": products,
            "brand_voice": context.get("brand_voice", ""),
            "target_audience": context.get("target_audience", {}),
            "content_types": context.get("content_types", ["ad_copy", "marketing_copy"]),
        })

    if engine_name == "email_marketing":
        return wrap_engine_input({
            "content": content,
            "audiences": audiences,
            "send_schedule": context.get("send_schedule", {}),
            "segmentation": context.get("segmentation", {}),
        })

    if engine_name == "social_media":
        return wrap_engine_input({
            "content": content,
            "platforms": context.get("platforms", ["instagram", "facebook", "tiktok"]),
            "hashtags": context.get("hashtags", []),
            "schedule": context.get("schedule", {}),
        })

    if engine_name == "ab_testing":
        return wrap_engine_input({
            "campaign_data": context.get("campaign_data", {}),
            "test_duration": context.get("test_duration", 7),
            "metrics": context.get("metrics", ["ctr", "conversion_rate"]),
        })

    if engine_name == "influencer":
        return wrap_engine_input({
            "products": products,
            "audience": context.get("target_audience", {}),
            "budget": constraints.get("budget", 0),
            "platforms": context.get("platforms", []),
        })

    if engine_name == "affiliate":
        return wrap_engine_input({
            "products": products,
            "commission_rates": context.get("commission_rates", {}),
            "partners": context.get("partners", []),
        })

    if engine_name == "landing_page":
        return wrap_engine_input({
            "content": content,
            "products": products,
            "templates": context.get("templates", []),
            "cta_variants": context.get("cta_variants", []),
        })

    if engine_name == "video_marketing":
        return wrap_engine_input({
            "products": products,
            "style": context.get("video_style", ""),
            "duration": context.get("video_duration", 30),
            "platforms": context.get("platforms", []),
        })

    # Defensive fallback: never leak context. Pass 35.
    return wrap_engine_input({})


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    if engine_name == "email_marketing" and any(s["name"] == "content_generation" for s in existing_steps):
        return ["content_generation"]
    if engine_name == "social_media" and any(s["name"] == "content_generation" for s in existing_steps):
        return ["content_generation"]
    if engine_name == "ab_testing" and any(s["name"] == "content_generation" for s in existing_steps):
        return ["content_generation"]
    if engine_name == "landing_page" and any(s["name"] == "content_generation" for s in existing_steps):
        return ["content_generation"]
    if engine_name == "video_marketing" and any(s["name"] == "content_generation" for s in existing_steps):
        return ["content_generation"]
    return []


def _determine_strategy(goal: str, context: dict[str, Any]) -> str:
    """Determine marketing strategy."""
    if "quick" in goal or "fast" in goal:
        return "quick_launch"
    if "full" in goal:
        return "full_funnel"
    if "email" in goal:
        return "email_focused"
    if "social" in goal:
        return "social_focused"
    if "influencer" in goal:
        return "influencer_driven"
    if "launch" in goal:
        return "campaign_launch"
    return "balanced"
