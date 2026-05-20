"""Social Media Engine — post creator.

Creates post content for each platform: caption, visual
description, CTA, and platform-specific formatting notes.
Adapts tone and length to the platform's character limits and
audience expectations.

Multi-modal output (opt-in via ``generate_media=True``):

  * For image-type posts (single_image / photo / carousel /
    pin / etc.), calls ``Capability.GENERATE_IMAGE`` via the
    adapter router. DALL-E 3 is wired today; future
    free-tier image providers route in automatically once
    registered.
  * The post output gains ``media_url`` (URL or b64) +
    ``media_model`` fields so the publisher can pick up the
    asset directly. On any generation failure (no provider
    configured, network blip, validation reject), the post
    still publishes with the textual visual_description as
    before -- multi-modal degrades to text gracefully.

Video gen (Replicate / Higgsfield) is intentionally NOT in
this PR. Video is async + needs status polling; it's a
follow-up.
"""
from __future__ import annotations

import copy
import os
from typing import Any

from utils.logger import get_logger

logger = get_logger("engines.social_media.post_creator")


# ---------------------------------------------------------------------------
# Caption templates per goal
# ---------------------------------------------------------------------------

_CAPTION_TEMPLATES: dict[str, list[str]] = {
    "engagement": [
        "What do you think about {product}? Drop your thoughts below!",
        "We want to hear from YOU — {product} is here and it's a game-changer.",
        "Tag someone who needs {product} in their life!",
        "This or that? Tell us your pick in the comments.",
    ],
    "awareness": [
        "Introducing {product} by {brand} — crafted for those who demand more.",
        "Meet {product}. Built different, designed for you.",
        "The wait is over. {product} has arrived.",
        "Discover what makes {product} stand out from the rest.",
    ],
    "traffic": [
        "Tap the link in bio to explore {product} — you won't regret it.",
        "New on the site: {product}. Link in bio to shop now.",
        "{product} is live! Head to our store to grab yours.",
        "Don't just scroll — shop {product} today. Link in bio.",
    ],
    "conversions": [
        "Limited stock alert: {product} is selling fast. Grab yours now!",
        "{product} — because you deserve the best. Shop now before it's gone.",
        "Your cart is waiting. Add {product} and check out today.",
        "Flash deal on {product}! Don't miss out — shop the link in bio.",
    ],
}

_DEFAULT_CAPTIONS = [
    "Check out {product} by {brand} — now available!",
    "{product} is here. Explore the collection today.",
]

_CTA_MAP: dict[str, str] = {
    "engagement": "Comment below and let us know!",
    "awareness": "Follow us for more updates.",
    "traffic": "Tap the link in bio to learn more.",
    "conversions": "Shop now — link in bio!",
}

_VISUAL_DESCRIPTIONS: dict[str, str] = {
    "reels": "Short-form vertical video (9:16) with dynamic transitions, text overlays, and trending audio.",
    "carousel": "Multi-slide square images (1:1) with consistent branding, each slide advancing the story.",
    "story": "Full-screen vertical (9:16) ephemeral content with stickers, polls, or countdown elements.",
    "single_image": "High-quality square or portrait image with clean composition and brand colors.",
    "video": "Landscape or square video with captions, brand intro, and clear CTA at the end.",
    "link_post": "Thumbnail image with compelling headline overlay and brand logo placement.",
    "photo": "Candid or styled product photo with natural lighting and lifestyle context.",
    "live": "Live broadcast setup with good lighting, branded backdrop, and engagement prompts.",
    "event": "Event banner graphic with date, time, and brand identity.",
    "short_video": "Vertical video (9:16) under 60 seconds, hook in first 3 seconds, trending sound.",
    "duet": "Split-screen vertical video reacting to or complementing trending content.",
    "stitch": "Video that incorporates a clip from another creator with your branded response.",
    "standard_pin": "Vertical image (2:3 ratio) with text overlay, product shot, and brand URL.",
    "idea_pin": "Multi-page vertical pin with step-by-step content and branded elements.",
    "video_pin": "Short vertical video pin with product demo and text captions.",
    "product_pin": "Product image with price, availability, and direct shopping link.",
    "thread": "Multi-tweet narrative with numbered posts, each under 280 characters.",
    "single_tweet": "Concise text post with one strong hook and relevant hashtags.",
    "poll": "Engaging poll with 2-4 options related to brand or product.",
    "space": "Live audio discussion with topic agenda and speaker introductions.",
    "quote_tweet": "Re-share of relevant content with branded commentary.",
}

