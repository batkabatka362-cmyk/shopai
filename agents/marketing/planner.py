"""Marketing Agent planner — decides which engines to use and in what order.

Planning logic:
  1. Start with content generation (create the message)
  2. Then distribute across channels (email, social, etc.)
  3. Set up testing (A/B tests)
  4. Add amplification (influencer, affiliate)

If goal is specific:
  - "launch_campaign" → content, email, social, A/B testing
  - "email_campaign" → content, email
  - "social_campaign" → content, social, video
  - "influencer_campaign" → influencer, content, social
  - "full_marketing" → all engines
"""
from __future__ import annotations

from typing import Any


# Engine capabilities mapping
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

# Goal → engine mapping
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


def create_plan(goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Create an execution plan for the Marketing Agent.

    Returns list of engines to call, in order, with their inputs.
    """
    # Defensive: coerce caller args. Audit pass 35.
    goal = goal if isinstance(goal, str) else ""
    context = context if isinstance(context, dict) else {}
    constraints = constraints if isinstance(constraints, dict) else {}

    goal_lower = goal.lower().replace(" ", "_")
    engines_needed = _select_engines(goal_lower, context)

    # Build engine input for each
    steps = []
    for engine_name in engines_needed:
        engine_input = _build_engine_input(engine_name, context, constraints)
        steps.append({
            "name": engine_name,
            "purpose": (
                (ENGINE_CAPABILITIES.get(engine_name) or {}).get("provides")
                or ["unknown"]
            )[0],
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
    for key, engines in GOAL_ENGINE_MAP.items():
        if key in goal:
            return engines

    # Default: basic campaign pipeline
    return ["content_generation", "email_marketing", "social_media"]


def _build_engine_input(engine_name: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Build the input payload for a specific engine."""
    products = context.get("products", [])
    audiences = context.get("audiences", [])
    content = context.get("content", {})

    if engine_name == "content_generation":
        return {
            "status": "success",
            "data": {
                "products": products,
                "brand_voice": context.get("brand_voice", ""),
                "target_audience": context.get("target_audience", {}),
                "content_types": context.get("content_types", ["ad_copy", "marketing_copy"]),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "email_marketing":
        return {
            "status": "success",
            "data": {
                "content": content,
                "audiences": audiences,
                "send_schedule": context.get("send_schedule", {}),
                "segmentation": context.get("segmentation", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "social_media":
        return {
            "status": "success",
            "data": {
                "content": content,
                "platforms": context.get("platforms", ["instagram", "facebook", "tiktok"]),
                "hashtags": context.get("hashtags", []),
                "schedule": context.get("schedule", {}),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "ab_testing":
        return {
            "status": "success",
            "data": {
                "campaign_data": context.get("campaign_data", {}),
                "test_duration": context.get("test_duration", 7),
                "metrics": context.get("metrics", ["ctr", "conversion_rate"]),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "influencer":
        return {
            "status": "success",
            "data": {
                "products": products,
                "audience": context.get("target_audience", {}),
                "budget": constraints.get("budget", 0),
                "platforms": context.get("platforms", []),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "affiliate":
        return {
            "status": "success",
            "data": {
                "products": products,
                "commission_rates": context.get("commission_rates", {}),
                "partners": context.get("partners", []),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "landing_page":
        return {
            "status": "success",
            "data": {
                "content": content,
                "products": products,
                "templates": context.get("templates", []),
                "cta_variants": context.get("cta_variants", []),
            },
            "meta": {},
            "error": None,
        }

    if engine_name == "video_marketing":
        return {
            "status": "success",
            "data": {
                "products": products,
                "style": context.get("video_style", ""),
                "duration": context.get("video_duration", 30),
                "platforms": context.get("platforms", []),
            },
            "meta": {},
            "error": None,
        }

    # Defensive fallback: never leak the entire caller context.
    # Audit pass 35.
    return {"status": "success", "data": {}, "meta": {}, "error": None}


def _get_dependencies(engine_name: str, existing_steps: list[dict]) -> list[str]:
    """Determine which previous steps this engine depends on."""
    # Email marketing depends on content generation
    if engine_name == "email_marketing" and any(s["name"] == "content_generation" for s in existing_steps):
        return ["content_generation"]
    # Social media depends on content generation
    if engine_name == "social_media" and any(s["name"] == "content_generation" for s in existing_steps):
        return ["content_generation"]
    # A/B testing depends on content generation
    if engine_name == "ab_testing" and any(s["name"] == "content_generation" for s in existing_steps):
        return ["content_generation"]
    # Landing page depends on content generation
    if engine_name == "landing_page" and any(s["name"] == "content_generation" for s in existing_steps):
        return ["content_generation"]
    # Video marketing depends on content generation
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
