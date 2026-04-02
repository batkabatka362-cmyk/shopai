"""Alternative Presenter — domain knowledge for presenting alternatives.

Principles for showing alternative products in a way that demonstrates
thoroughness without undermining confidence in the primary selection.
"""

from __future__ import annotations

from typing import Any


ALTERNATIVE_KNOWLEDGE: list[dict[str, Any]] = [
    {
        "id": "alternatives_prove_thoroughness",
        "insight": "Showing alternatives proves thoroughness",
        "detail": (
            "A recommendation that says 'we considered 5 products and here is "
            "why we picked this one over the others' is far more convincing than "
            "'buy this product.' The reader wants to know the analysis was "
            "exhaustive, not cherry-picked. Presenting alternatives shows that "
            "the selection was deliberate and comparative, not arbitrary."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 1,
    },
    {
        "id": "close_alternatives_are_backup",
        "insight": "Close alternatives = revisit if #1 fails",
        "detail": (
            "When a product scores 78 and the runner-up scores 75, that gap is "
            "within the margin of error. If the primary selection underperforms "
            "in the first 30 days, the close second is the natural pivot. "
            "Always flag alternatives within 5 points as viable backups. This "
            "gives the seller a plan B without starting the entire analysis "
            "from scratch."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 1,
    },
    {
        "id": "explain_the_gap",
        "insight": "Explain the gap — do not just show the numbers",
        "detail": (
            "'Product B scored 65 vs our pick's 82' tells the reader nothing "
            "about why. 'Product B scored 65 vs 82 — lower demand but similar "
            "margins' gives them the insight they need. The explanation of the "
            "gap is more valuable than the gap itself. It helps the seller "
            "understand what dimensions drove the decision."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 1,
    },
    {
        "id": "fairness_builds_trust",
        "insight": "Acknowledge where alternatives are stronger",
        "detail": (
            "If an alternative has better margins but lower demand, say so. "
            "Cherry-picking only the dimensions where the selection wins "
            "looks biased. Fair comparison — noting both strengths and "
            "weaknesses of alternatives — builds trust in the recommendation. "
            "The reader will notice if you are only showing one side."
        ),
        "applies_when": "always",
        "impact": "medium",
        "priority": 2,
    },
    {
        "id": "limit_alternative_count",
        "insight": "Three alternatives is enough — more creates decision paralysis",
        "detail": (
            "Showing 10 alternatives overwhelms the reader and undermines "
            "confidence in the selection. If there were so many options, maybe "
            "the analysis missed something. Three alternatives — the top two "
            "runners-up and one from a different angle — give enough context "
            "without creating doubt. The goal is to inform, not to reopen "
            "the decision."
        ),
        "applies_when": "always",
        "impact": "medium",
        "priority": 2,
    },
    {
        "id": "rejection_needs_specificity",
        "insight": "Rejection reasons must be specific, not generic",
        "detail": (
            "'Did not meet criteria' is useless. 'Margin of 12% is below the "
            "20% threshold for a profit-focused strategy' is specific and "
            "actionable. The reader should know exactly what dimension(s) "
            "disqualified the alternative so they can form their own judgment "
            "about whether that tradeoff matters for their situation."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
]


def get_alternative_insight(insight_id: str) -> dict[str, Any] | None:
    """Retrieve a specific alternative knowledge entry by ID."""
    for entry in ALTERNATIVE_KNOWLEDGE:
        if entry["id"] == insight_id:
            return entry
    return None


def get_relevant_alternative_insights(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return alternative insights relevant to the current context.

    Args:
        context: dict with keys like has_close_seconds, alt_count, etc.

    Returns:
        List of matching knowledge entries sorted by priority.
    """
    relevant: list[dict[str, Any]] = []
    for entry in ALTERNATIVE_KNOWLEDGE:
        if entry["applies_when"] == "always":
            relevant.append(entry)
    relevant.sort(key=lambda x: x["priority"])
    return relevant
