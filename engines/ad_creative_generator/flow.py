"""Ad Creative Generator Engine — winner → ready-to-execute creative pack.

Consumes a single scored winner record (output of
:mod:`engines.winning_products`) plus the product's commerce
data and produces a complete *creative pack specification*:

  * ``video_plan``     — stock-search queries OR AI prompt OR
                         slideshow image list, plus duration,
                         aspect ratio, and cost estimate
  * ``voiceover_plan`` — one script per selected copy angle,
                         voice style, language, cost estimate
  * ``copy_variants``  — 5 angle-specific copy variants
                         (problem/benefit/proof/curiosity/
                         urgency) with headline, body, CTA, hook
                         timestamp, and hashtag seeds
  * ``thumbnail_plan`` — text-overlay spec for the feed image
  * ``total_est_cost_usd`` — sum of creative-generation cost
  * ``readiness``      — ``ready`` / ``pending_approval`` /
                         ``blocked`` gate signal for the
                         product_launch orchestrator
  * ``blocks``         — list of reasons when readiness is
                         ``blocked`` (missing images, budget
                         exceeded, no hero ad, …)

This engine is PURELY DETERMINISTIC. It never calls adapters;
it only emits a spec that the downstream orchestrator can
hand to the video_gen / voice / ads adapters. Rationale:

  1. Testable without credentials — CI has no API keys and
     the same plan can be re-run bit-identical.
  2. Plan review is the semi-auto approval gate. Executing
     creative generation on an unapproved plan would waste
     money on discarded video renders.
  3. Separation of concerns — copy templating and cost
     arithmetic don't belong in the orchestrator.

Strategy auto-selection heuristic (when ``strategy="auto"``):

  * No hero creative_url AND no product images  → ``blocked``
  * price < $20                                  → ``stock``
    (minimise creative cost on low-margin SKUs)
  * price ≥ $20 AND verdict == "strong_buy"      → ``ai``
    (conviction justifies the premium render)
  * otherwise                                    → ``stock``
    (test cheaply first; upgrade to AI after ROAS proves)
"""
from __future__ import annotations

import copy
import re
import time
from typing import Any

ENGINE_NAME = "ad_creative_generator"

# All five supported copy angles. The order is the order in
# which variants appear in the output ``copy_variants`` list.
_ALL_ANGLES = (
    "problem_agitation",
    "benefit_driven",
    "social_proof",
    "curiosity_hook",
    "urgency_scarcity",
)

# Default creative budget when caller omits one. $0.50 covers
# voiceover TTS for 5 scripts (ElevenLabs turbo ~$0.024/1k chars)
# plus one Higgsfield render. Stock + voiceover path fits in $0.15.
_DEFAULT_BUDGET_USD = 0.50

# ElevenLabs turbo v2 pricing (public-API tier): $5 for 30k chars
# → $0.000167 per char, round up for safety. Used to estimate
# voiceover cost.
_TTS_COST_PER_CHAR = 0.00017

# Higgsfield starter tier: ~$0.09 per 6-second render.
_AI_VIDEO_COST_PER_RENDER = 0.09

# Minimum duration for a product ad (Meta/TikTok best-practice).
_MIN_VIDEO_DURATION_S = 10
_DEFAULT_VIDEO_DURATION_S = 15
_MAX_VIDEO_DURATION_S = 30


