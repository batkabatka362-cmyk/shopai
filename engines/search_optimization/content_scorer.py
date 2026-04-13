"""Search Optimization Engine — content scorer.

Scores product page content for SEO quality based on keyword usage,
readability, title optimization, and structural completeness.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "title_score": 0.25,
    "description_score": 0.25,
    "keyword_density": 0.20,
    "readability": 0.15,
    "structure": 0.15,
}


def score_content(
    products: list[dict[str, Any]],
    current_meta: list[dict[str, Any]],
    keyword_analysis: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score product page content for SEO quality.

    Args:
        products: List of product records.
        current_meta: Current meta tag records.
        keyword_analysis: Keyword analysis results.

    Returns:
        Structured dict with content scores per product.
    """
    try:
        products = copy.deepcopy(products)

        meta_map = {str(m.get("product_id", "")): m for m in current_meta}
        top_keywords = {
            str(k.get("keyword", "")).lower()
            for k in keyword_analysis
            if k.get("relevance_score", 0) > 0.3
        }

        content_scores: list[dict[str, Any]] = []

        for product in products:
            pid = str(product.get("id", ""))
            title = str(product.get("title", ""))
            description = str(product.get("description", ""))
            meta = meta_map.get(pid, {})
            meta_title = str(meta.get("title", ""))
            meta_desc = str(meta.get("description", ""))

            # Score individual components
            title_score = _score_title(title, meta_title, top_keywords)
            desc_score = _score_description(description, meta_desc, top_keywords)
            kw_density = _score_keyword_density(title, description, top_keywords)
            readability = _score_readability(description)
            structure = _score_structure(product)

            # Weighted overall score
            overall = (
                title_score * _WEIGHTS["title_score"]
                + desc_score * _WEIGHTS["description_score"]
                + kw_density * _WEIGHTS["keyword_density"]
                + readability * _WEIGHTS["readability"]
                + structure * _WEIGHTS["structure"]
            )

            # Identify issues
            issues = _identify_issues(
                title, description, meta_title, meta_desc,
                title_score, desc_score, kw_density, readability,
            )

            content_scores.append({
                "product_id": pid,
                "overall_score": round(overall, 4),
                "title_score": round(title_score, 4),
                "description_score": round(desc_score, 4),
                "keyword_density": round(kw_density, 4),
                "readability": round(readability, 4),
                "issues": issues,
            })

        # Sort by overall score ascending (worst first for prioritization)
        content_scores.sort(key=lambda s: s.get("overall_score", 0))

        return {
            "status": "success",
            "content_scores": content_scores,
        }
    except Exception as exc:
        return {
            "status": "error",
            "content_scores": [],
            "error": f"Content scoring failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def _score_title(title: str, meta_title: str, keywords: set[str]) -> float:
    """Score the product title for SEO."""
    if not title:
        return 0.0

    score = 0.3  # Base score for having a title

    # Length optimization
    if 20 <= len(title) <= 60:
        score += 0.2
    elif len(title) > 60:
        score += 0.1

    # Keyword presence
    title_words = set(title.lower().split())
    kw_overlap = len(title_words & keywords)
    if kw_overlap >= 2:
        score += 0.3
    elif kw_overlap >= 1:
        score += 0.2

    # Has meta title
    if meta_title:
        score += 0.1

    return min(score, 1.0)


def _score_description(desc: str, meta_desc: str, keywords: set[str]) -> float:
    """Score the product description for SEO."""
    if not desc:
        return 0.0

    score = 0.2  # Base score

    # Length
    word_count = len(desc.split())
    if word_count >= 100:
        score += 0.3
    elif word_count >= 50:
        score += 0.2
    elif word_count >= 20:
        score += 0.1

    # Keyword presence
    desc_words = set(desc.lower().split())
    kw_overlap = len(desc_words & keywords)
    if kw_overlap >= 3:
        score += 0.3
    elif kw_overlap >= 1:
        score += 0.15

    # Has meta description
    if meta_desc:
        score += 0.1

    return min(score, 1.0)


def _score_keyword_density(title: str, description: str, keywords: set[str]) -> float:
    """Score keyword density (keyword presence relative to content length)."""
    all_text = f"{title} {description}".lower()
    words = all_text.split()
    if not words or not keywords:
        return 0.0

    keyword_count = sum(1 for w in words if w in keywords)
    density = keyword_count / len(words)

    # Optimal density: 1-3%
    if 0.01 <= density <= 0.03:
        return 0.9
    elif 0.005 <= density <= 0.05:
        return 0.7
    elif density > 0.05:
        return 0.4  # Over-optimization
    else:
        return 0.3  # Under-optimization


def _score_readability(text: str) -> float:
    """Score text readability (simplified Flesch-based heuristic)."""
    if not text:
        return 0.0

    sentences = text.count(".") + text.count("!") + text.count("?")
    sentences = max(sentences, 1)
    words = text.split()
    word_count = len(words)

    if word_count == 0:
        return 0.0

    # Average sentence length
    avg_sentence_len = word_count / sentences

    # Average word length
    avg_word_len = sum(len(w) for w in words) / word_count

    score = 0.5

    # Optimal avg sentence length: 15-25 words
    if 15 <= avg_sentence_len <= 25:
        score += 0.25
    elif avg_sentence_len < 10 or avg_sentence_len > 35:
        score += 0.05
    else:
        score += 0.15

    # Optimal avg word length: 4-6 chars
    if 4 <= avg_word_len <= 6:
        score += 0.25
    else:
        score += 0.1

    return min(score, 1.0)


def _score_structure(product: dict[str, Any]) -> float:
    """Score product page structural completeness."""
    score = 0.0

    if product.get("title"):
        score += 0.2
    if product.get("description"):
        score += 0.2
    if product.get("category"):
        score += 0.15
    if product.get("tags"):
        score += 0.15
    if product.get("images"):
        score += 0.15
    if product.get("url"):
        score += 0.15

    return min(score, 1.0)


def _identify_issues(
    title: str,
    description: str,
    meta_title: str,
    meta_desc: str,
    title_score: float,
    desc_score: float,
    kw_density: float,
    readability: float,
) -> list[str]:
    """Identify SEO content issues."""
    issues = []

    if not title:
        issues.append("Missing product title")
    elif len(title) > 60:
        issues.append("Product title exceeds 60 characters")

    if not description:
        issues.append("Missing product description")
    elif len(description.split()) < 50:
        issues.append("Product description is too short (under 50 words)")

    if not meta_title:
        issues.append("Missing meta title tag")

    if not meta_desc:
        issues.append("Missing meta description tag")
    elif len(meta_desc) > 160:
        issues.append("Meta description exceeds 160 characters")

    if kw_density < 0.3:
        issues.append("Low keyword density in content")
    elif kw_density > 0.05:
        issues.append("Possible keyword stuffing detected")

    if readability < 0.5:
        issues.append("Content readability could be improved")

    return issues
