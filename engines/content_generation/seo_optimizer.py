"""Content Generation Engine — SEO optimizer.

Optimizes content for search engines: keyword density analysis, meta description
generation, title tag suggestions, and alt-text recommendations.

No model dependency — deterministic analysis and optimization.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any


# ---------------------------------------------------------------------------
# SEO constants
# ---------------------------------------------------------------------------

_IDEAL_META_DESC_LEN = (120, 160)
_IDEAL_TITLE_TAG_LEN = (30, 60)
_IDEAL_KEYWORD_DENSITY = (1.0, 2.5)  # percentage


def optimize_seo(
    draft: dict[str, Any],
    keyword_extraction: dict[str, Any],
    product: dict[str, Any],
) -> dict[str, Any]:
    """Optimize copy draft for SEO.

    Args:
        draft: CopyDraft dict from copy_writer.
        keyword_extraction: KeywordExtraction dict from keyword_extractor.
        product: Original ProductData dict.

    Returns:
        Structured dict with SEOResult data.
    """
    try:
        drft = copy.deepcopy(draft)
        kw = copy.deepcopy(keyword_extraction)
        prod = copy.deepcopy(product)

        headline = str(drft.get("headline", ""))
        body = str(drft.get("body", ""))
        bullets = list(drft.get("bullets", []))

        title = str(prod.get("title", "")).strip()
        category = str(prod.get("category", "")).strip()

        primary_keywords = list(kw.get("primary_keywords", []))
        secondary_keywords = list(kw.get("secondary_keywords", []))
        target_density = float(kw.get("target_density", 1.5))

        # Full text for analysis
        full_text = f"{headline} {body} {' '.join(bullets)}"

        # --- Keyword density analysis ---
        keyword_density = _compute_keyword_density(full_text, primary_keywords + secondary_keywords)

        # --- Meta description ---
        meta_description = _build_meta_description(title, body, primary_keywords, category)

        # --- Title tag ---
        title_tag = _build_title_tag(headline, title, primary_keywords)

        # --- Alt text suggestions ---
        alt_text_suggestions = _build_alt_texts(title, primary_keywords, category)

        # --- SEO score ---
        seo_score = _compute_seo_score(
            keyword_density, primary_keywords, meta_description,
            title_tag, full_text, target_density,
        )

        # --- Recommendations ---
        recommendations = _generate_recommendations(
            keyword_density, primary_keywords, meta_description,
            title_tag, seo_score, target_density,
        )

        return {
            "status": "success",
            "seo": {
                "meta_description": meta_description,
                "title_tag": title_tag,
                "alt_text_suggestions": alt_text_suggestions,
                "keyword_density": keyword_density,
                "seo_score": round(seo_score, 2),
                "recommendations": recommendations,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "seo": {},
            "error": f"SEO optimization failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Keyword density
# ---------------------------------------------------------------------------

def _compute_keyword_density(text: str, keywords: list[str]) -> dict[str, float]:
    """Compute keyword density as percentage for each keyword in text."""
    text_lower = text.lower()
    words = re.findall(r"[a-zA-Z]+", text_lower)
    total_words = len(words) if words else 1

    density: dict[str, float] = {}
    for kw in keywords:
        kw_lower = kw.lower().strip()
        if not kw_lower:
            continue
        # Count occurrences (phrase or single word)
        count = text_lower.count(kw_lower)
        kw_word_count = len(kw_lower.split())
        density_pct = (count * kw_word_count / total_words) * 100.0
        density[kw_lower] = round(density_pct, 2)

    return density


# ---------------------------------------------------------------------------
# Meta description
# ---------------------------------------------------------------------------

def _build_meta_description(
    title: str, body: str, keywords: list[str], category: str,
) -> str:
    """Build an SEO-optimized meta description."""
    kw_phrase = keywords[0] if keywords else category or "product"

    # Start with a compelling description
    desc = f"Discover the {title}"
    if kw_phrase and kw_phrase.lower() not in desc.lower():
        desc += f" — a top {kw_phrase}"
    desc += "."

    # Add from body if room
    body_sentences = [s.strip() for s in body.split(".") if s.strip()]
    for sentence in body_sentences[1:3]:
        candidate = f"{desc} {sentence}."
        if len(candidate) <= _IDEAL_META_DESC_LEN[1]:
            desc = candidate
        else:
            break

    # Truncate if over max
    if len(desc) > _IDEAL_META_DESC_LEN[1]:
        desc = desc[: _IDEAL_META_DESC_LEN[1] - 3].rstrip() + "..."

    return desc


# ---------------------------------------------------------------------------
# Title tag
# ---------------------------------------------------------------------------

def _build_title_tag(headline: str, product_title: str, keywords: list[str]) -> str:
    """Build an SEO title tag."""
    tag = headline if len(headline) <= _IDEAL_TITLE_TAG_LEN[1] else product_title

    # Ensure a primary keyword is present
    if keywords:
        kw = keywords[0]
        if kw.lower() not in tag.lower():
            candidate = f"{tag} | {kw.title()}"
            if len(candidate) <= _IDEAL_TITLE_TAG_LEN[1]:
                tag = candidate

    # Truncate if needed
    if len(tag) > _IDEAL_TITLE_TAG_LEN[1]:
        tag = tag[: _IDEAL_TITLE_TAG_LEN[1] - 3].rstrip() + "..."

    return tag


# ---------------------------------------------------------------------------
# Alt text suggestions
# ---------------------------------------------------------------------------

def _build_alt_texts(title: str, keywords: list[str], category: str) -> list[str]:
    """Build alt-text suggestions for product images."""
    suggestions: list[str] = []
    suggestions.append(f"{title} — {category}" if category else title)

    for kw in keywords[:2]:
        suggestions.append(f"{title} featuring {kw}")

    if category:
        suggestions.append(f"{category} product image — {title}")

    return suggestions[:4]


# ---------------------------------------------------------------------------
# SEO score
# ---------------------------------------------------------------------------

def _compute_seo_score(
    keyword_density: dict[str, float],
    primary_keywords: list[str],
    meta_desc: str,
    title_tag: str,
    full_text: str,
    target_density: float,
) -> float:
    """Compute an overall SEO score (0.0 to 1.0)."""
    score = 0.0
    max_score = 0.0

    # 1. Keyword density in ideal range (30 points)
    max_score += 30.0
    if primary_keywords:
        densities = [
            keyword_density.get(kw.lower(), 0.0)
            for kw in primary_keywords
        ]
        avg_density = sum(densities) / len(densities) if densities else 0.0
        low, high = _IDEAL_KEYWORD_DENSITY
        if low <= avg_density <= high:
            score += 30.0
        elif avg_density > 0:
            # Partial credit
            distance = min(abs(avg_density - low), abs(avg_density - high))
            score += max(0.0, 30.0 - distance * 10.0)

    # 2. Meta description length (20 points)
    max_score += 20.0
    meta_len = len(meta_desc)
    if _IDEAL_META_DESC_LEN[0] <= meta_len <= _IDEAL_META_DESC_LEN[1]:
        score += 20.0
    elif meta_len > 0:
        score += 10.0

    # 3. Title tag length (20 points)
    max_score += 20.0
    tag_len = len(title_tag)
    if _IDEAL_TITLE_TAG_LEN[0] <= tag_len <= _IDEAL_TITLE_TAG_LEN[1]:
        score += 20.0
    elif tag_len > 0:
        score += 10.0

    # 4. Primary keyword in headline/title (15 points)
    max_score += 15.0
    title_lower = title_tag.lower()
    for kw in primary_keywords[:2]:
        if kw.lower() in title_lower:
            score += 7.5

    # 5. Content length (15 points)
    max_score += 15.0
    word_count = len(full_text.split())
    if word_count >= 100:
        score += 15.0
    elif word_count >= 50:
        score += 10.0
    elif word_count >= 20:
        score += 5.0

    return score / max_score if max_score > 0 else 0.0


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def _generate_recommendations(
    keyword_density: dict[str, float],
    primary_keywords: list[str],
    meta_desc: str,
    title_tag: str,
    seo_score: float,
    target_density: float,
) -> list[str]:
    """Generate actionable SEO recommendations."""
    recs: list[str] = []

    # Check keyword density
    for kw in primary_keywords[:3]:
        kw_lower = kw.lower()
        density = keyword_density.get(kw_lower, 0.0)
        low, high = _IDEAL_KEYWORD_DENSITY
        if density < low:
            recs.append(f"Increase usage of '{kw}' — current density {density:.1f}% is below {low}%")
        elif density > high:
            recs.append(f"Reduce usage of '{kw}' — current density {density:.1f}% exceeds {high}%")

    # Check meta description
    meta_len = len(meta_desc)
    if meta_len < _IDEAL_META_DESC_LEN[0]:
        recs.append(f"Meta description too short ({meta_len} chars) — aim for {_IDEAL_META_DESC_LEN[0]}-{_IDEAL_META_DESC_LEN[1]} chars")
    elif meta_len > _IDEAL_META_DESC_LEN[1]:
        recs.append(f"Meta description too long ({meta_len} chars) — trim to under {_IDEAL_META_DESC_LEN[1]} chars")

    # Check title tag
    tag_len = len(title_tag)
    if tag_len < _IDEAL_TITLE_TAG_LEN[0]:
        recs.append(f"Title tag too short ({tag_len} chars) — aim for {_IDEAL_TITLE_TAG_LEN[0]}-{_IDEAL_TITLE_TAG_LEN[1]} chars")
    elif tag_len > _IDEAL_TITLE_TAG_LEN[1]:
        recs.append(f"Title tag too long ({tag_len} chars) — trim to under {_IDEAL_TITLE_TAG_LEN[1]} chars")

    if not recs:
        recs.append("SEO looks good — no critical issues found")

    return recs
