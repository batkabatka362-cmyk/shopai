"""Action Planner — domain knowledge for creating effective launch plans.

Principles for building action plans that sellers will actually follow.
Each insight covers what makes plans actionable versus aspirational.
"""

from __future__ import annotations

from typing import Any


ACTION_PLAN_KNOWLEDGE: list[dict[str, Any]] = [
    {
        "id": "plan_without_dates",
        "insight": "A plan without dates is a wish",
        "detail": (
            "'Order samples soon' is not a plan. 'Order samples by April 9, "
            "2026' is a plan. Every step needs a concrete deadline. Without "
            "dates, plans drift indefinitely. Sellers who follow dated plans "
            "launch 3x faster than those who follow vague timelines. The act "
            "of assigning a date creates commitment and enables accountability."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "first_milestone_samples",
        "insight": "First milestone = order samples within 7 days",
        "detail": (
            "The single best predictor of whether a seller will actually launch "
            "a product is whether they order samples within the first week. "
            "Analysis paralysis kills more businesses than bad products. The "
            "sample order is cheap ($20-100), low-risk, and creates momentum. "
            "Make it the first action item, with a 7-day deadline, every time."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "budget_per_step",
        "insight": "Every step needs a dollar amount, not a percentage",
        "detail": (
            "'Allocate 25% to marketing' is abstract. 'Spend $1,250 on PPC "
            "in weeks 4-6' is concrete. Sellers need to know exactly how much "
            "each step costs so they can plan cash flow. A $5,000 investment "
            "with unclear allocation leads to overspending early and running "
            "out of budget for advertising."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 1,
    },
    {
        "id": "success_criteria_are_numbers",
        "insight": "Success criteria must be measurable — numbers, not feelings",
        "detail": (
            "'The product is doing well' is not a success criterion. 'Selling "
            "3+ units/day with ACOS under 30% and margin above 25%' is. Every "
            "milestone needs a number that tells the seller: are we on track? "
            "Without measurable criteria, review steps become rubber stamps "
            "instead of genuine decision points."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "failure_action_matters",
        "insight": "What to do when it fails matters more than what to do when it works",
        "detail": (
            "Most plans only cover the happy path. The seller needs to know: "
            "if samples are bad, do I find a new supplier or a new product? "
            "If sales are slow in week 4, do I increase ad spend or cut losses? "
            "The failure actions at each milestone are the most valuable part "
            "of the plan because they reduce panic and enable fast pivots."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "momentum_over_perfection",
        "insight": "Momentum beats perfection — ship the listing, then optimize",
        "detail": (
            "Sellers who spend 4 weeks perfecting their listing before launching "
            "lose to sellers who launch in week 2 and optimize based on real "
            "data. The plan should bias toward action. A good listing live today "
            "beats a perfect listing in three weeks. Real customer data is "
            "infinitely more valuable than hypothetical optimization."
        ),
        "applies_when": "always",
        "impact": "medium",
        "priority": 3,
    },
    {
        "id": "review_at_30_days",
        "insight": "30 days is the minimum viable evaluation period",
        "detail": (
            "Evaluating a product after 7 days is premature — you are seeing "
            "launch effects, not steady-state performance. Evaluating after 90 "
            "days means you have already invested heavily before knowing if it "
            "works. 30 days gives enough data for a statistically meaningful "
            "assessment while limiting total exposure."
        ),
        "applies_when": "always",
        "impact": "medium",
        "priority": 3,
    },
]


def get_action_insight(insight_id: str) -> dict[str, Any] | None:
    """Retrieve a specific action plan knowledge entry by ID."""
    for entry in ACTION_PLAN_KNOWLEDGE:
        if entry["id"] == insight_id:
            return entry
    return None


def get_relevant_action_insights(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return action plan insights relevant to the current context.

    Args:
        context: dict with keys like product_type, risk_level, etc.

    Returns:
        List of matching knowledge entries sorted by priority.
    """
    relevant: list[dict[str, Any]] = []
    for entry in ACTION_PLAN_KNOWLEDGE:
        if entry["applies_when"] == "always":
            relevant.append(entry)
    relevant.sort(key=lambda x: x["priority"])
    return relevant
