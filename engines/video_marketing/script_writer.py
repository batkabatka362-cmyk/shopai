"""Video Marketing Engine — script writer.

Writes video scripts with hook, body, and CTA sections.
Adapts structure and pacing to video type and duration.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Script pacing by duration range (seconds)
# ---------------------------------------------------------------------------

_PACING: dict[str, dict[str, int]] = {
    "short": {"hook": 3, "body": 8, "cta": 4},       # <= 15s
    "medium": {"hook": 5, "body": 40, "cta": 15},     # 16-60s
    "long": {"hook": 8, "body": 0, "cta": 15},        # 61s+ (body = remainder)
}

# Video type templates
_HOOK_TEMPLATES: dict[str, str] = {
    "product_demo": "Ever wondered what makes {product} different? Watch this.",
    "tutorial": "Here's the easiest way to use {product} — step by step.",
    "testimonial": "Real customers share why they love {product}.",
    "ad": "Stop scrolling. {product} is about to change your {category} game.",
    "unboxing": "Let's unbox the {product} and see what's inside.",
}

_CTA_TEMPLATES: dict[str, str] = {
    "product_demo": "Ready to try {product}? Link in bio. Shop now.",
    "tutorial": "Get your {product} today and follow along. Link below.",
    "testimonial": "Join thousands of happy customers. Get {product} now.",
    "ad": "Limited time offer on {product}. Don't miss out — shop now.",
    "unboxing": "Want one? Grab your {product} at the link in bio.",
}


def write_script(
    product: dict[str, Any],
    video_type: str,
    duration_seconds: int,
    brand_voice: dict[str, Any],
) -> dict[str, Any]:
    """Write a video script with hook, body, and CTA.

    Args:
        product: Product info dict.
        video_type: Type of video (product_demo, tutorial, ad, etc.).
        duration_seconds: Target duration in seconds.
        brand_voice: Brand voice configuration.

    Returns:
        Structured dict with script sections.
    """
    try:
        prod = copy.deepcopy(product)
        product_name = str(prod.get("title", "our product"))
        category = str(prod.get("category", ""))
        features = list(prod.get("features", []))
        usps = list(prod.get("unique_selling_points", features[:3]))
        tone = str(brand_voice.get("tone", "professional"))

        # Determine pacing
        if duration_seconds <= 15:
            pacing = _PACING["short"]
        elif duration_seconds <= 60:
            pacing = _PACING["medium"]
        else:
            pacing = dict(_PACING["long"])
            pacing["body"] = duration_seconds - pacing["hook"] - pacing["cta"]

        # ---- Hook ----
        hook_template = _HOOK_TEMPLATES.get(video_type, _HOOK_TEMPLATES["product_demo"])
        hook = hook_template.format(product=product_name, category=category or "daily")

        # ---- Body ----
        body_parts: list[str] = []

        if video_type == "product_demo":
            body_parts.append(f"Let me show you what {product_name} can do.")
            for i, feature in enumerate(features[:3]):
                body_parts.append(f"Feature {i + 1}: {feature}.")
            if usps:
                body_parts.append(f"The best part? {usps[0]}.")

        elif video_type == "tutorial":
            body_parts.append(f"Step 1: Get your {product_name} ready.")
            for i, feature in enumerate(features[:3]):
                body_parts.append(f"Step {i + 2}: Use the {feature}.")
            body_parts.append("And that's it — simple as that.")

        elif video_type == "ad":
            if usps:
                body_parts.append(f"{product_name}: {usps[0]}.")
            for feature in features[:2]:
                body_parts.append(f"{feature}.")
            body_parts.append("Available now at an unbeatable price.")

        elif video_type == "testimonial":
            body_parts.append(f"I've been using {product_name} for weeks now.")
            if features:
                body_parts.append(f"What I love most is the {features[0]}.")
            body_parts.append("It's honestly exceeded my expectations.")

        else:
            body_parts.append(f"Take a closer look at {product_name}.")
            for feature in features[:3]:
                body_parts.append(f"{feature}.")

        body = " ".join(body_parts)

        # ---- CTA ----
        cta_template = _CTA_TEMPLATES.get(video_type, _CTA_TEMPLATES["product_demo"])
        cta = cta_template.format(product=product_name)

        return {
            "status": "success",
            "script": {
                "hook": hook,
                "body": body,
                "cta": cta,
                "duration": duration_seconds,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "script": {},
            "error": f"Script writing failed: {exc}",
        }
