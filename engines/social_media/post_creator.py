"""Social Media Engine — post creator.

Creates post content for each platform: caption, visual description, CTA,
and platform-specific formatting notes.  Adapts tone and length to the
platform's character limits and audience expectations.

Model note: Uses LLaMA for creative post composition.
"""
from __future__ import annotations

import copy
from typing import Any


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
) -> dict[str, Any]:
    """Create post content for each entry in the content calendar.

    Args:
        calendar_entries: Entries from the content calendar builder.
        brand: Brand info dict with 'name' and 'voice'.
        goal: Campaign goal.
        products: Product list for rotating through posts.

    Returns:
        Structured dict with created posts.
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
                "model_note": "LLaMA: creative post composition",
            }
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
