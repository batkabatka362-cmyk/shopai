"""Global Brain — context provider.

Builds a context payload for requesting engines. Packages relevant
knowledge, related patterns, and actionable recommendations.

Model note: Would use LLaMA for high-level insight synthesis
to generate recommendations.
No connections to other modules — called only from flow.py.
"""
from __future__ import annotations

from typing import Any


def build_context(
    retrieval_results: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    requesting_engine: str = "",
) -> dict[str, Any]:
    """Build a context payload for the requesting engine.

    Assembles retrieval results, finds related patterns, and
    generates recommendations based on available knowledge.

    Args:
        retrieval_results: List of RetrievalResult dicts from retriever.
        patterns: All known patterns from memory/current session.
        requesting_engine: Name of the engine requesting context.

    Returns:
        Structured dict with context, related_patterns, and recommendations.

    Model note: In production, LLaMA would synthesize insights from
    the retrieved knowledge to produce high-level recommendations.
    Here we use rule-based generation.
    """
    try:
        # ---- Build context list ----
        context = _build_context_items(retrieval_results)

        # ---- Find related patterns ----
        related_patterns = _find_related_patterns(retrieval_results, patterns)

        # ---- Generate recommendations ----
        recommendations = _generate_recommendations(
            retrieval_results, related_patterns, requesting_engine,
        )

        return {
            "status": "success",
            "context": context,
            "related_patterns": related_patterns,
            "recommendations": recommendations,
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "context": [],
            "related_patterns": [],
            "recommendations": [],
            "error": f"Context building failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_context_items(
    retrieval_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Format retrieval results as context items."""
    context: list[dict[str, Any]] = []
    for result in retrieval_results:
        context.append({
            "entry_id": result.get("entry_id", ""),
            "content": result.get("content", ""),
            "category": result.get("category", ""),
            "relevance_score": result.get("relevance_score", 0.0),
            "source_engine": result.get("source_engine", ""),
            "timestamp": result.get("timestamp", ""),
            "knowledge_type": result.get("knowledge_type", ""),
        })
    return context


def _find_related_patterns(
    retrieval_results: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find patterns related to the retrieved knowledge.

    Matches patterns whose supporting items overlap with retrieval results,
    or whose description shares keywords with retrieved content.
    """
    if not patterns or not retrieval_results:
        return []

    retrieved_ids = {r.get("entry_id", "") for r in retrieval_results}
    retrieved_words: set[str] = set()
    for r in retrieval_results:
        retrieved_words.update(r.get("content", "").lower().split())

    # Remove common words
    retrieved_words -= {
        "the", "a", "an", "is", "are", "was", "were", "to", "of", "in",
        "for", "on", "with", "at", "by", "from", "and", "or", "but",
    }

    related: list[dict[str, Any]] = []
    for pattern in patterns:
        # Check supporting item overlap
        supporting = set(pattern.get("supporting_items", []))
        id_overlap = supporting & retrieved_ids

        # Check description keyword overlap
        desc_words = set(pattern.get("description", "").lower().split())
        desc_words -= {
            "the", "a", "an", "is", "are", "was", "were", "to", "of", "in",
            "for", "on", "with", "at", "by", "from", "and", "or", "but",
            "detected", "across", "items", "between", "knowledge",
        }
        word_overlap = retrieved_words & desc_words

        if id_overlap or len(word_overlap) >= 2:
            related.append(pattern)

    return related


def _generate_recommendations(
    retrieval_results: list[dict[str, Any]],
    related_patterns: list[dict[str, Any]],
    requesting_engine: str,
) -> list[str]:
    """Generate actionable recommendations from context.

    Model note: In production, LLaMA would synthesize high-level
    recommendations. Here we use rule-based generation based on
    knowledge types and patterns found.
    """
    recommendations: list[str] = []

    if not retrieval_results:
        return recommendations

    # Recommendation from correlations
    correlations = [
        r for r in retrieval_results
        if r.get("knowledge_type") == "correlation"
    ]
    for corr in correlations[:2]:
        content = corr.get("content", "")
        if content:
            recommendations.append(
                f"Consider acting on correlation: {content}"
            )

    # Recommendation from rules
    rules = [
        r for r in retrieval_results
        if r.get("knowledge_type") == "rule"
    ]
    for rule in rules[:2]:
        content = rule.get("content", "")
        if content:
            recommendations.append(
                f"Ensure compliance with rule: {content}"
            )

    # Recommendation from high-confidence facts
    facts = [
        r for r in retrieval_results
        if r.get("knowledge_type") == "fact"
        and r.get("relevance_score", 0.0) >= 0.3
    ]
    for fact in facts[:2]:
        content = fact.get("content", "")
        if content:
            recommendations.append(
                f"Factor in established fact: {content}"
            )

    # Pattern-based recommendations
    for pattern in related_patterns[:2]:
        desc = pattern.get("description", "")
        ptype = pattern.get("pattern_type", "")
        if desc:
            if ptype == "recurring":
                recommendations.append(
                    f"Monitor recurring pattern: {desc}"
                )
            elif ptype == "trend":
                recommendations.append(
                    f"Track emerging trend: {desc}"
                )
            elif ptype == "correlation":
                recommendations.append(
                    f"Investigate cross-source correlation: {desc}"
                )

    # If no specific recommendations, provide a general insight-based one
    if not recommendations and retrieval_results:
        top = retrieval_results[0]
        content = top.get("content", "")
        if content:
            recommendations.append(
                f"Review top relevant insight: {content}"
            )

    return recommendations