class AdCreativeGeneratorEngine:
    """Wrapper class for engine-registry compatibility."""

    ENGINE_NAME = ENGINE_NAME
    engine_name = ENGINE_NAME

    def run(self, input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        return run(input_data)


def _fail(msg: str, start: float) -> dict[str, Any]:
    return {
        "status": "error",
        "data": {},
        "meta": {
            "engine": ENGINE_NAME,
            "timestamp": time.time(),
            "elapsed_seconds": round(time.monotonic() - start, 3),
        },
        "error": msg,
    }


def run(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Public entry point — winner → creative pack spec."""
    start = time.monotonic()
    data = copy.deepcopy(input_data or {})

    if data.get("status") == "fail":
        return _fail(data.get("error") or "Upstream failure", start)

    winner = data.get("winner")
    if not isinstance(winner, dict) or not winner:
        return _fail("'winner' dict is required", start)

    product = data.get("product") or {}
    if not isinstance(product, dict):
        return _fail(
            f"'product' must be a dict, got {type(product).__name__}",
            start,
        )

    target = data.get("target") or {}
    if not isinstance(target, dict):
        target = {}

    platform = str(target.get("platform", "meta") or "meta").lower()
    placement = str(target.get("placement", "reels") or "reels").lower()
    aspect_ratio = str(target.get("aspect_ratio", "9:16") or "9:16")
    language = str(target.get("language", "en") or "en")

    budget_usd = float(data.get("budget_usd", _DEFAULT_BUDGET_USD) or 0.0)
    if budget_usd < 0:
        budget_usd = _DEFAULT_BUDGET_USD

    # Duration bounded to sensible platform limits.
    duration_s = int(
        target.get("duration_seconds", _DEFAULT_VIDEO_DURATION_S) or 0,
    )
    if duration_s < _MIN_VIDEO_DURATION_S:
        duration_s = _DEFAULT_VIDEO_DURATION_S
    if duration_s > _MAX_VIDEO_DURATION_S:
        duration_s = _MAX_VIDEO_DURATION_S

    # Caller can request a subset of angles; default = all five.
    requested_angles = data.get("copy_angles") or list(_ALL_ANGLES)
    if not isinstance(requested_angles, list):
        requested_angles = list(_ALL_ANGLES)
    angles = [a for a in requested_angles if a in _ALL_ANGLES]
    if not angles:
        angles = list(_ALL_ANGLES)

    strategy_pref = str(data.get("strategy", "auto") or "auto").lower()
    brand_voice = str(data.get("brand_voice", "casual") or "casual")

    # ── Stage 1: pick a strategy (stock / ai / slideshow) ────
    video_plan, blocks = _plan_video(
        winner=winner,
        product=product,
        strategy_pref=strategy_pref,
        duration_s=duration_s,
        aspect_ratio=aspect_ratio,
        budget_usd=budget_usd,
    )

    # ── Stage 2: copy variants (angle templates) ────────────
    copy_variants = _build_copy_variants(
        winner=winner,
        product=product,
        angles=angles,
        brand_voice=brand_voice,
        platform=platform,
    )

    # ── Stage 3: voiceover scripts (one per selected angle) ─
    voiceover_plan = _build_voiceover_plan(
        copy_variants=copy_variants,
        language=language,
        brand_voice=brand_voice,
    )

    # ── Stage 4: thumbnail spec ─────────────────────────────
    thumbnail_plan = _build_thumbnail_plan(
        winner=winner, product=product, placement=placement,
    )

    # ── Stage 5: cost rollup + readiness verdict ────────────
    total_est_cost = round(
        float(video_plan.get("est_cost_usd", 0.0))
        + float(voiceover_plan.get("est_cost_usd", 0.0)),
        4,
    )

    if total_est_cost > budget_usd:
        blocks.append(
            f"est_cost ${total_est_cost:.2f} exceeds budget ${budget_usd:.2f}",
        )

    if blocks:
        readiness = "blocked"
    elif bool(data.get("auto_approve", False)):
        readiness = "ready"
    else:
        readiness = "pending_approval"

    creative_pack = {
        "video_plan":        video_plan,
        "voiceover_plan":    voiceover_plan,
        "copy_variants":     copy_variants,
        "thumbnail_plan":    thumbnail_plan,
        "total_est_cost_usd": total_est_cost,
        "budget_usd":        round(budget_usd, 4),
        "readiness":         readiness,
        "blocks":            blocks,
        "target": {
            "platform":      platform,
            "placement":     placement,
            "aspect_ratio":  aspect_ratio,
            "language":      language,
            "duration_seconds": duration_s,
        },
    }

    elapsed = round(time.monotonic() - start, 3)
    return {
        "status": "success",
        "data": {
            "creative_pack":   creative_pack,
            "product_key":     winner.get("product_key", ""),
            "winner_verdict":  winner.get("verdict", ""),
            "winner_score":    winner.get("score", 0),
        },
        "meta": {
            "engine": ENGINE_NAME,
            "timestamp": time.time(),
            "elapsed_seconds": elapsed,
        },
        "error": None,
    }



# ---------------------------------------------------------------------------
# Video plan
# ---------------------------------------------------------------------------



def _plan_video(
    *,
    winner: dict[str, Any],
    product: dict[str, Any],
    strategy_pref: str,
    duration_s: int,
    aspect_ratio: str,
    budget_usd: float,
) -> tuple[dict[str, Any], list[str]]:
    """Decide stock vs AI vs slideshow and produce the plan.

    Returns a ``(plan, blocks)`` tuple where ``blocks`` is a list
    of human-readable reasons that force readiness="blocked".
    An empty list means the plan is technically executable; the
    caller still decides whether it fits the budget.
    """
    blocks: list[str] = []
    hero = winner.get("hero_ad") or {}
    if not isinstance(hero, dict):
        hero = {}
    images = product.get("images") or []
    if not isinstance(images, list):
        images = []
    price = float(product.get("price", 0) or 0)
    verdict = str(winner.get("verdict", "") or "")

    # Auto-resolve strategy preference.
    kind = strategy_pref
    if kind not in ("stock", "ai", "slideshow"):
        kind = _auto_pick_strategy(
            hero=hero, images=images, price=price, verdict=verdict,
        )

    # Validate preconditions for each strategy and downgrade /
    # block when requirements aren't met. Downgrading preserves
    # operator intent but avoids impossible plans.
    if kind == "slideshow" and len(images) < 2:
        blocks.append(
            "slideshow strategy requires >= 2 product images",
        )
    if kind == "ai" and budget_usd < _AI_VIDEO_COST_PER_RENDER:
        # Not a hard block — caller may still have an AI adapter
        # on a different tier; we emit the block so approval
        # surfaces the mismatch rather than silently downgrading.
        blocks.append(
            f"ai video requires >= ${_AI_VIDEO_COST_PER_RENDER:.2f} "
            f"budget (got ${budget_usd:.2f})",
        )

    plan: dict[str, Any] = {
        "kind":            kind,
        "duration_seconds": duration_s,
        "aspect_ratio":    aspect_ratio,
        "strategy_reason": _explain_strategy(kind, price, verdict, hero, images),
        "est_cost_usd":    0.0,
        "stock_queries":   [],
        "ai_prompt":       "",
        "slideshow_images": [],
    }

    if kind == "stock":
        plan["stock_queries"] = _stock_queries(winner, product)
        plan["est_cost_usd"] = 0.0
    elif kind == "ai":
        plan["ai_prompt"] = _ai_prompt(winner, product, aspect_ratio)
        plan["est_cost_usd"] = _AI_VIDEO_COST_PER_RENDER
    elif kind == "slideshow":
        plan["slideshow_images"] = list(images)[:6]
        plan["est_cost_usd"] = 0.0

    return plan, blocks


def _auto_pick_strategy(
    *,
    hero: dict[str, Any],
    images: list[Any],
    price: float,
    verdict: str,
) -> str:
    """Heuristic strategy picker — see module docstring for rationale."""
    # Strong-buy high-price winners justify the AI render premium.
    if price >= 20 and verdict == "strong_buy":
        return "ai"
    # Low-price items prefer stock to protect margin; also covers
    # the "no signals either way" default.
    if price < 20:
        return "stock"
    # Mid-price buy / watch — test cheaply with stock first.
    return "stock"


def _stock_queries(
    winner: dict[str, Any], product: dict[str, Any],
) -> list[str]:
    """Three stock-search queries ordered most→least specific."""
    title = str(product.get("title", "") or "")
    category = str(
        (winner.get("hero_ad") or {}).get("headline", "") or "",
    )
    tags = product.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    queries: list[str] = []
    if title:
        queries.append(_keywords_from_text(title, max_words=3))
    if category:
        queries.append(_keywords_from_text(category, max_words=4))
    if tags:
        queries.append(" ".join(str(t) for t in tags[:2]))
    # Fallback generic query so downstream always has at least one
    fallback = _keywords_from_text(title, max_words=1) or "lifestyle"
    if not queries:
        queries.append(fallback)
    # Dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        q = q.strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[:3]


def _ai_prompt(
    winner: dict[str, Any],
    product: dict[str, Any],
    aspect_ratio: str,
) -> str:
    """Build a one-paragraph AI-video prompt from product data."""
    title = str(product.get("title", "") or "product")
    descr = str(product.get("description", "") or "")
    hero_copy = str(
        (winner.get("hero_ad") or {}).get("copy", "") or "",
    )
    # Use the hero ad's copy as the "mood" hint when present,
    # falling back to the product description. Aspect ratio is
    # injected so downstream Higgsfield / Runway honours vertical
    # placement without the operator having to re-specify.
    mood = _first_sentence(hero_copy or descr) or "lifestyle, vibrant"
    return (
        f"{title} in a natural use scene, {mood}. "
        f"Cinematic product demo, {aspect_ratio} aspect ratio, "
        "shallow depth of field, warm natural light, 5-second clip."
    )


def _explain_strategy(
    kind: str, price: float, verdict: str,
    hero: dict[str, Any], images: list[Any],
) -> str:
    if kind == "ai":
        return (
            f"price=${price:.2f} + verdict={verdict or 'n/a'} "
            f"→ AI render conviction justifies premium"
        )
    if kind == "slideshow":
        return f"slideshow over {len(images)} product images"
    return (
        f"price=${price:.2f} + verdict={verdict or 'n/a'} "
        f"→ stock clips (test cheaply first)"
    )


# ---------------------------------------------------------------------------
# Copy variants — 5 angle templates
# ---------------------------------------------------------------------------


# Each template takes a ``slots`` dict filled from the product +
# winner data and returns a (headline, body, hook) tuple. Hook
# is the first 3 seconds of the voiceover — the make-or-break
# segment on short-form video.
def _tpl_problem(slots: dict[str, str]) -> tuple[str, str, str]:
    return (
        f"Struggling with {slots['problem']}?",
        (
            f"If {slots['problem']} has been driving you crazy, "
            f"you're not alone. {slots['product']} fixes it in "
            f"{slots['time']} — no hassle, no gimmicks. "
            f"Over {slots['social_count']} happy buyers already switched."
        ),
        f"Tired of {slots['problem']}? Watch this.",
    )


def _tpl_benefit(slots: dict[str, str]) -> tuple[str, str, str]:
    return (
        f"Get {slots['benefit']} with {slots['product']}",
        (
            f"{slots['product']} gives you {slots['benefit']} in just "
            f"{slots['time']}. Built for {slots['audience']} who want "
            f"real results, not empty promises."
        ),
        f"Want {slots['benefit']}? This changes everything.",
    )


def _tpl_social_proof(slots: dict[str, str]) -> tuple[str, str, str]:
    return (
        f"{slots['social_count']}+ people love {slots['product']}",
        (
            f"Thousands are raving about {slots['product']}. "
            f"{slots['review_quote']} "
            f"See why it's trending right now."
        ),
        f"Everyone's talking about {slots['product']} — here's why.",
    )


def _tpl_curiosity(slots: dict[str, str]) -> tuple[str, str, str]:
    return (
        f"I didn't believe {slots['product']} worked…",
        (
            f"…until I tried it for 7 days. The difference with "
            f"{slots['benefit']} shocked me. Watch what happened."
        ),
        f"I was skeptical about {slots['product']} — until this.",
    )


def _tpl_urgency(slots: dict[str, str]) -> tuple[str, str, str]:
    return (
        f"Selling fast — grab {slots['product']} today",
        (
            f"{slots['product']} is almost sold out this week. "
            f"Only a limited batch left at {slots['price']}. "
            f"Get yours before it's gone."
        ),
        f"Last chance — {slots['product']} is running out.",
    )


_TEMPLATES = {
    "problem_agitation": _tpl_problem,
    "benefit_driven":    _tpl_benefit,
    "social_proof":      _tpl_social_proof,
    "curiosity_hook":    _tpl_curiosity,
    "urgency_scarcity":  _tpl_urgency,
}


# Platform-specific CTA preferences — Meta accepts a fixed set
# of CTA enums; TikTok uses the free-form "button_text" field.
_CTA_BY_PLATFORM_ANGLE = {
    ("meta", "urgency_scarcity"):  "SHOP_NOW",
    ("meta", "problem_agitation"): "LEARN_MORE",
    ("meta", "benefit_driven"):    "SHOP_NOW",
    ("meta", "social_proof"):      "SHOP_NOW",
    ("meta", "curiosity_hook"):    "LEARN_MORE",
    ("tiktok", "urgency_scarcity"): "Shop Now",
    ("tiktok", "problem_agitation"): "Watch More",
    ("tiktok", "benefit_driven"):    "Shop Now",
    ("tiktok", "social_proof"):      "Shop Now",
    ("tiktok", "curiosity_hook"):    "Watch More",
}


def _build_copy_variants(
    *,
    winner: dict[str, Any],
    product: dict[str, Any],
    angles: list[str],
    brand_voice: str,
    platform: str,
) -> list[dict[str, Any]]:
    slots = _extract_slots(winner, product)
    variants: list[dict[str, Any]] = []
    for angle in angles:
        tpl = _TEMPLATES.get(angle)
        if tpl is None:
            continue
        headline, body, hook = tpl(slots)
        cta = _CTA_BY_PLATFORM_ANGLE.get(
            (platform, angle),
            "SHOP_NOW" if platform == "meta" else "Shop Now",
        )
        variants.append({
            "angle":    angle,
            "headline": headline,
            "body":     body,
            "hook":     hook,
            "cta":      cta,
            "hook_seconds": 3,
            "hashtags": _hashtags_for(slots, angle),
            "brand_voice": brand_voice,
        })
    return variants


def _extract_slots(
    winner: dict[str, Any], product: dict[str, Any],
) -> dict[str, str]:
    """Derive every template slot from winner + product data."""
    title = str(product.get("title", "") or "your product")
    # Shorten overly long titles to a user-facing brand/product name.
    short_title = _shorten(title, max_words=4)

    price = float(product.get("price", 0) or 0)
    price_str = f"${price:.2f}" if price > 0 else "a great price"

    benefit = _first_phrase(product.get("benefit") or "") or _first_phrase(
        product.get("description", ""),
    ) or "real results"

    problem = _first_phrase(product.get("problem") or "") or (
        f"old-school {short_title.lower()}"
    )

    audience = _first_phrase(product.get("audience") or "") or "anyone"

    # Social count: prefer winner.factors.engagement_velocity.value
    # as a trailing-indicator proxy; fall back to a rounded floor.
    velocity_factor = (
        (winner.get("factors") or {}).get("engagement_velocity") or {}
    )
    velocity = velocity_factor.get("value", 0) if isinstance(
        velocity_factor, dict,
    ) else 0
    try:
        social_count = max(500, int(float(velocity) * 30))
    except (TypeError, ValueError):
        social_count = 1000
    # Round down to the nearest 500 so the claim reads as a
    # believable round number ("10,000+" not "10,234+").
    social_count = (social_count // 500) * 500
    if social_count >= 1000:
        social_display = f"{social_count:,}"
    else:
        social_display = str(social_count)

    review_quote = _first_phrase(
        product.get("review_quote") or "",
    ) or "\"Changed my routine, hands down.\""

    time_phrase = _first_phrase(product.get("time_to_value") or "") or (
        "minutes"
    )

    return {
        "product":      short_title,
        "benefit":      benefit,
        "problem":      problem,
        "audience":     audience,
        "price":        price_str,
        "social_count": social_display,
        "review_quote": review_quote,
        "time":         time_phrase,
    }


def _hashtags_for(slots: dict[str, str], angle: str) -> list[str]:
    """Cheap hashtag seeds derived from the product short-title.

    Real ad launches override these with a vetted tag list, but
    supplying sane defaults means the plan is shippable without
    a second round-trip.
    """
    tag_core = _slug(slots.get("product", "")) or "product"
    base = [f"#{tag_core}", "#fyp"]
    if angle == "urgency_scarcity":
        base.append("#sellingout")
    elif angle == "social_proof":
        base.append("#tiktokmademebuyit")
    elif angle == "problem_agitation":
        base.append("#gamechanger")
    elif angle == "curiosity_hook":
        base.append("#viral")
    elif angle == "benefit_driven":
        base.append("#musthave")
    return base


# ---------------------------------------------------------------------------
# Voiceover plan
# ---------------------------------------------------------------------------


def _build_voiceover_plan(
    *,
    copy_variants: list[dict[str, Any]],
    language: str,
    brand_voice: str,
) -> dict[str, Any]:
    """One voiceover script per copy variant + cost estimate."""
    # Brand-voice → ElevenLabs voice selection. "casual_female" is
    # the default — operators override via params if they've
    # already provisioned a custom voice.
    voice_style = _voice_style_for(brand_voice)

    scripts: dict[str, str] = {}
    total_chars = 0
    for variant in copy_variants:
        angle = str(variant.get("angle", "") or "")
        if not angle:
            continue
        script = _compose_voiceover_script(variant)
        scripts[angle] = script
        total_chars += len(script)

    est_cost_usd = round(total_chars * _TTS_COST_PER_CHAR, 4)
    return {
        "scripts":       scripts,
        "voice_style":   voice_style,
        "language":      language,
        "char_total":    total_chars,
        "est_cost_usd":  est_cost_usd,
        "tts_rate_per_char": _TTS_COST_PER_CHAR,
    }


def _voice_style_for(brand_voice: str) -> str:
    mapping = {
        "casual":        "casual_female",
        "authoritative": "authoritative_male",
        "playful":       "playful_female",
        "luxury":        "calm_male",
    }
    return mapping.get(brand_voice, "casual_female")


def _compose_voiceover_script(variant: dict[str, Any]) -> str:
    """Merge hook + body into a single ~15-20s voiceover script.

    The hook leads so the first 3 seconds (a.k.a. "the scroll
    stopper") land before the platform's user-is-still-watching
    threshold. Body carries the benefit + CTA.
    """
    hook = str(variant.get("hook", "") or "").strip()
    body = str(variant.get("body", "") or "").strip()
    cta_raw = str(variant.get("cta", "") or "").strip()
    cta_line = _cta_line_for(cta_raw)

    parts = [p for p in (hook, body, cta_line) if p]
    return " ".join(parts)


def _cta_line_for(cta: str) -> str:
    """Turn a CTA enum into a speakable closing line."""
    cta_up = cta.upper()
    if cta_up in ("SHOP_NOW", "SHOP NOW"):
        return "Tap the link to grab yours."
    if cta_up in ("LEARN_MORE", "LEARN MORE", "WATCH MORE"):
        return "Tap to see the full story."
    return "Tap the link below."


# ---------------------------------------------------------------------------
# Thumbnail plan
# ---------------------------------------------------------------------------


def _build_thumbnail_plan(
    *,
    winner: dict[str, Any],
    product: dict[str, Any],
    placement: str,
) -> dict[str, Any]:
    # Platform-native dimensions — vertical for TikTok/Reels,
    # square for Instagram feed, landscape for YouTube.
    if placement in ("reels", "tiktok", "story"):
        dims = (1080, 1920)
    elif placement in ("feed", "instagram_feed"):
        dims = (1080, 1080)
    else:
        dims = (1200, 628)

    hero = winner.get("hero_ad") or {}
    overlay_source = str(
        hero.get("headline", "") or product.get("title", "") or "",
    )
    overlay_text = _shorten(overlay_source, max_words=6).upper()

    return {
        "style":          "product_hero",
        "text_overlay":   overlay_text,
        "dimensions":     list(dims),
        "source_image":   _best_image(product),
        "placement":      placement,
    }


def _best_image(product: dict[str, Any]) -> str:
    imgs = product.get("images") or []
    if isinstance(imgs, list) and imgs:
        first = imgs[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return str(first.get("url", "") or "")
    return ""


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------


_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "of", "to",
    "in", "on", "at", "by", "is", "it", "this", "that", "your",
    "our", "my", "we", "you", "i", "from", "be",
}


def _keywords_from_text(text: str, *, max_words: int) -> str:
    """Return up to ``max_words`` content words from ``text``."""
    words = re.findall(r"[A-Za-z0-9']+", text.lower())
    kept: list[str] = []
    for w in words:
        if w in _STOPWORDS or len(w) <= 2:
            continue
        kept.append(w)
        if len(kept) >= max_words:
            break
    return " ".join(kept)


def _first_phrase(text: str, *, max_words: int = 8) -> str:
    """First clause of text, bounded to ``max_words``.

    Stops at the first sentence delimiter or conjunction so the
    phrase reads naturally when slotted into a template.
    """
    text = (text or "").strip()
    if not text:
        return ""
    # Cut at the first terminal punctuation.
    for delim in (". ", "! ", "? ", "; "):
        if delim in text:
            text = text.split(delim, 1)[0]
            break
    words = text.split()
    if len(words) > max_words:
        words = words[:max_words]
    return " ".join(words).strip().strip(",")


def _first_sentence(text: str, *, max_words: int = 20) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    for delim in (". ", "! ", "? "):
        if delim in text:
            text = text.split(delim, 1)[0]
            break
    words = text.split()
    if len(words) > max_words:
        words = words[:max_words]
    return " ".join(words).rstrip(".!? ,")


def _shorten(text: str, *, max_words: int) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    words = text.split()
    if len(words) > max_words:
        words = words[:max_words]
    return " ".join(words)


def _slug(text: str) -> str:
    """Lowercase, alpha-numeric only, no spaces — for hashtag seed."""
    return re.sub(r"[^A-Za-z0-9]+", "", (text or "").lower())
