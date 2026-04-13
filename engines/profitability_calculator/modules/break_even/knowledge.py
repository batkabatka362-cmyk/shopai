"""Break-even domain knowledge — expert heuristics and hard-won lessons.

What experienced e-commerce operators know about break-even analysis
that spreadsheets don't tell you. Sourced from Shopify seller communities,
failed launches post-mortems, and successful store case studies.
"""
from __future__ import annotations

from typing import Any


# Core break-even wisdom — each entry is a lesson learned the hard way
BREAK_EVEN_KNOWLEDGE = [
    {
        "id": "six_month_rule",
        "title": "If break-even > 6 months, don't launch",
        "insight": (
            "Products that take more than 6 months to break even almost never "
            "become profitable. By month 6, market conditions change, competitors "
            "appear, and your cash is trapped. The rare exceptions are highly "
            "defensible brands with patent protection."
        ),
        "category": "timing",
        "severity": "critical",
    },
    {
        "id": "first_batch_buffer",
        "title": "First batch should cover break-even + 20% buffer",
        "insight": (
            "Order 120% of your break-even units in the first batch. The extra "
            "20% covers: defective units (2-5%), samples for reviews (5%), "
            "returns (5-8%), and a small safety stock to avoid stockouts right "
            "when momentum builds."
        ),
        "category": "inventory",
        "severity": "important",
    },
    {
        "id": "include_marketing_in_break_even",
        "title": "Include marketing in break-even (most forget this)",
        "insight": (
            "The #1 mistake in break-even calculations: only counting inventory "
            "costs. Your real break-even includes ads, influencer payments, "
            "photography, and listing setup. A product that 'breaks even at "
            "50 units' actually needs 80+ when you add launch marketing."
        ),
        "category": "costs",
        "severity": "critical",
    },
    {
        "id": "hidden_costs_kill_margins",
        "title": "Hidden costs add 15-25% to your break-even point",
        "insight": (
            "Sellers consistently underestimate: payment processing fees (2.9%), "
            "return shipping (5-8% of orders), damaged inventory (2-3%), "
            "Shopify subscription ($39/month), app fees ($50-200/month), "
            "and their own time. Add 20% to your calculated break-even as a rule."
        ),
        "category": "costs",
        "severity": "important",
    },
    {
        "id": "velocity_ramp",
        "title": "Day 1 sales are not month 3 sales — don't average",
        "insight": (
            "New listings on Shopify start at near-zero organic traffic. "
            "Week 1 sales come almost entirely from paid ads. Organic traffic "
            "typically takes 60-90 days to materialize. Your break-even timeline "
            "should use month-1 velocity (lowest), not an average."
        ),
        "category": "timing",
        "severity": "important",
    },
    {
        "id": "test_before_commit",
        "title": "Spend $500 to validate before spending $5,000",
        "insight": (
            "Run a small Facebook/Instagram ad ($200-500) BEFORE ordering inventory. "
            "Send traffic to a 'coming soon' page or pre-order. If you can't get "
            "a 2% CTR and $0.50-2.00 CPC, the product likely won't sell. Better "
            "to lose $500 than $5,000."
        ),
        "category": "validation",
        "severity": "important",
    },
    {
        "id": "cash_flow_vs_profit",
        "title": "Break-even is not cash-flow positive",
        "insight": (
            "Breaking even on paper doesn't mean cash in the bank. You've already "
            "spent the money on inventory and setup. Break-even means you've "
            "recouped that spend. Real positive cash flow starts AFTER break-even "
            "when you reorder from profits, not savings."
        ),
        "category": "finance",
        "severity": "important",
    },
    {
        "id": "seasonality_trap",
        "title": "Don't launch right before your off-season",
        "insight": (
            "If your product sells best in Q4, don't launch in November — you'll "
            "miss the peak and crawl through Q1-Q3 trying to break even. Launch "
            "2-3 months before peak season to build reviews and organic ranking "
            "before the wave hits."
        ),
        "category": "timing",
        "severity": "important",
    },
    {
        "id": "price_anchoring",
        "title": "Your break-even price is not your selling price",
        "insight": (
            "Calculate break-even, then price 30-50% ABOVE it. You need margin "
            "for: inevitable discounts (10-20% off sales), coupon codes for "
            "email capture, bundle deals, and the occasional refund. If your "
            "break-even requires full price on every unit, you have no room to "
            "compete."
        ),
        "category": "pricing",
        "severity": "critical",
    },
    {
        "id": "reorder_timing",
        "title": "Plan your reorder at 60% of first batch sold",
        "insight": (
            "Lead time from supplier is 2-6 weeks. If you wait until you sell "
            "out to reorder, you'll have a 3-4 week stockout that kills your "
            "ranking and momentum. Place reorder when 60% of first batch is sold. "
            "This is BEFORE break-even for most products."
        ),
        "category": "inventory",
        "severity": "important",
    },
]


# Organized insights by topic for quick lookup
_INSIGHTS_BY_CATEGORY = {}
for _item in BREAK_EVEN_KNOWLEDGE:
    _cat = _item["category"]
    if _cat not in _INSIGHTS_BY_CATEGORY:
        _INSIGHTS_BY_CATEGORY[_cat] = []
    _INSIGHTS_BY_CATEGORY[_cat].append(_item)


def get_break_even_insight(topic: str | None = None) -> list[dict[str, Any]]:
    """Get break-even insights, optionally filtered by topic.

    Args:
        topic: Filter by category (timing, costs, inventory, finance,
               pricing, validation). None returns all.
    """
    if topic is None:
        return BREAK_EVEN_KNOWLEDGE
    return _INSIGHTS_BY_CATEGORY.get(topic, [])


def get_critical_insights() -> list[dict[str, Any]]:
    """Get only the critical-severity insights — must-knows before launch."""
    return [k for k in BREAK_EVEN_KNOWLEDGE if k["severity"] == "critical"]


def get_insight_summary() -> str:
    """One-paragraph summary of break-even wisdom for quick reference."""
    return (
        "Include ALL launch costs in break-even (marketing, photography, samples — not "
        "just inventory). Target break-even within 90 days; abort if projections exceed "
        "6 months. Order 120% of break-even quantity in your first batch to cover "
        "defects and returns. Validate demand with a $500 ad test before committing "
        "capital. Price 30-50% above break-even to leave room for discounts and "
        "competition. Remember: break-even is not profit — real cash flow starts after."
    )
