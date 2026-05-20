"""Landing Page Engine — page generator.

Generates a complete landing page structure from product data,
campaign context, and brand voice. Produces headline, subheadline,
hero section, benefits list, CTA, and social proof.

Two paths, in priority order (same pattern as
``engines/content_generation/copy_writer.py``):

  1. **LLM path** (preferred). Builds a structured prompt from
     the product / campaign / audience / voice inputs and calls
     ``Capability.CHAT_COMPLETE`` via the adapter router. The
     model returns JSON in the canonical ``{headline,
     subheadline, hero_section, benefits, cta, social_proof}``
     shape.

  2. **Template path** (fallback). Deterministic
     ``_build_*`` helpers below. Used when no LLM is
     configured, when the LLM call times out / errors, when the
     JSON parse fails, or under pytest (Pattern J guard).

The template path makes the engine usable in any environment;
the LLM path is what turns generic template prose into
brand-tuned, conversion-focused landing copy.
"""
from __future__ import annotations

import copy
import json
import os
import re
from typing import Any

from utils.logger import get_logger

logger = get_logger("engines.landing_page.generator")


# ---------------------------------------------------------------------------
# Copywriting frameworks by brand voice
# ---------------------------------------------------------------------------

_VOICE_MODIFIERS = {
    "professional": {"tone": "clear and authoritative", "cta_style": "direct"},
    "casual": {"tone": "friendly and approachable", "cta_style": "conversational"},
    "luxury": {"tone": "elegant and exclusive", "cta_style": "aspirational"},
    "urgent": {"tone": "compelling and time-sensitive", "cta_style": "scarcity"},
    "technical": {"tone": "precise and data-driven", "cta_style": "logical"},
}


