"""Risk Disclosure — domain knowledge for transparent risk communication.

Principles for disclosing risks in product selection reports. Each insight
covers why transparency matters and how to communicate risk effectively
without causing paralysis or false confidence.
"""

from __future__ import annotations

from typing import Any


RISK_DISCLOSURE_KNOWLEDGE: list[dict[str, Any]] = [
    {
        "id": "hiding_risks_destroys_trust",
        "insight": "Hiding risks destroys trust",
        "detail": (
            "A seller who discovers a risk you knew about but did not disclose "
            "will never use your system again. Trust is the foundation of any "
            "recommendation system. One hidden risk that materializes undoes "
            "a hundred accurate predictions. Disclose everything — the seller "
            "can decide how to handle it. Your job is to inform, not to protect "
            "them from uncomfortable truths."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "every_risk_needs_mitigation",
        "insight": "Every risk should have a mitigation",
        "detail": (
            "Listing risks without mitigations is just a list of problems. "
            "Every risk disclosure should answer: 'What can I do about this?' "
            "Even if the mitigation is 'reduce order size by 50%' or 'set a "
            "stop-loss at $X,' the seller needs an actionable response. A risk "
            "with a mitigation is manageable. A risk without one is terrifying."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "state_the_number",
        "insight": "State the number — 'you could lose $X'",
        "detail": (
            "'There is financial risk' is useless. 'You could lose up to $2,500 "
            "(50% of your $5,000 investment)' is actionable. Sellers need to "
            "know the dollar amount at risk to make informed decisions. Abstract "
            "risk descriptions do not enable decision-making. Concrete numbers "
            "do. Always translate risk into a dollar figure relative to the "
            "planned investment."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "severity_ranking_matters",
        "insight": "Rank risks by severity — do not alphabetize problems",
        "detail": (
            "A critical risk buried after three low-risk items might be missed. "
            "Always present risks in severity order: critical first, then high, "
            "then moderate, then low. The reader's attention decreases with each "
            "item — make sure the most dangerous risks get the most attention."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "risk_is_not_failure",
        "insight": "Risk does not mean failure — it means uncertainty",
        "detail": (
            "Disclosing risks should not cause paralysis. Frame risks as "
            "uncertainties to manage, not inevitable failures. 'There is a 15% "
            "chance of this outcome' is more useful than 'this might happen.' "
            "Help the seller understand probability, not just possibility. Most "
            "risks, properly mitigated, never materialize."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "worst_case_is_baseline",
        "insight": "The worst case is the baseline for smart planning",
        "detail": (
            "Knowing the worst case lets the seller ask: 'Can I survive this?' "
            "If the answer is yes, they can proceed with confidence. If no, they "
            "can reduce exposure until the worst case becomes survivable. The "
            "worst-case scenario is not pessimism — it is the foundation of "
            "responsible risk management. Plan for the worst, execute for the best."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
]


def get_risk_insight(insight_id: str) -> dict[str, Any] | None:
    """Retrieve a specific risk disclosure knowledge entry by ID."""
    for entry in RISK_DISCLOSURE_KNOWLEDGE:
        if entry["id"] == insight_id:
            return entry
    return None


def get_relevant_risk_insights(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return risk insights relevant to the current context.

    Args:
        context: dict with keys like has_critical_risks, total_risks, etc.

    Returns:
        List of matching knowledge entries sorted by priority.
    """
    relevant: list[dict[str, Any]] = []
    for entry in RISK_DISCLOSURE_KNOWLEDGE:
        if entry["applies_when"] == "always":
            relevant.append(entry)
    relevant.sort(key=lambda x: x["priority"])
    return relevant
