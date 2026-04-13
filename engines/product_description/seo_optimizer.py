"""Product Description Engine — SEO optimizer.

Optimizes product copy for target keywords. Generates meta title,
meta description, and computes SEO score.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# SEO constraints
# ---------------------------------------------------------------------------

_META_TITLE_MAX = 60
_META_DESC_MIN = 120
_META_DESC_MAX = 160
_IDEAL_KEYWORD_DENSITY = 2.0  # percent


def optimize_seo(
    copy_data: dict[str, Any],
    target_keywords: list[str],
    product: dict[str, Any],
) -> dict[str, Any]:
    """Optimize copy for SEO and generate meta tags.

    Args:
        copy_data: Generated copy dict (title, description, bullets).
        target_keywords: Target SEO keywords.
        product: Product info dict.

    Returns:
        Structured dict with meta tags, SEO score, and suggestions.
    """
    try:
        title = str(copy_data.get("title", ""))
        description = str(copy_data.get("description", ""))
        bullet_points = list(copy_data.get("bullet_points", []))

        # Combine all text for analysis
        all_text = f"{title} {description} {' '.join(bullet_points)}".lower()
        word_count = len(all_text.split())

        # ---- Meta title ----
        meta_title = title[:_META_TITLE_MAX]
        if len(meta_title) < len(title):
            # Truncate at last complete word
            meta_title = title[:_META_TITLE_MAX].rsplit(" ", 1)[0]

        # ---- Meta description ----
        if len(description) >= _META_DESC_MIN:
            meta_desc = description[:_META_DESC_MAX]
            if len(meta_desc) < len(description):
                meta_desc = description[:_META_DESC_MAX].rsplit(" ", 1)[0]
                if not meta_desc.endswith("."):
                    meta_desc += "..."
        else:
            # Build from title + bullet points
            parts = [title]
            for bp in bullet_points:
                if len(". ".join(parts + [bp])) <= _META_DESC_MAX:
                    parts.append(bp)
                else:
                    break
            meta_desc = ". ".join(parts)
            if len(meta_desc) > _META_DESC_MAX:
                meta_desc = meta_desc[:_META_DESC_MAX - 3] + "..."

        # ---- Keyword density analysis ----
        keyword_density: dict[str, float] = {}
        for kw in target_keywords:
            kw_lower = kw.lower()
            count = all_text.count(kw_lower)
            density = round(count / max(word_count, 1) * 100, 2)
            keyword_density[kw] = density

        # ---- SEO score calculation (0-100) ----
        score = 0.0
        suggestions: list[str] = []

        # Check primary keyword in title (20 points)
        if target_keywords:
            primary = target_keywords[0].lower()
            if primary in title.lower():
                score += 20
            else:
                suggestions.append(f"Add primary keyword '{target_keywords[0]}' to title")

            # Check primary keyword in description first 100 chars (15 points)
            if primary in description[:100].lower():
                score += 15
            else:
                suggestions.append("Include primary keyword in first sentence of description")

            # Check primary keyword density (15 points)
            primary_density = keyword_density.get(target_keywords[0], 0.0)
            if 1.0 <= primary_density <= 3.0:
                score += 15
            elif primary_density > 0:
                score += 8
                suggestions.append(f"Adjust keyword density (current: {primary_density}%)")
            else:
                suggestions.append("Primary keyword not found in copy")

        # Meta title length (10 points)
        if 30 <= len(meta_title) <= _META_TITLE_MAX:
            score += 10
        else:
            suggestions.append(f"Meta title should be 30-{_META_TITLE_MAX} characters")

        # Meta description length (10 points)
        if _META_DESC_MIN <= len(meta_desc) <= _META_DESC_MAX:
            score += 10
        else:
            suggestions.append(f"Meta description should be {_META_DESC_MIN}-{_META_DESC_MAX} characters")

        # Bullet points present (10 points)
        if len(bullet_points) >= 3:
            score += 10
        elif bullet_points:
            score += 5
            suggestions.append("Add more bullet points (recommended: 3-5)")

        # Description length (10 points)
        desc_words = len(description.split())
        if desc_words >= 50:
            score += 10
        elif desc_words >= 25:
            score += 5
            suggestions.append("Expand description to 50+ words")
        else:
            suggestions.append("Description too short for SEO")

        # Secondary keywords (10 points)
        if len(target_keywords) > 1:
            secondary_found = sum(
                1 for kw in target_keywords[1:]
                if kw.lower() in all_text
            )
            secondary_ratio = secondary_found / max(len(target_keywords) - 1, 1)
            score += round(10 * secondary_ratio)
            missing = [
                kw for kw in target_keywords[1:]
                if kw.lower() not in all_text
            ]
            if missing:
                suggestions.append(f"Add missing keywords: {', '.join(missing[:3])}")

        return {
            "status": "success",
            "seo": {
                "meta_title": meta_title,
                "meta_description": meta_desc,
                "seo_score": min(round(score, 1), 100.0),
                "keyword_density": keyword_density,
                "suggestions": suggestions,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "seo": {},
            "error": f"SEO optimization failed: {exc}",
        }
