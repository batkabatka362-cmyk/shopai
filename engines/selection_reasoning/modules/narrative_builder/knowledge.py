"""Narrative Builder — domain knowledge for effective decision narratives.

Lessons learned about how to communicate product selection decisions
in a way that builds trust and drives action. Each insight covers
the principle, why it matters, and when to apply it.
"""

from __future__ import annotations

from typing import Any


NARRATIVE_KNOWLEDGE: list[dict[str, Any]] = [
    {
        "id": "conclusion_first",
        "insight": "Start with the conclusion, then explain",
        "detail": (
            "Sellers do not want to read three paragraphs before learning which "
            "product was selected. Lead with the pick: 'We recommend Product X.' "
            "Then explain why. This is the inverted pyramid structure used in "
            "journalism — it respects the reader's time and ensures the most "
            "important information is seen even if they stop reading early. "
            "Burying the recommendation kills engagement."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "numbers_over_adjectives",
        "insight": "Numbers are more convincing than adjectives",
        "detail": (
            "'High margin' means nothing. '42% margin' means everything. "
            "'Strong demand' is vague. 'Demand score: 78/100 based on 12,000 "
            "monthly searches' is concrete. Every claim in the narrative should "
            "be backed by a specific number. If you cannot attach a number to a "
            "claim, the claim is too weak to include. Sellers making $50K+ "
            "decisions need data, not cheerleading."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "honesty_builds_trust",
        "insight": "Acknowledging weaknesses builds more trust than hiding them",
        "detail": (
            "If the product has a moderate risk score, say so. If demand is "
            "uncertain, disclose it. Sellers who discover hidden problems after "
            "committing will never trust your system again. A recommendation that "
            "says 'this product has moderate competition risk but strong margins "
            "that compensate' is more trustworthy than one that only mentions "
            "the margins. Transparency converts skeptics into loyal users."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "explain_the_tradeoff",
        "insight": "Every selection involves a tradeoff — make it explicit",
        "detail": (
            "No product wins on every dimension. The selected product might have "
            "the best margins but only moderate demand. Or strong demand but higher "
            "competition. Stating the tradeoff explicitly shows the analysis was "
            "thorough and helps the seller understand what they are optimizing for. "
            "'We chose margin over volume' is a clear, defensible position."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "brevity_is_respect",
        "insight": "Brevity is respect for the reader's time",
        "detail": (
            "A 500-word narrative that covers the key points is better than a "
            "2000-word report that repeats itself. Sellers are busy. Every sentence "
            "in the narrative should either state a fact, explain a decision, or "
            "recommend an action. Remove filler words, redundant qualifiers, and "
            "anything that does not advance the reader's understanding."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "risk_must_appear",
        "insight": "Risk disclosure is not optional — it is the price of credibility",
        "detail": (
            "A narrative that recommends a product without mentioning risk is "
            "either incomplete or dishonest. The reader will assume the worst: "
            "either you did not analyze risk, or you are hiding it. Always include "
            "at least one sentence about the risk profile, even if risk is low. "
            "'Risk is minimal' is still a risk statement."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "actionable_endings",
        "insight": "End with what to do next, not a summary",
        "detail": (
            "The last thing the reader sees should be an action item, not a "
            "restatement of the conclusion. 'Order a sample within 7 days to "
            "validate quality' is better than 'In conclusion, Product X is our "
            "recommendation.' The narrative should drive action, not just inform."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
]


def get_narrative_insight(insight_id: str) -> dict[str, Any] | None:
    """Retrieve a specific narrative knowledge entry by ID."""
    for entry in NARRATIVE_KNOWLEDGE:
        if entry["id"] == insight_id:
            return entry
    return None


def get_relevant_narrative_insights(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return narrative insights relevant to the current context.

    Args:
        context: dict with keys like has_risk_data, score_tier, etc.

    Returns:
        List of matching knowledge entries sorted by priority.
    """
    relevant: list[dict[str, Any]] = []
    for entry in NARRATIVE_KNOWLEDGE:
        if entry["applies_when"] == "always":
            relevant.append(entry)

    relevant.sort(key=lambda x: x["priority"])
    return relevant
