"""Synthesizer — combines analysis into coherent findings and recommendations.

Responsibility: take the ``AnalysisResult`` and source ``ResearchFeature``
list and produce a single, coherent ``SynthesisResult`` with a narrative
insight, key findings, and a recommended action.

Model note: would use **LLaMA** for creative synthesis.
"""
from __future__ import annotations

import copy
from typing import Any

from .types import AnalysisResult, ResearchFeature, SynthesisResult


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def synthesize(
    analysis: AnalysisResult,
    features: list[ResearchFeature],
    original_query: str,
) -> SynthesisResult:
    """Synthesize analysis results into a coherent research output.

    Never mutates inputs — works on deep copies.
    Returns a ``SynthesisResult`` even when inputs are sparse.
    """
    safe_analysis: AnalysisResult = copy.deepcopy(analysis)
    safe_features: list[ResearchFeature] = copy.deepcopy(features)

    if not safe_features:
        return SynthesisResult(
            insight=f"Insufficient evidence to draw conclusions about: {original_query}",
            key_findings=[],
            recommended_action="Broaden research scope or refine the query to gather more data.",
            model_used="llama",
        )

    insight = _compose_insight(safe_analysis, safe_features, original_query)
    key_findings = _extract_key_findings(safe_analysis, safe_features)
    recommended_action = _derive_recommendation(
        safe_analysis, safe_features, original_query,
    )

    return SynthesisResult(
        insight=insight,
        key_findings=key_findings,
        recommended_action=recommended_action,
        model_used="llama",
    )


# ---------------------------------------------------------------------------
# Insight composition
# ---------------------------------------------------------------------------

def _compose_insight(
    analysis: AnalysisResult,
    features: list[ResearchFeature],
    query: str,
) -> str:
    """Build a narrative summary paragraph from analysis and features.

    In production LLaMA would generate free-form text.  Here we use
    structured template composition for determinism.
    """
    parts: list[str] = []

    # Opening — frame the research topic
    total = len(features)
    sources = len({f["source_url"] for f in features})
    parts.append(
        f"Based on analysis of {total} research features from {sources} source(s) "
        f"regarding \"{query}\":"
    )

    # Core findings from strongest features
    strong = sorted(features, key=lambda f: f["strength"], reverse=True)[:3]
    if strong:
        claims = "; ".join(f["claim"][:120] for f in strong)
        parts.append(f"The strongest evidence indicates: {claims}.")

    # Patterns summary
    category_patterns = [
        p for p in analysis.get("patterns", [])
        if p.get("category") != "theme"
    ]
    if category_patterns:
        top = category_patterns[0]
        parts.append(
            f"The most prominent pattern is in {top['category']} data "
            f"({top['count']} features, avg strength {top['avg_strength']})."
        )

    # Contradiction caveat
    contradictions = analysis.get("contradictions", [])
    if contradictions:
        parts.append(
            f"Note: {len(contradictions)} contradiction(s) were found, "
            f"indicating areas where sources disagree."
        )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Key findings extraction
# ---------------------------------------------------------------------------

def _extract_key_findings(
    analysis: AnalysisResult,
    features: list[ResearchFeature],
) -> list[str]:
    """Select the most important findings, deduped and ranked."""
    findings: list[str] = []
    seen_claims: set[str] = set()

    # Pull from top-strength features
    ranked = sorted(features, key=lambda f: f["strength"], reverse=True)

    for f in ranked:
        normalised = f["claim"].lower().strip()
        if normalised in seen_claims:
            continue
        seen_claims.add(normalised)
        findings.append(f["claim"])
        if len(findings) >= 5:
            break

    # Add insights from analysis that aren't already covered
    for ins in analysis.get("insights", []):
        if len(findings) >= 7:
            break
        # Avoid near-duplicates
        ins_lower = ins.lower()
        if not any(fc.lower() in ins_lower or ins_lower in fc.lower() for fc in findings):
            findings.append(ins)

    return findings


# ---------------------------------------------------------------------------
# Recommendation derivation
# ---------------------------------------------------------------------------

_STRENGTH_THRESHOLDS = {
    "strong":   0.70,
    "moderate": 0.45,
}


def _derive_recommendation(
    analysis: AnalysisResult,
    features: list[ResearchFeature],
    query: str,
) -> str:
    """Produce a single recommended next-action based on the research.

    Logic:
    * Strong evidence + no contradictions → act on the findings
    * Strong evidence + contradictions → investigate contradictions first
    * Moderate evidence → supplement with primary research
    * Weak evidence → re-scope or broaden the research
    """
    avg_strength = (
        sum(f["strength"] for f in features) / len(features)
        if features else 0.0
    )
    has_contradictions = bool(analysis.get("contradictions"))
    stat_count = sum(1 for f in features if f["category"] == "statistic")

    if avg_strength >= _STRENGTH_THRESHOLDS["strong"] and not has_contradictions:
        return (
            f"Evidence strongly supports taking action on \"{query}\". "
            f"Proceed with implementation, leveraging the {stat_count} "
            f"statistical data points identified."
        )

    if avg_strength >= _STRENGTH_THRESHOLDS["strong"] and has_contradictions:
        return (
            f"Strong evidence exists but contradictions were detected. "
            f"Recommend targeted follow-up research to resolve conflicting "
            f"claims before committing resources."
        )

    if avg_strength >= _STRENGTH_THRESHOLDS["moderate"]:
        return (
            f"Moderate evidence found for \"{query}\". "
            f"Supplement with primary research (surveys, interviews, or A/B tests) "
            f"to strengthen confidence before making decisions."
        )

    return (
        f"Evidence for \"{query}\" is currently weak (avg strength "
        f"{avg_strength:.2f}). Recommend broadening the research scope, "
        f"refining the query, or sourcing domain-specific data."
    )
