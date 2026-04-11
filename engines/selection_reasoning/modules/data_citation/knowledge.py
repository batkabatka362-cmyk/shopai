"""Data Citation — domain knowledge for effective data citation.

Principles for citing data in selection reasoning reports. Each insight
covers why proper citation matters and how to do it effectively.
"""

from __future__ import annotations

from typing import Any


CITATION_KNOWLEDGE: list[dict[str, Any]] = [
    {
        "id": "data_without_source",
        "insight": "Data without source = opinion",
        "detail": (
            "Citing '42% margin' without saying where that number came from is "
            "just an assertion. Citing '42% margin (Profitability Calculator Engine, "
            "based on supplier quotes and marketplace fees)' is evidence. The source "
            "gives the reader the ability to assess credibility. Unsourced data "
            "points are indistinguishable from guesses, and sellers who are spending "
            "real money deserve to know the basis for every claim."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "lead_with_strongest",
        "insight": "Lead with strongest supporting data",
        "detail": (
            "The first citation the reader sees shapes their perception of the "
            "entire recommendation. Put the most compelling, highest-impact data "
            "point first. If the product has a 45% margin, that goes before the "
            "trend score. If risk is unusually low, lead with that. The order of "
            "citations is a persuasion tool — use it deliberately to build "
            "confidence in the recommendation."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 1,
    },
    {
        "id": "cite_the_negative",
        "insight": "Citing negative data builds more trust than hiding it",
        "detail": (
            "If the competition score is 35/100, cite it. Do not cherry-pick "
            "only the favorable numbers. A report that cites both strengths and "
            "weaknesses is more credible than one that only shows the good side. "
            "The reader will find the negatives eventually — better they find them "
            "in your report than on their own. Incomplete citation is dishonest "
            "citation."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "quantity_has_limits",
        "insight": "More citations is not always better — relevance trumps volume",
        "detail": (
            "Fifteen citations overwhelm the reader. Five to eight well-chosen "
            "citations covering the key dimensions (profit, demand, risk, "
            "competition) tell a complete story without information overload. "
            "Each citation should add a unique piece of evidence. If two citations "
            "say essentially the same thing, keep the more specific one."
        ),
        "applies_when": "always",
        "impact": "medium",
        "priority": 3,
    },
    {
        "id": "context_matters",
        "insight": "A number without context is just a number",
        "detail": (
            "'Demand score: 72' is less useful than 'Demand score: 72/100, "
            "indicating strong market pull.' Always provide the scale, unit, "
            "or benchmark that makes the number interpretable. A seller who "
            "does not know what 72 means out of 100 cannot act on it. Context "
            "transforms data into insight."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "consistency_in_format",
        "insight": "Consistent citation format builds professional credibility",
        "detail": (
            "Every citation should follow the same structure: Data Point: Value "
            "(Source: Engine Name). Inconsistent formatting — sometimes including "
            "the source, sometimes not; sometimes using percentages, sometimes "
            "decimals — looks sloppy and undermines trust. Consistency signals "
            "that the analysis was systematic, not ad hoc."
        ),
        "applies_when": "always",
        "impact": "medium",
        "priority": 3,
    },
]


def get_citation_insight(insight_id: str) -> dict[str, Any] | None:
    """Retrieve a specific citation knowledge entry by ID."""
    for entry in CITATION_KNOWLEDGE:
        if entry["id"] == insight_id:
            return entry
    return None


def get_relevant_citation_insights(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return citation insights relevant to the current context.

    Args:
        context: dict with keys like citation_count, categories_covered, etc.

    Returns:
        List of matching knowledge entries sorted by priority.
    """
    relevant: list[dict[str, Any]] = []
    for entry in CITATION_KNOWLEDGE:
        if entry["applies_when"] == "always":
            relevant.append(entry)
    relevant.sort(key=lambda x: x["priority"])
    return relevant
