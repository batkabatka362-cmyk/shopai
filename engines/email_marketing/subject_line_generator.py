"""Email Marketing Engine — subject line generator.

Generates multiple subject line variations with personalization tokens,
urgency hooks, curiosity hooks, and optional emoji. Each subject line
is under 60 characters for optimal deliverability.

Two paths (same pattern as
``engines/content_generation/copy_writer.py`` and
``engines/landing_page/page_generator.py``):

  1. **LLM path** -- ``Capability.CHAT_COMPLETE`` produces 4+
     fresh subject-line variants tuned to the store + discount
     + top product. Open-rate-impact scoring is then applied to
     each generated variant so the LLM's creativity is still
     graded by the same benchmark heuristic as templates.
  2. **Template path** (fallback) -- the
     ``_SUBJECT_TEMPLATES`` dict + token substitution.

The LLM path is what makes subject lines feel store-specific
("YouthBoost flash sale -- 25% off ends tonight") instead of
generic ("Don't miss 25% off on top picks").
"""
from __future__ import annotations

import copy
import json
import os
import re
from typing import Any

from utils.logger import get_logger

logger = get_logger("engines.email_marketing.subject_line")


# ---------------------------------------------------------------------------
# Subject line templates per campaign type
# ---------------------------------------------------------------------------

_SUBJECT_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "promotional": [
        {
            "template": "{{first_name}}, {discount_text} at {store} — Today Only",
            "style": "urgency",
            "personalized": True,
            "emoji": True,
            "emoji_char": "\U0001f525",
        },
        {
            "template": "Don't miss {discount_text} on {product_name}",
            "style": "benefit",
            "personalized": False,
            "emoji": False,
            "emoji_char": "",
        },
        {
            "template": "Your exclusive deal is waiting, {{first_name}}",
            "style": "curiosity",
            "personalized": True,
            "emoji": True,
            "emoji_char": "\U0001f381",
        },
        {
            "template": "{store}: {discount_text} — Limited Stock",
            "style": "scarcity",
            "personalized": False,
            "emoji": True,
            "emoji_char": "\u23f0",
        },
    ],
    "nurture": [
        {
            "template": "{{first_name}}, here's something just for you",
            "style": "personal",
            "personalized": True,
            "emoji": False,
            "emoji_char": "",
        },
        {
            "template": "5 tips to get more from {store}",
            "style": "value",
            "personalized": False,
            "emoji": False,
            "emoji_char": "",
        },
        {
            "template": "You asked, we answered — new from {store}",
            "style": "curiosity",
            "personalized": False,
            "emoji": True,
            "emoji_char": "\U0001f4a1",
        },
    ],
    "win-back": [
        {
            "template": "We miss you, {{first_name}} — here's {discount_text}",
            "style": "emotional",
            "personalized": True,
            "emoji": True,
            "emoji_char": "\U0001f49b",
        },
        {
            "template": "It's been a while — see what's new at {store}",
            "style": "curiosity",
            "personalized": False,
            "emoji": False,
            "emoji_char": "",
        },
        {
            "template": "Come back to {store} and save {discount_text}",
            "style": "incentive",
            "personalized": False,
            "emoji": True,
            "emoji_char": "\U0001f389",
        },
    ],
    "announcement": [
        {
            "template": "Big news from {store} — you'll want to see this",
            "style": "curiosity",
            "personalized": False,
            "emoji": True,
            "emoji_char": "\U0001f4e3",
        },
        {
            "template": "{{first_name}}, something exciting just dropped",
            "style": "personal",
            "personalized": True,
            "emoji": False,
            "emoji_char": "",
        },
        {
            "template": "Introducing the latest from {store}",
            "style": "direct",
            "personalized": False,
            "emoji": False,
            "emoji_char": "",
        },
    ],
}


