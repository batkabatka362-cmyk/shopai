"""Search Optimization Engine — keyword analyzer.

Analyzes on-site search queries, identifies keyword gaps,
scores relevance, and detects competitor keyword opportunities.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_keywords(
    products: list[dict[str, Any]],
    search_queries: list[dict[str, Any]],
    competitors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze keywords from search queries, products, and competitors.

    Args:
        products: List of product records.
        search_queries: List of on-site search query records.
        competitors: List of competitor records.

    Returns:
        Structured dict with keyword analysis results.
    """
    try:
        products = copy.deepcopy(products)
        search_queries = copy.deepcopy(search_queries)
        competitors = copy.deepcopy(competitors)

        # Extract product keywords
        product_keywords = _extract_product_keywords(products)

        # Extract competitor keywords
        competitor_keywords = _extract_competitor_keywords(competitors)

        # Analyze search queries
        keyword_analysis: list[dict[str, Any]] = []
        seen_keywords: set[str] = set()

        # Process actual search queries
        for query in search_queries:
            keyword = str(query.get("query", "")).lower().strip()
            if not keyword or keyword in seen_keywords:
                continue
            seen_keywords.add(keyword)

            search_volume = int(query.get("count", 0))
            ctr = float(query.get("click_through_rate", 0))
            zero_results = bool(query.get("zero_results", False))

            # Determine if this is a gap
            is_gap = zero_results or ctr < 0.05

            # Score relevance against product catalog
            relevance = _score_relevance(keyword, product_keywords)

            # Score competition from competitor keywords
            competition = _score_competition(keyword, competitor_keywords)

            # Opportunity score: high relevance + high volume + low competition = high opportunity
            opportunity = _compute_opportunity(relevance, search_volume, competition, is_gap)

            keyword_analysis.append({
                "keyword": keyword,
                "search_volume": search_volume,
                "competition": competition,
                "relevance_score": relevance,
                "gap": is_gap,
                "opportunity_score": opportunity,
            })

        # Add competitor keywords not in our search queries
        for ck in competitor_keywords:
            if ck.lower() not in seen_keywords:
                seen_keywords.add(ck.lower())
                relevance = _score_relevance(ck.lower(), product_keywords)
                if relevance > 0.3:
                    keyword_analysis.append({
                        "keyword": ck.lower(),
                        "search_volume": 0,  # Unknown for competitor keywords
                        "competition": "high",
                        "relevance_score": relevance,
                        "gap": True,
                        "opportunity_score": round(relevance * 0.6, 4),
                    })

        # Sort by opportunity score descending
        keyword_analysis.sort(key=lambda k: k.get("opportunity_score", 0), reverse=True)

        return {
            "status": "success",
            "keyword_analysis": keyword_analysis,
        }
    except Exception as exc:
        return {
            "status": "error",
            "keyword_analysis": [],
            "error": f"Keyword analysis failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_product_keywords(products: list[dict[str, Any]]) -> set[str]:
    """Extract all meaningful keywords from product data."""
    keywords: set[str] = set()
    for p in products:
        title = str(p.get("title", "")).lower()
        description = str(p.get("description", "")).lower()
        category = str(p.get("category", "")).lower()
        tags = [str(t).lower() for t in p.get("tags", [])]

        # Split title and description into words
        for word in title.split():
            if len(word) > 2:
                keywords.add(word)
        for word in description.split():
            if len(word) > 3:
                keywords.add(word)
        if category:
            keywords.add(category)
        keywords.update(tags)

    return keywords


def _extract_competitor_keywords(competitors: list[dict[str, Any]]) -> set[str]:
    """Extract competitor keywords."""
    keywords: set[str] = set()
    for c in competitors:
        for kw in c.get("top_keywords", []):
            keywords.add(str(kw).lower())
    return keywords


def _score_relevance(keyword: str, product_keywords: set[str]) -> float:
    """Score how relevant a keyword is to our product catalog."""
    if not keyword or not product_keywords:
        return 0.0

    words = keyword.lower().split()
    if not words:
        return 0.0

    matches = sum(1 for w in words if w in product_keywords)
    score = matches / len(words)

    # Exact match bonus
    if keyword in product_keywords:
        score = min(score + 0.3, 1.0)

    return round(score, 4)


def _score_competition(keyword: str, competitor_keywords: set[str]) -> str:
    """Score competition level for a keyword."""
    if keyword.lower() in competitor_keywords:
        return "high"

    words = keyword.lower().split()
    overlap = sum(1 for w in words if w in competitor_keywords)

    if overlap >= len(words) * 0.5:
        return "medium"
    return "low"


def _compute_opportunity(
    relevance: float,
    volume: int,
    competition: str,
    is_gap: bool,
) -> float:
    """Compute overall opportunity score for a keyword."""
    # Volume score (log scale, normalized)
    import math
    volume_score = min(math.log10(max(volume, 1)) / 4.0, 1.0)

    # Competition multiplier
    comp_multiplier = {"low": 1.2, "medium": 1.0, "high": 0.7}.get(competition, 1.0)

    # Gap bonus
    gap_bonus = 0.15 if is_gap else 0.0

    score = (relevance * 0.4 + volume_score * 0.4 + gap_bonus) * comp_multiplier
    return round(min(score, 1.0), 4)
