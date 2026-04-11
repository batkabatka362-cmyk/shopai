"""Scorer — computes confidence scores for research results.

Responsibility: evaluate the overall confidence of a research output by
examining source diversity, evidence strength, internal consistency, and
coverage depth.

Model note: no model usage — pure numeric scoring.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from .types import ResearchFeature, AnalysisResult, ScoreResult


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_results(
    features: list[ResearchFeature],
    analysis: AnalysisResult,
) -> ScoreResult:
    """Compute a composite confidence score for the research.

    Never mutates inputs — works on deep copies.
    Returns a ``ScoreResult`` with an overall confidence and sub-scores.
    """
    safe_features: list[ResearchFeature] = copy.deepcopy(features)
    safe_analysis: AnalysisResult = copy.deepcopy(analysis)

    if not safe_features:
        return ScoreResult(
            confidence=0.0,
            source_diversity=0.0,
            evidence_strength=0.0,
            consistency=1.0,
            detail_breakdown={},
        )

    source_diversity = _score_source_diversity(safe_features)
    evidence_strength = _score_evidence_strength(safe_features)
    consistency = _score_consistency(safe_features, safe_analysis)
    coverage = _score_coverage(safe_features)

    # Weighted composite
    confidence = (
        source_diversity * 0.20
        + evidence_strength * 0.35
        + consistency * 0.25
        + coverage * 0.20
    )
    confidence = round(min(max(confidence, 0.0), 1.0), 3)

    return ScoreResult(
        confidence=confidence,
        source_diversity=round(source_diversity, 3),
        evidence_strength=round(evidence_strength, 3),
        consistency=round(consistency, 3),
        detail_breakdown={
            "source_diversity": round(source_diversity, 3),
            "evidence_strength": round(evidence_strength, 3),
            "consistency": round(consistency, 3),
            "coverage": round(coverage, 3),
            "feature_count": len(safe_features),
            "unique_sources": len({f["source_url"] for f in safe_features}),
        },
    )


# ---------------------------------------------------------------------------
# Sub-scores
# ---------------------------------------------------------------------------

def _score_source_diversity(features: list[ResearchFeature]) -> float:
    """Score how diverse the sources are (0–1).

    A single source gets a low score; 5+ unique sources approach 1.0.
    Uses a log curve so there are diminishing returns beyond ~8 sources.
    """
    unique = len({f["source_url"] for f in features})
    if unique <= 1:
        return 0.2
    # log curve: score = ln(unique) / ln(10), capped at 1
    return min(math.log(unique) / math.log(10), 1.0)


def _score_evidence_strength(features: list[ResearchFeature]) -> float:
    """Score the overall strength of evidence (0–1).

    Combines the average feature strength with a bonus for having
    high-strength features and statistical evidence.
    """
    strengths = [f["strength"] for f in features]
    avg = sum(strengths) / len(strengths)

    # Bonus for high-strength features
    strong_count = sum(1 for s in strengths if s >= 0.7)
    strong_ratio = strong_count / len(strengths)

    # Bonus for statistical features (hard data)
    stat_count = sum(1 for f in features if f["category"] == "statistic")
    stat_ratio = min(stat_count / max(len(features), 1), 0.5)

    score = avg * 0.5 + strong_ratio * 0.3 + stat_ratio * 0.2
    return min(score, 1.0)


def _score_consistency(
    features: list[ResearchFeature],
    analysis: AnalysisResult,
) -> float:
    """Score internal consistency (0–1).

    Starts at 1.0 and penalises for contradictions.
    """
    contradictions = len(analysis.get("contradictions", []))
    total = len(features)

    if total == 0:
        return 1.0

    # Each contradiction reduces consistency proportionally
    penalty = contradictions * 0.15
    return max(1.0 - penalty, 0.0)


def _score_coverage(features: list[ResearchFeature]) -> float:
    """Score how thoroughly the research covers the topic (0–1).

    Based on category diversity and total feature count.
    """
    categories = {f["category"] for f in features}
    possible_categories = {"fact", "statistic", "trend", "opinion"}
    cat_coverage = len(categories & possible_categories) / len(possible_categories)

    # Feature count contribution (diminishing returns)
    count = len(features)
    count_score = min(math.log(count + 1) / math.log(20), 1.0)

    return cat_coverage * 0.5 + count_score * 0.5