_DEFAULT_VISUAL = "Clean, on-brand visual content with product focus and clear composition."


# ---------------------------------------------------------------------------
# Platform-specific formatting guidance
# ---------------------------------------------------------------------------

_FORMATTING_NOTES: dict[str, str] = {
    "instagram": "Use line breaks for readability. Place hashtags in first comment or after a line break. Emoji-friendly.",
    "facebook": "Longer captions OK. Use questions to drive comments. Include link directly in post if driving traffic.",
    "tiktok": "Keep caption short — the video does the talking. Use 3-5 hashtags max. Hook in first line.",
    "pinterest": "Focus on searchable keywords in description. Include relevant board context. CTA should be soft.",
    "twitter": "Stay under 280 chars per tweet. Use threads for longer narratives. 1-3 hashtags max.",
}

_DEFAULT_FORMATTING = "Keep caption clear and on-brand. Use platform-appropriate hashtags and CTA."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_posts(
    calendar_entries: list[dict[str, Any]],
    brand: dict[str, Any],
    goal: str,
    products: list[dict[str, Any]],
    *,
    generate_media: bool = False,
) -> dict[str, Any]:
    """Create post content for each entry in the content calendar.

    Args:
        calendar_entries: Entries from the content calendar builder.
        brand: Brand info dict with 'name' and 'voice'.
        goal: Campaign goal.
        products: Product list for rotating through posts.
        generate_media: Opt-in. When True, image-type posts get
            an AI-generated visual via ``Capability.GENERATE_IMAGE``
            (DALL-E 3 or whichever provider is configured). Default
            False so legacy callers + cost-sensitive cycles stay
            unchanged.

    Returns:
        Structured dict with created posts. Each post carries
        ``platform``, ``post_type``, ``caption``,
        ``visual_description``, ``cta``, ``formatting_notes``,
        ``model_note``, and -- when ``generate_media`` is True
        and the generation succeeded -- ``media_url`` (or
        ``media_b64``) + ``media_model``.
    """
    try:
        calendar_entries = copy.deepcopy(calendar_entries)
        brand = copy.deepcopy(brand)
        products = copy.deepcopy(products)

        brand_name = str(brand.get("name", "Our Brand")).strip() or "Our Brand"
        brand_voice = str(brand.get("voice", "professional")).strip().lower()
        templates = _CAPTION_TEMPLATES.get(goal, _DEFAULT_CAPTIONS)
        cta = _CTA_MAP.get(goal, "Learn more — link in bio.")

        posts: list[dict[str, Any]] = []

        for i, entry in enumerate(calendar_entries):
            platform = str(entry.get("platform", "")).lower().strip()
            post_type = str(entry.get("post_type", "image")).lower().strip()

            # Rotate through products
            product = _pick_product(products, i)
            product_title = product.get("title", "our latest product")

            # Build caption from template
            template = templates[i % len(templates)]
            caption = template.format(product=product_title, brand=brand_name)

            # Adjust caption voice
            caption = _apply_voice(caption, brand_voice)

            visual = _VISUAL_DESCRIPTIONS.get(post_type, _DEFAULT_VISUAL)
            formatting = _FORMATTING_NOTES.get(platform, _DEFAULT_FORMATTING)

            post: dict[str, Any] = {
                "platform": platform,
                "post_type": post_type,
                "caption": caption,
                "visual_description": visual,
                "cta": cta,
                "formatting_notes": formatting,
                "model_note": "template fallback: caption built from per-goal templates",
            }

            # ── Multi-modal media generation (opt-in) ───────────
            if generate_media and _is_image_post_type(post_type):
                media = _generate_image_for_post(
                    product_title=product_title,
                    brand_name=brand_name,
                    brand_voice=brand_voice,
                    platform=platform,
                    post_type=post_type,
                    visual_description=visual,
                )
                if media is not None:
                    post["media_url"] = media.get("url", "")
                    post["media_b64"] = media.get("b64", "")
                    post["media_model"] = media.get("model", "")
                    post["media_size"] = media.get("size", "")

            posts.append(post)

        return {
            "status": "success",
            "posts": posts,
        }
    except Exception as exc:
        return {
            "status": "error",
            "posts": [],
            "error": f"Post creation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Multi-modal media generation
# ---------------------------------------------------------------------------


# post_types that map to a still image (vs video). Video
# generation is async + heavier; deferred to a follow-up PR.
_IMAGE_POST_TYPES: frozenset[str] = frozenset({
    "single_image", "carousel", "photo", "link_post",
    "standard_pin", "idea_pin", "product_pin",
    "image",
})


def _is_image_post_type(post_type: str) -> bool:
    return post_type in _IMAGE_POST_TYPES


# Platform-aspect-ratio map. DALL-E 3 supports 1024x1024 /
# 1024x1792 / 1792x1024 only; map platforms to the closest
# native ratio.
_PLATFORM_TO_SIZE: dict[str, str] = {
    "instagram": "1024x1024",       # square is the IG sweet spot
    "facebook": "1024x1024",
    "tiktok": "1024x1792",          # vertical 9:16 closest
    "pinterest": "1024x1792",       # tall pins rank higher
    "twitter": "1792x1024",         # landscape for tweets
}
_DEFAULT_SIZE = "1024x1024"


def _generate_image_for_post(
    *,
    product_title: str,
    brand_name: str,
    brand_voice: str,
    platform: str,
    post_type: str,
    visual_description: str,
) -> dict[str, Any] | None:
    """Generate an AI image for a social post via the router.

    Returns ``{url, b64, model, size}`` on success or ``None``
    on any failure (caller publishes the post without media).
    Never raises.
    """
    # Pattern J -- never make live API calls under pytest.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None

    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("media gen: router import failed: %s", exc)
        return None

    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("media gen: router init failed: %s", exc)
        return None

    size = _PLATFORM_TO_SIZE.get(platform, _DEFAULT_SIZE)
    prompt = _build_image_prompt(
        product_title=product_title,
        brand_name=brand_name,
        brand_voice=brand_voice,
        platform=platform,
        post_type=post_type,
        visual_description=visual_description,
    )

    try:
        result = router.execute(Capability.GENERATE_IMAGE, {
            "prompt": prompt,
            "size": size,
            "quality": "standard",
            "n": 1,
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug("media gen: GENERATE_IMAGE raised: %s", exc)
        return None

    if not getattr(result, "ok", False):
        logger.debug(
            "media gen: GENERATE_IMAGE not-ok: %s",
            getattr(result, "error", "unknown"),
        )
        return None

    data = result.data or {}
    if not isinstance(data, dict):
        return None

    # The image adapter contract returns ``{images: [...]}``
    # with each image being ``{url, b64_json, revised_prompt}``.
    images = data.get("images") or []
    if not isinstance(images, list) or not images:
        return None
    first = images[0]
    if not isinstance(first, dict):
        return None

    return {
        "url": str(first.get("url") or "").strip(),
        "b64": str(first.get("b64_json") or "").strip(),
        "model": str(data.get("model") or "").strip(),
        "size": size,
    }


def _build_image_prompt(
    *,
    product_title: str,
    brand_name: str,
    brand_voice: str,
    platform: str,
    post_type: str,
    visual_description: str,
) -> str:
    """Build a clear image-gen prompt grounded in brand + product context."""
    voice_phrase = {
        "professional": "clean, premium, editorial photography style",
        "casual": "candid lifestyle photography with natural lighting",
        "playful": "vibrant, fun, slightly exaggerated colors",
        "luxury": "moody, high-contrast luxury aesthetic",
        "minimal": "minimal flat lay, neutral background, single focal point",
        "bold": "high-contrast, oversaturated, billboard-aggressive composition",
    }.get(brand_voice, "clean, professional product photography")

    return (
        f"Photorealistic product image for a {platform} {post_type} post. "
        f"Subject: {product_title} by {brand_name}. "
        f"Visual style: {voice_phrase}. "
        f"Composition guidance: {visual_description}. "
        f"No text overlay, no logos other than the product's. "
        f"On-brand for {brand_name}."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pick_product(products: list[dict[str, Any]], index: int) -> dict[str, Any]:
    """Pick a product by rotating through the list."""
    if not products:
        return {"title": "our latest product", "category": "general"}
    return products[index % len(products)]


def _apply_voice(caption: str, voice: str) -> str:
    """Lightly adjust caption tone based on brand voice."""
    if voice == "playful":
        caption = caption.replace(".", "! ").replace("!", "! ").strip()
        if not caption.endswith(("!", "?")):
            caption += " ✨"
    elif voice == "bold":
        caption = caption.upper() if len(caption) < 100 else caption
    elif voice == "minimal":
        # Strip excess punctuation, keep it clean
        caption = caption.replace("!", ".").replace("!!", ".")
    # "professional" — no adjustment needed
    return caption
