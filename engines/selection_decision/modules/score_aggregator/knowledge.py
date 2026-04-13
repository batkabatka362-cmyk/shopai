"""Domain knowledge for score aggregation in product selection.

Hard-won lessons about combining multiple data signals into a single
decision metric. Each insight covers when it matters and what to do.
"""

from __future__ import annotations

from typing import Any

AGGREGATION_KNOWLEDGE: list[dict[str, Any]] = [
    {
        "id": "never_trust_single_score",
        "insight": "Never trust a single score — always aggregate",
        "detail": (
            "A product can look great on one dimension and terrible on another. "
            "High demand means nothing if competition is brutal. High margins "
            "mean nothing if risk is extreme. The whole point of aggregation is "
            "to prevent tunnel vision. A seller who picks products based on one "
            "metric (e.g., only margin) will fail 60-70% of the time. The ones "
            "who cross-reference 4-5 dimensions succeed at 2-3x the rate."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "risk_is_multiplier",
        "insight": "Risk is a multiplier, not an addend",
        "detail": (
            "Adding risk as just another weighted score is wrong. A product with "
            "a score of 80 and critical risk is not a 65 — it is an 80 that might "
            "become a 0. Risk should scale the entire score downward because it "
            "affects the probability of realizing ANY of the projected value. "
            "A 50% chance of total failure halves the expected value of every "
            "other metric. Treat risk as a multiplier on the base score."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "missing_data_not_zero",
        "insight": "Missing data means higher uncertainty, not zero",
        "detail": (
            "When an engine has no score, the worst thing to do is treat it as "
            "zero. That artificially kills the product. The second worst thing "
            "is to ignore it entirely, which inflates the score. The right approach: "
            "redistribute weights to available engines AND apply a confidence "
            "penalty. If 3 of 6 engines are missing, the score might be correct "
            "but your confidence in it is halved. Flag it, do not fake it."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "conflicts_are_signals",
        "insight": "Conflicting scores are the most valuable signal you have",
        "detail": (
            "When profitability says 90 and risk says 85, that is not noise — "
            "it is the most important finding in your analysis. It means either "
            "the profit estimate is too optimistic, the risk model is too "
            "conservative, or you have genuinely found a high-risk high-reward "
            "opportunity. Each of those requires a different response. Never "
            "average away conflicts; surface them explicitly."
        ),
        "applies_when": "conflicts_detected == True",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "weights_reflect_strategy",
        "insight": "Your weights are your strategy — choose them deliberately",
        "detail": (
            "Default weights are a starting point, not gospel. A seller focused "
            "on cash flow should weight profitability and demand heavily. A seller "
            "building a brand should weight trend and market size. A risk-averse "
            "seller should weight risk and competition. If you do not customize "
            "weights to your situation, you are using someone else's strategy. "
            "Review and adjust weights every quarter as your business evolves."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "filter_is_binary",
        "insight": "Filter failures are binary — no score can compensate",
        "detail": (
            "If a product fails legal checks, shipping feasibility, or brand "
            "restrictions, it does not matter that every other score is 95. "
            "Filter failures are hard blockers. You cannot sell a product you "
            "cannot legally import, ship, or list. Apply filter results as a "
            "gate first, then aggregate remaining scores for products that pass."
        ),
        "applies_when": "filter_status == fail",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "score_precision_illusion",
        "insight": "A score of 72.3 is not meaningfully different from 71.8",
        "detail": (
            "Unified scores have a margin of error of roughly plus or minus 5 "
            "points given the uncertainty in each input engine. Treating scores "
            "as precise to the decimal creates false confidence. When two products "
            "are within 5 points, they are statistically tied. Make the decision "
            "on qualitative factors or get more data. Do not pick product A over "
            "product B because 72.3 > 71.8 — that is noise, not signal."
        ),
        "applies_when": "score_gap < 5",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "recency_matters",
        "insight": "A score from last month is not a score from today",
        "detail": (
            "Market conditions, competition, and trends change constantly. "
            "A profitability score calculated 45 days ago may reflect a price "
            "point that no longer exists. A competition score from before a "
            "major competitor entered is useless. Always check data freshness "
            "before trusting aggregated scores. Stale data is worse than missing "
            "data because it creates false confidence."
        ),
        "applies_when": "data_age > 30_days",
        "impact": "high",
        "priority": 2,
    },
]


def get_aggregation_insight(insight_id: str) -> dict[str, Any] | None:
    """Retrieve a specific aggregation knowledge entry by ID."""
    for entry in AGGREGATION_KNOWLEDGE:
        if entry["id"] == insight_id:
            return entry
    return None


def get_relevant_aggregation_insights(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return aggregation insights relevant to a given scoring context.

    Args:
        context: dict with keys like conflicts_detected, filter_status,
                 score_gap, data_age, etc.

    Returns:
        List of matching knowledge entries sorted by priority.
    """
    relevant: list[dict[str, Any]] = []

    conflicts = context.get("conflicts_detected", False)
    filter_status = context.get("filter_status", "pass")
    score_gap = context.get("score_gap", 999)
    data_age = context.get("data_age_days", 0)

    for entry in AGGREGATION_KNOWLEDGE:
        condition = entry["applies_when"]
        match = False

        if condition == "always":
            match = True
        elif "conflicts_detected" in condition and conflicts:
            match = True
        elif "filter_status == fail" in condition and filter_status == "fail":
            match = True
        elif "score_gap < 5" in condition and score_gap < 5:
            match = True
        elif "data_age > 30_days" in condition and data_age > 30:
            match = True

        if match:
            relevant.append(entry)

    relevant.sort(key=lambda x: x["priority"])
    return relevant