def generate_page(
    product: dict[str, Any],
    campaign: dict[str, Any],
    target_audience: str,
    brand_voice: str,
) -> dict[str, Any]:
    """Generate a landing page structure from product and campaign data.

    Tries the LLM path first; on any failure (no provider
    configured, network blip, malformed JSON) falls back to the
    deterministic template path so the engine output stays valid
    in every environment.

    Args:
        product: Product data dict.
        campaign: Campaign context dict.
        target_audience: Description of the target audience.
        brand_voice: Brand voice style (professional, casual, luxury, etc.).

    Returns:
        Structured dict with page structure.
    """
    try:
        product = copy.deepcopy(product)
        campaign = copy.deepcopy(campaign)

        title = str(product.get("title", "Our Product"))
        description = str(product.get("description", ""))
        price = float(product.get("price", 0))
        features = list(product.get("features", []))
        category = str(product.get("category", ""))

        campaign_goal = str(campaign.get("goal", "conversion"))
        channel = str(campaign.get("channel", "web"))

        voice_key = brand_voice.lower() if isinstance(brand_voice, str) else "professional"
        voice = _VOICE_MODIFIERS.get(voice_key, _VOICE_MODIFIERS["professional"])

        layout = "single_column" if channel == "mobile" else "standard"

        # ── Path 1: LLM-driven generation ────────────────────────
        llm_page = _generate_page_via_llm(
            title=title,
            description=description,
            price=price,
            features=features,
            category=category,
            target_audience=target_audience,
            brand_voice=voice_key,
            voice=voice,
            campaign_goal=campaign_goal,
            channel=channel,
            layout=layout,
        )
        if llm_page is not None:
            return {"status": "success", "page": llm_page}

        # ── Path 2: Deterministic template fallback ──────────────
        headline = _build_headline(title, features, campaign_goal, voice)
        subheadline = _build_subheadline(title, description, target_audience, voice)
        hero_section = _build_hero(title, description, price, campaign_goal)
        benefits = _build_benefits(features, category)
        cta = _build_cta(campaign_goal, price, voice)
        social_proof = _build_social_proof(category, campaign_goal)

        page = {
            "headline": headline,
            "subheadline": subheadline,
            "hero_section": hero_section,
            "benefits": benefits,
            "cta": cta,
            "social_proof": social_proof,
            "layout": layout,
        }

        return {
            "status": "success",
            "page": page,
        }
    except Exception as exc:
        return {
            "status": "error",
            "page": {},
            "error": f"Page generation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# LLM-driven path
# ---------------------------------------------------------------------------


def _generate_page_via_llm(
    *,
    title: str,
    description: str,
    price: float,
    features: list[Any],
    category: str,
    target_audience: str,
    brand_voice: str,
    voice: dict[str, str],
    campaign_goal: str,
    channel: str,
    layout: str,
) -> dict[str, Any] | None:
    """Try to generate landing page copy via an LLM through the router.

    Returns the page dict on success, or ``None`` on any failure
    so the caller falls back to the deterministic template path.
    Never raises out.
    """
    # Pattern J: never call live LLMs under pytest. Tests that
    # specifically exercise the LLM path mock the router.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None

    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM router import failed: %s", exc)
        return None

    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM router init failed: %s", exc)
        return None

    system_prompt = _build_llm_system_prompt(brand_voice, voice, campaign_goal)
    user_prompt = _build_llm_user_prompt(
        title=title,
        description=description,
        price=price,
        features=features,
        category=category,
        target_audience=target_audience,
        campaign_goal=campaign_goal,
        channel=channel,
    )

    try:
        result = router.execute(Capability.CHAT_COMPLETE, {
            "system": system_prompt,
            "prompt": user_prompt,
            "max_tokens": 1200,
            "temperature": 0.7,
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM call raised: %s", exc)
        return None

    if not getattr(result, "ok", False):
        logger.debug(
            "LLM call returned not-ok: %s",
            getattr(result, "error", "unknown"),
        )
        return None

    text = ((result.data or {}).get("text") or "").strip()
    if not text:
        return None

    parsed = _parse_llm_json(text)
    if not parsed:
        return None

    # Validate the minimum-viable shape. Without headline OR
    # cta, the rendered page is unusable -- fall back to template.
    headline = str(parsed.get("headline") or "").strip()
    cta = str(parsed.get("cta") or "").strip()
    if not headline or not cta:
        return None

    subheadline = str(parsed.get("subheadline") or "").strip()
    hero_section = str(parsed.get("hero_section") or "").strip()
    social_proof = str(parsed.get("social_proof") or "").strip()

    benefits_raw = parsed.get("benefits") or []
    benefits = [
        str(b).strip() for b in benefits_raw if str(b).strip()
    ][:8]
    # Benefits is the load-bearing structural element of a landing
    # page; an empty list is a degenerate result -> fall back.
    if not benefits:
        return None

    return {
        "headline": headline,
        "subheadline": subheadline,
        "hero_section": hero_section,
        "benefits": benefits,
        "cta": cta,
        "social_proof": social_proof,
        "layout": layout,
    }


def _build_llm_system_prompt(
    brand_voice: str,
    voice: dict[str, str],
    campaign_goal: str,
) -> str:
    """Build the system prompt that primes the LLM as a Shopify
    landing-page copywriter with the right voice + goal."""
    tone = voice.get("tone", "clear and authoritative")
    cta_style = voice.get("cta_style", "direct")
    return (
        "You are an expert Shopify conversion copywriter. You write "
        "landing pages that convert. Brand voice: "
        f"{brand_voice} ({tone}). Campaign goal: "
        f"{campaign_goal}. Preferred CTA style: {cta_style}. "
        "Write benefit-first (not feature-first) -- every line should "
        "answer 'what does the visitor get?'. Concrete > vague: "
        "use numbers, comparisons, specific outcomes. "
        "Always respond with STRICT JSON in the requested shape; no "
        "markdown fences, no commentary outside the JSON."
    )


def _build_llm_user_prompt(
    *,
    title: str,
    description: str,
    price: float,
    features: list[Any],
    category: str,
    target_audience: str,
    campaign_goal: str,
    channel: str,
) -> str:
    """Build the user prompt with product + campaign context."""
    price_str = f"${price:.2f}" if price and float(price) > 0 else "n/a"
    desc_excerpt = description[:400] if description else "(no description provided)"

    return (
        f"Write a {channel} landing page for the following Shopify product.\n\n"
        f"Product: {title}\n"
        f"Category: {category or 'n/a'}\n"
        f"Price: {price_str}\n"
        f"Description excerpt: {desc_excerpt}\n"
        f"Features:\n"
        + "\n".join(f"  - {f}" for f in features[:10]) + "\n"
        + f"Target audience: {target_audience}\n"
        + f"Campaign goal: {campaign_goal}\n\n"
        + "Return STRICT JSON in this exact shape:\n"
        + "{\n"
        + '  "headline": "primary value-proposition headline",\n'
        + '  "subheadline": "1-sentence supporting line",\n'
        + '  "hero_section": "2-3 sentence hero paragraph",\n'
        + '  "benefits": ["benefit 1", "benefit 2", "benefit 3", ...],\n'
        + '  "cta": "call-to-action phrase",\n'
        + '  "social_proof": "1-sentence trust signal"\n'
        + "}"
    )


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON parse of an LLM response.

    Tolerates the model wrapping the JSON in markdown fences or
    prefixing it with commentary -- locks onto the outermost
    ``{...}`` block.
    """
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        pass
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_headline(
    title: str,
    features: list[str],
    goal: str,
    voice: dict[str, str],
) -> str:
    """Build a headline based on product and goal."""
    key_benefit = features[0] if features else "quality and value"

    if goal == "awareness":
        return f"Discover {title} — {key_benefit.title()}"
    elif goal == "retention":
        return f"Still Loving {title}? See What's New"
    else:  # conversion
        return f"Get {title} — {key_benefit.title()} You Can Count On"


def _build_subheadline(
    title: str,
    description: str,
    target_audience: str,
    voice: dict[str, str],
) -> str:
    """Build a supporting subheadline."""
    if description:
        # Use first sentence of description
        first_sentence = description.split(".")[0].strip()
        if len(first_sentence) <= 120:
            return first_sentence + "."
        return first_sentence[:117] + "..."
    return f"Built for {target_audience} who demand the best."


def _build_hero(title: str, description: str, price: float, goal: str) -> str:
    """Build the hero section content."""
    parts = []
    if description:
        parts.append(description[:200])
    if price > 0:
        parts.append(f"Starting at ${price:.2f}")
    if goal == "conversion" and price > 0:
        parts.append("Free shipping on all orders.")
    return " | ".join(parts) if parts else f"Experience {title} today."


def _build_benefits(features: list[str], category: str) -> list[str]:
    """Convert product features into benefit-oriented bullet points."""
    if not features:
        return [
            "Premium quality materials",
            "Designed for everyday use",
            "Backed by our satisfaction guarantee",
        ]

    benefits = []
    for feature in features[:6]:
        feature = str(feature).strip()
        if feature:
            # Transform feature into benefit language
            if any(w in feature.lower() for w in ["fast", "quick", "speed"]):
                benefits.append(f"Save time with {feature.lower()}")
            elif any(w in feature.lower() for w in ["durable", "strong", "lasting"]):
                benefits.append(f"Built to last — {feature.lower()}")
            elif any(w in feature.lower() for w in ["easy", "simple", "intuitive"]):
                benefits.append(f"No learning curve — {feature.lower()}")
            else:
                benefits.append(feature)

    return benefits if benefits else ["Quality you can trust"]


def _build_cta(goal: str, price: float, voice: dict[str, str]) -> str:
    """Build a call-to-action based on campaign goal and voice."""
    style = voice.get("cta_style", "direct")

    ctas = {
        ("conversion", "direct"): "Buy Now" if price > 0 else "Get Started",
        ("conversion", "conversational"): "Yes, I Want This!" if price > 0 else "Let's Go!",
        ("conversion", "aspirational"): "Elevate Your Experience",
        ("conversion", "scarcity"): "Claim Yours Before They're Gone",
        ("conversion", "logical"): "See the Details & Order",
        ("awareness", "direct"): "Learn More",
        ("awareness", "conversational"): "Tell Me More",
        ("awareness", "aspirational"): "Explore the Collection",
        ("awareness", "scarcity"): "See What Everyone's Talking About",
        ("awareness", "logical"): "View Full Specifications",
        ("retention", "direct"): "Shop New Arrivals",
        ("retention", "conversational"): "See What's New!",
        ("retention", "aspirational"): "Continue Your Journey",
        ("retention", "scarcity"): "Exclusive Access — Shop Now",
        ("retention", "logical"): "Compare and Upgrade",
    }

    return ctas.get((goal, style), "Shop Now")


def _build_social_proof(category: str, goal: str) -> str:
    """Build a social proof section."""
    if goal == "conversion":
        return "Join thousands of satisfied customers who chose quality."
    elif goal == "awareness":
        return "Featured in leading publications and trusted by experts."
    else:
        return "Our returning customers speak for themselves."
