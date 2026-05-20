"""Content Generation Engine — copy writer.

Writes the actual marketing copy: headlines, body text, bullet points, and
calls-to-action, tailored to the content type and tone.

Two paths, in priority order:

  1. **LLM path** (preferred). Builds a structured prompt from the
     brief / tone / keyword / product / brand inputs and calls
     ``Capability.CHAT_COMPLETE`` via the adapter router. The
     router picks whichever LLM provider is configured first
     (Ollama local / Groq / Gemini / DeepSeek / Mistral / OpenAI /
     Anthropic, in that fallback order). The LLM returns JSON
     with the canonical ``{headline, body, bullets, cta,
     alt_headlines}`` shape, which we hand straight back to the
     caller.

  2. **Template path** (fallback). Pure string interpolation
     against the ``_CONTENT_TEMPLATES`` / ``_CTA_PHRASES`` /
     ``_TONE_ADJECTIVES`` constants. Used when no LLM is wired
     up, when the LLM call times out / errors, when the JSON
     parse fails, or under pytest (Pattern J guard).

The template path is deterministic and test-friendly; the LLM
path is what makes the AI behave at master-level (brand-tuned
voice, audience-aware framing, SEO-keyword woven naturally
into prose rather than awkward feature dumps).
"""
from __future__ import annotations

import copy
import json
import os
import re
from typing import Any

from utils.logger import get_logger

logger = get_logger("engines.content_generation.copy_writer")


# ---------------------------------------------------------------------------
# Content-type templates and constraints
# ---------------------------------------------------------------------------

_CONTENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "product_description": {
        "headline_pattern": "{benefit} — {product}",
        "body_length": (150, 300),
        "bullet_count": (3, 6),
        "cta_style": "purchase",
    },
    "ad_copy": {
        "headline_pattern": "{hook} {product}",
        "body_length": (25, 90),
        "bullet_count": (0, 3),
        "cta_style": "click",
    },
    "social_post": {
        "headline_pattern": "{hook}",
        "body_length": (50, 150),
        "bullet_count": (0, 3),
        "cta_style": "engage",
    },
    "blog": {
        "headline_pattern": "{topic}: {angle}",
        "body_length": (800, 1500),
        "bullet_count": (3, 8),
        "cta_style": "learn_more",
    },
    "email": {
        "headline_pattern": "{personalized_hook}",
        "body_length": (100, 300),
        "bullet_count": (2, 5),
        "cta_style": "conversion",
    },
}

_CTA_PHRASES: dict[str, list[str]] = {
    "purchase": [
        "Shop Now",
        "Add to Cart",
        "Get Yours Today",
        "Buy Now and Save",
    ],
    "click": [
        "Learn More",
        "See the Deal",
        "Tap to Discover",
        "Don't Miss Out",
    ],
    "engage": [
        "Tell us what you think!",
        "Tag a friend who needs this",
        "Double-tap if you agree",
        "Share your experience",
    ],
    "learn_more": [
        "Read the Full Guide",
        "Discover More Tips",
        "Continue Reading",
        "Explore Our Resources",
    ],
    "conversion": [
        "Claim Your Offer",
        "Get Started Today",
        "Unlock Your Discount",
        "Take the Next Step",
    ],
}

_TONE_ADJECTIVES: dict[str, list[str]] = {
    "professional": ["reliable", "trusted", "proven", "industry-leading"],
    "casual": ["awesome", "cool", "handy", "go-to"],
    "urgent": ["limited-time", "exclusive", "last-chance", "hurry"],
    "luxury": ["exquisite", "premium", "refined", "distinguished"],
    "playful": ["fun", "exciting", "delightful", "surprising"],
    "informative": ["comprehensive", "essential", "detailed", "thorough"],
}


