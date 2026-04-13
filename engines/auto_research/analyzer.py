"""Analyzer — finds patterns and insights across research features.

Responsibility: consume ``ResearchFeature`` records produced by the
feature builder, detect patterns (agreement, contradiction, trends),
and surface actionable insights.

Model note: would use **Mistral** for analysis and validation.
"""
from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any

from .types import ResearchFeature, AnalysisResult


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_features(
    features: list[ResearchFeature],
    original_query: str,
) -> AnalysisResult:
    """Analyze a set of research features and return patterns + insights.

    Never mutates *features* — works on a deep copy.
    Returns an ``AnalysisResult`` dict even when the input is empty.
    """
    safe_features: list[ResearchFeature] = copy.deepcopy(features)

    if not safe_features:
        return AnalysisResult(
            patterns=[],
            insights=["Insufficient data to generate insights."],
            contradictions=[],
            model_used="mistral",
        )

    patterns = _detect_patterns(safe_features)
    contradictions = _detect_contradictions(safe_features)
    insights = _generate_insights(safe_features, patterns, contradictions, original_query)

    return AnalysisResult(
        patterns=patterns,
        insights=insights,
        contradictions=contradictions,
        model_used="mistral",
    )


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------

def _detect_patterns(features: list[ResearchFeature]) -> list[dict[str, Any]]:
    """Group features by category and surface recurring themes."""
    patterns: list[dict[str, Any]] = []

    # Group by category
    by_category: dict[str, list[ResearchFeature]] = defaultdict(list)
    for f in features:
        by_category[f["category"]].append(f)

    for category, group in by_category.items():
        if len(group) < 1:
            continue

        avg_strength = sum(f["strength"] for f in group) / len(group)
        sources = list({f["source_url"] for f in group})

        # Identify the top claim in this category
        top = max(group, key=lambda f: f["strength"])

        patterns.append({
            "category": category,
            "count": len(group),
            "avg_strength": round(avg_strength, 3),
            "top_claim": top["claim"],
            "sources": sources,
        })

    # Theme clustering via keyword co-occurrence
    keyword_groups = _cluster_by_keywords(features)
    for theme, members in keyword_groups.items():
        if len(members) >= 2:
            patterns.append({
                "category": "theme",
                "theme": theme,
                "count": len(members),
                "avg_strength": round(
                    sum(f["strength"] for f in members) / len(members), 3
                ),
                "top_claim": max(members, key=lambda f: f["strength"])["claim"],
                "sources": list({f["source_url"] for f in members}),
            })

    # Sort patterns by combined significance
    patterns.sort(
        key=lambda p: p.get("count", 0) * p.get("avg_strength", 0),
        reverse=True,
    )

    return patterns


def _cluster_by_keywords(features: list[ResearchFeature]) -> dict[str, list[ResearchFeature]]:
    """Cluster features by shared significant keywords."""
    # Extract significant keywords from each claim
    _STOP_WORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "and", "but", "or",
        "nor", "not", "so", "yet", "both", "either", "neither", "each",
        "every", "all", "any", "few", "more", "most", "other", "some",
        "such", "no", "only", "own", "same", "than", "too", "very",
        "that", "this", "these", "those", "it", "its", "their", "them",
    }

    keyword_map: dict[str, list[ResearchFeature]] = defaultdict(list)

    for f in features:
        tokens = set(f["claim"].lower().split())
        significant = tokens - _STOP_WORDS
        # Keep only tokens >= 4 chars to avoid noise
        significant = {t.strip(".,;:!?\"'()") for t in significant if len(t) >= 4}
        for kw in significant:
            keyword_map[kw].append(f)

    # Only return keywords that appear in multiple features
    return {kw: members for kw, members in keyword_map.items() if len(members) >= 2}


# ---------------------------------------------------------------------------
# Contradiction detection
# ---------------------------------------------------------------------------

_CONTRADICTION_PAIRS = [
    ({"increase", "growth", "rising", "grew", "rose", "surge"},
     {"decrease", "decline", "falling", "fell", "dropped", "shrink"}),
    ({"outperform", "better", "superior", "leading"},
     {"underperform", "worse", "inferior", "lagging"}),
]


def _detect_contradictions(features: list[ResearchFeature]) -> list[str]:
    """Find features that make opposing claims."""
    contradictions: list[str] = []

    for i, fa in enumerate(features):
        tokens_a = set(fa["claim"].lower().split())
        for fb in features[i + 1:]:
            tokens_b = set(fb["claim"].lower().split())

            for pos_set, neg_set in _CONTRADICTION_PAIRS:
                a_pos = bool(tokens_a & pos_set)
                a_neg = bool(tokens_a & neg_set)
                b_pos = bool(tokens_b & pos_set)
                b_neg = bool(tokens_b & neg_set)

                if (a_pos and b_neg) or (a_neg and b_pos):
                    msg = (
                        f"Potential contradiction: \"{fa['claim'][:80]}\" "
                        f"vs \"{fb['claim'][:80]}\""
                    )
                    contradictions.append(msg)

    return contradictions


# ---------------------------------------------------------------------------
# Insight generation
# ---------------------------------------------------------------------------

def _generate_insights(
    features: list[ResearchFeature],
    patterns: list[dict[str, Any]],
    contradictions: list[str],
    query: str,
) -> list[str]:
    """Produce human-readable insights from the analysis.

    In production, Mistral would generate these.  Here we use
    template-based generation for determinism.
    """
    insights: list[str] = []

    # Category distribution insight
    cat_counts: dict[str, int] = defaultdict(int)
    for f in features:
        cat_counts[f["category"]] += 1

    total = len(features)
    if total > 0:
        dominant = max(cat_counts, key=lambda c: cat_counts[c])
        pct = round(cat_counts[dominant] / total * 100)
        insights.append(
            f"Research is dominated by {dominant} content ({pct}% of {total} features), "
            f"suggesting {'strong quantitative evidence' if dominant == 'statistic' else 'qualitative coverage'}."
        )

    # Strength distribution insight
    strong = [f for f in features if f["strength"] >= 0.7]
    if strong:
        insights.append(
            f"{len(strong)} high-confidence features identified, "
            f"with the strongest being: \"{strong[0]['claim'][:100]}\"."
        )

    # Source diversity insight
    unique_sources = {f["source_url"] for f in features}
    insights.append(
        f"Evidence gathered from {len(unique_sources)} unique source(s), "
        f"{'providing good cross-validation' if len(unique_sources) >= 3 else 'consider expanding source diversity'}."
    )

    # Theme-based insight
    theme_patterns = [p for p in patterns if p.get("category") == "theme"]
    if theme_patterns:
        top_theme = theme_patterns[0]
        insights.append(
            f"Dominant research theme: '{top_theme['theme']}' appears across "
            f"{top_theme['count']} features with avg strength {top_theme['avg_strength']}."
        )

    # Contradiction warning
    if contradictions:
        insights.append(
            f"Warning: {len(contradictions)} potential contradiction(s) detected — "
            f"findings should be interpreted with caution."
        )

    return insights
