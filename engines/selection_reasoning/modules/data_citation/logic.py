"""Data Citation — ranking and filtering logic for citations.

Ranks citations by their impact on the decision and filters out
citations that are not relevant to the specific selection rationale.
Higher-impact citations appear first to lead with the strongest evidence.
"""

from __future__ import annotations

from typing import Any


# Impact priority ordering
IMPACT_PRIORITY: dict[str, int] = {
    "high": 1,
    "medium": 2,
    "low": 3,
}

# Category priority — profitability and risk data always matter most
CATEGORY_PRIORITY: dict[str, int] = {
    "profitability": 1,
    "risk": 2,
    "demand": 3,
    "competition": 4,
    "overall": 5,
    "trend": 6,
    "market": 7,
}


def rank_citations_by_impact(
    citations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rank citations by impact and category priority.

    High-impact citations from critical categories (profitability, risk)
    appear first. Within the same impact level, category priority breaks ties.

    Args:
        citations: List of citation dicts with 'impact' and 'category' keys.

    Returns:
        Sorted list of citations (highest impact first).
    """
    if not citations:
        return []

    def sort_key(citation: dict[str, Any]) -> tuple[int, int]:
        impact = citation.get("impact", "low")
        category = citation.get("category", "general")
        return (
            IMPACT_PRIORITY.get(impact, 99),
            CATEGORY_PRIORITY.get(category, 99),
        )

    return sorted(citations, key=sort_key)


def filter_relevant_citations(
    citations: list[dict[str, Any]],
    decision: dict[str, Any],
) -> list[dict[str, Any]]:
    """Filter citations to keep only those relevant to the decision.

    Always keeps profitability, demand, and risk citations (required).
    Other citations are kept if they contributed to the decision rationale
    or have high impact. Removes duplicate data points.

    Args:
        citations: Ranked list of citation dicts.
        decision: Decision rationale dict with factors that drove selection.

    Returns:
        Filtered list of citations.
    """
    if not citations:
        return []

    # Required categories — always include at least one from each
    required_categories = {"profitability", "demand", "risk"}
    seen_data_points: set[str] = set()
    result: list[dict[str, Any]] = []

    # First pass: include required categories and high-impact citations
    for citation in citations:
        data_point = citation.get("data_point", "")
        if data_point in seen_data_points:
            continue

        category = citation.get("category", "")
        impact = citation.get("impact", "low")

        include = False
        if category in required_categories:
            include = True
        elif impact == "high":
            include = True
        elif category == "overall":
            include = True

        if include:
            result.append(citation)
            seen_data_points.add(data_point)

    # Second pass: fill with medium-impact if we have fewer than 5
    if len(result) < 5:
        for citation in citations:
            data_point = citation.get("data_point", "")
            if data_point in seen_data_points:
                continue
            impact = citation.get("impact", "low")
            if impact in ("medium", "high"):
                result.append(citation)
                seen_data_points.add(data_point)
            if len(result) >= 8:
                break

    # Third pass: add remaining if still under minimum
    if len(result) < 5:
        for citation in citations:
            data_point = citation.get("data_point", "")
            if data_point in seen_data_points:
                continue
            result.append(citation)
            seen_data_points.add(data_point)
            if len(result) >= 5:
                break

    return result


def calculate_citation_coverage(
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate which data categories are represented in citations.

    Args:
        citations: List of citation dicts.

    Returns:
        Coverage report with categories present, missing, and coverage ratio.
    """
    expected_categories = {"profitability", "demand", "risk", "competition", "overall"}
    present = {c.get("category") for c in citations if c.get("category")}
    missing = expected_categories - present
    coverage = len(present & expected_categories) / len(expected_categories) if expected_categories else 0

    return {
        "categories_present": sorted(present),
        "categories_missing": sorted(missing),
        "coverage_ratio": round(coverage, 2),
        "sufficient": coverage >= 0.6,
    }