def write_copy(
    brief_analysis: dict[str, Any],
    tone_selection: dict[str, Any],
    keyword_extraction: dict[str, Any],
    product: dict[str, Any],
    brand: dict[str, Any],
) -> dict[str, Any]:
    """Write marketing copy based on analysis results.

    Tries the LLM path first; on any failure (no provider
    configured, network blip, timeout, malformed JSON response)
    falls back to the deterministic template path so the engine
    output stays valid in every environment.

    Args:
        brief_analysis: Output from brief_analyzer.
        tone_selection: Output from tone_selector.
        keyword_extraction: Output from keyword_extractor.
        product: Original ProductData dict.
        brand: Original BrandData dict.

    Returns:
        Structured dict with CopyDraft data.
    """
    try:
        prod = copy.deepcopy(product)
        brnd = copy.deepcopy(brand)

        title = str(prod.get("title", "Product")).strip()
        features = list(prod.get("features", []))
        price = prod.get("price", 0.0)
        category = str(prod.get("category", "")).strip()

        brand_name = str(brnd.get("name", "")).strip()

        content_type = str(brief_analysis.get("content_type", "product_description"))
        usps = list(brief_analysis.get("usps", features[:3]))
        target_audience = str(brief_analysis.get("target_audience", "consumers"))
        desired_outcome = str(brief_analysis.get("desired_outcome", ""))

        primary_tone = str(tone_selection.get("primary_tone", "professional"))
        emotional_appeal = str(tone_selection.get("emotional_appeal", "trust"))

        primary_keywords = list(keyword_extraction.get("primary_keywords", []))
        secondary_keywords = list(keyword_extraction.get("secondary_keywords", []))

        template = _CONTENT_TEMPLATES.get(
            content_type, _CONTENT_TEMPLATES["product_description"],
        )

        # ── Path 1: LLM-driven generation ────────────────────────
        llm_draft = _write_copy_via_llm(
            title=title,
            features=features,
            price=price,
            category=category,
            brand_name=brand_name,
            content_type=content_type,
            usps=usps,
            target_audience=target_audience,
            desired_outcome=desired_outcome,
            primary_tone=primary_tone,
            emotional_appeal=emotional_appeal,
            primary_keywords=primary_keywords,
            secondary_keywords=secondary_keywords,
            template=template,
        )
        if llm_draft is not None:
            return {"status": "success", "draft": llm_draft}

        # ── Path 2: Deterministic template fallback ──────────────
        headline = _build_headline(
            title, usps, primary_tone, category, content_type,
        )
        alt_headlines = _build_alt_headlines(
            title, usps, primary_tone, category,
        )
        body = _build_body(
            title, features, usps, primary_tone, emotional_appeal,
            target_audience, primary_keywords, secondary_keywords,
            brand_name, price, content_type, template,
        )
        bullets = _build_bullets(features, usps, primary_tone, template)
        cta_style = template.get("cta_style", "purchase")
        cta_options = _CTA_PHRASES.get(cta_style, _CTA_PHRASES["purchase"])
        cta = cta_options[0]

        return {
            "status": "success",
            "draft": {
                "headline": headline,
                "body": body,
                "bullets": bullets,
                "cta": cta,
                "alt_headlines": alt_headlines,
                "model_note": (
                    "template fallback: no LLM provider configured "
                    "or LLM call failed; deterministic copy returned"
                ),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "draft": {},
            "error": f"Copy writing failed: {exc}",
        }


# ---------------------------------------------------------------------------
# LLM-driven path
# ---------------------------------------------------------------------------

# Token budget for the JSON response. Product descriptions tend
# to fit comfortably in 800; blogs may need 1500-2000.
_LLM_MAX_TOKENS_BY_CONTENT_TYPE: dict[str, int] = {
    "product_description": 800,
    "ad_copy": 400,
    "social_post": 400,
    "blog": 2000,
    "email": 700,
}


def _write_copy_via_llm(
    *,
    title: str,
    features: list[str],
    price: float,
    category: str,
    brand_name: str,
    content_type: str,
    usps: list[str],
    target_audience: str,
    desired_outcome: str,
    primary_tone: str,
    emotional_appeal: str,
    primary_keywords: list[str],
    secondary_keywords: list[str],
    template: dict[str, Any],
) -> dict[str, Any] | None:
    """Try to generate copy via an LLM provider through the router.

    Returns the draft dict on success, or ``None`` on any failure
    (so the caller falls back to the deterministic template).
    The return value never raises -- failures are logged and the
    caller routes around them.
    """
    # Pattern J: never call live LLMs under pytest. Tests that
    # specifically want to exercise the LLM path mock the router
    # via patch().
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

    system_prompt = _build_llm_system_prompt(primary_tone, emotional_appeal)
    user_prompt = _build_llm_user_prompt(
        title=title,
        features=features,
        price=price,
        category=category,
        brand_name=brand_name,
        content_type=content_type,
        usps=usps,
        target_audience=target_audience,
        desired_outcome=desired_outcome,
        primary_keywords=primary_keywords,
        secondary_keywords=secondary_keywords,
        template=template,
    )

    max_tokens = _LLM_MAX_TOKENS_BY_CONTENT_TYPE.get(content_type, 800)
    try:
        result = router.execute(Capability.CHAT_COMPLETE, {
            "system": system_prompt,
            "prompt": user_prompt,
            "max_tokens": max_tokens,
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

    # Validate shape and coerce types defensively (LLM output is
    # untrusted no matter how strict the prompt is).
    headline = str(parsed.get("headline") or "").strip()
    body = str(parsed.get("body") or "").strip()
    if not headline or not body:
        return None

    bullets_raw = parsed.get("bullets") or []
    bullets = [str(b).strip() for b in bullets_raw if str(b).strip()][:8]

    cta = str(parsed.get("cta") or "").strip()
    if not cta:
        # Fall back to the canned CTA for this content type rather
        # than failing the whole LLM path on a missing CTA.
        cta_style = template.get("cta_style", "purchase")
        cta = _CTA_PHRASES.get(cta_style, _CTA_PHRASES["purchase"])[0]

    alt_headlines_raw = parsed.get("alt_headlines") or []
    alt_headlines = [
        str(h).strip() for h in alt_headlines_raw if str(h).strip()
    ][:5]

    model = ""
    try:
        model = str((result.data or {}).get("model") or "")
    except Exception:  # noqa: BLE001
        pass

    return {
        "headline": headline,
        "body": body,
        "bullets": bullets,
        "cta": cta,
        "alt_headlines": alt_headlines,
        "model_note": (
            f"llm: {model}" if model else "llm: provider-default"
        ),
    }


def _build_llm_system_prompt(tone: str, emotional_appeal: str) -> str:
    """Build the system prompt that primes the LLM as a Shopify
    copywriter with the right tone."""
    return (
        "You are an expert Shopify copywriter. You write marketing "
        "copy that converts. Voice: "
        f"{tone}. Emotional appeal: {emotional_appeal}. "
        "Weave keywords naturally into prose -- never keyword-stuff. "
        "Address the target audience directly. Highlight USPs "
        "concretely (numbers, comparisons, specifics) over generic "
        "claims. Always respond with STRICT JSON in the requested "
        "shape; no markdown fences, no commentary outside the JSON."
    )


def _build_llm_user_prompt(
    *,
    title: str,
    features: list[str],
    price: float,
    category: str,
    brand_name: str,
    content_type: str,
    usps: list[str],
    target_audience: str,
    desired_outcome: str,
    primary_keywords: list[str],
    secondary_keywords: list[str],
    template: dict[str, Any],
) -> str:
    """Build the user prompt with the product + brief context."""
    body_min, body_max = template.get("body_length", (150, 300))
    bullet_min, bullet_max = template.get("bullet_count", (3, 6))
    price_str = f"${price:.2f}" if price and float(price) > 0 else "n/a"
    brand_line = f"Brand: {brand_name}" if brand_name else "Brand: (unbranded)"

    return (
        f"Write {content_type.replace('_', ' ')} copy for the following "
        f"Shopify product.\n\n"
        f"Product: {title}\n"
        f"{brand_line}\n"
        f"Category: {category or 'n/a'}\n"
        f"Price: {price_str}\n"
        f"Features:\n"
        + "\n".join(f"  - {f}" for f in features[:10]) + "\n"
        + f"Unique selling points:\n"
        + "\n".join(f"  - {u}" for u in usps[:5]) + "\n"
        + f"Target audience: {target_audience}\n"
        + f"Desired outcome: {desired_outcome or 'drive purchase'}\n"
        + f"Primary keywords (work these in naturally): "
        + (", ".join(primary_keywords[:5]) or "n/a") + "\n"
        + f"Secondary keywords: "
        + (", ".join(secondary_keywords[:5]) or "n/a") + "\n\n"
        + f"Length constraints: body {body_min}-{body_max} words, "
        + f"{bullet_min}-{bullet_max} bullet points.\n\n"
        + "Return STRICT JSON:\n"
        + "{\n"
        + '  "headline": "primary catchy headline",\n'
        + '  "alt_headlines": ["alt 1", "alt 2", "alt 3"],\n'
        + '  "body": "main marketing copy",\n'
        + '  "bullets": ["bullet 1", "bullet 2", ...],\n'
        + '  "cta": "call-to-action phrase"\n'
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
    # Direct parse first (the strictly-prompted happy path).
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        pass
    # Find the outermost JSON object.
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Headline builders
# ---------------------------------------------------------------------------

def _build_headline(
    title: str,
    usps: list[str],
    tone: str,
    category: str,
    content_type: str,
) -> str:
    """Build the primary headline."""
    adjectives = _TONE_ADJECTIVES.get(tone, _TONE_ADJECTIVES["professional"])
    adj = adjectives[0] if adjectives else "quality"

    usp_text = usps[0] if usps else "quality"

    if content_type == "ad_copy":
        return f"Discover the {adj.title()} {title}"
    elif content_type == "social_post":
        return f"{usp_text.capitalize()} — Meet the {title}"
    elif content_type == "blog":
        return f"Why {title} Is the {adj.title()} Choice for {category.title() or 'You'}"
    elif content_type == "email":
        return f"Your {adj.title()} {category.title() or 'Product'} Awaits"
    else:
        # product_description default
        return f"{title} — {adj.title()} {category.title() or 'Product'} for Every Need"


def _build_alt_headlines(
    title: str,
    usps: list[str],
    tone: str,
    category: str,
) -> list[str]:
    """Build alternative headline variations."""
    adjectives = _TONE_ADJECTIVES.get(tone, _TONE_ADJECTIVES["professional"])
    alts: list[str] = []

    if len(adjectives) > 1:
        alts.append(f"The {adjectives[1].title()} {title} You've Been Looking For")
    if usps:
        alts.append(f"{usps[0].capitalize()} — Introducing {title}")
    if category:
        alts.append(f"Elevate Your {category.title()} Experience with {title}")

    return alts[:3]


# ---------------------------------------------------------------------------
# Body builder
# ---------------------------------------------------------------------------

def _build_body(
    title: str,
    features: list[str],
    usps: list[str],
    tone: str,
    emotional_appeal: str,
    audience: str,
    primary_kw: list[str],
    secondary_kw: list[str],
    brand_name: str,
    price: float,
    content_type: str,
    template: dict[str, Any],
) -> str:
    """Build the body text with keyword integration."""
    adjectives = _TONE_ADJECTIVES.get(tone, _TONE_ADJECTIVES["professional"])
    adj = adjectives[0] if adjectives else "quality"

    brand_mention = f"by {brand_name} " if brand_name else ""

    # Opening sentence
    opening = (
        f"Introducing the {title} {brand_mention}— a {adj} solution designed "
        f"for {audience}."
    )

    # Feature sentences
    feature_sentences: list[str] = []
    for i, feat in enumerate(features[:4]):
        kw_insert = ""
        if i < len(primary_kw):
            kw_insert = f" As a top {primary_kw[i]},"
        feature_sentences.append(
            f"{kw_insert} {feat.strip().rstrip('.')}." if kw_insert
            else f"{feat.strip().rstrip('.')}."
        )

    # USP paragraph
    usp_parts = [u.strip().rstrip(".") for u in usps[:3]]
    usp_sentence = ""
    if usp_parts:
        usp_sentence = (
            f"What sets this apart: {', '.join(usp_parts)}."
        )

    # Closing
    if price and price > 0:
        closing = (
            f"Available at ${price:.2f}, the {title} delivers outstanding value."
        )
    else:
        closing = f"The {title} is ready to exceed your expectations."

    # Secondary keyword weaving
    kw_sentence = ""
    if secondary_kw:
        kw_terms = ", ".join(secondary_kw[:3])
        kw_sentence = f"Key highlights include {kw_terms}."

    # Assemble based on content type length
    parts = [opening]
    parts.extend(feature_sentences)
    if usp_sentence:
        parts.append(usp_sentence)
    if kw_sentence:
        parts.append(kw_sentence)
    parts.append(closing)

    body = " ".join(parts)

    # Trim for short-form content
    min_len, max_len = template.get("body_length", (150, 300))
    if content_type in ("ad_copy", "social_post"):
        # Keep it short: opening + closing
        body = f"{opening} {usp_sentence} {closing}".strip()
        words = body.split()
        if len(words) > max_len:
            body = " ".join(words[:max_len])

    return body


# ---------------------------------------------------------------------------
# Bullet builder
# ---------------------------------------------------------------------------

def _build_bullets(
    features: list[str],
    usps: list[str],
    tone: str,
    template: dict[str, Any],
) -> list[str]:
    """Build bullet point list from features and USPs."""
    min_count, max_count = template.get("bullet_count", (3, 6))

    bullets: list[str] = []
    for feat in features:
        clean = feat.strip().rstrip(".")
        if clean:
            bullets.append(clean)

    # Fill with USPs if needed
    existing = {b.lower() for b in bullets}
    for usp in usps:
        clean = usp.strip().rstrip(".")
        if clean and clean.lower() not in existing:
            bullets.append(clean)
            existing.add(clean.lower())

    return bullets[:max_count]
