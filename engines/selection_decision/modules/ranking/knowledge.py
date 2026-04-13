"""Domain knowledge for product ranking and selection.

Hard-won lessons about ranking products, interpreting score gaps,
and making final selection decisions. Each insight includes context
on when it matters most and what to do about it.
"""

from __future__ import annotations

from typing import Any

RANKING_KNOWLEDGE: list[dict[str, Any]] = [
    {
        "id": "close_scores_mean_bad_data",
        "insight": "Close scores mean your data is not good enough to decide — get more data",
        "detail": (
            "When two products are within 5 points of each other, the ranking "
            "is telling you something important: it cannot distinguish them. "
            "This is not a failure of the ranking algorithm — it is a signal "
            "that your input data lacks the resolution to make this call. "
            "Instead of agonizing over 72 vs 69, invest the time in getting "
            "better data: run a small test order, get real customer feedback, "
            "or analyze competitor reviews more deeply. The cost of better data "
            "is always less than the cost of picking the wrong product."
        ),
        "applies_when": "score_gap < 5",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "top_three_is_enough",
        "insight": "Top 3 is enough — do not analyze 20 products",
        "detail": (
            "Analysis paralysis is real and expensive. Every hour spent "
            "evaluating product #12 is an hour not spent launching product #1. "
            "If your filtering and scoring pipeline works, the top 3 products "
            "are your real candidates. Products ranked 4th or lower are backups "
            "at best. Focus your deep analysis on the top 3, pick one, and "
            "execute. A good product launched today beats a perfect product "
            "launched next month."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 1,
    },
    {
        "id": "clear_winner_threshold",
        "insight": "A score gap greater than 15 points means a clear winner — stop analyzing",
        "detail": (
            "When one product leads by 15+ points across multiple weighted "
            "dimensions, the signal is strong enough to act on. Further analysis "
            "will almost never flip a 15-point gap. The risk of over-analysis "
            "(delayed launch, missed trends, analysis fatigue) exceeds the risk "
            "of the gap being wrong. Trust the data, select the winner, and "
            "redirect your energy to execution: supplier negotiation, listing "
            "optimization, and launch strategy."
        ),
        "applies_when": "score_gap > 15",
        "impact": "high",
        "priority": 1,
    },
    {
        "id": "rank_stability_matters",
        "insight": "If changing one assumption flips the ranking, neither product is clearly better",
        "detail": (
            "A ranking that changes when you adjust profitability by 3 points "
            "or demand by 5 points is an unstable ranking. This means the "
            "products are genuinely close in overall attractiveness, and the "
            "winner depends on which assumptions you believe. In this case, "
            "stop trying to pick the objectively better product. Instead, pick "
            "the one that aligns better with your specific strengths: your "
            "supplier relationships, your marketing skills, your category "
            "expertise, or your existing brand positioning."
        ),
        "applies_when": "stability == low",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "tiers_not_ranks",
        "insight": "Think in tiers, not ranks — there is no meaningful difference between #2 and #3",
        "detail": (
            "Ranking creates a false sense of precision. Product #2 at 71 points "
            "and product #3 at 69 points are in the same tier — they are both "
            "good options. The meaningful distinction is between tiers: top tier "
            "(within 10%% of the leader), middle tier (viable but weaker), and "
            "bottom tier (not worth pursuing). Pick any product from the top tier "
            "and you are making a good decision. Obsessing over rank order within "
            "a tier wastes time and creates anxiety over noise."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "disqualified_is_disqualified",
        "insight": "A disqualified product is not a ranked-last product — it is off the table",
        "detail": (
            "Products that fail minimum score, have critical risk, or show "
            "negative profitability are not at the bottom of the list — they "
            "are removed from the list. There is a psychological trap where "
            "sellers say 'but it scored 38, that is close to 40' and try to "
            "include it. The threshold exists because products below it have "
            "a fundamental problem that scoring cannot fix. Do not negotiate "
            "with the floor — find better products."
        ),
        "applies_when": "disqualified_count > 0",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "execution_beats_selection",
        "insight": "A mediocre product with great execution beats a great product with mediocre execution",
        "detail": (
            "Ranking helps you avoid terrible products, but the difference "
            "between the #1 and #3 product is usually less impactful than "
            "the difference between great and average execution. A product "
            "ranked #3 with outstanding photos, optimized PPC, strong reviews, "
            "and fast shipping will outperform a #1 product with a lazy listing "
            "and no marketing plan. Use ranking to narrow your options, then "
            "invest your real energy in execution."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "revisit_quarterly",
        "insight": "Rankings expire — revisit every quarter or when market conditions shift",
        "detail": (
            "A ranking done in January may be invalid by April. New competitors "
            "enter, trends shift, costs change, and demand fluctuates. If you "
            "ranked products 3 months ago and have not launched yet, re-run the "
            "full pipeline before committing capital. The market does not wait "
            "for your analysis to finish. Treat rankings as perishable — they "
            "have a shelf life of roughly 60-90 days."
        ),
        "applies_when": "ranking_age > 60_days",
        "impact": "high",
        "priority": 2,
    },
]


def get_ranking_insight(insight_id: str) -> dict[str, Any] | None:
    """Retrieve a specific ranking knowledge entry by ID."""
    for entry in RANKING_KNOWLEDGE:
        if entry["id"] == insight_id:
            return entry
    return None


def get_relevant_ranking_insights(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return ranking insights relevant to a given ranking context.

    Args:
        context: dict with keys like score_gap, stability,
                 disqualified_count, ranking_age_days, etc.

    Returns:
        List of matching knowledge entries sorted by priority.
    """
    relevant: list[dict[str, Any]] = []

    score_gap = context.get("score_gap", 999)
    stability = context.get("stability", "high")
    disqualified = context.get("disqualified_count", 0)
    ranking_age = context.get("ranking_age_days", 0)

    for entry in RANKING_KNOWLEDGE:
        condition = entry["applies_when"]
        match = False

        if condition == "always":
            match = True
        elif "score_gap < 5" in condition and score_gap < 5:
            match = True
        elif "score_gap > 15" in condition and score_gap > 15:
            match = True
        elif "stability == low" in condition and stability == "low":
            match = True
        elif "disqualified_count > 0" in condition and disqualified > 0:
            match = True
        elif "ranking_age > 60_days" in condition and ranking_age > 60:
            match = True

        if match:
            relevant.append(entry)

    relevant.sort(key=lambda x: x["priority"])
    return relevant
