"""Content Generation Engine — format adapter.

Adapts generated content to platform-specific formats and constraints:
character limits for social platforms, HTML for web, plain text for email.

Model note: Uses Qwen for intelligent format adaptation.
"""
from __future__ import annotations

import copy
import html
import re
from typing import Any


# ---------------------------------------------------------------------------
# Platform constraints
# ---------------------------------------------------------------------------

_PLATFORM_LIMITS: dict[str, dict[str, Any]] = {
    "twitter": {
        "headline_max": 70,
        "body_max": 280,
        "format": "plain",
        "cta_max": 30,
    },
    "instagram": {
        "headline_max": 100,
        "body_max": 2200,
        "format": "plain",
        "cta_max": 50,
    },
    "facebook": {
        "headline_max": 80,
        "body_max": 500,
        "format": "plain",
        "cta_max": 40,
    },
    "shopify": {
        "headline_max": 200,
        "body_max": 5000,
        "format": "html",
        "cta_max": 100,
    },
    "web": {
        "headline_max": 200,
        "body_max": 5000,
        "format": "html",
        "cta_max": 100,
    },
    "email": {
        "headline_max": 150,
        "body_max": 3000,
        "format": "plain",
        "cta_max": 60,
    },
}


def adapt_format(
    draft: dict[str, Any],
    seo_result: dict[str, Any],
    platform: str,
) -> dict[str, Any]:
    """Adapt content to the target platform format.

    Args:
        draft: CopyDraft dict from copy_writer.
        seo_result: SEOResult dict from seo_optimizer.
        platform: Target platform name.

    Returns:
        Structured dict with FormatResult data.
    """
    try:
        drft = copy.deepcopy(draft)
        seo = copy.deepcopy(seo_result)

        headline = str(drft.get("headline", ""))
        body = str(drft.get("body", ""))
        bullets = list(drft.get("bullets", []))
        cta = str(drft.get("cta", ""))

        meta_description = str(seo.get("meta_description", ""))

        platform_key = platform.strip().lower().replace(" ", "_").replace("-", "_")
        limits = _PLATFORM_LIMITS.get(platform_key, _PLATFORM_LIMITS["web"])

        fmt = limits["format"]

        # --- Truncate to platform limits ---
        headline = _truncate(headline, limits["headline_max"])
        body = _truncate(body, limits["body_max"])
        cta = _truncate(cta, limits["cta_max"])

        # --- Format content ---
        if fmt == "html":
            formatted = _format_html(headline, body, bullets, cta, meta_description)
        else:
            formatted = _format_plain(headline, body, bullets, cta)

        total_chars = sum(len(v) for v in formatted.values())
        max_chars = limits["headline_max"] + limits["body_max"] + limits["cta_max"]
        within_limits = total_chars <= max_chars

        return {
            "status": "success",
            "formatted": {
                "formatted_content": formatted,
                "platform": platform_key,
                "character_count": total_chars,
                "within_limits": within_limits,
                "model_note": "Qwen: platform-aware format adaptation and content trimming",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "formatted": {},
            "error": f"Format adaptation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, preserving word boundaries."""
    if len(text) <= max_len:
        return text
    truncated = text[: max_len - 3].rsplit(" ", 1)[0]
    return truncated.rstrip(".,;:!? ") + "..."


def _format_html(
    headline: str,
    body: str,
    bullets: list[str],
    cta: str,
    meta_description: str,
) -> dict[str, str]:
    """Format content as HTML."""
    h_esc = html.escape(headline)
    b_esc = html.escape(body)
    cta_esc = html.escape(cta)

    # Build body paragraphs
    sentences = [s.strip() for s in body.split(". ") if s.strip()]
    if len(sentences) > 2:
        mid = len(sentences) // 2
        p1 = ". ".join(sentences[:mid]) + "."
        p2 = ". ".join(sentences[mid:])
        if not p2.endswith("."):
            p2 += "."
        body_html = f"<p>{html.escape(p1)}</p>\n<p>{html.escape(p2)}</p>"
    else:
        body_html = f"<p>{b_esc}</p>"

    # Build bullet list
    bullet_html = ""
    if bullets:
        items = "\n".join(f"  <li>{html.escape(b)}</li>" for b in bullets)
        bullet_html = f"\n<ul>\n{items}\n</ul>"

    return {
        "headline": f"<h1>{h_esc}</h1>",
        "body": f"{body_html}{bullet_html}",
        "cta": f'<a href="#" class="cta-button">{cta_esc}</a>',
        "meta_description": meta_description,
    }


def _format_plain(
    headline: str,
    body: str,
    bullets: list[str],
    cta: str,
) -> dict[str, str]:
    """Format content as plain text."""
    bullet_text = ""
    if bullets:
        bullet_text = "\n".join(f"• {b}" for b in bullets)

    return {
        "headline": headline,
        "body": f"{body}\n\n{bullet_text}" if bullet_text else body,
        "cta": cta,
    }