def generate_subject_lines(
    goal: str,
    store_name: str,
    discount: dict[str, Any],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate multiple subject line variants for the campaign.

    Tries the LLM path first; on any failure falls back to the
    deterministic template path so output stays valid in every
    environment.

    Args:
        goal: Campaign goal / type.
        store_name: Store display name.
        discount: DiscountInfo dict.
        products: List of ProductInfo dicts.

    Returns:
        Structured dict with SubjectLineSet data.
    """
    try:
        goal_key = str(goal).lower().strip()
        prods = copy.deepcopy(products)

        discount_text = _format_discount(discount)
        product_name = prods[0].get("title", "top picks") if prods else "top picks"

        # ── Path 1: LLM ──────────────────────────────────────────
        llm_lines = _generate_subject_lines_via_llm(
            goal=goal_key,
            store_name=store_name,
            discount_text=discount_text,
            product_name=product_name,
            products=prods,
        )
        if llm_lines is not None:
            return {
                "status": "success",
                "subject_lines": llm_lines,
            }

        # ── Path 2: Templates ────────────────────────────────────
        templates = copy.deepcopy(
            _SUBJECT_TEMPLATES.get(goal_key, _SUBJECT_TEMPLATES["promotional"])
        )

        subject_lines: list[dict[str, Any]] = []
        best_index = 0
        best_score = 0.0

        for idx, tpl in enumerate(templates):
            raw = tpl["template"]
            text = raw.replace("{store}", store_name)
            text = text.replace("{discount_text}", discount_text)
            text = text.replace("{product_name}", product_name)

            if tpl["emoji"] and tpl["emoji_char"]:
                text = tpl["emoji_char"] + " " + text

            if len(text) > 60:
                text = text[:57] + "..."

            score = _score_subject_line(tpl["style"], tpl["personalized"], tpl["emoji"])
            if score > best_score:
                best_score = score
                best_index = idx

            subject_lines.append({
                "text": text,
                "style": tpl["style"],
                "personalized": tpl["personalized"],
                "emoji": tpl["emoji"],
                "score": round(score, 2),
            })

        return {
            "status": "success",
            "subject_lines": {
                "subject_lines": subject_lines,
                "recommended_index": best_index,
                "model_note": (
                    "template fallback: no LLM provider configured "
                    "or LLM call failed"
                ),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "subject_lines": {},
            "error": f"Subject line generation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# LLM-driven path
# ---------------------------------------------------------------------------


_VALID_STYLES: frozenset[str] = frozenset({
    "urgency", "scarcity", "curiosity", "personal",
    "emotional", "incentive", "benefit", "value", "direct",
})


def _generate_subject_lines_via_llm(
    *,
    goal: str,
    store_name: str,
    discount_text: str,
    product_name: str,
    products: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """LLM-driven subject line generation.

    Returns the wrapped subject-lines dict on success, ``None``
    on any failure (caller falls back to template path).
    """
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

    system_prompt = _build_llm_system_prompt(goal)
    user_prompt = _build_llm_user_prompt(
        goal=goal,
        store_name=store_name,
        discount_text=discount_text,
        product_name=product_name,
        products=products,
    )

    try:
        result = router.execute(Capability.CHAT_COMPLETE, {
            "system": system_prompt,
            "prompt": user_prompt,
            "max_tokens": 600,
            "temperature": 0.8,  # higher creativity for subject lines
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

    variants_raw = parsed.get("variants") or []
    if not isinstance(variants_raw, list) or not variants_raw:
        return None

    subject_lines: list[dict[str, Any]] = []
    best_index = 0
    best_score = 0.0

    for idx, v in enumerate(variants_raw):
        if not isinstance(v, dict):
            continue
        line_text = str(v.get("text") or "").strip()
        if not line_text:
            continue

        # Defensively cap at the 60-char deliverability ceiling.
        if len(line_text) > 60:
            line_text = line_text[:57] + "..."

        style = str(v.get("style") or "benefit").strip().lower()
        if style not in _VALID_STYLES:
            style = "benefit"

        personalized = bool(v.get("personalized", False))
        # Detect emoji presence by scanning the actual text for
        # non-ASCII codepoints (don't trust the model's flag).
        emoji = any(ord(c) > 127 for c in line_text)

        # Re-score with the canonical heuristic so the LLM's
        # creativity is still graded by the same benchmark.
        score = _score_subject_line(style, personalized, emoji)

        if score > best_score:
            best_score = score
            best_index = len(subject_lines)

        subject_lines.append({
            "text": line_text,
            "style": style,
            "personalized": personalized,
            "emoji": emoji,
            "score": round(score, 2),
        })

    if not subject_lines:
        return None

    model = ""
    try:
        model = str((result.data or {}).get("model") or "")
    except Exception:  # noqa: BLE001
        pass

    return {
        "subject_lines": subject_lines,
        "recommended_index": best_index,
        "model_note": (
            f"llm: {model}" if model else "llm: provider-default"
        ),
    }


def _build_llm_system_prompt(goal: str) -> str:
    """Build the system prompt that primes the LLM as an email
    subject-line copywriter for the given campaign type."""
    return (
        "You are an expert email-marketing copywriter. Your job: "
        "write subject lines that get OPENED. Each line MUST be "
        "60 characters or fewer (deliverability cap). Use "
        "personalization tokens like {{first_name}} when "
        "appropriate -- the email tool substitutes them at send "
        f"time. Campaign type: {goal}. "
        "Always respond with STRICT JSON in the requested shape; "
        "no markdown fences, no commentary."
    )


def _build_llm_user_prompt(
    *,
    goal: str,
    store_name: str,
    discount_text: str,
    product_name: str,
    products: list[dict[str, Any]],
) -> str:
    """Build the user prompt with the campaign context."""
    product_titles = [
        str(p.get("title") or "").strip()
        for p in products[:5]
        if isinstance(p, dict)
    ]
    product_titles = [t for t in product_titles if t]
    product_line = (
        "Featured products: " + ", ".join(product_titles)
        if product_titles
        else f"Featured product: {product_name}"
    )

    return (
        f"Write 4 subject-line variants for a {goal} email campaign.\n\n"
        f"Store: {store_name}\n"
        f"Offer: {discount_text}\n"
        f"{product_line}\n\n"
        f"Style guidance: include at least one urgency, one "
        f"curiosity, one personalized (with {{{{first_name}}}}) "
        f"variant, and one benefit-first. Keep each under 60 chars.\n\n"
        f"Return STRICT JSON in this exact shape:\n"
        "{\n"
        '  "variants": [\n'
        '    {"text": "subject line A", "style": "urgency", "personalized": false},\n'
        '    {"text": "subject line B", "style": "curiosity", "personalized": false},\n'
        '    {"text": "subject line C", "style": "personal", "personalized": true},\n'
        '    {"text": "subject line D", "style": "benefit", "personalized": false}\n'
        "  ]\n"
        "}\n"
        "Valid style values: urgency, scarcity, curiosity, "
        "personal, emotional, incentive, benefit, value, direct."
    )


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON parse, tolerates markdown fences."""
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


def _format_discount(discount: dict[str, Any]) -> str:
    """Format a discount dict into readable text."""
    if not discount:
        return "a special offer"
    disc_type = discount.get("type", "percentage")
    disc_val = discount.get("value", 0)
    if disc_type == "percentage":
        return f"{int(disc_val)}% off"
    return f"${disc_val} off"


def _score_subject_line(style: str, personalized: bool, emoji: bool) -> float:
    """Score a subject line variant on expected open-rate impact.

    Based on email marketing benchmarks:
    - Personalization adds ~26% lift
    - Urgency/scarcity adds ~22% lift
    - Emoji adds ~5% lift on average (varies by audience)
    """
    base = 0.50

    style_boosts: dict[str, float] = {
        "urgency": 0.22,
        "scarcity": 0.20,
        "curiosity": 0.18,
        "personal": 0.15,
        "emotional": 0.16,
        "incentive": 0.14,
        "benefit": 0.12,
        "value": 0.10,
        "direct": 0.08,
    }
    base += style_boosts.get(style, 0.10)

    if personalized:
        base += 0.15

    if emoji:
        base += 0.05

    return min(base, 1.0)
